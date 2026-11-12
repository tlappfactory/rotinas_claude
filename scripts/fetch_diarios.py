#!/usr/bin/env python3
"""
fetch_diarios.py — coleta do DJEN (CSJT) e do Diário da Justiça Eletrônico do CNJ.

Fecha duas lacunas do boletim: (1) os acórdãos/decisões do CSJT publicados no
DJEN (Diário de Justiça Eletrônico Nacional) e (2) as decisões e atos do CNJ que
NÃO saem no DOU (o DOU só traz resoluções, recomendações e instruções normativas).

Fontes (cada uma com candidatas em ordem; vale a primeira que responder):
  djen_csjt  API pública do DJEN (comunicaapi.pje.jus.br), siglaTribunal=CSJT
  djen_cnj   API pública do DJEN, siglaTribunal=CNJ
  dje_cnj    candidatas HTML/RSS do portal do CNJ (diagnóstico em `probe`)

IMPORTANTE — formato não verificado a partir do sandbox do Claude (o egresso para
esses hosts é bloqueado lá; só o runner do GitHub Actions alcança). Por isso cada
fonte grava `status` (ok | no_feed | error) e `probe` com o HTTP de todos os
endpoints tentados, no mesmo padrão de fetch_jurisprudencia.py. Um `status` ≠ ok
NUNCA deve ser lido como "sem novidades": o boletim declara a fonte como não
consultada.

Filtro: só ficam itens que casam com o vocabulário temático da SGP
(STRONG_KEYWORDS de parse_dou.py + TEMA_EXTRA). Itens do DJEN são, em regra,
comunicações de processos; por LGPD guardamos apenas dados públicos do ato
(tipo, classe, órgão, nº do processo, data, link e um trecho curto do texto) e
descartamos qualquer item marcado como segredo de justiça/sigilo.

Grava: <DIARIOS_ROOT>/<YYYY-MM-DD>/diarios-filtered.json

Uso:
    python3 scripts/fetch_diarios.py [--lookback 4] [--dry-run]
"""
import argparse
import html
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DIARIOS_ROOT = Path(os.environ.get("DIARIOS_ROOT", REPO_ROOT / "diarios"))
sys.path.insert(0, str(SCRIPT_DIR))
from parse_dou import STRONG_KEYWORDS, WEAK_KEYWORDS, normalize, match_patterns  # noqa: E402
from perfis import CFG as PERFIL_CFG, PERFIL, arquivo  # noqa: E402

TIMEOUT = 40
PAGINA_MAX = 100         # itens por página do DJEN
PAGINAS_MAX = 15         # teto de segurança por fonte/janela
TRECHO_MAX = 1500        # chars de texto guardados por item
HEADERS = {"User-Agent": "rotinas-claude-trt17/1.0 (+boletim-normativo)",
           "Accept": "application/json, application/rss+xml, application/xml, text/html;q=0.8, */*;q=0.5"}

DJEN_API = "https://comunicaapi.pje.jus.br/api/v1/comunicacao"
# O CNJ deixou de publicar no DJEN em 2020; seu DJe é o sistema próprio em cnj.jus.br/dje.
DJEN_SIGLAS = {"djen_csjt": "CSJT"}

TEMA_EXTRA = [
    r"\bservidor(?:es)? public", r"\bmagistrad", r"\bteto\b", r"\bremuneracao\b", r"\bvencimentos?\b",
    r"\bsubsidio\b", r"\bgratificacao\b", r"\badicional\b", r"\bregime proprio\b",
    r"\bteletrabalho\b", r"\bacumulacao\b", r"\bconcurso publico\b", r"\bcarreira\b",
    r"\bquadro de pessoal\b", r"\bgestao de pessoas\b", r"\bfuncao comissionada\b",
    r"\bcargo em comissao\b", r"\bplano de cargos\b", r"\bpolitica de pessoal\b",
]
if PERFIL != "sgp":
    TEMA_EXTRA = PERFIL_CFG["tema_extra"]
SIGILO = re.compile(r"segredo de justica|sigilo|tramita em segredo|sob sigilo")


def strip_html(t: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(t or ""))).strip()


def probe_get(url: str, probe: list, params: dict | None = None):
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
    except requests.RequestException as exc:
        probe.append({"url": url, "erro": f"{type(exc).__name__}: {exc}"[:200]})
        return None
    probe.append({"url": r.url[:220], "http": r.status_code, "content_type": r.headers.get("content-type", ""),
                  "bytes": len(r.content), "inicio": r.text[:200].replace("\n", " ")})
    return r if r.status_code == 200 else None


def _g(d: dict, *chaves, default=""):
    for k in chaves:
        if d.get(k) not in (None, ""):
            return d[k]
    return default


