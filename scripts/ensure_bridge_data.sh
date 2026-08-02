#!/usr/bin/env bash
# ensure_bridge_data.sh — usado pela Routine COLEP-01 (ver CLAUDE.md).
#
# Garante que os JSONs do bridge para a data-alvo existam ANTES de o boletim
# ser montado. Se faltarem, dispara o workflow do GitHub Actions via
# workflow_dispatch e aguarda os JSONs aparecerem no repositório — em vez de
# a rotina cair silenciosamente para a edição anterior.
#
# Uso:
#   scripts/ensure_bridge_data.sh [YYYY-MM-DD]              # default: hoje (UTC)
#   scripts/ensure_bridge_data.sh [YYYY-MM-DD] --wait-only  # só aguarda, não dispara
#
# O modo --wait-only existe para o caso em que quem dispara o workflow é a
# própria sessão do Claude, pela ferramenta MCP do GitHub
# (mcp__github__actions_run_trigger). Nesse fluxo o script não tenta disparar:
# apenas sincroniza o repo em laço até os JSONs chegarem.
#
# Códigos de saída (a rotina decide o que fazer com cada um):
#   0   dados da data-alvo presentes (já existiam ou chegaram após o dispatch)
#   10  dados ausentes e o dispatch NÃO pôde ser feito por falta de credencial
#       ou de ferramenta (sem BRIDGE_DISPATCH_TOKEN/GH_TOKEN, sem gh e sem
#       curl) — a rotina deve ESCALAR, não cair em silêncio
#   11  dispatch feito, mas os dados não chegaram dentro do tempo-limite
#   12  a API do GitHub não é alcançável a partir desta sessão (chamadas a
#       api.github.com são interceptadas pelo ambiente e respondem 403). O
#       token, se houver, sequer chega ao GitHub. NÃO adianta trocar o token:
#       a rotina deve disparar o workflow pela ferramenta MCP do GitHub e
#       depois reexecutar este script com --wait-only.
#
# Sobre o código 12: o sandbox onde o Claude roda intermedia o acesso ao
# GitHub. O tráfego git (clone/pull/push) passa por um proxy local e funciona;
# já as chamadas REST diretas a api.github.com são respondidas pelo próprio
# ambiente com HTTP 403 e a mensagem "GitHub access is not enabled for this
# session. An org admin must connect the Claude GitHub App for this
# organization." — ou seja, o disparo por curl/gh nunca sai do sandbox. Este
# script detecta essa assinatura e a reporta separadamente de "sem token",
# para não induzir o operador a caçar um problema de credencial inexistente.

set -uo pipefail

REPO="tlappfactory/rotinas_claude"
WORKFLOW="fetch-dou.yml"
BRANCH="main"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
POLL_TIMEOUT_SECS="${POLL_TIMEOUT_SECS:-1200}"   # 20 min
POLL_INTERVAL_SECS="${POLL_INTERVAL_SECS:-30}"

TARGET_DATE=""
WAIT_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --wait-only) WAIT_ONLY=1 ;;
    -*) echo "ensure_bridge_data: opção desconhecida: $arg" >&2; exit 2 ;;
    *) TARGET_DATE="$arg" ;;
  esac
done
TARGET_DATE="${TARGET_DATE:-$(date -u +%Y-%m-%d)}"

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

# Aguarda os JSONs chegarem, sincronizando o repo a cada rodada.
# Sai 0 se chegarem, 11 no timeout.
wait_for_data() {
  log "aguardando os JSONs de $TARGET_DATE (até ${POLL_TIMEOUT_SECS}s)."
  local elapsed=0
  while [ "$elapsed" -lt "$POLL_TIMEOUT_SECS" ]; do
    sleep "$POLL_INTERVAL_SECS"
    elapsed=$((elapsed + POLL_INTERVAL_SECS))
    sync_repo
    if have_data; then
      log "dados de $TARGET_DATE recebidos após ~${elapsed}s."
      return 0
    fi
  done
  log "TIMEOUT: dados de $TARGET_DATE não chegaram em ${POLL_TIMEOUT_SECS}s." >&2
  return 11
}

