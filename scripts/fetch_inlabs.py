#!/usr/bin/env python3
"""
fetch_inlabs.py — autentica no INLabs (Imprensa Nacional) e baixa o DOU em XML.

Credenciais:
- Lê INLABS_EMAIL e INLABS_PASSWORD das variáveis de ambiente.
- Em fallback, lê de um arquivo .env (KEY=VALUE) na raiz do repositório.

Dados:
- DOU_ROOT (env) ou <repo>/dou/ por padrão. Cria <DOU_ROOT>/<YYYY-MM-DD>/<...>.zip
  e extrai os XMLs em <DOU_ROOT>/<YYYY-MM-DD>/extracted/.

Uso:
    python3 scripts/fetch_inlabs.py                  # hoje + catch-up de 7 dias
    python3 scripts/fetch_inlabs.py 2026-05-11
    python3 scripts/fetch_inlabs.py --catchup 14
    python3 scripts/fetch_inlabs.py --sections DO1,DO2
"""
import argparse
import os
import sys
import time
import zipfile
from datetime import date, timedelta
from pathlib import Path

import requests

BASE = "https://inlabs.in.gov.br"
LOGIN_URL = f"{BASE}/logar.php"
DL_URL = f"{BASE}/index.php?p={{date}}&dl={{file}}"
DEFAULT_SECTIONS = ("DO1", "DO2", "DO1E", "DO2E")

# O login no INLabs falha de forma intermitente (~1 a cada 4 execuções
# agendadas, historicamente) com o cookie de sessão simplesmente ausente na
# resposta — sem qualquer 4xx/5xx que indicasse credencial inválida. Antes,
# uma falha aqui matava a execução do dia inteira (DOU+DEJT+TCU) sem nenhuma
# nova tentativa. Repetir o POST de login costuma resolver.
LOGIN_MAX_ATTEMPTS = int(os.environ.get("INLABS_LOGIN_MAX_ATTEMPTS", "3"))
LOGIN_RETRY_DELAY_SECS = int(os.environ.get("INLABS_LOGIN_RETRY_DELAY_SECS", "45"))

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DOU_ROOT = Path(os.environ.get("DOU_ROOT", REPO_ROOT / "dou"))
LOG_PATH = Path(os.environ.get("FETCH_LOG", REPO_ROOT / "logs" / "fetch_inlabs.log"))


def log(msg: str) -> None:
    line = f"[{date.today().isoformat()}] {msg}"
    print(line, file=sys.stderr)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def load_credentials() -> tuple[str, str]:
    email = os.environ.get("INLABS_EMAIL", "").strip()
    pwd = os.environ.get("INLABS_PASSWORD", "").strip()
    if email and pwd:
        return email, pwd
    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == "INLABS_EMAIL" and not email:
                email = v.strip()
            elif k.strip() == "INLABS_PASSWORD" and not pwd:
                pwd = v.strip()
    if not email or not pwd:
        sys.exit("ERRO: INLABS_EMAIL/INLABS_PASSWORD ausentes (env vars ou .env na raiz do repo).")
    return email, pwd


def login(session: requests.Session, email: str, password: str) -> str:
    payload = {"email": email, "password": password}
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    last_error = "motivo desconhecido"
    for attempt in range(1, LOGIN_MAX_ATTEMPTS + 1):
        try:
            session.post(LOGIN_URL, data=payload, headers=headers, timeout=30)
            cookie = session.cookies.get("inlabs_session_cookie")
        except requests.RequestException as exc:
            cookie = None
            last_error = f"erro de rede ({exc})"
        else:
            if not cookie:
                last_error = "cookie 'inlabs_session_cookie' ausente na resposta"

        if cookie:
            if attempt > 1:
                log(f"Autenticado no INLabs na tentativa {attempt}/{LOGIN_MAX_ATTEMPTS}.")
            else:
                log("Autenticado no INLabs.")
            return cookie

        if attempt < LOGIN_MAX_ATTEMPTS:
            log(f"login falhou (tentativa {attempt}/{LOGIN_MAX_ATTEMPTS}): {last_error}. "
                f"nova tentativa em {LOGIN_RETRY_DELAY_SECS}s.")
            session.cookies.clear()
            time.sleep(LOGIN_RETRY_DELAY_SECS)

    sys.exit(
        f"ERRO: falha de autenticação no INLabs após {LOGIN_MAX_ATTEMPTS} tentativas "
        f"({last_error})."
    )


