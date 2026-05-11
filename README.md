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
│   └── fetch-dou.yml     # cron diário (08h Brasília, seg-sex) + dispatch manual
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

3. **Testar manualmente** — *Actions → fetch-dou-diario → Run workflow → Run* (deixe `data` vazio para hoje + catch-up). Verificar se a execução conclui sem erro e se um commit `DOU filtrado — …` aparece no repo.

## Operação diária

- O cron dispara seg-sex às 09h UTC (06h Brasília), antes da sessão Claude das 07h.
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
