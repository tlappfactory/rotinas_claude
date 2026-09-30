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
    "aviso": {"destaque": false, "texto": "..."},      # opcional; destaque=true
                                                        # => caixa vermelha (fallback)
    "alto":          [{titulo, ementa, unidades, acao, fonte_url, fonte_titulo}],
    "medio":         [idem],
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
SEM_NOVIDADES = '<p><em>Sem novidades pertinentes nesta data.</em></p>'
CAMPOS = {
    "medio": ("titulo", "ementa", "unidades", "acao", "fonte_url", "fonte_titulo"),
    "alto": ("titulo", "ementa", "unidades", "acao", "fonte_url", "fonte_titulo"),
    "informativo": ("titulo", "ementa", "unidades", "fonte_url", "fonte_titulo"),
    "monitoramento": ("titulo", "status", "reflexo", "fonte_url", "fonte_titulo"),
}
SECOES = [
    ("alto", '<h3 style="color: #c0392b;">🔴 1. ALTO IMPACTO (ação imediata)</h3>', "1. ALTO IMPACTO"),
    ("medio", '<h3 style="color: #d68910;">🟡 2. MÉDIO IMPACTO (ciência)</h3>', "2. MÉDIO IMPACTO (ciência)"),
    ("informativo", '<h3 style="color: #2874a6;">🔵 3. INFORMATIVO (arquivo)</h3>', "3. INFORMATIVO (arquivo)"),
    ("monitoramento", '<h3 style="color: #1e8449;">🟢 4. EM MONITORAMENTO (TCU / Conselhos / STF / STJ)</h3>',
     "4. EM MONITORAMENTO (TCU / STF / STJ)"),
]
ROTULOS = {"ementa": "Ementa", "unidades": "Unidade(s)", "acao": "Ação sugerida",
           "status": "Status", "reflexo": "Possível reflexo"}


def validar(t: dict) -> None:
    for chave, campos in CAMPOS.items():
        for i, item in enumerate(t.get(chave, []), 1):
            falta = [c for c in campos if not str(item.get(c, "")).strip()]
            if falta:
                sys.exit(f"ERRO: {chave}[{i}] sem campo(s): {', '.join(falta)}")
    for c in ("data", "timestamp", "fontes_ok", "fontes_sem_retorno"):
        if not str(t.get(c, "")).strip():
            sys.exit(f"ERRO: triagem sem o campo '{c}'")


def bloco_html(item: dict, chave: str) -> str:
    mb = "6px" if chave in ("alto", "medio") else "4px"
    linhas = [f'<p style="margin: 0 0 {mb} 0;"><strong>{E(item["titulo"])}</strong></p>']
    for c in CAMPOS[chave][1:-2]:
        linhas.append(f'<p style="margin: 0 0 {mb} 0;"><strong>{ROTULOS[c]}:</strong> {E(item[c])}</p>')
    linhas.append('<p style="margin: 0;"><strong>Fonte:</strong> '
                  f'<a href="{E(item["fonte_url"])}">{E(item["fonte_titulo"])}</a></p>')
    return '<div style="margin-bottom: 16px;">\n  ' + '\n  '.join(linhas) + '\n</div>'


def aviso_html(aviso: dict | None) -> str:
    if not aviso or not aviso.get("texto"):
        return ""
    if aviso.get("destaque"):
        return ('<p style="border: 2px solid #c0392b; padding: 10px;">⚠ <strong>Aviso metodológico (em destaque):</strong> '
                f'{E(aviso["texto"])}</p>\n')
    return f'<p style="border: 1px solid #888; padding: 8px;"><strong>Aviso metodológico:</strong> {E(aviso["texto"])}</p>\n'


def renderizar_html(t: dict) -> str:
    tpl = (ROOT / "boletim-template.html").read_text(encoding="utf-8")
    cabeca = tpl.split('<h3 style="color: #c0392b;">')[0]
    marco = '<hr style="border: none; border-top: 2px solid #333; margin: 20px 0;">\n<h3 style="margin: 0 0 8px 0; font-size: 14px;">RESUMO ESTATÍSTICO'
    cauda = marco + tpl.split("RESUMO ESTATÍSTICO", 1)[1]
    aviso = aviso_html(t.get("aviso"))
    if aviso:
        h2 = '<hr style="border: none; border-top: 2px solid #333; margin: 20px 0;">\n<h2'
        cabeca = cabeca.replace(h2, aviso + h2, 1)
    partes = [cabeca]
    for chave, titulo, _ in SECOES:
        itens = t.get(chave, [])
        partes.append(titulo + "\n" + ("\n".join(bloco_html(i, chave) for i in itens) if itens else SEM_NOVIDADES) + "\n")
    corpo = "".join(partes) + cauda
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
         "Prezado(a) servidor(a), segue o Boletim Normativo. Conteúdo gerado por IA; requer revisão humana "
         "antes da distribuição oficial às unidades da SGP (RA TRT-17 nº 4/2025). Confira números, ementas e links na fonte.", ""]
    aviso = t.get("aviso") or {}
    if aviso.get("texto"):
        rot = "AVISO METODOLÓGICO (DESTAQUE)" if aviso.get("destaque") else "AVISO METODOLÓGICO"
        L += [f"{rot}: {aviso['texto']}", ""]
    for chave, _, titulo in SECOES:
        L += [titulo, ""]
        itens = t.get(chave, [])
        if not itens:
            L += ["Sem novidades pertinentes nesta data.", ""]
        for i in itens:
            L.append("* " + i["titulo"])
            for c in CAMPOS[chave][1:-2]:
                L.append(f"  {ROTULOS[c]}: {i[c]}")
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
