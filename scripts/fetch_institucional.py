#!/usr/bin/env python3
"""
fetch_institucional.py — notícias institucionais do CNJ, CSJT e TST (perfil SEGEST).

Cobre o que não sai no DOU nem no DEJT e é o dia a dia da SEGEST: Metas
Nacionais, Estratégia do Judiciário, Justiça em Números/e-Gestão, Prêmio CNJ de
Qualidade, Agenda 2030/PLS, acessibilidade, governança e gestão de riscos.

Lê feeds oficiais (WordPress wp-json ou RSS), em ordem de candidatos — vale o
primeiro que responder — e filtra pelo vocabulário da SEGEST (scripts/perfis.py):
>=1 termo forte (termos fracos só acompanham). O JSON traz só título, data, link e o
resumo da própria fonte; nunca tese/conteúdo inferido (carece de leitura humana).
Cada fonte grava `status` (ok | no_feed | error) e `probe` com o HTTP de cada
tentativa, para diagnóstico remoto quando um portal muda de formato.

Grava: <INSTITUCIONAL_ROOT>/<YYYY-MM-DD>/institucional-filtered-segest.json

Uso:
    BOLETIM_PERFIL=segest python3 scripts/fetch_institucional.py [--lookback 7] [--dry-run]
"""
import argparse
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from fetch_jurisprudencia import parse_rss, parse_wp, probe_get  # noqa: E402
from parse_dou import STRONG_KEYWORDS, WEAK_KEYWORDS, match_patterns, normalize  # noqa: E402
from perfis import PERFIL, arquivo  # noqa: E402

ROOT = Path(os.environ.get("INSTITUCIONAL_ROOT", SCRIPT_DIR.parent / "institucional"))

WP = "?per_page=100&after={after}&_fields=id,date,link,title,excerpt"
SOURCES = {
    "cnj": [("wp", "https://www.cnj.jus.br/wp-json/wp/v2/posts" + WP),
            ("rss", "https://www.cnj.jus.br/feed/")],
    "csjt": [("rss", "https://www.csjt.jus.br/web/csjt/rss"),
             ("rss", "https://www.csjt.jus.br/web/csjt/noticias?p_p_id=com_liferay_asset_publisher_web_portlet_AssetPublisherPortlet&p_p_lifecycle=2&p_p_resource_id=rss"),
             ("wp", "https://www.csjt.jus.br/wp-json/wp/v2/posts" + WP)],
    "tst": [("rss", "https://www.tst.jus.br/rss"),
            ("rss", "https://www.tst.jus.br/web/guest/noticias/-/asset_publisher/rss"),
            ("wp", "https://www.tst.jus.br/wp-json/wp/v2/posts" + WP)],
}
# Páginas só consultadas para diagnóstico (ficam em `probe`).
DESCOBERTA = {
    "cnj": ["https://www.cnj.jus.br/noticias/"],
    "csjt": ["https://www.csjt.jus.br/web/csjt/noticias"],
    "tst": ["https://www.tst.jus.br/noticias"],
}


def obter(url: str, probe: list):
    """GET com 2 novas tentativas (espera 8s) se o portal responder 202 vazio
    (aceite sem conteúdo, típico de desafio anti-robô). Se persistir, desiste:
    não se contorna o bloqueio (ver CLAUDE.md)."""
    for n in range(3):
        r = probe_get(url, probe)
        if r is not None or probe[-1].get("http") != 202 or n == 2:
            return r
        time.sleep(8)


# Páginas de listagem lidas por navegador real (Chromium headless, sem disfarce:
# o UA é o padrão do Chromium) quando feeds/HTTP simples falham. Autorizado pelo
# operador em 12/11/2026 para CSJT e TST; só leitura de páginas públicas.
LISTAGENS_NAVEGADOR = {
    "csjt": ["https://www.csjt.jus.br/web/csjt/noticias"],
    "tst": ["https://www.tst.jus.br/noticias"],
}
JS_LINKS = """() => [...document.querySelectorAll('a[href]')].map(a => {
  const bloco = a.closest('article, li, .card, .asset-abstract, .noticia, div') || a;
  return {href: a.href, texto: (a.innerText || '').trim(), bloco: (bloco.innerText || '').trim().slice(0, 400)};
}).filter(x => x.texto.length >= 25)"""
DATA_BR = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")


