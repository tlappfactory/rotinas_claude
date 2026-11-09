#!/usr/bin/env python3
"""
fetch_diarios.py — coleta do DJEN (CSJT) e do Diário da Justiça Eletrônico do CNJ.

Fecha duas lacunas do boletim: (1) os acórdãos/decisões do CSJT publicados no
DJEN (Diário de Justiça Eletrônico Nacional) e (2) as decisões e atos do CNJ que
NÃO saem no DOU (o DOU só traz resoluções, recomendações e instruções normativas).

Fontes (cada uma com candidatas em ordem; vale a primeira que responder):
  djen_csjt  API pública do DJEN (comunicaapi.pje.jus.br), siglaTribunal=CSJT
  djen_cnj   API pública do DJEN, siglaTribunal=CNJ
  dje_cnj    candidatas HTML/RSS do portal do CNJ (diagnóstico em `probe`)

IMPORTANTE — formato não verificado a partir do sandbox do Claude (o egresso para
esses hosts é bloqueado lá; só o runner do GitHub Actions alcança). Por isso cada
fonte grava `status` (ok | no_feed | error) e `probe` com o HTTP de todos os
endpoints tentados, no mesmo padrão de fetch_jurisprudencia.py. Um `status` ≠ ok
NUNCA deve ser lido como "sem novidades": o boletim declara a fonte como não
consultada.

Filtro: só ficam itens que casam com o vocabulário temático da SGP
(STRONG_KEYWORDS de parse_dou.py + TEMA_EXTRA). Itens do DJEN são, em regra,
comunicações de processos; por LGPD guardamos apenas dados públicos do ato
(tipo, classe, órgão, nº do processo, data, link e um trecho curto do texto) e
descartamos qualquer item marcado como segredo de justiça/sigilo.

Grava: <DIARIOS_ROOT>/<YYYY-MM-DD>/diarios-filtered.json

Uso:
    python3 scripts/fetch_diarios.py [--lookback 4] [--dry-run]
"""
import argparse
import html
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DIARIOS_ROOT = Path(os.environ.get("DIARIOS_ROOT", REPO_ROOT / "diarios"))
sys.path.insert(0, str(SCRIPT_DIR))
from parse_dou import STRONG_KEYWORDS, WEAK_KEYWORDS, normalize, match_patterns  # noqa: E402

TIMEOUT = 40
PAGINA_MAX = 100         # itens por página do DJEN
PAGINAS_MAX = 15         # teto de segurança por fonte/janela
TRECHO_MAX = 1500        # chars de texto guardados por item
HEADERS = {"User-Agent": "rotinas-claude-trt17/1.0 (+boletim-normativo)",
           "Accept": "application/json, application/rss+xml, application/xml, text/html;q=0.8, */*;q=0.5"}

DJEN_API = "https://comunicaapi.pje.jus.br/api/v1/comunicacao"
DJEN_SIGLAS = {"djen_csjt": "CSJT", "djen_cnj": "CNJ"}

# Portal do CNJ: candidatas sondadas (o formato exato é descoberto pelo `probe`).
CNJ_CANDIDATAS = [
    ("rss", "https://www.cnj.jus.br/feed/"),
    ("html", "https://www.cnj.jus.br/diario-da-justica-eletronico/"),
    ("html", "https://www.cnj.jus.br/atos-normativos/"),
]

TEMA_EXTRA = [
    r"\bservidor(?:es)? public", r"\bmagistrad", r"\bteto\b", r"\bremuneracao\b", r"\bvencimentos?\b",
    r"\bsubsidio\b", r"\bgratificacao\b", r"\badicional\b", r"\bregime proprio\b",
    r"\bteletrabalho\b", r"\bacumulacao\b", r"\bconcurso publico\b", r"\bcarreira\b",
    r"\bquadro de pessoal\b", r"\bgestao de pessoas\b", r"\bfuncao comissionada\b",
    r"\bcargo em comissao\b", r"\bplano de cargos\b", r"\bpolitica de pessoal\b",
]
SIGILO = re.compile(r"segredo de justica|sigilo|tramita em segredo|sob sigilo")


