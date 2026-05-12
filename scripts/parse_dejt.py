#!/usr/bin/env python3
"""
parse_dejt.py — extrai texto dos PDFs do DEJT e filtra por temas SGP.

Reutiliza o vocabulário (STRONG_KEYWORDS / WEAK_KEYWORDS) e a normalização
do parse_dou.py para consistência com o filtro do DOU.

Particionamento: tenta separar o caderno em "atos" via padrões de cabeçalho
(PORTARIA Nº, ATO Nº, RESOLUÇÃO Nº, etc.). Se não encontrar nenhum cabeçalho,
trata o caderno como bloco único.

Lê:    <DEJT_ROOT>/<YYYY-MM-DD>/{trt17,csjt,tst}.pdf
Grava: <DEJT_ROOT>/<YYYY-MM-DD>/dejt-filtered.json
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DEJT_ROOT = Path(os.environ.get("DEJT_ROOT", REPO_ROOT / "dejt"))

# Reutiliza vocabulário e helpers do parse_dou.py
sys.path.insert(0, str(SCRIPT_DIR))
from parse_dou import (  # noqa: E402
    STRONG_KEYWORDS, WEAK_KEYWORDS, normalize, match_patterns,
)

# Mapa source → órgão emissor canônico (para o JSON)
SOURCE_TO_ORGAO = {
    "trt17": "Tribunal Regional do Trabalho da 17ª Região",
    "csjt":  "Conselho Superior da Justiça do Trabalho",
    "tst":   "Tribunal Superior do Trabalho",
}

# Padrões de cabeçalho de ato (início de linha). Aceita siglas/unidades arbitrárias
# entre o tipo e o número (ex.: "PORTARIA PRESI Nº 139", "ATO PRESI SECOR nº 44").
ATO_HEADER_RE = re.compile(
    r"^[ \t]*(?P<header>"
    r"(?:PORTARIA(?:\s+CONJUNTA)?"
    r"|ATO(?:\s+CONJUNTO|\s+DA\s+PRESID[EÊ]NCIA|\s+DELIBERATIVO|\s+DECLARAT[OÓ]RIO)?"
    r"|RESOLU[CÇ][AÃ]O(?:\s+ADMINISTRATIVA|\s+CONJUNTA)?"
    r"|PROVIMENTO|EDITAL|DESPACHO|DECIS[AÃ]O"
    r"|INSTRU[CÇ][AÃ]O\s+NORMATIVA|ORDEM\s+DE\s+SERVI[CÇ]O"
    r"|RECOMENDA[CÇ][AÃ]O|CONVOCA[CÇ][AÃ]O|EXTRATO"
    r")"
    r"\b[^\n]{0,250}"
    r"(?:N[°º.]?\s*\d|DE\s+\d{1,2}\s+DE\s+[A-ZÇ]+\s+DE\s+\d{4})"
    r"[^\n]*"
    r")",
    re.IGNORECASE | re.MULTILINE,
)


def pdf_to_text(pdf_path: Path) -> str:
    try:
        r = subprocess.run(
            ["pdftotext", "-layout", str(pdf_path), "-"],
            capture_output=True, text=True, timeout=300, check=False,
        )
        return r.stdout or ""
    except FileNotFoundError:
        print("ERRO: pdftotext (poppler-utils) não está instalado.", file=sys.stderr)
        return ""


def split_into_atos(text: str) -> list[dict]:
    """Particiona o texto em atos baseando-se em cabeçalhos típicos."""
    matches = list(ATO_HEADER_RE.finditer(text))
    if not matches:
        return [{"identifica": "[caderno inteiro — sem cabeçalhos detectados]",
                 "text": text}]
    atos = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk = text[start:end].strip()
        first_line = chunk.split("\n", 1)[0].strip()[:250]
        atos.append({"identifica": first_line, "text": chunk[:6000]})
    return atos


def process_pdf(pdf_path: Path, source_label: str) -> dict:
    text = pdf_to_text(pdf_path)
    if not text:
        return {"source": source_label, "status": "empty_or_no_pdftotext",
                "total_atos": 0, "matched_atos": 0, "articles": [],
                "headers_sample": [], "pdf_text_chars": 0}

    orgao_canonico = SOURCE_TO_ORGAO.get(source_label, source_label)
    atos = split_into_atos(text)

    # Sample dos cabeçalhos detectados (primeiros 80 chars) para diagnóstico
    headers_sample = [a["identifica"][:80] for a in atos[:30] if a.get("identifica")]

    matched = []
    for a in atos:
        text_norm = normalize(a["text"])
        strong_hits = match_patterns(text_norm, STRONG_KEYWORDS)
        weak_hits = match_patterns(text_norm, WEAK_KEYWORDS)
        if not strong_hits and len(weak_hits) < 2:
            continue
        score = 10 + 5 * len(strong_hits) + 1 * len(weak_hits)
        matched.append({
            "source": source_label,
            "orgao": orgao_canonico,
            "identifica": a["identifica"],
            "text_resumo": a["text"][:1200],
            "strong_keywords": sorted(set(strong_hits)),
            "weak_keywords": sorted(set(weak_hits)),
            "score": score,
        })
    matched.sort(key=lambda m: -m["score"])
    return {
        "source": source_label,
        "orgao": orgao_canonico,
        "pdf_size_kb": pdf_path.stat().st_size // 1024,
        "pdf_text_chars": len(text),
        "total_atos_detectados": len(atos),
        "matched_atos": len(matched),
        "headers_sample": headers_sample,
        "articles": matched,
    }


def load_last_fetch_status() -> dict:
    """Carrega o resumo do último fetch (escrito por fetch_dejt.py).
    Permite distinguir 'sem PDF na pasta' por causa de no_publication vs http_xxx."""
    last_fetch_path = DEJT_ROOT / "_last_fetch.json"
    if not last_fetch_path.exists():
        return {}
    try:
        return json.loads(last_fetch_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def process_date_dir(date_dir: Path, force: bool, last_fetch: dict) -> dict:
    out_path = date_dir / "dejt-filtered.json"
    if out_path.exists() and not force:
        return {"date": date_dir.name, "status": "already_parsed"}

    by_label = last_fetch.get("by_label", {}) if last_fetch else {}

    sources = {}
    all_articles = []
    for label in SOURCE_TO_ORGAO:
        pdf = date_dir / f"{label}.pdf"
        if not pdf.exists():
            fetch_info = by_label.get(label, {})
            fetch_status = fetch_info.get("status")
            if fetch_status == "no_publication":
                sources[label] = {
                    "status": "no_publication",
                    "explanation": (f"{SOURCE_TO_ORGAO[label]} não publicou caderno "
                                    f"administrativo nesta data (resposta HTTP "
                                    f"{fetch_info.get('http_status')} com "
                                    f"{fetch_info.get('size_bytes')} bytes, "
                                    f"content-type {fetch_info.get('content_type') or '?'})."),
                    "fetch_run_utc": last_fetch.get("run_utc"),
                }
            elif fetch_status and fetch_status.startswith("http_"):
                sources[label] = {
                    "status": "fetch_failed",
                    "http_status": fetch_status,
                    "explanation": f"Falha de acesso à URL do {SOURCE_TO_ORGAO[label]} "
                                   f"({fetch_status}). Conferência manual necessária.",
                    "fetch_run_utc": last_fetch.get("run_utc"),
                }
            elif fetch_status in ("network_error", "pdf_corrupt"):
                sources[label] = {
                    "status": "fetch_failed",
                    "reason": fetch_status,
                    "detail": fetch_info.get("detail", ""),
                    "explanation": f"Falha técnica baixando {SOURCE_TO_ORGAO[label]} "
                                   f"({fetch_status}). Conferência manual necessária.",
                    "fetch_run_utc": last_fetch.get("run_utc"),
                }
            else:
                sources[label] = {"status": "no_pdf"}
            continue
        result = process_pdf(pdf, label)
        sources[label] = {
            "status": "ok",
            "pdf_size_kb": result["pdf_size_kb"],
            "pdf_text_chars": result["pdf_text_chars"],
            "total_atos_detectados": result["total_atos_detectados"],
            "matched_atos": result["matched_atos"],
            "headers_sample": result["headers_sample"],
        }
        all_articles.extend(result["articles"])

    all_articles.sort(key=lambda a: (-a["score"], a["source"], a["identifica"]))
    payload = {
        "date": date_dir.name,
        "sources": sources,
        "total_matched": len(all_articles),
        "strong_keyword_tags": list(STRONG_KEYWORDS.keys()),
        "weak_keyword_tags": list(WEAK_KEYWORDS.keys()),
        "articles": all_articles,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    return {"date": date_dir.name, "status": "ok",
            "total_matched": len(all_articles)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("date", nargs="?", help="Data YYYY-MM-DD; omitida = todas.")
    ap.add_argument("--force", action="store_true",
                    help="Reprocessa mesmo se dejt-filtered.json já existe.")
    args = ap.parse_args()

    if args.date:
        date_dirs = [DEJT_ROOT / args.date]
    else:
        if not DEJT_ROOT.exists():
            sys.exit(f"Diretório DEJT não existe: {DEJT_ROOT}")
        date_dirs = sorted(p for p in DEJT_ROOT.iterdir() if p.is_dir())

    if not date_dirs or not date_dirs[0].exists():
        sys.exit(f"Nenhum diretório de data encontrado em {DEJT_ROOT}.")

    last_fetch = load_last_fetch_status()
    for d in date_dirs:
        result = process_date_dir(d, args.force, last_fetch)
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
