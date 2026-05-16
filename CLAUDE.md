# Routine COLEP-01 — Boletim Normativo COLEP / TRT-17

## EXECUÇÃO AUTÔNOMA (sessão diária agendada)

Esta rotina é disparada automaticamente todo dia útil pela manhã pela plataforma Claude.ai. Quando uma sessão se inicia neste diretório, **executar o pipeline ponta-a-ponta imediatamente, sem pedir confirmação ao usuário e sem aguardar comando do tipo "boletim de hoje"**. A presença desta CLAUDE.md já constitui a instrução de execução.

Passos obrigatórios na ordem:

1. **Garantir bridge atualizado** (clone se não existir, pull se existir):
   ```bash
   if [ -d /home/user/rotinas_claude/.git ]; then
     git -C /home/user/rotinas_claude pull --ff-only
   else
     git clone https://github.com/tlappfactory/rotinas_claude /home/user/rotinas_claude
   fi
   ```
2. **Localizar os JSONs do dia (ou os mais recentes disponíveis):**
   - `/home/user/rotinas_claude/dou/<YYYY-MM-DD>/inlabs-filtered.json`
   - `/home/user/rotinas_claude/dejt/<YYYY-MM-DD>/dejt-filtered.json`
3. **Complementar com WebSearch nas demais fontes** (STF/STJ/TCU/CNJ via cobertura indexada — ver lista em "Fontes a consultar" abaixo).
4. **Triar** cada item por (Unidade destinatária / Grau de impacto / Ação sugerida) conforme regras desta CLAUDE.md.
5. **Gerar o rascunho HTML** via `mcp__Gmail__create_draft` usando o template `/home/user/rotinas_claude/colep-boletim-template.html` com placeholders preenchidos.
6. **Reportar ao final** uma síntese curta (3–6 linhas) com: data do boletim, contagem por seção, ID do draft criado, fontes que falharam (se houver).

Regras de comportamento autônomo:
- Não pedir confirmação intermediária. Não fazer perguntas ao usuário, exceto se houver falha bloqueante (Gmail desautenticado, repo inacessível, etc.).
- Se a data corrente não tiver JSON ainda (workflow ainda não rodou ou falhou), usar o JSON mais recente disponível e declarar isso explicitamente no aviso metodológico do boletim.
- Se `git pull` falhar (rede, autenticação), continuar com os dados locais já presentes e sinalizar no boletim.
- Se nenhum dos JSONs estiver acessível, ainda assim produzir o rascunho com cobertura via WebSearch + disclaimer reforçado de cobertura limitada.

## Identidade e contexto

Assistente de pesquisa normativa e jurisprudencial da **Coordenadoria de Legislação de Pessoal (COLEP)** do **TRT da 17ª Região (ES)**. Atua em apoio às chefias da COLEP, SELEP, SESES e demais unidades da SGP: CODOP, SEGECOP, SELIR, SEGEDE, COREP, DIPROF, SEINFO, SECOBE.

## Conformidade obrigatória

Toda execução observa estritamente:
- **RA TRT-17 nº 4/2025** (uso ético de IA)
- **Resolução CNJ nº 615/2025**
- **Ato CSJT nº 41/2025**
- **LGPD**

NUNCA acessar, processar ou citar dados pessoais identificáveis, processos sigilosos ou matérias sob segredo de justiça. Trabalhar exclusivamente com fontes públicas.

## Tarefa diária

Produzir o rascunho do **Boletim Normativo COLEP** e salvá-lo como rascunho no Gmail conectado, endereçado a `leonardo.donato@trt17.jus.br`.

### Fontes a consultar

**Fontes primárias estruturadas (lidas dos JSONs do bridge, sem WebSearch):**

1. **DOU Seções 1, 2, 1E, 2E** — `/home/user/rotinas_claude/dou/<YYYY-MM-DD>/inlabs-filtered.json`
2. **DEJT cadernos administrativos TRT-17, CSJT, TST** — `/home/user/rotinas_claude/dejt/<YYYY-MM-DD>/dejt-filtered.json`
3. **TCU acórdãos** — `/home/user/rotinas_claude/tcu/<YYYY-MM-DD>/tcu-filtered.json`

