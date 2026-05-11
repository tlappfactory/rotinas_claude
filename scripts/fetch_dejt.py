#!/usr/bin/env python3
"""
fetch_dejt.py — baixa os cadernos administrativos do DEJT (TRT-17, CSJT, TST).

URLs públicas servem APENAS a última edição (sem catch-up retroativo). O script
detecta a data interna do PDF e arquiva por data; se a mesma data já foi capturada,
não sobrescreve.

Uso:
    python3 scripts/fetch_dejt.py
"""
import os
import re
import subprocess
import sys
import unicodedata
from datetime import date
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DEJT_ROOT = Path(os.environ.get("DEJT_ROOT", REPO_ROOT / "dejt"))
LOG_PATH = Path(os.environ.get("FETCH_DEJT_LOG", REPO_ROOT / "logs" / "fetch_dejt.log"))

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


def detect_pub_date(text: str) -> date | None:
    """Detecta a data de publicação. Procura "DD de MES de AAAA" e "DD/MM/AAAA"."""
    norm = normalize(text)
    m = re.search(r"(\d{1,2})\s*de\s*([a-z]+)\s*de\s*(20\d{2})", norm)
    if m:
        d, mes, y = int(m.group(1)), m.group(2), int(m.group(3))
        if mes in MESES:
            try:
                return date(y, MESES[mes], d)
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
    log(f"Baixando {label}: {url}")
    try:
        r = requests.get(url, headers=HEADERS, timeout=180, stream=True)
    except Exception as e:
        log(f"  ERRO de rede: {e}")
        return {"label": label, "status": "network_error"}
    if r.status_code != 200:
        log(f"  HTTP {r.status_code}")
        return {"label": label, "status": f"http_{r.status_code}"}

    tmp_dir = REPO_ROOT / ".tmp_dejt"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp = tmp_dir / f"{label}.pdf"
    with tmp.open("wb") as fh:
        for chunk in r.iter_content(chunk_size=64 * 1024):
            fh.write(chunk)
    size = tmp.stat().st_size
    log(f"  baixado: {size // 1024} KB")

    if size < 1024:
        log("  AVISO: arquivo muito pequeno (provável bloqueio/erro do servidor).")
        tmp.unlink()
        return {"label": label, "status": "too_small"}

    text = pdftotext_first_pages(tmp, pages=2)
    pub_date = detect_pub_date(text)
    if not pub_date:
        log("  AVISO: data não detectada no PDF; usando data corrente como fallback.")
        pub_date = date.today()
    log(f"  data detectada: {pub_date.isoformat()}")

    target_dir = DEJT_ROOT / pub_date.isoformat()
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{label}.pdf"

    if target.exists() and target.stat().st_size == size:
        log(f"  já existe: {target.relative_to(REPO_ROOT)} (mesmo tamanho — skip)")
        tmp.unlink()
        return {"label": label, "status": "duplicate", "date": pub_date.isoformat()}

    tmp.replace(target)
    log(f"  salvo: {target.relative_to(REPO_ROOT)}")
    return {"label": label, "status": "ok", "date": pub_date.isoformat(),
            "path": str(target.relative_to(REPO_ROOT)), "size": size}


def main() -> None:
    DEJT_ROOT.mkdir(parents=True, exist_ok=True)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    results = [fetch_one(label, url) for label, url in SOURCES.items()]
    log("\nResumo:")
    for r in results:
        log(f"  {r['label']}: {r['status']} {r.get('date','')}")


if __name__ == "__main__":
    main()
