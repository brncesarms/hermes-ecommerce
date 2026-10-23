#!/usr/bin/env bash
set -o pipefail
set -a
# shellcheck disable=SC1091
[ -f "$(dirname "$0")/../credentials.env" ] && . "$(dirname "$0")/../credentials.env" 2>/dev/null
set +a

THEME="casa"
LOG_FILE="/home/brn/.hermes/ecommerce/data/cron.log"
BOT_TOKEN="${ADMIN_TELEGRAM_BOT_TOKEN:-${TELEGRAM_BOT_TOKEN}}"
CHAT_ID="${ADMIN_TELEGRAM_CHAT_ID:-${TELEGRAM_CHAT_ID}}"

if ! python3 /home/brn/.hermes/ecommerce/shopee_engine.py batch --theme "$THEME" --count 3 --min-discount 20 >>"$LOG_FILE" 2>&1; then
	EXIT_CODE=$?
	ERR_TAIL=$(tail -n 15 "$LOG_FILE")
	if [ -n "$BOT_TOKEN" ] && [ -n "$CHAT_ID" ]; then
		curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" -d chat_id="${CHAT_ID}" -d parse_mode="HTML" -d text="🚨 <b>ALERTA CRÍTICO: CRON FALHOU NO SHELL</b>%0A⏰ $(date "+%d/%m/%Y %H:%M:%S")%0A📦 Tema: <code>${THEME}</code>%0A❌ Código de saída: <code>${EXIT_CODE}</code>%0A<pre>${ERR_TAIL}</pre>" >/dev/null 2>&1
	fi
	exit "$EXIT_CODE"
fi
