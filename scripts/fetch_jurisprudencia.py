#!/usr/bin/env python3
"""
fetch_jurisprudencia.py — coleta estruturada de jurisprudência vinculante (STF/STJ).

Substitui a busca web genérica por feeds de notícias OFICIAIS dos tribunais,
filtrados por (a) sinal de precedente vinculante — repercussão geral, tema,
recurso repetitivo, tese, súmula vinculante — E (b) tema de interesse da SGP
(servidor público, remuneração, aposentadoria etc., reaproveitando o vocabulário
de parse_dou.py). Só o SINAL vai para o boletim: a tese em si exige leitura
humana do texto integral — o JSON traz título, data, link e o resumo da própria
fonte, nunca uma tese inferida.

Fontes (cada uma com candidatas em ordem; vale a primeira que responder):
  STF  noticias.stf.jus.br — API REST do WordPress (wp-json) e feed RSS
  STJ  portal de notícias   — feeds RSS candidatos

Cada fonte grava `status` (ok | no_feed | error), o endpoint que respondeu e, em
`probe`, o resultado HTTP de todos os endpoints tentados — para diagnóstico
remoto quando um portal muda de formato.

Grava: <JURIS_ROOT>/<YYYY-MM-DD>/jurisprudencia-filtered.json

Uso:
    python3 scripts/fetch_jurisprudencia.py [--lookback 7] [--dry-run]
"""
import argparse
import csv
import html
import io
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
JURIS_ROOT = Path(os.environ.get("JURIS_ROOT", REPO_ROOT / "jurisprudencia"))
sys.path.insert(0, str(SCRIPT_DIR))
from parse_dou import STRONG_KEYWORDS, normalize, match_patterns  # noqa: E402

TIMEOUT = 30
HEADERS = {"User-Agent": "rotinas-claude-trt17/1.0 (+boletim-normativo)",
           "Accept": "application/json, application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.5"}

SOURCES = {
    "stf": [
        # As URLs do portal são /postsnoticias/…: o tipo de post é customizado.
        ("wp", "https://noticias.stf.jus.br/wp-json/wp/v2/postsnoticias?per_page=100&after={after}"
               "&_fields=id,date,link,title,excerpt"),
        ("wp", "https://noticias.stf.jus.br/wp-json/wp/v2/posts?per_page=100&after={after}"
               "&_fields=id,date,link,title,excerpt"),
        ("rss", "https://noticias.stf.jus.br/feed/"),
    ],
    "stj": [
        # www.stj.jus.br responde 403 (WAF) a runners do GitHub; res.stj.jus.br expira.
        # Mantido como tentativa barata; a via viável é o CKAN de dados abertos.
        ("rss", "https://www.stj.jus.br/sites/portalp/Paginas/RSS.aspx"),
    ],
}

# (a) sinal de precedente vinculante
SINAL_VINCULANTE = [
    r"\brepercussao geral\b", r"\btema \d", r"\btemas? repetitivos?\b", r"\brecursos? repetitivos?\b",
    r"\bsumula vinculante\b", r"\bteses? (?:fixada|firmada|de repercussao)", r"\bprecedente qualificado\b",
    r"\bincidente de assuncao de competencia\b", r"\biac\b", r"\birdr\b",
]
# (b) tema adicional, além do vocabulário forte de parse_dou.py
TEMA_EXTRA = [
    r"\bservidor(?:es)? public", r"\bfuncionalismo\b", r"\bmagistrad", r"\bteto\b", r"\bremuneracao\b",
    r"\bvencimentos?\b", r"\bsubsidio\b", r"\bferias\b", r"\bgratificacao\b", r"\badicional\b",
    r"\bregime proprio\b", r"\bregime juridico unico\b", r"\btelework\b|\bteletrabalho\b",
    r"\bacumulacao\b", r"\bconcurso publico\b", r"\bjustica do trabalho\b",
]


def strip_html(t: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(t or ""))).strip()