def download(session: requests.Session, cookie: str, day: str, section: str, dest_dir: Path) -> Path | None:
    fname = f"{day}-{section}.zip"
    dest = dest_dir / fname
    if dest.exists() and dest.stat().st_size > 0:
        log(f"  já baixado: {fname}")
        return dest
    url = DL_URL.format(date=day, file=fname)
    headers = {"Cookie": f"inlabs_session_cookie={cookie}", "origem": "736372697074"}
    r = session.get(url, headers=headers, stream=True, timeout=180)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    with dest.open("wb") as fh:
        for chunk in r.iter_content(chunk_size=64 * 1024):
            fh.write(chunk)
    log(f"  baixado: {fname} ({dest.stat().st_size // 1024} KB)")
    return dest


def extract(zip_path: Path, out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            if not name.lower().endswith(".xml"):
                continue
            target = out_dir / Path(name).name
            if target.exists():
                count += 1
                continue
            with zf.open(name) as src, target.open("wb") as dst:
                dst.write(src.read())
            count += 1
    return count


def target_dates(explicit: str | None, catchup: int) -> list[str]:
    if explicit:
        return [explicit]
    today = date.today()
    return [(today - timedelta(days=i)).isoformat() for i in range(catchup + 1)]


def process_day(session: requests.Session, cookie: str, day: str, sections: tuple[str, ...]) -> dict:
    day_dir = DOU_ROOT / day
    extract_dir = day_dir / "extracted"
    day_dir.mkdir(parents=True, exist_ok=True)
    log(f"Processando {day}")
    zips_ok: list[str] = []
    xml_total = 0
    for section in sections:
        try:
            z = download(session, cookie, day, section, day_dir)
            if z is None:
                continue
            zips_ok.append(z.name)
            xml_total += extract(z, extract_dir)
        except Exception as exc:
            log(f"  ERRO em {day}-{section}.zip: {exc}")
    if not zips_ok:
        log(f"  sem publicação em {day}.")
        return {"date": day, "status": "empty", "xmls": 0}
    return {"date": day, "status": "ok", "xmls": xml_total, "zips": zips_ok}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("date", nargs="?", help="Data YYYY-MM-DD (padrão: hoje + catch-up).")
    ap.add_argument("--catchup", type=int, default=7,
                    help="Dias anteriores além da data corrente quando data não é explícita (padrão: 7).")
    ap.add_argument("--sections", default=",".join(DEFAULT_SECTIONS),
                    help="Seções DOU a baixar, separadas por vírgula (padrão: DO1,DO2,DO1E,DO2E).")
    args = ap.parse_args()

    sections = tuple(s.strip().upper() for s in args.sections.split(",") if s.strip())
    days = target_dates(args.date, args.catchup)
    log(f"DOU_ROOT={DOU_ROOT} | datas={days} | seções={sections}")

    email, pwd = load_credentials()
    session = requests.Session()
    cookie = login(session, email, pwd)

    summary = [process_day(session, cookie, d, sections) for d in days]
    ok = sum(1 for s in summary if s["status"] == "ok")
    log(f"Concluído. {ok}/{len(summary)} dias com publicação processada.")
    for s in summary:
        log(f"  {s['date']}: {s['status']} — {s.get('xmls', 0)} XMLs")


if __name__ == "__main__":
    main()