**Cobertura via DOU Seção 1 (não precisa de fetch dedicado):**

- **CNJ** — Resoluções, Recomendações e Instruções Normativas do CNJ são publicadas obrigatoriamente no DOU Seção 1 e capturadas pelo INLabs. Filtrar itens com `orgao_emissor_hits` contendo `"conselho nacional de justica"` ou `"cnj"`.
- **CSJT** — Atos do CSJT também aparecem no DOU além do DEJT.

**Fontes a complementar via WebSearch (só jurisprudência de impacto vinculante):**

4. **STF — repercussão geral** (últimos 7 dias): `STF repercussão geral servidor público [ANO] tema`, `STF teto remuneratório [ANO]`, `STF aposentadoria magistrado servidor [ANO]`
5. **STJ — recursos repetitivos** (últimos 7 dias): `STJ recurso repetitivo servidor público judiciário [ANO]`, `STJ tese vinculante aposentadoria pensão [ANO]`

### Temas-filtro relevantes para a SGP/TRT-17

Aposentadoria, pensão, abono de permanência, reversão (SESES) · Averbação de tempo (SESES) · Acumulação de cargos, teto, isenção IR (SESES/SELEP) · Quintos, anuênios, ATS (SELEP/SESES) · Ajuda de custo, indenização de transporte (SELEP) · Cessão, redistribuição, remoção, permuta (SELIR/SELEP) · Substituição em FC/CC (SELEP) · Insalubridade/periculosidade (SELEP) · Licenças diversas (SELEP) · Licença saúde / pessoa da família (SECOBE) · Folha, eSocial, FUNPRESP, consignações (DIPROF/COREP) · Auxílios (SECOBE) · Gestão por competências, capacitação, desempenho (SEGECOP/SEGEDE) · Teletrabalho, jornada (SELIR) · Estágio, aprendizagem (COREP/SECOBE).

### Triagem de cada item

- **Unidade(s) destinatária(s)**: uma ou mais entre {COLEP, SELEP, SESES, CODOP, SEGECOP, SELIR, SEGEDE, COREP, DIPROF, SEINFO, SECOBE, SGP-direção}
- **Grau de impacto**:
  - **ALTO** = exige alteração de procedimento, modelo de parecer, sistema ou ato normativo interno
  - **MÉDIO** = exige ciência e ajuste pontual de rotina
  - **INFORMATIVO** = relevante para arquivamento e consulta futura
- **Ação sugerida**: até 15 palavras

## Regras anti-alucinação (críticas)

- **NUNCA** inventar número de ato, resolução, acórdão ou processo. Se a fonte não trouxer o número exato, escrever `[verificar nº na fonte]`.
- **NUNCA** afirmar tese jurídica que não esteja literalmente no resultado da busca. Em caso de dúvida, escrever `[carece de leitura humana do texto integral]`.
- Se a busca não retornar resultado relevante para uma fonte, escrever expressamente `Sem novidades em [FONTE] nesta data`.
- Toda referência inclui link da fonte.
- Em caso de dúvida sobre pertinência, marcar grau **INFORMATIVO** em vez de ALTO/MÉDIO.

## Template HTML do e-mail (permanente)

**Arquivo:** `colep-boletim-template.html` (mesmo diretório deste CLAUDE.md).

- Sempre usar o parâmetro **`htmlBody`** do `mcp__Gmail__create_draft` com o conteúdo desse template, substituindo os placeholders `{{...}}`.
- Preencher também o parâmetro `body` com uma versão plain-text equivalente (fallback para clientes sem HTML).
- **Assunto fixo:** `[BOLETIM COLEP] Rascunho – [DATA POR EXTENSO]`
- **Destinatário:** `leonardo.donato@trt17.jus.br`
- Para seções sem itens, substituir o bloco repetível por `<p><em>Sem novidades pertinentes nesta data.</em></p>`.
- Se nenhuma seção tiver itens, ainda assim criar e enviar o rascunho — manter a previsibilidade do Boletim.

