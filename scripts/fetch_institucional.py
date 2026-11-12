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
import sys
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
        if not itens:
            continue
        probe.append({"amostra_titulos": [i["titulo"][:90] for i in itens[:6]]})
        return {"status": "ok", "endpoint": tmpl.split("?")[0], "itens": itens, "probe": probe}
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
