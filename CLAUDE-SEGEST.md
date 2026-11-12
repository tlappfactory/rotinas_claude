# Boletim Normativo Diário - SEGEST — TRT-17

Runbook da rotina da **Secretaria de Governança e Gestão Estratégica (SEGEST)**
do TRT da 17ª Região. É o gêmeo do boletim da SGP (`CLAUDE.md`): mesmas fontes,
mesmo bridge, mesmas regras de integridade — o que muda é o **filtro temático**,
as **unidades destinatárias**, os **arquivos** e o **envio**.

> **Regras comuns (valem aqui sem repetição):** leia em `CLAUDE.md` as seções
> *Conformidade obrigatória*, *Regras anti-alucinação*, *Linguagem da minuta —
> boletim limpo*, *Garantia de dados frescos do dia* (códigos de saída `0/10/11/12/13/14`
> e diagnóstico por `mcp__github__actions_list`), *Convenção de data do DEJT*,
> *Convenção de linguagem por fonte na minuta*, *Regra de transparência* e
> *LGPD e finalidade pública*. Onde este arquivo disser diferente, vale este.

## Execução autônoma (sessão diária agendada — SEGEST)

Quando a sessão pedir o boletim da SEGEST, executar ponta a ponta, sem pedir
confirmação, e **sem** rodar o pipeline da SGP:

1. Atualizar o repositório:
   ```bash
   if [ -d /home/user/rotinas_claude/.git ]; then
     git -C /home/user/rotinas_claude pull --ff-only
   else
     git clone https://github.com/tlappfactory/rotinas_claude /home/user/rotinas_claude
   fi
   ```
2. Garantir os dados do dia **do perfil SEGEST** (confere os JSONs `-segest`):
   ```bash
   bash /home/user/rotinas_claude/scripts/ensure_bridge_data.sh --perfil=segest
   ```
   Tratar os códigos de saída exatamente como em `CLAUDE.md` (inclusive o `12`:
   disparar `fetch-dou.yml` por `mcp__github__actions_run_trigger` e reexecutar com
   `--wait-only --perfil=segest`). O workflow do bridge gera os dois perfis numa
   só execução; se a SGP já rodou hoje mas faltam os `-segest`, o script redispara.
3. Ler os JSONs do dia (ou o mais recente, com escalonamento visível como em `CLAUDE.md`):

   | Fonte | Arquivo |
   |---|---|
   | DOU S1/S2/1E/2E | `dou/<YYYY-MM-DD>/inlabs-filtered-segest.json` |
   | DEJT TRT-17 / CSJT / TST | `dejt/<YYYY-MM-DD>/dejt-filtered-segest.json` |
   | Acórdãos do TCU | `tcu/<YYYY-MM-DD>/tcu-filtered-segest.json` |
   | DJe do CNJ / DJEN (CSJT) | `diarios/<YYYY-MM-DD>/diarios-filtered-segest.json` |
   | Notícias STF/STJ | `jurisprudencia/<YYYY-MM-DD>/jurisprudencia-filtered-segest.json` |

   Os campos e o significado de `status` são os mesmos dos JSONs da SGP
   (`CLAUDE.md`, "Fontes a consultar"). **Não** ler os JSONs sem sufixo: são do
   filtro da SGP e não passam pelo vocabulário da SEGEST.
4. Complementar com WebSearch **só** jurisprudência/atos de impacto vinculante
   ou fallback das fontes que falharam (como em `CLAUDE.md`). Consultas úteis:
   `CNJ metas nacionais Poder Judiciário [ANO]`, `Estratégia Nacional do Poder Judiciário [ANO]`,
   `CNJ Justiça em Números [ANO]`, `CSJT planejamento estratégico Justiça do Trabalho [ANO]`.
5. Triar cada item (regras abaixo), gravar `triagem-segest/<YYYY-MM-DD>.json`
   (**mesmo formato** do cabeçalho de `scripts/build_boletim.py`; fora de
   `boletins-segest/`, para não disparar o envio) e renderizar/publicar:
   ```bash
   cd /home/user/rotinas_claude
   python3 scripts/build_boletim.py --perfil segest --data <YYYY-MM-DD>   # boletins-segest/<data>.{html,txt}
   python3 scripts/send_boletim.py --perfil segest --data <YYYY-MM-DD> --dry-run
   git add triagem-segest/ boletins-segest/
   git commit -m "Boletim Normativo Diário - SEGEST <YYYY-MM-DD>"
   git push -u origin HEAD
   ```
   O push em `claude/**` ou `main` tocando `boletins-segest/**` dispara o workflow
   **`send-boletim-segest.yml`**, que envia o e-mail (SMTP). Não usar
   `mcp__Gmail__create_draft`.