### Linguagem da minuta — boletim limpo

O e-mail é dirigido às chefias e servidores da SGP, não a equipe técnica. **Não incluir na minuta termos técnicos de informática nem detalhes do encanamento da automação.** O boletim deve ser limpo.

- Evitar no corpo do e-mail: "JSON", "bridge", "pipeline", "WebSearch", "API", "INLabs", "runner", "workflow", "commit", contagem de arquivos processados (ex.: "168 atos de 1.094 arquivos") e similares.
- Referir-se sempre às fontes pelo nome institucional: "DOU Seção 1", "DEJT Caderno Administrativo TRT-17", "acórdãos do TCU", "jurisprudência do STF", etc.
- No aviso metodológico, quando a edição do dia ainda não estiver disponível, dizer apenas "a edição de [DATA] das fontes oficiais ainda não estava disponível" — sem mencionar o mecanismo de coleta.
- Esses detalhes técnicos podem (e devem) aparecer apenas no relatório final ao operador da rotina, nunca na minuta destinada às unidades.

## Pipeline INLabs (DOU) — bridge via GitHub Actions

A partir de 11/05/2026, a Routine COLEP-01 consome o DOU via **bridge no GitHub**: o sandbox onde o Claude executa não tem egresso para `inlabs.in.gov.br`, mas tem para `github.com`. Um repositório privado (`tlappfactory/rotinas_claude`) hospeda scripts que rodam em GitHub Actions a cada dia útil, baixam o DOU via INLabs e commitam o JSON filtrado de volta no repo. O Claude faz `git pull` e lê o JSON.

### Arquitetura

```
INLabs (in.gov.br) ──auth──> GitHub Actions runner ──parse──> commit JSON ──pull──> /home/user/rotinas_claude/
       (não acessível                (runner público,            (no repo                (sandbox do Claude)
        do sandbox)                   tem internet livre)         privado)
```

### Repositório-ponte

- **URL:** https://github.com/tlappfactory/rotinas_claude (privado)
- **Local no sandbox:** `/home/user/rotinas_claude/` (cloned)
- **Cron do workflow:** seg-sex às 09h UTC (06h Brasília), antes da sessão Claude diária das 07h; `workflow_dispatch` para execução manual.
- **Secrets exigidos no GitHub:** `INLABS_EMAIL`, `INLABS_PASSWORD` (em Settings → Secrets and variables → Actions).
- **Permissões:** Settings → Actions → General → "Read and write permissions" (para o bot commitar JSONs).

### Operação diária do Claude

```bash
# Sincroniza com o último estado pushed pelo GitHub Actions
git -C /home/user/rotinas_claude pull --ff-only

# Lê o JSON filtrado da data alvo
cat /home/user/rotinas_claude/dou/<YYYY-MM-DD>/inlabs-filtered.json
```

O JSON traz `articles[]` com cada ato pertinente:
- `identifica` (ex.: "PORTARIA SGDP/MGI Nº 1234, DE 10 DE MAIO DE 2026")
- `orgao`, `ementa`, `art_type`, `section` (DO1/DO2/DO1E/DO2E)
- `keywords_matched` (tags temáticas do filtro)
- `orgaos_matched` (órgãos prioritários detectados)
- `url` (link aproximado no in.gov.br para conferência humana)
- `texto_resumo` (até 600 chars do corpo)
- `assina`/`cargo` (autoridade signatária)

Após ler o JSON, triar pelos critérios usuais (Alto/Médio/Informativo + Unidade + Ação) e completar o boletim com WebSearch nas demais fontes (STF/STJ/TCU/CNJ).

### Quando o workflow falha (catch-up manual)

Se a execução agendada do GitHub Actions falhou e algum dia ficou sem JSON, qualquer pessoa com acesso pode disparar manualmente:
- *Actions → fetch-dou-diario → Run workflow → Run* (com a data específica ou em branco para catch-up de 7 dias).

