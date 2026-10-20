set -a; [ -f "$(dirname "$0")/../credentials.env" ] && . "$(dirname "$0")/../credentials.env" 2>/dev/null; set +a
#!/usr/bin/env bash
set -o pipefail
THEME="casa"
LOG_FILE="/home/brn/.hermes/ecommerce/data/cron.log"

if ! python3 /home/brn/.hermes/ecommerce/shopee_engine.py batch --theme "$THEME" --count 3 --min-discount 20 >> "$LOG_FILE" 2>&1; then
    EXIT_CODE=$?
    ERR_TAIL=$(tail -n 15 "$LOG_FILE")
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage"         -d chat_id="${TELEGRAM_CHAT_ID}"         -d parse_mode="HTML"         -d text="🚨 <b>ALERTA CRÍTICO: CRON FALHOU NO SHELL</b>%0A⏰ $(date "+%d/%m/%Y %H:%M:%S")%0A📦 Tema: <code>${THEME}</code>%0A❌ Código de saída: <code>${EXIT_CODE}</code>%0A<pre>${ERR_TAIL}</pre>" >/dev/null 2>&1
    exit $EXIT_CODE
fi