def strip_html(t: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(t or ""))).strip()


def probe_get(url: str, probe: list, params: dict | None = None):
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
    except requests.RequestException as exc:
        probe.append({"url": url, "erro": f"{type(exc).__name__}: {exc}"[:200]})
        return None
    probe.append({"url": r.url[:220], "http": r.status_code, "content_type": r.headers.get("content-type", ""),
                  "bytes": len(r.content), "inicio": r.text[:200].replace("\n", " ")})
    return r if r.status_code == 200 else None


def _g(d: dict, *chaves, default=""):
    for k in chaves:
        if d.get(k) not in (None, ""):
            return d[k]
    return default


def normalizar_djen(item: dict, sigla: str) -> dict | None:
    """Converte um item do DJEN no formato interno. Descarta sigiloso."""
    texto = strip_html(_g(item, "texto", "conteudo"))
    meta = normalize(" ".join(str(_g(item, k)) for k in
                              ("tipoComunicacao", "tipoDocumento", "nomeClasse", "classe", "meiocompleto"))
                     + " " + texto[:600])
    if item.get("segredoJustica") in (True, "S", "true", 1) or SIGILO.search(meta):
        return None
    return {
        "fonte": sigla,
        "id": str(_g(item, "id", "hash")),
        "data": str(_g(item, "data_disponibilizacao", "dataDisponibilizacao", "datadisponibilizacao"))[:10],
        "tipo": str(_g(item, "tipoDocumento", "tipoComunicacao", "tipo_comunicacao")),
        "classe": str(_g(item, "nomeClasse", "classe")),
        "orgao": str(_g(item, "nomeOrgao", "orgao")),
        "numero_processo": str(_g(item, "numero_processo", "numeroprocessocommascara", "numeroProcesso")),
        "titulo": " – ".join(x for x in (str(_g(item, "tipoDocumento", "tipoComunicacao")),
                                         str(_g(item, "nomeClasse", "classe"))) if x),
        "resumo": texto[:TRECHO_MAX],
        "texto_truncated": len(texto) > TRECHO_MAX,
        "url": str(_g(item, "link", "url")),
    }


def coletar_djen(sigla: str, ini: str, fim: str) -> dict:
    probe: list = []
    itens: list[dict] = []
    pagina = 1
    while pagina <= PAGINAS_MAX:
        r = probe_get(DJEN_API, probe, params={
            "siglaTribunal": sigla, "dataDisponibilizacaoInicio": ini, "dataDisponibilizacaoFim": fim,
            "pagina": pagina, "itensPorPagina": PAGINA_MAX})
        if r is None:
            break
        try:
            corpo = r.json()
        except ValueError:
            probe.append({"erro": "resposta não é JSON"})
            break
        lote = corpo.get("items") if isinstance(corpo, dict) else corpo
        if not isinstance(lote, list) or not lote:
            break
        for it in lote:
            n = normalizar_djen(it, sigla)
            if n:
                itens.append(n)
        total = corpo.get("count") if isinstance(corpo, dict) else None
        if len(lote) < PAGINA_MAX or (total and pagina * PAGINA_MAX >= total):
            break
        pagina += 1
    ok = any(p.get("http") == 200 for p in probe)
    houve_erro = any("erro" in p or p.get("http", 200) >= 400 for p in probe)
    status = "ok" if ok else ("error" if houve_erro else "no_feed")
    return {"status": status, "endpoint": DJEN_API, "itens": itens, "probe": probe}


