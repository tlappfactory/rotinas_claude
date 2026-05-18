#!/usr/bin/env bash
# ensure_bridge_data.sh — usado pela Routine COLEP-01 (ver CLAUDE.md).
#
# Garante que os JSONs do bridge para a data-alvo existam ANTES de o boletim
# ser montado. Se faltarem, dispara o workflow do GitHub Actions via
# workflow_dispatch e aguarda os JSONs aparecerem no repositório — em vez de
# a rotina cair silenciosamente para a edição anterior.
#
# Uso:
#   scripts/ensure_bridge_data.sh [YYYY-MM-DD]   # default: hoje (UTC)
#
# Códigos de saída (a rotina decide o que fazer com cada um):
#   0   dados da data-alvo presentes (já existiam ou chegaram após o dispatch)
#   10  dados ausentes e o dispatch NÃO pôde ser feito (sem token ou sem
#       ferramenta de disparo) — a rotina deve ESCALAR, não cair em silêncio
#   11  dispatch feito, mas os dados não chegaram dentro do tempo-limite
#
# Para disparar o workflow é necessário um token com permissão actions:write
# (fine-grained: Actions = Read and write) exposto em BRIDGE_DISPATCH_TOKEN
# (ou GH_TOKEN). Sem token o script sai com 10.

set -uo pipefail

REPO="tlappfactory/rotinas_claude"
WORKFLOW="fetch-dou.yml"
BRANCH="main"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET_DATE="${1:-$(date -u +%Y-%m-%d)}"
POLL_TIMEOUT_SECS="${POLL_TIMEOUT_SECS:-1200}"   # 20 min
POLL_INTERVAL_SECS="${POLL_INTERVAL_SECS:-30}"

log() { echo "ensure_bridge_data: $*"; }

sync_repo() {
  git -C "$ROOT" pull --ff-only origin "$BRANCH" >/dev/null 2>&1 || true
}

# Considera os dados presentes quando existem o JSON do DOU e o do DEJT da
# data-alvo. O TCU é deliberadamente omitido: a API do TCU pode legitimamente
# falhar num dia e a ausência dele é tratada pela rotina como "fonte não
# acessível" — não deve, sozinha, forçar um redisparo.
have_data() {
  [ -f "$ROOT/dou/$TARGET_DATE/inlabs-filtered.json" ] \
    && [ -f "$ROOT/dejt/$TARGET_DATE/dejt-filtered.json" ]
}

sync_repo
if have_data; then
  log "dados de $TARGET_DATE já presentes no bridge."
  exit 0
fi

log "dados de $TARGET_DATE AUSENTES — acionando o bridge (workflow_dispatch)."

TOKEN="${BRIDGE_DISPATCH_TOKEN:-${GH_TOKEN:-}}"
if [ -z "$TOKEN" ]; then
  log "ERRO: sem BRIDGE_DISPATCH_TOKEN/GH_TOKEN — não é possível disparar." >&2
  exit 10
fi

dispatch() {
  if command -v gh >/dev/null 2>&1; then
    GH_TOKEN="$TOKEN" gh workflow run "$WORKFLOW" -R "$REPO" \
      --ref "$BRANCH" -f data="$TARGET_DATE"
  elif command -v curl >/dev/null 2>&1; then
    curl -fsS -X POST \
      -H "Authorization: Bearer $TOKEN" \
      -H "Accept: application/vnd.github+json" \
      -H "X-GitHub-Api-Version: 2022-11-28" \
      "https://api.github.com/repos/$REPO/actions/workflows/$WORKFLOW/dispatches" \
      -d "{\"ref\":\"$BRANCH\",\"inputs\":{\"data\":\"$TARGET_DATE\"}}"
  else
    log "ERRO: nem 'gh' nem 'curl' disponíveis para o disparo." >&2
    return 1
  fi
}

if ! dispatch; then
  log "ERRO: falha ao disparar o workflow_dispatch." >&2
  exit 10
fi

log "workflow disparado; aguardando os JSONs (até ${POLL_TIMEOUT_SECS}s)."
elapsed=0
while [ "$elapsed" -lt "$POLL_TIMEOUT_SECS" ]; do
  sleep "$POLL_INTERVAL_SECS"
  elapsed=$((elapsed + POLL_INTERVAL_SECS))
  sync_repo
  if have_data; then
    log "dados de $TARGET_DATE recebidos após ~${elapsed}s."
    exit 0
  fi
done

log "TIMEOUT: dados de $TARGET_DATE não chegaram em ${POLL_TIMEOUT_SECS}s." >&2
exit 11