6. Confirmar o envio (`mcp__github__actions_list`, `list_workflow_runs` de
   `send-boletim-segest.yml`) e reportar em 3–6 linhas: data, contagem por seção,
   resultado do envio, fontes que falharam e se houve dispatch do bridge.

Se o push falhar, não abandonar o boletim: relatar que `boletins-segest/<data>.{html,txt}`
ficaram locais e que o envio exige push manual (ou *Actions → send-boletim-segest → Run workflow*).

## Identidade e escopo

Assistente de pesquisa normativa da **SEGEST** e de suas unidades subordinadas
(Regulamento da Secretaria, arts. 92, 94, 96 e 98):

- **SEGEST** — direção da Secretaria (art. 92);
- **DIEPE** — Divisão de Estatística e Pesquisa (art. 94);
- **NUGERP** — Núcleo de Gestão de Riscos e Projetos Institucionais (art. 96);
- **SESAC** — Seção de Sustentabilidade e Acessibilidade (art. 98).

Destinatário do e-mail: o revisor (secret `BOLETIM_TO_SEGEST`; default
`leonardo.donato@trt17.jus.br`). A distribuição às unidades da SEGEST é ato humano.

## Temas-filtro da SEGEST → unidade

O vocabulário implementado está em `scripts/perfis.py` (`STRONG_SEGEST` / `WEAK_SEGEST`).
O mapa tema → unidade abaixo orienta a triagem:

| Tema | Competências | Unidade(s) |
|---|---|---|
| Planejamento estratégico, Estratégia Nacional do Poder Judiciário, macrodesafios, indicadores estratégicos | SEGEST I–VI, XII; NUGERP I–III | SEGEST, NUGERP |
| **Metas Nacionais do Poder Judiciário** (CNJ), Encontros Nacionais, cumprimento e reporte ao CNJ | SEGEST III–IV | SEGEST, DIEPE |
| Governança corporativa/judiciária, integridade, colegiados temáticos, políticas e controles | SEGEST XV–XVII | SEGEST |
| Estatística e pesquisa: SIESPJ, Justiça em Números, **e-Gestão**, DataJud, indicadores, relatórios gerenciais, tabelas de padronização | DIEPE I–XX; SEGEST XI | DIEPE |
| Pesquisa de Clima Organizacional e Pesquisa de Satisfação do Usuário | SEGEST XIV | SEGEST, DIEPE |
| Gestão de riscos (política, metodologia, riscos-chave), gestão de projetos e portfólio, escritório de projetos | NUGERP I–XXI | NUGERP |
| Capacitação em planejamento, riscos e projetos; boas práticas e inovação organizacional | SEGEST VIII–IX; NUGERP IV–V | SEGEST, NUGERP |
| Proposta orçamentária e prioridades estratégicas | SEGEST VII | SEGEST |
| Plano de Logística Sustentável (PLS), sustentabilidade, contratações sustentáveis, socioambiental, resíduos, carbono, Metas do Judiciário sobre sustentabilidade | SESAC I–XIV | SESAC |
| Acessibilidade e inclusão, pessoa com deficiência, indicadores de acessibilidade no CNJ, acompanhamento funcional de servidores com deficiência | SESAC XV–XXII | SESAC |
| Intercâmbio com outros TRTs / CSJT em governança e gestão estratégica | SEGEST X | SEGEST |

Itens sem unidade clara: **"SEGEST-direção — ciência"**.

> **Fronteira com a SGP.** Atos de pessoal (aposentadoria, pensão, licenças,
> remuneração, folha…) **não** pertencem a este boletim — são da SGP. Se um ato de
> gestão de pessoas citar de passagem o planejamento estratégico ou a capacitação, só
> entra se o assunto central for tema da SEGEST. A capacitação (art. 92, VIII) entra
> apenas na parte de planejamento, riscos e projetos.

## Fontes e particularidades

- **DOU:** os atos individuais de pessoal são descartados **inclusive** de CNJ/CSJT/TRT-17
  (perfil `descarta_individuais_de_prioritarios`), e portarias de pessoal, editais de notificação e atas
  de órgãos não prioritários são ignorados. Declare "N selecionados, M atos individuais descartados"
  usando `discarded_individual_acts`. Órgãos prioritários da SEGEST: **CNJ, CSJT e TRT-17**
  (TST, TCU, STF e STJ entram só pelo vocabulário). Resoluções/Recomendações do CNJ no DOU S1
  são a principal fonte de normas de governança do Judiciário.
