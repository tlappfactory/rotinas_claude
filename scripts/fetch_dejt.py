#!/usr/bin/env python3
"""
fetch_dejt.py — baixa os cadernos administrativos do DEJT (TRT-17, CSJT, TST).

URLs públicas servem APENAS a última edição (sem catch-up retroativo). O script
detecta a data de DISPONIBILIZAÇÃO interna do PDF, calcula a data de PUBLICAÇÃO
(art. 4º, §3º da Lei 11.419/2006 — primeiro dia útil seguinte à disponibilização)
e arquiva por data de PUBLICAÇÃO em <DEJT_ROOT>/<YYYY-MM-DD>/.

Convenção: a chave de pasta é a data de publicação (= dia em que a edição
"circula" e em que os prazos começam a correr), não a data de disponibilização
estampada no cabeçalho do PDF. Ex.: disponibilizado em 12/05 às 19h ⇒ publicado
em 13/05 ⇒ pasta dejt/2026-05-13/. Isso evita a confusão histórica em que a
chefia esperava ver "DEJT de 13/05" na pasta dejt/2026-05-12/.

Validação de freshness (opcional): se a env var DEJT_EXPECTED_PUBLICATION_DATE
estiver definida (YYYY-MM-DD) e a publicação detectada for ANTERIOR à esperada,
o caderno é marcado como `pdf_stale` em vez de `ok` — sinal para re-tentar mais
tarde ou alertar.

Uso:
    python3 scripts/fetch_dejt.py
    DEJT_EXPECTED_PUBLICATION_DATE=2026-05-14 python3 scripts/fetch_dejt.py
"""
import os
import re
import subprocess
import sys
import unicodedata
from datetime import date, timedelta
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DEJT_ROOT = Path(os.environ.get("DEJT_ROOT", REPO_ROOT / "dejt"))
LOG_PATH = Path(os.environ.get("FETCH_DEJT_LOG", REPO_ROOT / "logs" / "fetch_dejt.log"))

EXPECTED_PUB_RAW = (os.environ.get("DEJT_EXPECTED_PUBLICATION_DATE") or "").strip()
try:
    EXPECTED_PUB: date | None = date.fromisoformat(EXPECTED_PUB_RAW) if EXPECTED_PUB_RAW else None
except ValueError:
    EXPECTED_PUB = None

SOURCES: dict[str, str] = {
    "trt17": "https://diario.jt.jus.br/cadernos/Diario_A_17.pdf",
    "csjt":  "https://diario.jt.jus.br/cadernos/Diario_A_CSJT.pdf",
    "tst":   "https://diario.jt.jus.br/cadernos/Diario_A_TST.pdf",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "application/pdf,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}

MESES = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "março": 3, "abril": 4,
    "maio": 5, "junho": 6, "julho": 7, "agosto": 8, "setembro": 9,
    "outubro": 10, "novembro": 11, "dezembro": 12,
}


def log(msg: str) -> None:
    print(msg, file=sys.stderr)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(f"[{date.today().isoformat()}] {msg}\n")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def next_business_day(d: date) -> date:
    """Próximo dia útil após `d`, pulando sábado e domingo.

    Feriados nacionais/locais não são considerados nesta versão — em véspera de
    feriado, a publicação real pode ser empurrada mais um dia útil. Quando isso
    ocorrer, a validação `DEJT_EXPECTED_PUBLICATION_DATE` marca como `pdf_stale`
    e o próximo run corrige.
    """
    nxt = d + timedelta(days=1)
    while nxt.weekday() >= 5:  # 5 = sábado, 6 = domingo
        nxt += timedelta(days=1)
    return nxt


def pdftotext_first_pages(pdf: Path, pages: int = 2) -> str:
    try:
        r = subprocess.run(["pdftotext", "-l", str(pages), "-layout", str(pdf), "-"],
                           capture_output=True, text=True, timeout=60, check=False)
        return r.stdout or ""
    except FileNotFoundError:
        log("AVISO: pdftotext (poppler-utils) não está instalado.")
        return ""
    except Exception as e:
        log(f"ERRO pdftotext em {pdf}: {e}")
        return ""


