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

# Padrões de cabeçalho de ato (início de linha)
ATO_HEADER_RE = re.compile(
    r"^[ \t]*(?P<header>"
    r"PORTARIA\s+(?:GP|DGP|PRES|SEGECOP|SEINFO|COREP|CGEST)?\s*N[°º]?\s*\d+"
    r"|PORTARIA\s+CONJUNTA\s+N[°º]?\s*\d+"
    r"|ATO\s+(?:DA\s+PRESID[EÊ]NCIA\s+)?N[°º]?\s*\d+"
    r"|ATO\s+CONJUNTO\s+N[°º]?\s*\d+"
    r"|RESOLU[CÇ][AÃ]O\s+(?:ADMINISTRATIVA\s+)?N[°º]?\s*\d+"
    r"|PROVIMENTO\s+N[°º]?\s*\d+"
    r"|EDITAL\s+N[°º]?\s*\d+"
    r"|INSTRU[CÇ][AÃ]O\s+NORMATIVA\s+N[°º]?\s*\d+"
    r"|ORDEM\s+DE\s+SERVI[CÇ]O\s+N[°º]?\s*\d+"
    r"|DESPACHO\s+N[°º]?\s*\d+"
    r"|DECIS[AÃ]O\s+N[°º]?\s*\d+"
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
                "total_atos": 0, "matched_atos": 0, "articles": []}

    orgao_canonico = SOURCE_TO_ORGAO.get(source_label, source_label)
    atos = split_into_atos(text)

    matched = []
    for a in atos:
        text_norm = normalize(a["text"])
        strong_hits = match_patterns(text_norm, STRONG_KEYWORDS)
        weak_hits = match_patterns(text_norm, WEAK_KEYWORDS)
        # Inclusão: precisa de pelo menos uma strong OU duas weak distintas
        if not strong_hits and len(weak_hits) < 2:
            continue
        score = 10 + 5 * len(strong_hits) + 1 * len(weak_hits)  # base 10 por ser DEJT
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
        "total_atos_detectados": len(atos),
        "matched_atos": len(matched),
        "articles": matched,
    }


def process_date_dir(date_dir: Path, force: bool) -> dict:
    out_path = date_dir / "dejt-filtered.json"
    if out_path.exists() and not force:
        return {"date": date_dir.name, "status": "already_parsed"}

    sources = {}
    all_articles = []
    for label in SOURCE_TO_ORGAO:
        pdf = date_dir / f"{label}.pdf"
        if not pdf.exists():
            sources[label] = {"status": "no_pdf"}
            continue
        result = process_pdf(pdf, label)
        sources[label] = {
            "status": "ok",
            "pdf_size_kb": result["pdf_size_kb"],
            "total_atos_detectados": result["total_atos_detectados"],
            "matched_atos": result["matched_atos"],
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

    for d in date_dirs:
        result = process_date_dir(d, args.force)
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
