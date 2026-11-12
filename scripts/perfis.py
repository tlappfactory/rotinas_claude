#!/usr/bin/env python3
"""perfis.py — perfis do Boletim Normativo Diário (SGP, SEGEST).

Cada perfil define: nomes, diretórios, sufixo dos JSONs filtrados, destinatário
e o vocabulário do filtro temático. O perfil ativo vem da variável de ambiente
`BOLETIM_PERFIL` (default `sgp`), de modo que os mesmos coletores servem aos dois
boletins: o workflow roda cada filtro uma vez por perfil.

O perfil `sgp` NÃO redefine vocabulário aqui: usa o que já está em parse_dou.py
(a fonte única do filtro SGP). Só o perfil `segest` traz vocabulário próprio,
derivado das competências do Regulamento da Secretaria (arts. 92, 94, 96 e 98):

  SEGEST (art. 92) — planejamento estratégico, metas nacionais, governança,
                     orçamento (prioridades estratégicas), pesquisas de clima e
                     de satisfação, relatórios gerenciais;
  DIEPE  (art. 94) — estatística (SIESPJ, Justiça em Números, e-Gestão, DataJud);
  NUGERP (art. 96) — gestão de riscos, de projetos e portfólio;
  SESAC  (art. 98) — Plano de Logística Sustentável, sustentabilidade,
                     acessibilidade e inclusão.

Os padrões são regex sobre texto normalizado (sem acento, minúsculo).
"""
from __future__ import annotations

import os

PERFIL = (os.environ.get("BOLETIM_PERFIL") or "sgp").strip().lower()

# Keywords FORTES da SEGEST — sozinhas já bastam para incluir o ato/item.
STRONG_SEGEST: dict[str, list[str]] = {
    "planejamento_estrategico": [
        r"\bplanejamento estrategico\b", r"\bplano estrategico\b", r"\bgestao estrategica\b",
        r"\bestrategia nacional do poder judiciario\b", r"\bestrategia judiciario\b",
        r"\bmacrodesafios?\b", r"\bobjetivos? estrategicos?\b", r"\bmapa estrategico\b",
        r"\bindicadores? estrategicos?\b", r"\bbalanced scorecard\b",
        r"\bgovernanca e gestao estrategica\b",
    ],
    "metas_nacionais": [
        r"\bmetas? nacionais?\b", r"\bmetas? do poder judiciario\b", r"\bmetas? estrategicas?\b",
        r"\bencontros? nacionais? do poder judiciario\b", r"\bpainel de metas\b",
    ],
    "governanca": [
        r"\bgovernanca judiciaria\b", r"\bgovernanca corporativa\b", r"\bgovernanca institucional\b",
        r"\bgovernanca publica\b", r"\bpolitica de governanca\b", r"\bsistema de governanca\b",
        r"\bgovernanca e gestao\b", r"\bprograma de integridade\b", r"\bplano de integridade\b",
        r"\bgestao da integridade\b", r"\bcolegiados? tematicos?\b",
    ],
    "gestao_riscos": [
        r"\bgestao de riscos?\b", r"\bpolitica de gestao de riscos?\b", r"\briscos?[- ]chave\b",
        r"\bmatriz de riscos?\b", r"\bapetite a riscos?\b", r"\bplano de tratamento de riscos?\b",
    ],
    "gestao_projetos": [
        r"\bgestao de projetos?\b", r"\bportfolio de projetos?\b", r"\bcarteira de projetos?\b",
        r"\bescritorio de projetos?\b", r"\bprojetos? estrategicos?\b",
        r"\bmetodologia de gestao de projetos?\b",
    ],
    "estatistica_judiciaria": [
        r"\bestatisticas? do poder judiciario\b", r"\bsistema de estatisticas\b", r"\bsiespj\b",
        r"\bjustica em numeros\b", r"\be-gestao\b", r"\bdatajud\b",
        r"\bbase nacional de dados do poder judiciario\b", r"\bdados estatisticos\b",
        r"\bindicadores? estatisticos?\b", r"\brelatorios? gerenciais?\b",
    ],
    "pesquisas_institucionais": [
        r"\bpesquisa de clima\b", r"\bclima organizacional\b", r"\bpesquisa de satisfacao\b",
        r"\bsatisfacao do usuario\b", r"\bpesquisa de percepcao\b",
    ],
    "sustentabilidade": [
        r"\bplano de logistica sustentavel\b", r"\blogistica sustentavel\b",
        r"\bresponsabilidade socioambiental\b", r"\bcontrata(?:cao|coes) sustentaveis?\b",
        r"\bcompras? sustentaveis?\b", r"\bcriterios? de sustentabilidade\b",
        r"\bagenda 2030\b", r"\bobjetivos de desenvolvimento sustentavel\b",
        r"\binventario de emissoes\b", r"\bemissoes? de (?:dioxido de )?carbono\b",
        r"\bpegada de carbono\b", r"\bgestao de residuos\b",
        r"\bpainel de indicadores institucionais de sustentabilidade\b",
    ],
    "acessibilidade_inclusao": [
        r"\bacessibilidade\b", r"\bpessoas? com deficiencia\b", r"\blei brasileira de inclusao\b",
        r"\btecnologia assistiva\b", r"\bdesenho universal\b", r"\bmobilidade reduzida\b",
        r"\blibras\b", r"\binclusao e acessibilidade\b", r"\bacessibilidade e inclusao\b",
    ],
}

