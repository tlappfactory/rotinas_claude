#!/usr/bin/env python3
"""send_boletim.py — envia o Boletim Normativo COLEP por SMTP.

Lê o par de arquivos versionados pela Routine COLEP-01:

    boletins/<YYYY-MM-DD>.html   corpo rich-text
    boletins/<YYYY-MM-DD>.txt    alternativa plain-text

e envia como multipart/alternative. O assunto é derivado da data, no formato
fixo exigido pelo runbook:

    [BOLETIM COLEP] Rascunho – 2 de agosto de 2026

"Rascunho" permanece no assunto de propósito: o boletim segue pendente de
revisão humana antes da distribuição oficial às unidades da SGP (RA TRT-17
nº 4/2025). O que a automação entrega é a minuta ao revisor — não a
distribuição.

Configuração por variáveis de ambiente (no workflow, vindas de secrets):

    SMTP_HOST       obrigatório  ex.: smtp.trt17.jus.br
    SMTP_PORT       opcional     default 587 (starttls) / 465 (ssl)
    SMTP_USER       obrigatório
    SMTP_PASSWORD   obrigatório
    SMTP_SECURITY   opcional     starttls (default) | ssl | plain
    SMTP_FROM       opcional     default: SMTP_USER
    BOLETIM_TO      opcional     default: leonardo.donato@trt17.jus.br
                                 (aceita vários, separados por vírgula)

Uso:
    python scripts/send_boletim.py                    # boletim mais recente
    python scripts/send_boletim.py --data 2026-08-03
    python scripts/send_boletim.py --dry-run          # não envia, só valida
"""

from __future__ import annotations

import argparse
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOLETINS_DIR = ROOT / "boletins"
DEFAULT_TO = "leonardo.donato@trt17.jus.br"

MESES = [
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]


def env(nome: str, default: str = "") -> str:
    """Lê uma variável de ambiente tratando vazio como ausente.

    O GitHub Actions define a variável como string vazia quando o secret
    correspondente não existe — não a omite. Sem isso, um secret opcional
    não cadastrado sobrescreveria o default em vez de cair nele.
    """
    return (os.environ.get(nome) or "").strip() or default


def data_por_extenso(data: str) -> str:
    """2026-08-02 -> '2 de agosto de 2026'."""
    ano, mes, dia = (int(p) for p in data.split("-"))
    return f"{dia} de {MESES[mes - 1]} de {ano}"


def resolver_data(data: str | None) -> str:
    """Devolve a data-alvo: a informada, ou a do boletim mais recente."""
    if data:
        return data
    encontrados = sorted(p.stem for p in BOLETINS_DIR.glob("*.html"))
    if not encontrados:
        sys.exit(f"ERRO: nenhum boletim em {BOLETINS_DIR}/ — nada a enviar.")
    return encontrados[-1]


def ler_corpos(data: str) -> tuple[str, str]:
    html_path = BOLETINS_DIR / f"{data}.html"
    txt_path = BOLETINS_DIR / f"{data}.txt"
    faltando = [str(p.relative_to(ROOT)) for p in (html_path, txt_path) if not p.is_file()]
    if faltando:
        sys.exit(f"ERRO: arquivo(s) ausente(s): {', '.join(faltando)}")
    html = html_path.read_text(encoding="utf-8")
    texto = txt_path.read_text(encoding="utf-8")
    if not html.strip() or not texto.strip():
        sys.exit(f"ERRO: boletim de {data} está vazio — envio abortado.")
    return html, texto


def montar_mensagem(data: str, html: str, texto: str,
                    remetente: str, destinatarios: list[str]) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = f"[BOLETIM COLEP] Rascunho – {data_por_extenso(data)}"
    msg["From"] = remetente
    msg["To"] = ", ".join(destinatarios)
    msg.set_content(texto)
    msg.add_alternative(html, subtype="html")
    return msg


def enviar(msg: EmailMessage, destinatarios: list[str]) -> None:
    host = env("SMTP_HOST")
    user = env("SMTP_USER")
    senha = os.environ.get("SMTP_PASSWORD") or ""
    faltando = [n for n, v in (("SMTP_HOST", host), ("SMTP_USER", user),
                               ("SMTP_PASSWORD", senha)) if not v]
    if faltando:
        sys.exit(f"ERRO: secret(s) obrigatório(s) não configurado(s): {', '.join(faltando)}")

    seguranca = env("SMTP_SECURITY", "starttls").lower()
    if seguranca not in ("starttls", "ssl", "plain"):
        sys.exit(f"ERRO: SMTP_SECURITY inválido: {seguranca!r} "
                 "(use starttls, ssl ou plain)")
    porta_raw = env("SMTP_PORT")
    if porta_raw and not porta_raw.isdigit():
        sys.exit(f"ERRO: SMTP_PORT inválido: {porta_raw!r}")
    porta = int(porta_raw) if porta_raw else (465 if seguranca == "ssl" else 587)

    contexto = ssl.create_default_context()
    if seguranca == "ssl":
        servidor = smtplib.SMTP_SSL(host, porta, context=contexto, timeout=60)
    else:
        servidor = smtplib.SMTP(host, porta, timeout=60)
    with servidor:
        servidor.ehlo()
        if seguranca == "starttls":
            servidor.starttls(context=contexto)
            servidor.ehlo()
        servidor.login(user, senha)
        servidor.send_message(msg, to_addrs=destinatarios)


def main() -> None:
    parser = argparse.ArgumentParser(description="Envia o Boletim Normativo COLEP por SMTP.")
    parser.add_argument("--data", help="Data do boletim (YYYY-MM-DD). Default: o mais recente.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Valida e imprime o cabeçalho, sem enviar.")
    args = parser.parse_args()

    data = resolver_data(args.data)
    html, texto = ler_corpos(data)

    destinatarios = [e.strip() for e in env("BOLETIM_TO", DEFAULT_TO).split(",") if e.strip()]
    if not destinatarios:
        sys.exit("ERRO: BOLETIM_TO não resolveu nenhum destinatário.")
    remetente = env("SMTP_FROM") or env("SMTP_USER")
    if not remetente:
        # Em --dry-run o remetente é dispensável: o objetivo ali é validar que
        # a rotina produziu um boletim íntegro, não a configuração de SMTP.
        if not args.dry_run:
            sys.exit("ERRO: defina SMTP_FROM ou SMTP_USER.")
        remetente = "(SMTP_FROM/SMTP_USER não definido)"

    msg = montar_mensagem(data, html, texto, remetente, destinatarios)

    print(f"boletim: {data}")
    print(f"assunto: {msg['Subject']}")
    print(f"de:      {remetente}")
    print(f"para:    {', '.join(destinatarios)}")
    print(f"tamanho: html {len(html)} chars, texto {len(texto)} chars")

    if args.dry_run:
        print("--dry-run: nada foi enviado.")
        return

    enviar(msg, destinatarios)
    print("enviado.")


if __name__ == "__main__":
    main()
