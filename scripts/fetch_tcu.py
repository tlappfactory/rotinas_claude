#!/usr/bin/env python3
"""
fetch_tcu.py — baixa e filtra acórdãos recentes do TCU via API JSON dos dados abertos.

Endpoint:  GET https://dados-abertos.apps.tcu.gov.br/api/acordao/recupera-acordaos
Parâmetros: inicio (int), quantidade (int)
Resposta:  JSON array com objetos contendo key, anoAcordao, titulo, numeroAcordao,
           colegiado, dataSessao (DD/MM/AAAA), relator, situacao, sumario,
           urlArquivo, urlArquivoPDF, urlAcordao.

Estratégia:
  1. Pagina a API até encontrar acórdãos mais antigos que LOOKBACK_DAYS.
     (A ordem retornada é descoberta empiricamente no primeiro run — o script
      detecta se vem do mais novo para o mais antigo e adapta o critério de
      parada; se vier do mais antigo, escapa após PAGE_SAFETY_LIMIT páginas
      e o operador ajusta.)
  2. Filtra cada acórdão por:
       (a) dataSessao dentro da janela LOOKBACK_DAYS.
       (b) sumario/titulo casando com STRONG_KEYWORDS / WEAK_KEYWORDS do parse_dou.py
           OU menção explícita a "TRT-17" / "17ª Região" / "trabalho 17".
  3. Grava em <TCU_ROOT>/<run-date-iso>/tcu-filtered.json.

Uso:
    python3 scripts/fetch_tcu.py                 # janela padrão (14 dias)
    python3 scripts/fetch_tcu.py --lookback 30   # janela ampliada
    python3 scripts/fetch_tcu.py --dry-run       # imprime amostra, não grava
"""
import argparse
import json
import os
import re
import sys
import unicodedata
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlencode

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
TCU_ROOT = Path(os.environ.get("TCU_ROOT", REPO_ROOT / "tcu"))

sys.path.insert(0, str(SCRIPT_DIR))
from parse_dou import STRONG_KEYWORDS, WEAK_KEYWORDS, normalize, match_patterns  # noqa: E402

API_URL = "https://dados-abertos.apps.tcu.gov.br/api/acordao/recupera-acordaos"
PAGE_SIZE = 500
PAGE_SAFETY_LIMIT = 40           # máx. 20.000 acórdãos varridos por run
DEFAULT_LOOKBACK_DAYS = 14
REQUEST_TIMEOUT = 60

HEADERS = {
    "Accept": "application/json",
    "User-Agent": "rotinas-claude-trt17/1.0 (+routine-colep-01)",
}

TRT17_PATTERNS = [
    r"\btrt[-\s]?17\b",
    r"\b17[ªa]?\s*regiao\b",
    r"\btribunal regional do trabalho da 17\b",
    r"\bjustica do trabalho da 17\b",
    r"\bes\s*[-/]\s*espirito santo\b",  # heurística fraca, só conta como weak
]


def parse_data_sessao(s: str) -> date | None:
    s = (s or "").strip()
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def fetch_page(inicio: int, quantidade: int) -> list[dict]:
    url = f"{API_URL}?{urlencode({'inicio': inicio, 'quantidade': quantidade})}"
    r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict) and "data" in data:  # caso a API empacote
        data = data["data"]
    if not isinstance(data, list):
        raise ValueError(f"Resposta inesperada do TCU: tipo {type(data).__name__}")
    return data