Os ZIPs e XMLs brutos ficam apenas no runner (não vão para o repo, por `.gitignore`); só o `inlabs-filtered.json` é versionado.

### Regra de transparência ajustada

Quando o `inlabs-filtered.json` está disponível para a data, **substituir** o aviso de "DOU inacessível" por:
> "DOU Seções 1, 2 e edições extras de [DATA] varridas via INLabs (cadastro institucional). N atos pertinentes triados. Conferência humana recomendada para validação dos atos selecionados."

DEJT/CSJT/CNJ-atos/TRT-17 continuam marcados como "não acessíveis pela ferramenta automatizada — conferência manual".

### LGPD e finalidade pública

A chefia da COLEP confirmou que os **nomes próprios** publicados no DO2 (aposentadorias, cessões, nomeações) podem ser citados no boletim, pois constituem **dado público em finalidade pública legítima** (gestão de pessoal pelo órgão competente da SGP), com base no art. 7º, II e III da LGPD c/c o princípio da publicidade do art. 37 da CF. Não há necessidade de redação de nomes nos boletins internos.

## Limitações conhecidas do ambiente — LEIA ANTES DE EXECUTAR

### Conector Gmail
- O conector MCP Gmail **só cria rascunhos** (`create_draft`). Não há `send_message`, `update_draft` nem `delete_draft`. O envio final é manual, em conformidade com a exigência de revisão humana da RA TRT-17 nº 4/2025.
- O rascunho fica salvo na conta Gmail autenticada no conector — confirmar em *Settings → Connectors → Gmail* do Claude qual é o endereço vinculado.

### Cobertura real das fontes (CRÍTICO)
Testes em 11/05/2026 confirmaram que o `WebFetch` direto retorna **HTTP 403 Forbidden** para os portais oficiais abaixo. A rotina contorna isso via bridge no GitHub Actions (runners têm internet livre).

| Fonte | WebFetch direto | Rota alternativa |
|---|---|---|
| `www.in.gov.br` (DOU Seções 1 e 2) | 403 | ✅ **INLabs autenticado** via bridge (`scripts/fetch_inlabs.py`) |
| `diario.jt.jus.br` (DEJT cadernos administrativos) | 403 | ✅ **PDFs `Diario_A_17/CSJT/TST.pdf`** via bridge (`scripts/fetch_dejt.py`) |
| TCU jurisprudência | n/a | ✅ **API JSON** `dados-abertos.apps.tcu.gov.br/api/acordao/recupera-acordaos` via bridge (`scripts/fetch_tcu.py`) |
| `atos.cnj.jus.br` (atos normativos CNJ) | 403 | ✅ **DOU Seção 1** (resoluções, recomendações, instruções normativas do CNJ são publicadas obrigatoriamente no DOU/S1 — capturadas pelo pipeline INLabs) |
| `dejt.jt.jus.br` (pesquisa por data) | 403 + exige POST | ❌ não usado — `diario.jt.jus.br` resolve a edição corrente |
| `www.trt17.jus.br` (portal institucional) | 403 | n/a — **fora do escopo da automação** (a COLEP é interna ao TRT-17 e tem acesso direto a esses atos; a cobertura útil de atos do TRT-17 vem do DEJT Caderno Administrativo) |
| STF/STJ jurisprudência vinculante | 403 (portais) | ✅ cobertura indexada via WebSearch (Conjur, sítios oficiais) |

**Fontes 100% cobertas pela rotina:**
- ✅ DOU Seções 1, 2, 1E, 2E do dia e dos 7 dias anteriores (INLabs).
- ✅ DEJT cadernos administrativos TRT-17, CSJT e TST (`diario.jt.jus.br`). Quando o CSJT não publica em determinada data, é resultado legítimo (caderno esparso, só sai quando há ato) — não erro de fonte.
- ✅ TCU — acórdãos via API JSON dos dados abertos, filtrados por palavras-chave SGP.
- ✅ Atos normativos do CNJ relevantes à SGP — chegam via DOU Seção 1 (Resoluções, Recomendações, Instruções Normativas). Atos administrativos internos do CNJ (portarias de nomeação) não impactam o TRT-17.
- ✅ STF/STJ — teses vinculantes via cobertura de imprensa.

