#!/bin/zsh
# ============================================================
#  lembrar-token-github.sh — Forster
#  O que faz: avisa quando o token do GitHub que grava as aprovações
#             estiver perto de vencer, para não falhar em silêncio.
#  Versão: 1.0 — 2026-07-18
#  Dependências: osascript (nativo do macOS)
# ============================================================
#
# Por que existe: a página de aprovação grava o estado do cliente pela
# Pages Function do Cloudflare, que usa o secret GH_TOKEN. Esse token é um
# PAT fine-grained do GitHub e vence em 18/07/2027. Quando vencer, o cliente
# vai continuar clicando em aprovar e a gravação vai falhar sem avisar
# ninguém, que é exatamente o problema que a remediação de 18/07/2026
# resolveu. Este script existe para que o vencimento não vire o mesmo bug.
#
# Roda no dia 1 de cada mês pelo launchd (com.forster.lembrete-token-github)
# e não faz nada até a data de alerta.

set -u

DATA_ALERTA="2027-06-01"   # um mês e meio antes do vencimento
DATA_VENCIMENTO="18/07/2027"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$SCRIPT_DIR/lembrete.log"

hoje="$(date +%Y-%m-%d)"

registrar() {
    echo "[$(date '+%Y-%m-%d %H:%M')] $1" >> "$LOG" 2>/dev/null || true
}

# Comparação de data como string funciona no formato AAAA-MM-DD.
if [[ "$hoje" < "$DATA_ALERTA" ]]; then
    registrar "Silencioso: ainda falta para $DATA_ALERTA."
    exit 0
fi

MENSAGEM="O token do GitHub que grava as aprovações dos clientes vence em $DATA_VENCIMENTO.

Se vencer sem troca, o cliente clica em aprovar e nada é gravado, sem erro na tela.

O que fazer:
1. Emitir novo PAT fine-grained em github.com/settings/tokens, restrito ao repositório forster-aprovacoes, com permissão Contents: Read and write.
2. Substituir o secret GH_TOKEN do projeto Pages forster-aprovacoes, em Production e Preview.
3. Revogar o token antigo.

Passo a passo completo no vault, em _Interno/Processos/Migracao_Cloudflare_Pages.md

Para parar este aviso depois de renovar:
launchctl bootout gui/\$(id -u)/com.forster.lembrete-token-github
rm ~/Library/LaunchAgents/com.forster.lembrete-token-github.plist"

if ! osascript -e "display alert \"Renovar o token do GitHub\" message \"$MENSAGEM\" as critical" >/dev/null 2>&1; then
    registrar "❌ Falha ao exibir o alerta. Verifique se a sessão gráfica está ativa."
    exit 1
fi

registrar "Alerta exibido."
exit 0