- **DEJT Caderno Administrativo do TRT-17:** continua **sem filtro temático** (todos os
  atos, como no boletim da SGP). Atos que não são da SEGEST entram como INFORMATIVO
  ("SEGEST-direção — ciência"); consolidar lotes de atos do mesmo tipo em `linhas`.
  Dê atenção a Resoluções Administrativas, Atos da Presidência/DG e portarias que
  criem/alterem comissões, colegiados temáticos, políticas, planos ou designem gestores de metas.
  CSJT e TST seguem o filtro temático.
- **TCU:** acórdãos que casem com o vocabulário da SEGEST (auditorias de governança,
  gestão de riscos, planejamento…) vão para EM MONITORAMENTO. Declare a janela de sessões
  (`min_date_seen`–`max_date_seen`). Atenção: o filtro (≥2 termos fracos) pode trazer
  ruído — na dúvida, descarte e declare "N selecionados".
- **DJe do CNJ / DJEN:** como em `CLAUDE.md` (`status` ≠ `ok` ⇒ "não consultado — conferência manual").
  O DJe do CNJ costuma trazer decisões do plenário e atos de governança do CNJ: itens `ok`
  vão a EM MONITORAMENTO (ou MÉDIO/INFORMATIVO), sempre `[carece de leitura humana do texto integral]`.
- **STF/STJ:** só com sinal de precedente vinculante **e** tema SEGEST; o mais comum é
  `Sem novidades em STF/STJ nesta data`.
- Calendário, data do DEJT (publicação ≠ disponibilização) e fallback com aviso metodológico:
  como em `CLAUDE.md`. O e-mail não menciona o mecanismo de coleta.

## Triagem de cada item

- **Unidade(s):** uma ou mais entre {SEGEST, DIEPE, NUGERP, SESAC, SEGEST-direção — ciência}.
- **Grau de impacto** (adaptado):
  - **ALTO** = exige alterar plano, meta, indicador, metodologia, política, painel, relatório ou sistema da SEGEST
    (ex.: nova Meta Nacional, nova resolução do CNJ sobre planejamento/estatística/PLS, mudança de regra do e-Gestão/Justiça em Números, prazo de reporte ao CNJ);
  - **MÉDIO** = exige ciência e ajuste pontual de rotina;
  - **INFORMATIVO** = arquivo e consulta futura.
- **Ação sugerida:** até 15 palavras.
- Em caso de dúvida sobre pertinência, **INFORMATIVO**. Nunca inventar número de ato; sem número na fonte:
  `[verificar nº na fonte]`. Tese não literal na fonte: `[carece de leitura humana do texto integral]`.

## Template e e-mail

- Triagem no mesmo formato de `scripts/build_boletim.py` (campos `alto`, `medio`, `informativo`,
  `monitoramento`, `fontes_ok`, `fontes_sem_retorno`, `timestamp`), em `triagem-segest/<data>.json`.
- Mesmo `boletim-template.html`; o cabeçalho sai como **Boletim Normativo Diário - SEGEST** automaticamente.
- Assunto (automático): `Boletim Normativo SEGEST - Edição de [DATA POR EXTENSO]` (prefixo fixo, usado em filtros de e-mail).
- Mesmas regras da SGP: sem lembrete de revisão nem "aviso metodológico" no corpo; sem jargão técnico;
  o diagnóstico técnico (EXIT_CODE, dispatch, runs) só vai ao relatório final ao operador.
- Seção sem itens: `Sem novidades pertinentes nesta data.`; sem nenhuma seção com itens, ainda assim gerar e enviar.

## Operação (para o operador)

- **Agendamento:** criar na plataforma Claude.ai uma rotina própria (mesmo horário da SGP, ~11h30 BRT) com o prompt:
  *"Execute IMEDIATAMENTE, sem pedir confirmação, o Boletim Normativo Diário - SEGEST: clone/atualize
  `tlappfactory/rotinas_claude`, leia e siga TODAS as instruções de `CLAUDE-SEGEST.md` (e, para as regras comuns,
  `CLAUDE.md`), e reporte ao final em 3–6 linhas."*
- **Secrets:** os do SMTP são compartilhados com a SGP. Opcional: `BOLETIM_TO_SEGEST` (destinatário do boletim da SEGEST).
- **Reenvio/validação:** *Actions → send-boletim-segest → Run workflow* (`data`, `dry_run`).
- **Ajuste fino do filtro:** `scripts/perfis.py` (`STRONG_SEGEST`, `WEAK_SEGEST`, `PRIORITY_ORGAOS_SEGEST`,
  `IGNORA_IDENTIFICA_SEGEST`). Nada além disso precisa mudar nos coletores.
- **Importante:** o workflow do bridge (`fetch-dou.yml`) e os de envio só valem a partir de `main`.
  Enquanto a branch com estas mudanças não for mesclada, não haverá JSONs `-segest` no bridge.