def detect_disponibilizacao_date(text: str) -> date | None:
    """Detecta a data de DISPONIBILIZAÇÃO do caderno DEJT (cabeçalho).

    Atenção: o DEJT distingue *disponibilização* (entrega no portal, ~19h do dia
    anterior) e *publicação* (primeiro dia útil seguinte, em que os prazos
    começam a correr — Lei 11.419/2006, art. 4º, §3º). Esta função extrai a
    primeira; a publicação é calculada por `next_business_day` no chamador.

    Estratégia em camadas (a primeira que casar vence):
      1. Cabeçalho oficial "Data da Disponibilização: <dia>, DD de MÊS de AAAA"
         que o DEJT estampa no topo de cada caderno.
      2. Variantes próximas ("Disponibilizado em ...", "Disponibilização em ...").
      3. Fallback antigo: primeiro "DD de MÊS de AAAA" / "DD/MM/AAAA" do PDF
         (sujeito ao bug histórico de capturar a data interna de um ato em
         vez da data do caderno; mantido só como último recurso).
    """
    norm = normalize(text)

    header_patterns = (
        r"data\s+da\s+disponibiliza[c]?ao\s*[:\-]?\s*"
        r"(?:[a-z\-]+\s*[,\-]?\s*)?"
        r"(\d{1,2})\s+de\s+([a-z]+)\s+de\s+(20\d{2})",
        r"disponibiliza[c]?ao\s+em\s*[:\-]?\s*"
        r"(\d{1,2})\s+de\s+([a-z]+)\s+de\s+(20\d{2})",
        r"disponibilizado\s+em\s*[:\-]?\s*"
        r"(\d{1,2})\s+de\s+([a-z]+)\s+de\s+(20\d{2})",
    )
    for pat in header_patterns:
        m = re.search(pat, norm)
        if m and m.group(2) in MESES:
            try:
                return date(int(m.group(3)), MESES[m.group(2)], int(m.group(1)))
            except ValueError:
                continue

    header_numeric = re.search(
        r"data\s+da\s+disponibiliza[c]?ao\s*[:\-]?\s*"
        r"(?:[a-z\-]+\s*[,\-]?\s*)?"
        r"(\d{1,2})/(\d{1,2})/(20\d{2})",
        norm,
    )
    if header_numeric:
        try:
            return date(int(header_numeric.group(3)),
                        int(header_numeric.group(2)),
                        int(header_numeric.group(1)))
        except ValueError:
            pass

    m = re.search(r"(\d{1,2})\s*de\s*([a-z]+)\s*de\s*(20\d{2})", norm)
    if m and m.group(2) in MESES:
        try:
            return date(int(m.group(3)), MESES[m.group(2)], int(m.group(1)))
        except ValueError:
            pass
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(20\d{2})\b", text)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            pass
    return None