def coletar_navegador(fonte: str, probe: list) -> list[dict]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        probe.append({"navegador": "playwright não instalado"})
        return []
    itens, vistos = [], set()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(args=["--no-sandbox"], executable_path=os.environ.get("CHROMIUM_PATH") or None)
            page = browser.new_page()
            for url in LISTAGENS_NAVEGADOR.get(fonte, []):
                try:
                    resp = page.goto(url, wait_until="networkidle", timeout=60000)
                    page.wait_for_timeout(3000)
                    links = page.evaluate(JS_LINKS)
                    probe.append({"navegador": url, "http": resp.status if resp else None,
                                  "titulo_pagina": (page.title() or "")[:120], "links": len(links),
                                  "inicio": (page.inner_text("body") or "")[:200].replace("\n", " ")})
                except Exception as exc:  # noqa: BLE001 — diagnóstico, nunca derrubar a coleta
                    probe.append({"navegador": url, "erro": f"{type(exc).__name__}: {exc}"[:200]})
                    continue
                for l in links:
                    if l["href"] in vistos:
                        continue
                    vistos.add(l["href"])
                    m = DATA_BR.search(l["bloco"])
                    data = f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else ""
                    itens.append({"data": data, "url": l["href"], "titulo": l["texto"][:200],
                                  "resumo": re.sub(r"\s+", " ", l["bloco"])[:300],
                                  **({} if data else {"data_nao_identificada": True})})
            browser.close()
    except Exception as exc:  # noqa: BLE001
        probe.append({"navegador_erro": f"{type(exc).__name__}: {exc}"[:200]})
    return itens


def coletar(fonte: str, lookback: int) -> dict:
    after = (datetime.now(timezone.utc) - timedelta(days=lookback)).strftime("%Y-%m-%dT00:00:00")
    probe: list = []
    for kind, tmpl in SOURCES[fonte]:
        r = obter(tmpl.format(after=after), probe)
        if r is None:
            continue
        try:
            itens = parse_wp(r) if kind == "wp" else parse_rss(r)
        except (ValueError, ET.ParseError) as exc:
            probe[-1]["parse_erro"] = str(exc)[:200]
            continue
        if not itens:
            continue
        probe.append({"amostra_titulos": [i["titulo"][:90] for i in itens[:6]]})
        return {"status": "ok", "endpoint": tmpl.split("?")[0], "itens": itens, "probe": probe}
    if os.environ.get("INSTITUCIONAL_NAVEGADOR") == "1" and fonte in LISTAGENS_NAVEGADOR:
        itens = coletar_navegador(fonte, probe)
        if itens:
            probe.append({"amostra_titulos": [i["titulo"][:90] for i in itens[:6]]})
            return {"status": "ok", "endpoint": "navegador:" + LISTAGENS_NAVEGADOR[fonte][0], "itens": itens, "probe": probe}
    else:
        for url in DESCOBERTA.get(fonte, []):
            probe_get(url, probe)
    return {"status": "error" if any("erro" in p for p in probe) else "no_feed", "itens": [], "probe": probe}


def filtrar(itens: list[dict], desde: str) -> tuple[list[dict], int]:
    sel, fora = [], 0
    for it in itens:
        if it["data"] and it["data"] < desde:
            fora += 1
            continue
        texto = normalize(f"{it['titulo']} {it['resumo']}")
        fortes, fracas = match_patterns(texto, STRONG_KEYWORDS), match_patterns(texto, WEAK_KEYWORDS)
        if fortes:  # notícias são ruidosas: só termo forte (par de fracos trazia saúde/CPF/etc.)
            sel.append({**it, "temas": sorted(set(fortes)), "temas_fracos": sorted(set(fracas)),
                        "aviso": "só o resumo da fonte: carece de leitura humana do texto integral"})
    return sel, fora


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lookback", type=int, default=7)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if PERFIL != "segest":
        sys.exit("fetch_institucional.py só existe para o perfil segest (BOLETIM_PERFIL=segest).")
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
            print("   probe", json.dumps(p, ensure_ascii=False)[:400])
    payload["total_matched"] = len(payload["articles"])
    if a.dry_run:
        print(json.dumps(payload["articles"][:3], ensure_ascii=False, indent=2))
        return
    out = ROOT / hoje.isoformat()
    out.mkdir(parents=True, exist_ok=True)
    (out / arquivo("institucional-filtered")).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"gravado: {out}/{arquivo('institucional-filtered')}")


if __name__ == "__main__":
    main()
