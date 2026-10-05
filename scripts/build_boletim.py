#!/usr/bin/env python3
"""build_boletim.py — renderiza o Boletim Normativo a partir da triagem.

Entrada:  triagem/<YYYY-MM-DD>.json   (itens já triados pela rotina)
Saída:    boletins/<YYYY-MM-DD>.html  e  boletins/<YYYY-MM-DD>.txt

A triagem fica FORA de boletins/ de propósito: o workflow send-boletim
dispara em push que toque boletins/**, e só o par html/txt deve fazê-lo.

Formato da triagem (todas as listas podem ser vazias):

  {
    "data": "2026-09-30",
    "timestamp": "30/09/2026, 11h35 (Brasília)",
    "aviso": {"destaque": false, "texto": "..."},      # opcional; NÃO é mais renderizado no e-mail; destaque=true
                                                        # => caixa vermelha (fallback)
    "alto":          [{titulo, ementa, unidades, acao, fonte_url, fonte_titulo}],
    "medio":         [idem],   # item pode ter "linhas": [str, ...] — detalhamento em
                               # lista (ex.: atos de nomeação do mesmo lote consolidados
                               # em um único bloco, cada ato numa linha)
    "informativo":   [{titulo, ementa, unidades, fonte_url, fonte_titulo}],
    "monitoramento": [{titulo, status, reflexo, fonte_url, fonte_titulo}],
    "fontes_ok": "...", "fontes_sem_retorno": "..."
  }

Uso:
    python scripts/build_boletim.py triagem/2026-09-30.json
    python scripts/build_boletim.py --data 2026-09-30
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from send_boletim import data_por_extenso  # noqa: E402

E = html.escape
CAMPOS = {
    "medio": ("titulo", "ementa", "unidades", "acao", "fonte_url", "fonte_titulo"),
    "alto": ("titulo", "ementa", "unidades", "acao", "fonte_url", "fonte_titulo"),
    "informativo": ("titulo", "ementa", "unidades", "fonte_url", "fonte_titulo"),
    "monitoramento": ("titulo", "status", "reflexo", "fonte_url", "fonte_titulo"),
}
# (chave, rótulo HTML, subtítulo HTML, cor, título no texto simples)
SECOES = [
    ("alto", "Alto impacto", "Ação imediata", "#9b2c2c", "1. ALTO IMPACTO"),
    ("medio", "Médio impacto", "Ciência e ajuste de rotina", "#a8650f", "2. MÉDIO IMPACTO (ciência)"),
    ("informativo", "Informativo", "Para arquivo e consulta", "#2c5282", "3. INFORMATIVO (arquivo)"),
    ("monitoramento", "Em monitoramento", "TCU, Conselhos, STF e STJ", "#276749", "4. EM MONITORAMENTO (TCU / STF / STJ)"),
]
SANS = "font-family: Arial, Helvetica, sans-serif;"
ROTULOS = {"ementa": "Ementa", "unidades": "Unidade(s)", "acao": "Ação sugerida",
           "status": "Status", "reflexo": "Possível reflexo"}


def validar(t: dict) -> None:
    for chave, campos in CAMPOS.items():
        for i, item in enumerate(t.get(chave, []), 1):
            if "linhas" in item and not (isinstance(item["linhas"], list) and all(isinstance(x, str) for x in item["linhas"])):
                sys.exit(f"ERRO: {chave}[{i}].linhas deve ser lista de textos")
            falta = [c for c in campos if not str(item.get(c, "")).strip()]
            if falta:
                sys.exit(f"ERRO: {chave}[{i}] sem campo(s): {', '.join(falta)}")
    for c in ("data", "timestamp", "fontes_ok", "fontes_sem_retorno"):
        if not str(t.get(c, "")).strip():
            sys.exit(f"ERRO: triagem sem o campo '{c}'")


def _linha(rotulo: str, texto: str) -> str:
    return (f'<p style="margin: 0 0 8px 0; font-size: 15px; line-height: 1.6; color: #333333;">'
            f'<span style="{SANS} font-size: 10px; letter-spacing: 1px; text-transform: uppercase; color: #7a7466;">{rotulo}</span><br>'
            f'{E(texto)}</p>')


def bloco_html(item: dict, chave: str, cor: str) -> str:
    p = [f'<h3 style="margin: 0 0 8px 0; font-size: 19px; line-height: 1.3; font-weight: bold; color: #1a1a1a;">{E(item["titulo"])}</h3>']
    if item.get("unidades"):
        p.append(f'<p style="margin: 0 0 10px 0; {SANS} font-size: 11px; letter-spacing: 1px; text-transform: uppercase; color: {cor};">'
                 f'{E(item["unidades"].replace(", ", " · "))}</p>')
    if chave == "monitoramento":
        p.append(_linha("Status", item["status"]))
        p.append(_linha("Possível reflexo", item["reflexo"]))
    else:
        p.append(f'<p style="margin: 0 0 8px 0; font-size: 15px; line-height: 1.6; color: #333333;">{E(item["ementa"])}</p>')
    if item.get("linhas"):
        lis = "".join(f'<li style="margin: 0 0 3px 0;">{E(x)}</li>' for x in item["linhas"])
        p.append(f'<ul style="margin: 0 0 10px 18px; padding: 0; font-size: 14px; line-height: 1.5; color: #444444;">{lis}</ul>')
    if item.get("acao"):
        p.append(f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin: 4px 0 10px 0;"><tr>'
                 f'<td style="border-left: 3px solid {cor}; padding: 2px 0 2px 12px; font-size: 15px; line-height: 1.5; font-style: italic; color: #333333;">'
                 f'<span style="{SANS} font-size: 10px; letter-spacing: 1px; text-transform: uppercase; font-style: normal; color: {cor};">Ação sugerida</span><br>'
                 f'{E(item["acao"])}</td></tr></table>')
    p.append(f'<p style="margin: 0; {SANS} font-size: 12px; color: #7a7466;">Fonte: '
             f'<a href="{E(item["fonte_url"])}" style="color: {cor};">{E(item["fonte_titulo"])}</a></p>')
    return ('<tr><td style="padding: 0 40px 22px 40px;">\n  ' + "\n  ".join(p) + '\n</td></tr>\n'
            '<tr><td style="padding: 0 40px 22px 40px;"><div style="border-top: 1px solid #e6e0d0; font-size: 0; line-height: 0;">&nbsp;</div></td></tr>')


def secao_html(rotulo: str, sub: str, cor: str, itens: list, chave: str) -> str:
    topo = (f'<tr><td style="padding: 34px 40px 18px 40px;">'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-top: 3px solid {cor};">'
            f'<tr><td style="padding-top: 12px; {SANS} font-size: 13px; letter-spacing: 2px; text-transform: uppercase; font-weight: bold; color: {cor};">'
            f'{rotulo} <span style="font-weight: normal; letter-spacing: 1px; color: #7a7466;">&nbsp;&middot;&nbsp; {sub}</span></td></tr>'
            f'</table></td></tr>\n')
    if not itens:
        return topo + ('<tr><td style="padding: 0 40px 10px 40px; font-size: 15px; font-style: italic; color: #666255;">'
                       'Sem novidades pertinentes nesta data.</td></tr>\n')
    return topo + "\n".join(bloco_html(i, chave, cor) for i in itens) + "\n"


def renderizar_html(t: dict) -> str:
    tpl = (ROOT / "boletim-template.html").read_text(encoding="utf-8")
    if "<!--SECOES-->" not in tpl:
        sys.exit("ERRO: marcador <!--SECOES--> ausente no template.")
    secoes = "".join(secao_html(r, sub, cor, t.get(ch, []), ch) for ch, r, sub, cor, _ in SECOES)
    corpo = tpl.replace("<!--SECOES-->", secoes)
    subs = {"{{DATA_POR_EXTENSO}}": data_por_extenso(t["data"]),
            "{{N_ALTO}}": str(len(t.get("alto", []))), "{{N_MEDIO}}": str(len(t.get("medio", []))),
            "{{N_INFO}}": str(len(t.get("informativo", []))),
            "{{N_MONITORAMENTO}}": str(len(t.get("monitoramento", []))),
            "{{LISTA_FONTES_OK}}": E(t["fontes_ok"]), "{{LISTA_FONTES_SEM_RETORNO}}": E(t["fontes_sem_retorno"]),
            "{{TIMESTAMP}}": E(t["timestamp"])}
    for k, v in subs.items():
        corpo = corpo.replace(k, v)
    if "{{" in corpo:
        sys.exit("ERRO: placeholder não substituído no template.")
    return corpo


def renderizar_txt(t: dict) -> str:
    L = [f"BOLETIM NORMATIVO — {data_por_extenso(t['data'])}", "",
         "Prezado(a) servidor(a), segue o Boletim Normativo.", ""]
    for chave, _, _, _, titulo in SECOES:
        L += [titulo, ""]
        itens = t.get(chave, [])
        if not itens:
            L += ["Sem novidades pertinentes nesta data.", ""]
        for i in itens:
            L.append("* " + i["titulo"])
            for c in CAMPOS[chave][1:-2]:
                L.append(f"  {ROTULOS[c]}: {i[c]}")
            L += [f"    - {x}" for x in i.get("linhas", [])]
            L += [f"  Fonte: {i['fonte_titulo']} — {i['fonte_url']}", ""]
    L += ["RESUMO ESTATÍSTICO",
          f"- Alto Impacto: {len(t.get('alto', []))}", f"- Médio Impacto: {len(t.get('medio', []))}",
          f"- Informativos: {len(t.get('informativo', []))}", f"- Em Monitoramento: {len(t.get('monitoramento', []))}",
          f"- Fontes consultadas: {t['fontes_ok']}", f"- Sem retorno relevante: {t['fontes_sem_retorno']}", "",
          "CONFORMIDADE: RA TRT-17 nº 4/2025, Resolução CNJ nº 615/2025, Ato CSJT nº 41/2025 e LGPD. Nenhum processo "
          "sigiloso ou sob segredo de justiça foi consultado. Itens marcados [carece de leitura humana do texto integral] "
          "ou [verificar nº na fonte] exigem conferência na fonte.", "",
          f"Boletim gerado pela rotina do Boletim Normativo (Claude AI) em {t['timestamp']}. Conteúdo sujeito a revisão "
          "humana antes de distribuição oficial."]
    return "\n".join(L) + "\n"


def main() -> None:
    p = argparse.ArgumentParser(description="Renderiza boletins/<data>.{html,txt} a partir da triagem.")
    p.add_argument("arquivo", nargs="?", help="triagem/<data>.json")
    p.add_argument("--data", help="atalho: usa triagem/<data>.json")
    p.add_argument("--saida", default=str(ROOT / "boletins"), help="diretório de saída (default: boletins/)")
    a = p.parse_args()
    caminho = Path(a.arquivo) if a.arquivo else ROOT / "triagem" / f"{a.data}.json" if a.data else None
    if not caminho or not caminho.is_file():
        sys.exit("ERRO: informe o arquivo de triagem (ou --data) existente.")
    t = json.loads(caminho.read_text(encoding="utf-8"))
    validar(t)
    saida = Path(a.saida)
    saida.mkdir(parents=True, exist_ok=True)
    (saida / f"{t['data']}.html").write_text(renderizar_html(t), encoding="utf-8")
    (saida / f"{t['data']}.txt").write_text(renderizar_txt(t), encoding="utf-8")
    print(f"gerado: {saida}/{t['data']}.html e .txt")


if __name__ == "__main__":
    main()