def probe_get(url: str, probe: list, timeout: int = TIMEOUT, tentativas: int = 1) -> requests.Response | None:
    for n in range(1, tentativas + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            break
        except requests.RequestException as exc:
            if n < tentativas:
                continue
            probe.append({"url": url, "erro": f"{type(exc).__name__}: {exc}"[:200], "tentativas": n})
            return None
    try:
        probe.append({"url": url, "http": r.status_code, "content_type": r.headers.get("content-type", ""),
                      "bytes": len(r.content), "inicio": r.text[:300].replace("\n", " ")})
        return r if r.status_code == 200 else None
    except requests.RequestException:
        return None


def parse_wp(r: requests.Response) -> list[dict]:
    out = []
    for p in r.json():
        out.append({"data": (p.get("date") or "")[:10], "url": p.get("link", ""),
                    "titulo": strip_html((p.get("title") or {}).get("rendered", "")),
                    "resumo": strip_html((p.get("excerpt") or {}).get("rendered", ""))})
    return out


def parse_rss(r: requests.Response) -> list[dict]:
    root = ET.fromstring(r.content)
    out = []
    for it in root.iter():
        tag = it.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue
        g = lambda n: next((strip_html(e.text or "") for e in it if e.tag.split("}")[-1] == n and (e.text or "").strip()), "")
        link = g("link") or next((e.attrib.get("href", "") for e in it if e.tag.split("}")[-1] == "link"), "")
        raw = g("pubDate") or g("published") or g("updated")
        try:
            d = parsedate_to_datetime(raw).date().isoformat()
        except (TypeError, ValueError):
            d = raw[:10]
        out.append({"data": d, "url": link, "titulo": g("title"), "resumo": g("description") or g("summary")})
    return out


# URLs consultadas apenas para diagnóstico (ficam em `probe`), a fim de
# descobrir o formato certo quando um candidato acima não responde.
DESCOBERTA = {
    "stf": ["https://noticias.stf.jus.br/wp-json/wp/v2/types",
            "https://noticias.stf.jus.br/wp-json/wp/v2/postsnoticias?per_page=3&_fields=id,date,link,title"],
    "stj": [],
}


def descobrir_ckan_stj(probe: list) -> None:
    """Lista conjuntos/recursos do portal de dados abertos do STJ (CKAN) que
    tratam de precedentes — só diagnóstico, para escolher o recurso a consumir."""
    for q in ("repetitivo", "precedentes", "tema", "sumula"):
        r = probe_get("https://dadosabertos.web.stj.jus.br/api/3/action/package_search"
                      f"?q={q}&rows=10", [])
        if r is None:
            continue
        try:
            for pk in r.json()["result"]["results"]:
                probe.append({"ckan_q": q, "dataset": pk.get("name"), "titulo": pk.get("title"),
                              "atualizado": pk.get("metadata_modified"),
                              "recursos": [{"nome": x.get("name"), "formato": x.get("format"),
                                            "url": x.get("url")} for x in pk.get("resources", [])][:12]})
        except (ValueError, KeyError) as exc:
            probe.append({"ckan_q": q, "parse_erro": str(exc)[:150]})


CKAN_TEMAS = "https://dadosabertos.web.stj.jus.br/dataset/4238da2f-c07b-4c1a-b345-4402accacdcf/resource/{rid}/download/{nome}"
STJ_TEMAS_CSV = CKAN_TEMAS.format(rid="df29da13-7d6b-41ba-ad96-cd1a5bbd191c", nome="temas.csv")
STJ_DICIONARIO_CSV = CKAN_TEMAS.format(rid="d5e50514-6dba-4f1e-8557-94f135eae03b", nome="dicionario-temas.csv")
DATA_BR = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")
DATA_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
# Esquema do Temas.csv (dicionário oficial do conjunto "Precedentes qualificados").
COLUNAS_DATA_STJ = ("dataJulgamento", "dataPrimeiraAfetacao", "dataPublicacaoAcordao")


def ler_csv(r: requests.Response) -> list[dict]:
    try:
        texto = r.content.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = r.content.decode("latin-1")
    cabecalho = texto.splitlines()[0] if texto else ""
    delim = max(";,\t|", key=cabecalho.count)
    linhas = []
    for row in csv.DictReader(io.StringIO(texto), delimiter=delim):
        # colunas a mais viram chave None -> lista; colunas a menos viram None
        linhas.append({(k if k is not None else "_extra"):
                       (" ".join(v) if isinstance(v, list) else (v or "")) for k, v in row.items()})
    return linhas


def para_iso(valor: str) -> str:
    """'2026-09-25T…' ou '25/9/2026' -> '2026-09-25'; vazio se não for data."""
    if (m := DATA_ISO.search(valor or "")):
        return m.group(0)
    if (m := DATA_BR.search(valor or "")):
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return ""


def datas_da_linha(linha: dict, colunas: tuple = COLUNAS_DATA_STJ) -> list[str]:
    return [d for c in colunas if (d := para_iso(linha.get(c, "")))]


def coletar_stj_ckan(lookback: int, probe: list) -> list[dict]:
    """Temas de precedentes qualificados do STJ (CKAN de dados abertos).

    O esquema das colunas é descoberto em tempo de execução: cabeçalho e
    amostra vão para `probe` e para o dicionário oficial do conjunto. Um item
    entra quando alguma data da linha cai na janela; o filtro de tema é feito
    depois, em `filtrar` (com o texto de todas as colunas)."""
    # CSV grande (milhares de linhas com texto longo): timeout folgado e retry
    r = probe_get(STJ_TEMAS_CSV, probe, timeout=150, tentativas=3)
    if r is None:
        return []
    try:
        linhas = ler_csv(r)
    except (csv.Error, UnicodeDecodeError) as exc:
        probe.append({"csv_erro": str(exc)[:200]})
        return []
    if not linhas:
        return []
    probe.append({"colunas": list(linhas[0].keys()), "linhas": len(linhas),
                  "amostra": [{k: (v or "")[:80] for k, v in l.items()} for l in linhas[:2]]})
    d = probe_get(STJ_DICIONARIO_CSV, probe, timeout=60, tentativas=2)
    if d is not None:
        try:
            probe.append({"dicionario": [{k: (v or "")[:120] for k, v in l.items()} for l in ler_csv(d)[:40]]})
        except (csv.Error, UnicodeDecodeError):
            pass
    desde = (date.today() - timedelta(days=lookback)).isoformat()
    recentes = sorted(((max(datas_da_linha(l), default=""), l) for l in linhas), key=lambda x: x[0], reverse=True)
    probe.append({"mais_recentes": [{"data": d, "tipo": l.get("tipoPrecedente"), "numero": l.get("numeroPrecedente"),
                                     "situacao": l.get("situacao")} for d, l in recentes[:5]]})
    itens = []
    for recente, l in recentes:
        if recente < desde:
            break
        tipo, num = (l.get("tipoPrecedente") or "").strip(), (l.get("numeroPrecedente") or "").strip()
        q, tese = (l.get("questaoSubmetidaAJulgamento") or "").strip(), (l.get("teseFirmada") or "").strip()
        itens.append({
            "data": recente,
            "url": ("https://processo.stj.jus.br/repetitivos/temas_repetitivos/pesquisa.jsp?"
                    f"novaConsulta=true&tipo_pesquisa=T&num_tema={num}" if num else
                    "https://processo.stj.jus.br/repetitivos/temas_repetitivos/"),
            "titulo": f"STJ — precedente qualificado ({tipo or '[verificar tipo na fonte]'}) nº {num or '[verificar nº na fonte]'}"
                      f" — situação: {(l.get('situacao') or '').strip() or '[verificar na fonte]'}",
            # tese_firmada é reproduzida literalmente do conjunto de dados oficial
            "resumo": f"Questão submetida a julgamento: {q[:700]}" + (f" | Tese firmada (texto da fonte): {tese[:900]}" if tese else ""),
            "assuntos": (l.get("Assuntos") or "").strip()[:200],
            "tese_firmada_fonte": tese[:2000],
        })
    return itens


def coletar(fonte: str, lookback: int) -> dict:
    after = (datetime.now(timezone.utc) - timedelta(days=lookback)).strftime("%Y-%m-%dT00:00:00")
    probe: list = []
    for kind, tmpl in SOURCES[fonte]:
        r = probe_get(tmpl.format(after=after), probe)
        if r is None:
            continue
        try:
            itens = parse_wp(r) if kind == "wp" else parse_rss(r)
        except (ValueError, ET.ParseError) as exc:
            probe[-1]["parse_erro"] = str(exc)[:200]
            continue
        if not itens and kind == "wp":       # rota existe mas vazia: tenta a próxima
            continue
        probe.append({"amostra_titulos": [i["titulo"][:90] for i in itens[:6]]})
        return {"status": "ok", "endpoint": tmpl.split("?")[0], "itens": itens, "probe": probe}
    for url in DESCOBERTA.get(fonte, []):
        probe_get(url, probe)
    if fonte == "stj":
        try:
            itens = coletar_stj_ckan(lookback, probe)
        except Exception as exc:  # diagnóstico: nunca derrubar a coleta inteira
            probe.append({"excecao": f"{type(exc).__name__}: {exc}"[:300]})
            itens = []
        if itens or any(p.get("colunas") for p in probe):
            return {"status": "ok", "endpoint": STJ_TEMAS_CSV, "itens": itens, "probe": probe}
    houve_erro = any("erro" in p for p in probe)
    return {"status": "error" if houve_erro else "no_feed", "itens": [], "probe": probe}


def filtrar(itens: list[dict], desde: str) -> tuple[list[dict], int]:
    sel, fora = [], 0
    for it in itens:
        if it["data"] and it["data"] < desde:
            fora += 1
            continue
        texto = normalize(f"{it['titulo']} {it['resumo']}")
        sinais = [p.strip("\\b") for p in SINAL_VINCULANTE if re.search(p, texto)]
        temas = sorted(set(match_patterns(texto, STRONG_KEYWORDS)) |
                       ({"tema_servidor_remuneracao"} if any(re.search(p, texto) for p in TEMA_EXTRA) else set()))
        if sinais and temas:
            sel.append({**it, "sinais_vinculantes": sinais, "temas": temas,
                        "aviso": "tese não extraída: carece de leitura humana do texto integral"})
    return sel, fora


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lookback", type=int, default=7)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    hoje = date.today()
    desde = (hoje - timedelta(days=a.lookback)).isoformat()
    payload = {"run_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "lookback_days": a.lookback, "desde": desde, "fontes": {}, "articles": []}
    for fonte in SOURCES:
        res = coletar(fonte, a.lookback)
        sel, fora = filtrar(res["itens"], desde)
        payload["fontes"][fonte] = {"status": res["status"], "endpoint": res.get("endpoint"),
                                    "itens_vistos": len(res["itens"]), "fora_da_janela": fora,
                                    "selecionados": len(sel), "probe": res["probe"]}
        payload["articles"] += [{"fonte": fonte.upper(), **s} for s in sel]
        print(f"{fonte}: {res['status']} vistos={len(res['itens'])} selecionados={len(sel)}")
        for p in res["probe"]:
            print("   probe", json.dumps(p, ensure_ascii=False))
    payload["total_matched"] = len(payload["articles"])
    if a.dry_run:
        print(json.dumps(payload["articles"][:3], ensure_ascii=False, indent=2))
        return
    out = JURIS_ROOT / hoje.isoformat()
    out.mkdir(parents=True, exist_ok=True)
    (out / "jurisprudencia-filtered.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"gravado: {out}/jurisprudencia-filtered.json")


if __name__ == "__main__":
    main()
