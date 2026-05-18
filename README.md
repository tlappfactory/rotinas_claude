# rotinas_claude — bridge DOU/INLabs para a Routine COLEP-01

Repositório-ponte que executa a varredura diária do DOU (via API INLabs da Imprensa Nacional) fora do sandbox do Claude e disponibiliza os atos filtrados em JSON para consumo posterior.

## Por que existe

O sandbox onde o Claude executa bloqueia, por allowlist de egresso, todos os portais oficiais brasileiros relevantes (`in.gov.br`, `dejt.jt.jus.br`, `csjt.jus.br`, `atos.cnj.jus.br`, `trt17.jus.br`). GitHub está liberado. Este repo aproveita isso: o GitHub Actions executa o fetch+parse a cada dia útil e versiona os JSONs filtrados; o Claude faz `git pull` e lê o resultado.

## Estrutura

```
.
├── scripts/
│   ├── fetch_inlabs.py   # autentica no INLabs e baixa ZIPs DO1/DO2/DO1E/DO2E
│   └── parse_dou.py      # filtra XMLs por temas SGP/TRT-17 → JSON
├── .github/workflows/
│   └── fetch-dou.yml     # cron seg-sex + sábado (09h UTC) + dispatch manual
├── dou/                  # JSONs filtrados (ZIPs e XMLs ficam fora do git via .gitignore)
│   └── <YYYY-MM-DD>/inlabs-filtered.json
├── requirements.txt
├── .gitignore
└── README.md
```

## Configuração inicial (uma única vez)

1. **Secrets do GitHub** — em *Settings → Secrets and variables → Actions → New repository secret*, criar:
   - `INLABS_EMAIL` — e-mail cadastrado no INLabs
   - `INLABS_PASSWORD` — senha do INLabs

2. **Permissão de write para o workflow** — *Settings → Actions → General → Workflow permissions → "Read and write permissions"*. Necessário para que o bot commite os JSONs filtrados.

3. **Testar manualmente** — *Actions → fetch-dou-dejt-tcu-diario → Run workflow → Run* (deixe `data` vazio para hoje + catch-up). Verificar se a execução conclui sem erro e se um commit `DOU+DEJT+TCU filtrados — …` aparece no repo.

## Disparo automático do bridge pela rotina (opcional)

Ao montar o boletim, a Routine COLEP-01 executa `scripts/ensure_bridge_data.sh`: se faltarem os JSONs do dia, ela dispara este workflow via `workflow_dispatch` e aguarda — em vez de cair silenciosamente para a edição anterior (ver `CLAUDE.md`, seção "Garantia de dados frescos do dia").

Para o disparo automático funcionar, a sessão Claude precisa de um token GitHub na variável de ambiente `BRIDGE_DISPATCH_TOKEN` (ou `GH_TOKEN`). **Sem token a rotina não trava**: o script sai com código `10` e o boletim escala o aviso, mantendo o disparo manual como alternativa.

1. **Gerar o token** — fine-grained PAT em <https://github.com/settings/personal-access-tokens/new>:
   - *Only select repositories* → apenas `tlappfactory/rotinas_claude`.
   - Permissão: **Actions — Read and write** (apenas; `Metadata` entra automaticamente). **Não** conceder `Contents` nem `Workflows` — o script só dispara o workflow, não dá push.
   - Definir expiração e rotacionar periodicamente.

2. **Cadastrar a variável** — no Claude Code on the web: ícone de nuvem → editar o ambiente que executa a rotina → campo *Variáveis de ambiente* (formato `.env`), acrescentar uma linha, **sem aspas**:
   ```
   BRIDGE_DISPATCH_TOKEN=github_pat_...
   ```
   Atenção: variáveis de ambiente são visíveis a qualquer sessão do ambiente — não há cofre de secrets. Prefira um ambiente dedicado à rotina; se usar o ambiente compartilhado, mantenha o token com o escopo mínimo acima para conter o risco.

3. **Verificar** — numa sessão nova, após salvar:
   ```bash
   echo "${BRIDGE_DISPATCH_TOKEN:+definido}"      # deve imprimir: definido
   bash scripts/ensure_bridge_data.sh 2099-01-01  # data sem JSON → deve disparar o workflow
   ```

## Operação diária

- O cron dispara seg-sex às 09h UTC (06h Brasília), antes da sessão Claude das 07h. Há também um run aos sábados (09h UTC) que captura a edição do DEJT cuja publicação cai na segunda-feira (disponibilizada sexta ~19h).
- O job: faz catch-up de 7 dias para trás (para apanhar publicações ausentes), filtra por temas/órgãos SGP e commita apenas os JSONs em `dou/<DATA>/inlabs-filtered.json`.
- Os ZIPs e XMLs brutos NÃO são commitados (ficam só no runner) — repo permanece pequeno.

## Consumo pelo Claude

No sandbox do Claude (sessão diária da Routine COLEP-01):

```bash
git -C /home/user/rotinas_claude pull
# depois ler /home/user/rotinas_claude/dou/<DATA>/inlabs-filtered.json
```

## Filtros aplicados

O `parse_dou.py` casa por:

- **Keywords temáticas** (20 grupos) — aposentadoria, pensão, abono de permanência, averbação, teto, isenção IR, quintos/anuênios/ATS, ajuda de custo, cessão/redistribuição/remoção, FC/CC, insalubridade, licenças, FUNPRESP, auxílios, capacitação, teletrabalho, estágio, eSocial, consignações.
- **Órgãos prioritários** — CSJT, TST, CNJ, TCU, STF, STJ, TRT-17, MGI/SGDP, FUNPRESP-JUD, Previc, Receita Federal.

Cada artigo casado entra no JSON com `identifica`, `orgao`, `ementa`, `art_type`, `section`, `assina`/`cargo`, `texto_resumo` (600 chars), `url` aproximada no `in.gov.br`, `keywords_matched`, `orgaos_matched`.

## LGPD e finalidade pública

Os JSONs preservam **nomes próprios** publicados no DO2 (aposentadorias, cessões, nomeações), por se tratar de dado público em finalidade pública legítima (gestão de pessoal da SGP), com base no art. 7º, II e III da LGPD c/c o princípio da publicidade do art. 37 da CF. O repo é privado.

## Conformidade

Operação observa estritamente: RA TRT-17 nº 4/2025, Resolução CNJ nº 615/2025, Ato CSJT nº 41/2025 e LGPD. Conteúdo dos boletins gerados a partir destes dados requer revisão humana antes da distribuição oficial.