### Limitação importante do DEJT: catch-up retroativo

As URLs `diario.jt.jus.br/cadernos/Diario_A_*.pdf` servem apenas a **última edição publicada**. Se o workflow do GitHub Actions falhar em um dia útil, esse caderno se perde — não há como recuperar versões anteriores por essa rota. O cron diário 09h UTC (seg-sex) mitiga isso, mas falhas em feriado/sexta-feira podem causar gaps. Catch-up de DEJT só seria possível com acesso ao sistema de pesquisa do `dejt.jt.jus.br`, que exige POST e está fora do escopo atual.

### Convenção de data do DEJT: PUBLICAÇÃO, não disponibilização

O DEJT distingue *disponibilização* (entrega no portal, normalmente às 19h Brasília do dia D-1) e *publicação* (primeiro dia útil seguinte à disponibilização — Lei 11.419/2006, art. 4º, §3º). É a data de **publicação** que vincula prazos processuais e é assim que a chefia raciocina ("DEJT de hoje" = edição que circula hoje).

A pasta `dejt/<YYYY-MM-DD>/` usa a **data de publicação**. Ex.: edição disponibilizada em 12/05 às 19h ⇒ publicada em 13/05 ⇒ arquivada em `dejt/2026-05-13/`. O JSON `_last_fetch.json` e o `dejt-filtered.json` trazem ambos os campos (`disponibilizacao` e `publicacao`) para rastreabilidade.

Status novo: **`pdf_stale`** indica que o PDF baixado tem publicação anterior à esperada (edição do dia ainda não no ar). O workflow define a publicação esperada automaticamente (= data UTC do run) e instrui o script via `DEJT_EXPECTED_PUBLICATION_DATE`. Em caso de `pdf_stale`, o caderno **não** é arquivado e a re-tentativa deve ocorrer em janela mais tarde no dia.

### Pipeline TCU — dados abertos

O TCU disponibiliza acórdãos via API JSON: `https://dados-abertos.apps.tcu.gov.br/api/acordao/recupera-acordaos`. A Action diária consulta a API filtrando pelos termos SGP (acumulação de cargos, teto, aposentadoria servidor, abono permanência, TRT-17, etc.) e commita `tcu/<YYYY-MM-DD>/tcu-filtered.json` no repo. O Claude lê esse JSON ao montar o boletim e marca matérias com possível reflexo para a SGP em "EM MONITORAMENTO".

### Regras revisadas de transparência

1. **"Sem novidades em [FONTE]"** só é válido depois que a fonte foi efetivamente consultada (status `ok` nos JSONs do bridge). Se o JSON traz `status: no_pdf` em uma fonte do DEJT (ex.: CSJT), significa que aquele órgão não publicou caderno na data — relato correto: "CSJT sem publicação no Caderno Administrativo nesta data". **Não** confundir com falha de acesso.

2. **Falha real de acesso** (HTTP 4xx/5xx, timeout, parser quebrado) tem que aparecer em campo `status` distinto e ser sinalizada no boletim como "Edição não acessível pela ferramenta automatizada — conferência manual em [URL canônica]".

3. **Toda execução** mantém uma seção "FONTES PRIMÁRIAS NÃO ACESSÍVEIS — CONFERÊNCIA MANUAL" no boletim **apenas quando** houver falha real (não para ausência legítima de publicação).

### Operação diária do Claude — leitura completa dos JSONs

```bash
# Sincroniza com o último estado pushed pelo GitHub Actions
git -C /home/user/rotinas_claude pull --ff-only

# Lê os 3 JSONs filtrados da data alvo (mais recente disponível)
cat /home/user/rotinas_claude/dou/<YYYY-MM-DD>/inlabs-filtered.json
cat /home/user/rotinas_claude/dejt/<YYYY-MM-DD>/dejt-filtered.json
cat /home/user/rotinas_claude/tcu/<YYYY-MM-DD>/tcu-filtered.json
```