def fetch_one(label: str, url: str) -> dict:
    """Baixa um caderno do DEJT.

    Status retornados (consumidos pelo parse_dejt.py para distinguir
    "ausência legítima de publicação" de "falha de acesso"):
      ok                  — PDF baixado com sucesso.
      duplicate           — PDF idêntico já existe em <publicacao>/.
      pdf_stale           — PDF baixado mas a publicação detectada é ANTERIOR à
                            esperada (DEJT_EXPECTED_PUBLICATION_DATE). Sinal de
                            que a edição do dia ainda não entrou no ar — re-tentar
                            mais tarde.
      no_publication      — servidor retornou objeto válido mas vazio/placeholder
                            (HTTP 200 + tamanho < THRESHOLD_BYTES OU content-type
                            não-PDF). Significa que o órgão NÃO publicou caderno
                            naquele dia — comportamento legítimo, sobretudo para
                            o CSJT (caderno esparso).
      http_<code>         — HTTP != 200. Falha real do servidor (404 transitório,
                            5xx etc.).
      network_error       — exceção na requisição (timeout, DNS, TLS).
      pdf_corrupt         — pdftotext não conseguiu extrair texto (PDF baixado
                            mas inválido).
    """
    log(f"Baixando {label}: {url}")
    try:
        r = requests.get(url, headers=HEADERS, timeout=180, stream=True)
    except Exception as e:
        log(f"  ERRO de rede: {e}")
        return {"label": label, "status": "network_error", "detail": str(e)}
    if r.status_code != 200:
        log(f"  HTTP {r.status_code}")
        return {"label": label, "status": f"http_{r.status_code}"}

    content_type = (r.headers.get("Content-Type") or "").lower()
    content_length_header = r.headers.get("Content-Length")
    log(f"  Content-Type: {content_type or '(ausente)'}; "
        f"Content-Length: {content_length_header or '(ausente)'}")

    tmp_dir = REPO_ROOT / ".tmp_dejt"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp = tmp_dir / f"{label}.pdf"
    with tmp.open("wb") as fh:
        for chunk in r.iter_content(chunk_size=64 * 1024):
            fh.write(chunk)
    size = tmp.stat().st_size
    log(f"  baixado: {size} bytes ({size // 1024} KB)")

    # Threshold: PDFs reais do DEJT têm pelo menos algumas dezenas de KB.
    # Abaixo disso, é placeholder/erro silencioso ou caderno sem matéria.
    THRESHOLD_BYTES = 8 * 1024
    is_pdf_content_type = "pdf" in content_type
    looks_like_pdf = False
    try:
        with tmp.open("rb") as fh:
            magic = fh.read(5)
        looks_like_pdf = magic.startswith(b"%PDF-")
    except Exception:
        pass

    if size < THRESHOLD_BYTES or (not is_pdf_content_type and not looks_like_pdf):
        log(f"  → no_publication (size={size}, ct={content_type or '?'}, "
            f"magic_pdf={looks_like_pdf})")
        tmp.unlink()
        return {
            "label": label,
            "status": "no_publication",
            "http_status": r.status_code,
            "content_type": content_type,
            "size_bytes": size,
            "magic_is_pdf": looks_like_pdf,
        }

    text = pdftotext_first_pages(tmp, pages=2)
    if not text.strip():
        log("  → pdf_corrupt (pdftotext não extraiu texto)")
        tmp.unlink()
        return {
            "label": label,
            "status": "pdf_corrupt",
            "size_bytes": size,
            "content_type": content_type,
        }

    disp_date = detect_disponibilizacao_date(text)
    if not disp_date:
        log("  AVISO: data de disponibilização não detectada no PDF; "
            "usando data corrente como fallback.")
        disp_date = date.today()
    publ_date = next_business_day(disp_date)
    log(f"  disponibilizado em: {disp_date.isoformat()} "
        f"→ publicado em: {publ_date.isoformat()}")

    base_record = {
        "label": label,
        "disponibilizacao": disp_date.isoformat(),
        "publicacao": publ_date.isoformat(),
        "date": publ_date.isoformat(),  # retrocompat: clientes antigos leem "date"
    }

    if EXPECTED_PUB and publ_date < EXPECTED_PUB:
        log(f"  → pdf_stale (publicação {publ_date} < esperada {EXPECTED_PUB})")
        tmp.unlink()
        return {**base_record, "status": "pdf_stale",
                "expected_publicacao": EXPECTED_PUB.isoformat(),
                "size_bytes": size, "content_type": content_type}

    target_dir = DEJT_ROOT / publ_date.isoformat()
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{label}.pdf"

    if target.exists() and target.stat().st_size == size:
        log(f"  já existe: {target.relative_to(REPO_ROOT)} (mesmo tamanho — skip)")
        tmp.unlink()
        return {**base_record, "status": "duplicate"}

    tmp.replace(target)
    log(f"  salvo: {target.relative_to(REPO_ROOT)}")
    return {**base_record, "status": "ok",
            "path": str(target.relative_to(REPO_ROOT)), "size_bytes": size}


def main() -> None:
    import json
    from datetime import datetime, timezone

    DEJT_ROOT.mkdir(parents=True, exist_ok=True)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    run_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    results = [fetch_one(label, url) for label, url in SOURCES.items()]
    log("\nResumo:")
    for r in results:
        log(f"  {r['label']}: {r['status']} {r.get('date','')}")

    # Persiste o resultado do run para o parse_dejt.py interpretar status
    # (no_publication vs http_xxx vs pdf_corrupt vs pdf_stale) ao montar
    # dejt-filtered.json.
    last_fetch = {
        "run_utc": run_iso,
        "expected_publicacao": EXPECTED_PUB.isoformat() if EXPECTED_PUB else None,
        "by_label": {r["label"]: r for r in results},
    }
    (DEJT_ROOT / "_last_fetch.json").write_text(
        json.dumps(last_fetch, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