def evaluate_acordao(item: dict) -> dict | None:
    """Retorna dict-resumo com hits se o acórdão é relevante, senão None."""
    sumario = item.get("sumario") or ""
    titulo = item.get("titulo") or ""
    relator = item.get("relator") or ""
    full = " ".join([titulo, sumario, relator])
    norm = normalize(full)

    strong_hits = match_patterns(norm, STRONG_KEYWORDS)
    weak_hits = match_patterns(norm, WEAK_KEYWORDS)

    trt17_hits = [p for p in TRT17_PATTERNS if re.search(p, norm)]

    # Critério: TRT-17 explícito OU >=1 strong keyword OU >=2 weak keywords.
    if not (trt17_hits or strong_hits or len(weak_hits) >= 2):
        return None

    score = 10 * len(trt17_hits) + 5 * len(strong_hits) + len(weak_hits)
    return {
        "key": item.get("key"),
        "tipo": item.get("tipo"),
        "numeroAcordao": item.get("numeroAcordao"),
        "anoAcordao": item.get("anoAcordao"),
        "colegiado": item.get("colegiado"),
        "dataSessao": item.get("dataSessao"),
        "relator": relator,
        "situacao": item.get("situacao"),
        "titulo": titulo,
        "sumario": sumario[:1200],
        "urlAcordao": item.get("urlAcordao"),
        "urlArquivoPDF": item.get("urlArquivoPDF"),
        "strong_keywords": sorted(set(strong_hits)),
        "weak_keywords": sorted(set(weak_hits)),
        "trt17_hits": trt17_hits,
        "score": score,
    }


def run(lookback_days: int, dry_run: bool) -> dict:
    today = date.today()
    cutoff = today - timedelta(days=lookback_days)
    seen_keys: set[str] = set()
    matched: list[dict] = []
    pages_with_recent = 0
    pages_old_in_a_row = 0
    last_dates: list[date | None] = []

    for page_idx in range(PAGE_SAFETY_LIMIT):
        inicio = page_idx * PAGE_SIZE
        try:
            items = fetch_page(inicio, PAGE_SIZE)
        except Exception as e:
            print(f"ERRO fetch_page(inicio={inicio}): {e}", file=sys.stderr)
            break
        if not items:
            break

        page_dates = []
        recent_in_page = 0
        for it in items:
            key = it.get("key")
            if key and key in seen_keys:
                continue
            if key:
                seen_keys.add(key)
            ds = parse_data_sessao(it.get("dataSessao", ""))
            page_dates.append(ds)
            if ds and ds >= cutoff:
                recent_in_page += 1
                row = evaluate_acordao(it)
                if row:
                    matched.append(row)

        last_dates.extend(page_dates)
        print(f"  página {page_idx} (inicio={inicio}): {len(items)} itens, "
              f"{recent_in_page} dentro da janela; matched acumulado: {len(matched)}",
              file=sys.stderr)

        if recent_in_page > 0:
            pages_with_recent += 1
            pages_old_in_a_row = 0
        else:
            pages_old_in_a_row += 1
            # 2 páginas seguidas sem nada recente → provavelmente saímos da janela.
            if pages_old_in_a_row >= 2 and pages_with_recent > 0:
                break
            # Se NUNCA achamos nada recente após 5 páginas, abortar — provável
            # que a ordem da API seja oldest-first e estamos no início histórico.
            if pages_old_in_a_row >= 5 and pages_with_recent == 0:
                print("AVISO: nenhuma data recente nas 5 primeiras páginas. "
                      "Possível ordenação oldest-first — ajustar estratégia.",
                      file=sys.stderr)
                break

    matched.sort(key=lambda m: (-m["score"], m.get("dataSessao", "")))

    valid_dates = [d for d in last_dates if d]
    payload = {
        "run_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lookback_days": lookback_days,
        "cutoff_date": cutoff.isoformat(),
        "endpoint": API_URL,
        "pages_fetched": page_idx + 1,
        "items_seen": len(seen_keys),
        "min_date_seen": min(valid_dates).isoformat() if valid_dates else None,
        "max_date_seen": max(valid_dates).isoformat() if valid_dates else None,
        "total_matched": len(matched),
        "articles": matched,
    }

    if dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2)[:4000])
        return payload

    out_dir = TCU_ROOT / today.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "tcu-filtered.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(f"GRAVADO: {out_path.relative_to(REPO_ROOT)} "
          f"({payload['total_matched']} matches em {payload['items_seen']} itens)")
    return payload


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lookback", type=int, default=DEFAULT_LOOKBACK_DAYS,
                    help=f"Janela em dias (padrão {DEFAULT_LOOKBACK_DAYS}).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Imprime amostra do payload e não grava arquivo.")
    args = ap.parse_args()
    run(args.lookback, args.dry_run)


if __name__ == "__main__":
    main()