sync_repo
if have_data; then
  log "dados de $TARGET_DATE já presentes no bridge."
  exit 0
fi

if [ "$WAIT_ONLY" -eq 1 ]; then
  log "modo --wait-only: o disparo é responsabilidade de quem chamou."
  wait_for_data
  exit $?
fi

log "dados de $TARGET_DATE AUSENTES — acionando o bridge (workflow_dispatch)."

TOKEN="${BRIDGE_DISPATCH_TOKEN:-${GH_TOKEN:-}}"
if [ -z "$TOKEN" ]; then
  log "ERRO: sem BRIDGE_DISPATCH_TOKEN/GH_TOKEN — não é possível disparar." >&2
  exit 10
fi

# Assinaturas de bloqueio pelo ambiente da sessão (não é problema de token).
# Cobrem tanto a resposta do intermediador do GitHub quanto uma recusa do
# proxy de egresso (403/407 no CONNECT, que o curl reporta sem corpo).
env_blocked() {
  case "$1" in
    *"GitHub access is not enabled for this session"*) return 0 ;;
    *"connect the Claude GitHub App"*) return 0 ;;
    *"Received HTTP code 403 from proxy"*) return 0 ;;
    *"Received HTTP code 407 from proxy"*) return 0 ;;
  esac
  return 1
}

# Executa o disparo e devolve:
#   0  disparado
#   10 falta de ferramenta / erro de credencial no GitHub
#   12 bloqueio de ambiente (a chamada não chega ao GitHub)
dispatch() {
  local out code
  if command -v gh >/dev/null 2>&1; then
    out="$(GH_TOKEN="$TOKEN" gh workflow run "$WORKFLOW" -R "$REPO" \
      --ref "$BRANCH" -f data="$TARGET_DATE" 2>&1)"
    code=$?
    [ "$code" -eq 0 ] && return 0
  elif command -v curl >/dev/null 2>&1; then
    # -w anexa o status HTTP ao fim da saída; sem -f, para preservar o corpo
    # do erro, que é o que permite distinguir bloqueio de ambiente de 401/403
    # legítimos do GitHub.
    out="$(curl -sS -w $'\nHTTP_STATUS=%{http_code}' -X POST \
      -H "Authorization: Bearer $TOKEN" \
      -H "Accept: application/vnd.github+json" \
      -H "X-GitHub-Api-Version: 2022-11-28" \
      "https://api.github.com/repos/$REPO/actions/workflows/$WORKFLOW/dispatches" \
      -d "{\"ref\":\"$BRANCH\",\"inputs\":{\"data\":\"$TARGET_DATE\"}}" 2>&1)"
    case "$out" in
      *"HTTP_STATUS=204"*) return 0 ;;
    esac
  else
    log "ERRO: nem 'gh' nem 'curl' disponíveis para o disparo." >&2
    return 10
  fi

  if env_blocked "$out"; then
    log "BLOQUEIO DE AMBIENTE: a API do GitHub não é alcançável desta sessão." >&2
    log "  resposta: $(printf '%s' "$out" | tr '\n' ' ' | cut -c1-300)" >&2
    log "  o token (se houver) não chega ao GitHub — trocá-lo não resolve." >&2
    log "  dispare pela ferramenta MCP do GitHub e reexecute com --wait-only." >&2
    return 12
  fi

  log "ERRO: falha ao disparar o workflow_dispatch." >&2
  log "  resposta: $(printf '%s' "$out" | tr '\n' ' ' | cut -c1-300)" >&2
  return 10
}

dispatch
dispatch_rc=$?
if [ "$dispatch_rc" -ne 0 ]; then
  exit "$dispatch_rc"
fi

log "workflow disparado."
wait_for_data
exit $?