def normalizar_djen(item: dict, sigla: str) -> dict | None:
    """Converte um item do DJEN no formato interno. Descarta sigiloso."""
    texto = strip_html(_g(item, "texto", "conteudo"))
    meta = normalize(" ".join(str(_g(item, k)) for k in
                              ("tipoComunicacao", "tipoDocumento", "nomeClasse", "classe", "meiocompleto"))
                     + " " + texto[:600])
    if item.get("segredoJustica") in (True, "S", "true", 1) or SIGILO.search(meta):
        return None
    return {
        "fonte": sigla,
        "id": str(_g(item, "id", "hash")),
        "data": str(_g(item, "data_disponibilizacao", "dataDisponibilizacao", "datadisponibilizacao"))[:10],
        "tipo": str(_g(item, "tipoDocumento", "tipoComunicacao", "tipo_comunicacao")),
        "classe": str(_g(item, "nomeClasse", "classe")),
        "orgao": str(_g(item, "nomeOrgao", "orgao")),
        "numero_processo": str(_g(item, "numero_processo", "numeroprocessocommascara", "numeroProcesso")),
        "titulo": " – ".join(x for x in (str(_g(item, "tipoDocumento", "tipoComunicacao")),
                                         str(_g(item, "nomeClasse", "classe"))) if x),
        "resumo": texto[:TRECHO_MAX],
        "texto_truncated": len(texto) > TRECHO_MAX,
        "url": str(_g(item, "link", "url")),
    }


def coletar_djen(sigla: str, ini: str, fim: str) -> dict:
    probe: list = []
    itens: list[dict] = []
    pagina = 1
    while pagina <= PAGINAS_MAX:
        r = probe_get(DJEN_API, probe, params={
            "siglaTribunal": sigla, "dataDisponibilizacaoInicio": ini, "dataDisponibilizacaoFim": fim,
            "pagina": pagina, "itensPorPagina": PAGINA_MAX})
        if r is None:
            break
        try:
            corpo = r.json()
        except ValueError:
            probe.append({"erro": "resposta não é JSON"})
            break
        lote = corpo.get("items") if isinstance(corpo, dict) else corpo
        if not isinstance(lote, list) or not lote:
            break
        for it in lote:
            n = normalizar_djen(it, sigla)
            if n:
                itens.append(n)
        total = corpo.get("count") if isinstance(corpo, dict) else None
        if len(lote) < PAGINA_MAX or (total and pagina * PAGINA_MAX >= total):
            break
        pagina += 1
    ok = any(p.get("http") == 200 for p in probe)
    houve_erro = any("erro" in p or p.get("http", 200) >= 400 for p in probe)
    status = "ok" if ok else ("error" if houve_erro else "no_feed")
    return {"status": status, "endpoint": DJEN_API, "itens": itens, "probe": probe}


DJE_CNJ_URL = "https://www.cnj.jus.br/dje/djeletronico?visaoId=tjdf.djeletronico.comum.internet.apresentacao.VisaoDiarioEletronicoInternetPorData"
PDF_MAX_BYTES = 60 * 1024 * 1024
BLOCOS_MAX = 40


def extrair_ultima_edicao(html_txt: str) -> dict | None:
    """Lê a tabela "Última Edição - DJ-e" da página pública do DJe do CNJ."""
    linha = re.search(r"<tbody>\s*<tr>(.*?)</tr>", html_txt, re.S)
    if not linha:
        return None
    tds = re.findall(r"<td[^>]*>(.*?)</td>", linha.group(1), re.S)
    if len(tds) < 4:
        return None
    link = re.search(r"href\s*=\s*'([^']+)'", tds[3])
    if not link:
        return None
    ano, numero, data = (strip_html(t) for t in tds[:3])
    dd, mm, aaaa = data.split("/")
    pdf = html.unescape(link.group(1)).replace("http://www.cnj.jus.br:80", "https://www.cnj.jus.br")
    return {"ano": ano, "numero": numero, "data": f"{aaaa}-{mm}-{dd}", "pdf": pdf}


def blocos_tematicos(texto: str) -> list[str]:
    """Separa o texto do caderno em blocos e fica com os que casam com o vocabulário SGP."""
    out = []
    for b in re.split(r"\n\s*\n", texto):
        b = re.sub(r"\s+", " ", b).strip()
        if len(b) < 80:
            continue
        n = normalize(b)
        if SIGILO.search(n):
            continue
        if match_patterns(n, STRONG_KEYWORDS) or any(re.search(p, n) for p in TEMA_EXTRA):
            out.append(b)
    return out


