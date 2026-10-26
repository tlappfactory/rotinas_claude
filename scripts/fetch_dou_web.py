#!/usr/bin/env python3
"""
fetch_dou_web.py — plano B para o DOU quando o INLabs está fora do ar.

Lê o índice público da edição (https://www.in.gov.br/leiturajornal?data=DD-MM-AAAA&secao=do1|do2|do1e|do2e),
que embute os atos do dia num JSON (`<script id="params">`, chave `jsonArray`),
e grava um XML sintético por ato em <DOU_ROOT>/<YYYY-MM-DD>/extracted/, no
mesmo formato lido por parse_dou.py. Assim o filtro temático e o JSON de saída
são os mesmos do caminho INLabs; só muda a origem, registrada em
<DOU_ROOT>/<YYYY-MM-DD>/origem.json (parse_dou.py copia para o JSON filtrado).

Escopo deliberado: apenas a edição pedida (por padrão, a de hoje em Brasília).
Não reconstrói edições anteriores.

Diferenças em relação ao INLabs:
  - o índice traz só um trecho (~400 caracteres) de cada ato; o texto integral é
    buscado na página individual (/web/dou/-/<urlTitle>). Ato cuja página não
    abriu fica com o trecho e texto_truncated=true (o filtro enxerga só o trecho);
  - sem DO1E/DO2E garantidos (tenta-se; seção sem retorno não é erro);
  - `assina`/`cargo`/`ementa` não vêm separados (ficam dentro do texto);
  - o link do ato é o real (`urlTitle` já contém o content-id do portal).

Uso:
    python scripts/fetch_dou_web.py              # edição de hoje (Brasília)
    python scripts/fetch_dou_web.py 2026-10-26
"""
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DOU_ROOT = Path(os.environ.get("DOU_ROOT", REPO_ROOT / "dou"))
LOG_PATH = Path(os.environ.get("FETCH_LOG", REPO_ROOT / "logs" / "fetch_dou_web.log"))

INDEX_URL = "https://www.in.gov.br/leiturajornal?data={dia}&secao={secao}"
SECTIONS = ("do1", "do2", "do1e", "do2e")
USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/124.0 Safari/537.36")
MAX_ATTEMPTS = int(os.environ.get("DOU_WEB_MAX_ATTEMPTS", "3"))
RETRY_DELAY_SECS = int(os.environ.get("DOU_WEB_RETRY_DELAY_SECS", "20"))

ARTICLE_URL = "https://www.in.gov.br/web/dou/-/{slug}"
ENRICH_WORKERS = int(os.environ.get("DOU_WEB_WORKERS", "6"))
# Teto de tempo para buscar o texto integral dos atos; o que não der tempo
# fica com o trecho do índice (marcado como parcial).
ENRICH_BUDGET_SECS = int(os.environ.get("DOU_WEB_ENRICH_BUDGET_SECS", "900"))

PARAMS_RE = re.compile(r'<script[^>]*id="params"[^>]*>(.*?)</script>', re.S)
# Caracteres de controle proibidos em XML 1.0.
XML_INVALID_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def log(msg: str) -> None:
    line = f"[{datetime.now(ZoneInfo('America/Sao_Paulo')).strftime('%Y-%m-%d %H:%M')}] {msg}"
    print(line, file=sys.stderr)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def clean(text: str) -> str:
    return XML_INVALID_RE.sub(" ", text or "")


