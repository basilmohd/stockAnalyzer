#!/bin/bash
# Starts ngrok + webhook server + scheduler for local dev with working buttons

echo "Starting Portfolio Agent locally with ngrok tunnel..."

# Resolve ngrok — prefer system PATH, fall back to winget install location
NGROK=$(command -v ngrok 2>/dev/null || echo "/c/Users/basil/AppData/Local/Microsoft/WinGet/Links/ngrok.exe")
echo "Using ngrok: $NGROK"

# Kill any existing ngrok
pkill -f ngrok 2>/dev/null
sleep 1

# Start ngrok in background
"$NGROK" http 8000 --log=stdout > logs/ngrok.log 2>&1 &
NGROK_PID=$!
echo "ngrok started (PID: $NGROK_PID)"

# Retry until ngrok API is ready (up to 15 seconds)
echo "Waiting for ngrok tunnel to be ready..."
NGROK_URL=""
for i in $(seq 1 15); do
    sleep 1
    NGROK_URL=$(curl -s http://localhost:4040/api/tunnels \
      | python -c "
import sys, json
try:
    data = json.load(sys.stdin)
    tunnels = data.get('tunnels', [])
    https = [t for t in tunnels if t['proto'] == 'https']
    print(https[0]['public_url'] if https else '')
except Exception:
    print('')
" 2>/dev/null)
    if [ -n "$NGROK_URL" ]; then
        echo "ngrok ready after ${i}s"
        break
    fi
done

if [ -z "$NGROK_URL" ]; then
    echo "ERROR: Could not get ngrok URL after 15s. Check logs/ngrok.log"
    cat logs/ngrok.log
    exit 1
fi

echo "ngrok URL: $NGROK_URL"

# Set Telegram webhook to ngrok URL
python -c "
import asyncio
from core.telegram_bot import set_webhook
async def main():
    result = await set_webhook('$NGROK_URL')
    print(f'Webhook set: {result}')
asyncio.run(main())
"

# Export ngrok URL for the app to know its own address
export PUBLIC_URL=$NGROK_URL

echo ""
echo "Ready. Starting webhook server..."
echo "Webhook: $NGROK_URL/telegram/webhook"
echo "Health:  $NGROK_URL/health"
echo ""
echo "Open a new terminal and run: python scheduler.py"
echo ""

# Start webhook server
python webhook_server.py