# Keywords FRACAS — ajudam na classificação; sozinhas só incluem quando vierem
# com órgão emissor prioritário (DOU) ou em par (DEJT/TCU: >= 2 fracas).
WEAK_SEGEST: dict[str, list[str]] = {
    "estatistica_pesquisa": [r"\bestatistica\b", r"\bestatisticas\b", r"\bindicadores?\b",
                             r"\bpesquisa institucional\b", r"\bpainel\b"],
    "inovacao_processos": [r"\binovacao\b", r"\binovacoes\b", r"\blaboratorio de inovacao\b",
                           r"\bmapeamento de processos\b", r"\bgestao de processos\b",
                           r"\bmelhoria de processos\b", r"\bracionalizacao\b",
                           r"\bboas praticas\b", r"\bpremio\b"],
    "governanca_geral": [r"\bgovernanca\b", r"\bintegridade\b", r"\bcompliance\b",
                         r"\bcontroles? internos?\b", r"\bplano de acao\b"],
    "riscos_projetos": [r"\briscos?\b", r"\bprojetos?\b", r"\bportfolio\b"],
    "sustentabilidade_geral": [r"\bsustentabilidade\b", r"\bsustentaveis?\b", r"\bsocioambiental\b",
                               r"\bmeio ambiente\b", r"\bresiduos\b"],
    "inclusao_diversidade": [r"\binclusao\b", r"\bdiversidade\b", r"\bequidade\b",
                             r"\bdeficiencia\b", r"\bacessivel\b"],
    "orcamento_estrategia": [r"\bproposta orcamentaria\b", r"\bplano plurianual\b",
                             r"\bplanejamento\b", r"\bmetas?\b"],
}

# Órgãos emissores (DOU) cujas matérias entram mesmo sem keyword: só os que
# editam normas de governança do próprio Judiciário do Trabalho. TST, TCU, STF e
# STJ ficam de fora (volume de atos de pessoal sem relação com a SEGEST); suas
# matérias entram pelo vocabulário.
PRIORITY_ORGAOS_SEGEST: list[str] = [
    "csjt", "conselho superior da justica do trabalho",
    "cnj", "conselho nacional de justica",
    "trt da 17", "tribunal regional do trabalho da 17",
]

# Tipos de ato do DOU que, vindos de órgão NÃO prioritário, só geram ruído para a
# SEGEST: portarias de pessoal (citam nomes de unidades em designações), editais
# de notificação e atas de sessões (ex.: TCU, que reproduzem dezenas de ementas).
IGNORA_IDENTIFICA_SEGEST = r"\b(?:portaria(?:s)? de pessoal|edital de notificacao)\b|^ata\b"

PERFIS: dict[str, dict] = {
    "sgp": {
        "sigla": "SGP",
        "titulo": "Boletim Normativo Diário - SGP",
        "assunto": "Boletim Normativo SGP",   # prefixo fixo do assunto (filtros de e-mail)
        "secretaria": "Secretaria de Gestão de Pessoas",
        "sufixo": "",                      # inlabs-filtered.json, dejt-filtered.json…
        "triagem_dir": "triagem",
        "boletins_dir": "boletins",
        "destinatario_env": "BOLETIM_TO",
        "descarta_individuais_de_prioritarios": False,
        "ignora_identifica": "",
    },
    "segest": {
        "sigla": "SEGEST",
        "titulo": "Boletim Normativo Diário - SEGEST",
        "assunto": "Boletim Normativo SEGEST",
        "secretaria": "Secretaria de Governança e Gestão Estratégica",
        "sufixo": "-segest",              # inlabs-filtered-segest.json…
        "triagem_dir": "triagem-segest",
        "boletins_dir": "boletins-segest",
        "destinatario_env": "BOLETIM_TO_SEGEST",
        # Atos individuais de pessoal (aposentadoria, nomeação, designação) não
        # interessam à SEGEST nem quando vêm de CNJ/CSJT/TRT-17.
        "descarta_individuais_de_prioritarios": True,
        "strong": STRONG_SEGEST,
        "weak": WEAK_SEGEST,
        "priority_orgaos": PRIORITY_ORGAOS_SEGEST,
        # Termos extras dos coletores de DJe/DJEN e STF/STJ (no SGP: servidor,
        # remuneração…). Na SEGEST o vocabulário forte já cobre o tema.
        "tema_extra": [],
        "ignora_identifica": IGNORA_IDENTIFICA_SEGEST,
    },
}

if PERFIL not in PERFIS:
    raise SystemExit(f"BOLETIM_PERFIL inválido: {PERFIL!r} (use: {', '.join(PERFIS)})")

CFG = PERFIS[PERFIL]
SUFIXO: str = CFG["sufixo"]


def arquivo(base: str) -> str:
    """'inlabs-filtered' -> 'inlabs-filtered.json' (sgp) | 'inlabs-filtered-segest.json'."""
    return f"{base}{SUFIXO}.json"