def fetch_section(session: requests.Session, dia_url: str, secao: str) -> list[dict] | None:
    """Itens da seção, [] se a seção não existe no dia, None se o portal falhou."""
    url = INDEX_URL.format(dia=dia_url, secao=secao)
    last_error = "motivo desconhecido"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = session.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
            if resp.status_code == 200:
                m = PARAMS_RE.search(resp.text)
                if not m:
                    last_error = "HTTP 200 sem <script id=\"params\"> (layout mudou?)"
                else:
                    return json.loads(m.group(1)).get("jsonArray") or []
            else:
                last_error = f"HTTP {resp.status_code}"
        except (requests.RequestException, ValueError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        if attempt < MAX_ATTEMPTS:
            log(f"{secao}: falhou ({last_error}); nova tentativa em {RETRY_DELAY_SECS}s "
                f"({attempt}/{MAX_ATTEMPTS})")
            time.sleep(RETRY_DELAY_SECS)
    log(f"{secao}: falha definitiva ({last_error})")
    return None


class _TextoDou(HTMLParser):
    """Extrai o texto da <div class="texto-dou"> (corpo do ato) de uma página do portal."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.done = False
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if self.done:
            return
        if tag == "div":
            classes = (dict(attrs).get("class") or "").split()
            if self.depth == 0 and "texto-dou" in classes:
                self.depth = 1
            elif self.depth:
                self.depth += 1
        elif self.depth and tag in ("p", "br", "tr", "li"):
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if self.done or not self.depth:
            return
        if tag == "div":
            self.depth -= 1
            if self.depth == 0:
                self.done = True
        elif tag in ("p", "tr", "li", "td", "th"):
            self.parts.append(" ")

    def handle_data(self, data):
        if self.depth and not self.done:
            self.parts.append(data)

    def texto(self) -> str:
        return re.sub(r"\s+", " ", "".join(self.parts)).strip()


def fetch_full_text(slug: str) -> str | None:
    """Texto integral do ato pela página individual; None se não deu para obter."""
    url = ARTICLE_URL.format(slug=slug)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=45)
            if resp.status_code == 200:
                parser = _TextoDou()
                parser.feed(resp.text)
                texto = parser.texto()
                if texto:
                    return texto
        except requests.RequestException:
            pass
        if attempt < MAX_ATTEMPTS:
            time.sleep(2 * attempt)
    return None


def enrich_items(itens: list[dict]) -> int:
    """Troca o trecho de `content` pelo texto integral; devolve quantos atos foram enriquecidos.

    Atos sem texto integral (falha ou tempo esgotado) ficam com o trecho e
    recebem `_parcial=True`."""
    deadline = time.time() + ENRICH_BUDGET_SECS

    def um(item: dict) -> bool:
        if time.time() > deadline or not item.get("urlTitle"):
            return False
        texto = fetch_full_text(str(item["urlTitle"]))
        if texto and len(texto) >= len(item.get("content") or ""):
            item["content"] = texto
            return True
        return False

    with ThreadPoolExecutor(max_workers=ENRICH_WORKERS) as pool:
        resultados = list(pool.map(um, itens))
    for item, ok in zip(itens, resultados):
        if not ok:
            item["_parcial"] = True
    return sum(resultados)


def to_xml(item: dict, pub_name: str, pub_date: str) -> bytes:
    """Ato do índice -> XML no formato que parse_dou.parse_xml_file entende."""
    categoria = clean(item.get("hierarchyStr", ""))
    art = ET.Element("article", {
        "id": clean(str(item.get("urlTitle", ""))),
        # name = urlTitle: parse_dou monta .../web/dou/-/<name>, que aqui é o link real.
        "name": clean(str(item.get("urlTitle", ""))),
        "pubName": pub_name,
        "pubDate": pub_date,
        "artType": clean(str(item.get("artType", ""))),
        "artCategory": categoria,
        "numberPage": clean(str(item.get("numberPage", ""))),
        "editionNumber": clean(str(item.get("editionNumber", ""))),
    })
    # Sem o texto integral da página do ato, resta o trecho (~400 caracteres) do índice.
    if item.get("_parcial", True):
        art.set("textoParcial", "1")
    body = ET.SubElement(art, "body")
    for tag, valor in (("Identifica", item.get("title", "")),
                       ("Titulo", item.get("titulo", "")),
                       ("SubTitulo", item.get("subTitulo", "")),
                       ("OrgaoDouSec", categoria),
                       ("Texto", item.get("content", ""))):
        ET.SubElement(body, tag).text = clean(str(valor))
    return ET.tostring(art, encoding="utf-8", xml_declaration=True)


def main() -> None:
    if len(sys.argv) > 1:
        dia = sys.argv[1]
    else:
        dia = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%Y-%m-%d")
    try:
        ano, mes, d = dia.split("-")
        datetime(int(ano), int(mes), int(d))
    except ValueError:
        sys.exit(f"ERRO: data inválida '{dia}' (use YYYY-MM-DD).")
    dia_url = f"{d}-{mes}-{ano}"
    pub_date = f"{d}/{mes}/{ano}"

    day_dir = DOU_ROOT / dia
    extracted = day_dir / "extracted"
    extracted.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    por_secao: dict[str, int] = {}
    falhas: list[str] = []
    completos = 0
    for secao in SECTIONS:
        itens = fetch_section(session, dia_url, secao)
        if itens is None:
            falhas.append(secao)
            continue
        pub_name = secao.upper()
        t0 = time.time()
        ok = enrich_items(itens)
        log(f"{secao}: texto integral de {ok}/{len(itens)} atos em {time.time() - t0:.0f}s")
        completos += ok
        for n, item in enumerate(itens):
            nome = f"{pub_name}_{n:04d}.xml"
            (extracted / nome).write_bytes(to_xml(item, pub_name, pub_date))
        por_secao[pub_name] = len(itens)
        log(f"{secao}: {len(itens)} atos")

    # DO1 e DO2 são obrigatórias; falha só nas extras (do1e/do2e) é tolerada.
    if not por_secao.get("DO1") and not por_secao.get("DO2"):
        sys.exit(f"ERRO: índice público do DOU de {dia} indisponível ou vazio "
                 f"(seções com falha: {', '.join(falhas) or 'nenhuma — edição sem atos'}).")

    (day_dir / "origem.json").write_text(json.dumps({
        "origem": "in.gov.br/leiturajornal (índice público; INLabs indisponível)",
        "coleta_alternativa": True,
        "atos_por_secao": por_secao,
        "atos_com_texto_integral": completos,
        "secoes_com_falha": falhas,
        "coletado_em": datetime.now(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"OK: {sum(por_secao.values())} atos em {dia} (seções com falha: {falhas or 'nenhuma'})")


if __name__ == "__main__":
    main()