def parse_rss(r: requests.Response) -> list[dict]:
    out = []
    root = ET.fromstring(r.content)
    for it in root.iter():
        if it.tag.split("}")[-1] not in ("item", "entry"):
            continue
        g = lambda n: next((strip_html(e.text or "") for e in it if e.tag.split("}")[-1] == n and (e.text or "").strip()), "")
        link = g("link") or next((e.attrib.get("href", "") for e in it if e.tag.split("}")[-1] == "link"), "")
        raw = g("pubDate") or g("published") or g("updated")
        try:
            d = parsedate_to_datetime(raw).date().isoformat()
        except (TypeError, ValueError):
            d = raw[:10]
        out.append({"fonte": "DJE_CNJ", "id": link, "data": d, "tipo": "", "classe": "", "orgao": "CNJ",
                    "numero_processo": "", "titulo": g("title"),
                    "resumo": (g("description") or g("summary"))[:TRECHO_MAX], "texto_truncated": False, "url": link})
    return out


def coletar_cnj_portal() -> dict:
    probe: list = []
    for kind, url in CNJ_CANDIDATAS:
        r = probe_get(url, probe)
        if r is None:
            continue
        if kind == "html":
            links = sorted(set(re.findall(r'href="([^"]+)"', r.text)))
            links = [l for l in links if re.search(r"dje|diario|\.pdf|caderno", l, re.I)]
            probe.append({"links_candidatos": links[:40]})
        if kind == "rss":
            r._content = re.sub(rb"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)", b"&amp;", r.content)
            try:
                itens = parse_rss(r)
            except ET.ParseError as exc:
                probe.append({"erro": f"RSS inválido: {exc}"[:150]})
                continue
            if itens:
                return {"status": "ok", "endpoint": url, "itens": itens, "probe": probe}
        # HTML: só registra no probe (formato a descobrir); não infere itens de páginas livres.
    houve_erro = any("erro" in p or p.get("http", 200) >= 400 for p in probe)
    return {"status": "error" if houve_erro else "no_feed", "endpoint": None, "itens": [], "probe": probe}


def filtrar(itens: list[dict], desde: str) -> tuple[list[dict], int]:
    sel, fora = [], 0
    for it in itens:
        if it["data"] and it["data"] < desde:
            fora += 1
            continue
        texto = normalize(f"{it['titulo']} {it['resumo']}")
        temas = sorted(set(match_patterns(texto, STRONG_KEYWORDS)) | set(match_patterns(texto, WEAK_KEYWORDS))
                       | ({"tema_servidor_remuneracao"} if any(re.search(p, texto) for p in TEMA_EXTRA) else set()))
        fortes = set(match_patterns(texto, STRONG_KEYWORDS)) or any(re.search(p, texto) for p in TEMA_EXTRA)
        if fortes:
            sel.append({**it, "temas": temas,
                        "aviso": "tese não extraída: carece de leitura humana do texto integral"})
    return sel, fora


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lookback", type=int, default=4)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    hoje = date.today()
    ini = (hoje - timedelta(days=a.lookback)).isoformat()
    fim = hoje.isoformat()
    payload = {"run_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "lookback_days": a.lookback, "desde": ini, "ate": fim, "fontes": {}, "articles": []}
    resultados = {k: coletar_djen(s, ini, fim) for k, s in DJEN_SIGLAS.items()}
    resultados["dje_cnj"] = coletar_cnj_portal()
    for nome, res in resultados.items():
        sel, fora = filtrar(res["itens"], ini)
        payload["fontes"][nome] = {"status": res["status"], "endpoint": res.get("endpoint"),
                                   "itens_vistos": len(res["itens"]), "fora_da_janela": fora,
                                   "selecionados": len(sel), "probe": res["probe"]}
        payload["articles"] += [{"origem": nome, **s} for s in sel]
        print(f"{nome}: {res['status']} vistos={len(res['itens'])} selecionados={len(sel)}")
        for p in res["probe"]:
            print("   probe", json.dumps(p, ensure_ascii=False))
    payload["total_matched"] = len(payload["articles"])
    if a.dry_run:
        print(json.dumps(payload["articles"][:3], ensure_ascii=False, indent=2))
        return
    out = DIARIOS_ROOT / hoje.isoformat()
    out.mkdir(parents=True, exist_ok=True)
    (out / "diarios-filtered.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"gravado: {out}/diarios-filtered.json")


if __name__ == "__main__":
    main()