def coletar_dje_cnj() -> dict:
    """DJe do CNJ: baixa o PDF assinado da última edição (página pública) e extrai blocos temáticos."""
    probe: list = []
    r = probe_get(DJE_CNJ_URL, probe)
    if r is None:
        return {"status": "error", "endpoint": DJE_CNJ_URL, "itens": [], "probe": probe}
    ed = extrair_ultima_edicao(r.text)
    if not ed:
        probe.append({"erro": "tabela da última edição não encontrada (layout mudou?)"})
        return {"status": "error", "endpoint": DJE_CNJ_URL, "itens": [], "probe": probe}
    probe.append({"edicao": ed})
    try:
        pdf = requests.get(ed["pdf"], headers=HEADERS, timeout=120)
    except requests.RequestException as exc:
        probe.append({"erro": f"download do PDF: {type(exc).__name__}: {exc}"[:200]})
        return {"status": "error", "endpoint": DJE_CNJ_URL, "itens": [], "probe": probe}
    probe.append({"pdf_http": pdf.status_code, "bytes": len(pdf.content)})
    if pdf.status_code != 200 or not pdf.content.startswith(b"%PDF") or len(pdf.content) > PDF_MAX_BYTES:
        probe.append({"erro": "PDF inválido, ausente ou grande demais"})
        return {"status": "error", "endpoint": DJE_CNJ_URL, "itens": [], "probe": probe}
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "dje.pdf"
        f.write_bytes(pdf.content)
        try:
            txt = subprocess.run(["pdftotext", "-layout", str(f), "-"], capture_output=True, text=True,
                                 timeout=180, check=True).stdout
        except (OSError, subprocess.SubprocessError) as exc:
            probe.append({"erro": f"pdftotext: {type(exc).__name__}: {exc}"[:200]})
            return {"status": "error", "endpoint": DJE_CNJ_URL, "itens": [], "probe": probe}
    blocos = blocos_tematicos(txt)
    probe.append({"chars_texto": len(txt), "blocos_tematicos": len(blocos)})
    itens = [{"fonte": "DJE_CNJ", "id": f"DJ{ed['numero']}_{ed['ano']}#{i}", "data": ed["data"],
              "tipo": "Diário da Justiça Eletrônico do CNJ", "classe": "", "orgao": "CNJ", "numero_processo": "",
              "titulo": f"DJe CNJ nº {ed['numero']}/{ed['ano']}",
              "resumo": b[:TRECHO_MAX], "texto_truncated": len(b) > TRECHO_MAX, "url": ed["pdf"]}
             for i, b in enumerate(blocos[:BLOCOS_MAX], 1)]
    return {"status": "ok", "endpoint": DJE_CNJ_URL, "itens": itens, "probe": probe,
            "edicao": f"{ed['numero']}/{ed['ano']}", "data_edicao": ed["data"]}


def filtrar(itens: list[dict], desde: str) -> tuple[list[dict], int]:
    sel, fora = [], 0
    for it in itens:
        if it["data"] and it["data"] < desde:
            fora += 1
            continue
        texto = normalize(f"{it['titulo']} {it['resumo']}")
        temas = sorted(set(match_patterns(texto, STRONG_KEYWORDS)) | set(match_patterns(texto, WEAK_KEYWORDS))
                       | ({"tema_servidor_remuneracao"} if any(re.search(p, texto) for p in TEMA_EXTRA) else set()))
        fortes = set(match_patterns(texto, STRONG_KEYWORDS)) or any(re.search(p, texto) for p in TEMA_EXTRA)
        if fortes:
            sel.append({**it, "temas": temas,
                        "aviso": "tese não extraída: carece de leitura humana do texto integral"})
    return sel, fora


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lookback", type=int, default=4)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    hoje = date.today()
    ini = (hoje - timedelta(days=a.lookback)).isoformat()
    fim = hoje.isoformat()
    payload = {"run_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "lookback_days": a.lookback, "desde": ini, "ate": fim, "fontes": {}, "articles": []}
    resultados = {k: coletar_djen(s, ini, fim) for k, s in DJEN_SIGLAS.items()}
    resultados["dje_cnj"] = coletar_dje_cnj()
    for nome, res in resultados.items():
        sel, fora = filtrar(res["itens"], ini)
        payload["fontes"][nome] = {"status": res["status"], "endpoint": res.get("endpoint"),
                                   "itens_vistos": len(res["itens"]), "fora_da_janela": fora,
                                   "selecionados": len(sel), "probe": res["probe"],
                                   **{k: res[k] for k in ("edicao", "data_edicao") if k in res}}
        payload["articles"] += [{"origem": nome, **s} for s in sel]
        print(f"{nome}: {res['status']} vistos={len(res['itens'])} selecionados={len(sel)}")
        for p in res["probe"]:
            print("   probe", json.dumps(p, ensure_ascii=False))
    payload["total_matched"] = len(payload["articles"])
    if a.dry_run:
        print(json.dumps(payload["articles"][:3], ensure_ascii=False, indent=2))
        return
    out = DIARIOS_ROOT / hoje.isoformat()
    out.mkdir(parents=True, exist_ok=True)
    (out / arquivo("diarios-filtered")).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"gravado: {out}/{arquivo('diarios-filtered')}")


if __name__ == "__main__":
    main()
