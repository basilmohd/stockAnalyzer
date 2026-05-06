# start_local.ps1
# Full local dev startup: verifies Redis, starts ngrok, registers Telegram webhook.
# Run once before starting scheduler.py and webhook_server.py.
# Usage: powershell -ExecutionPolicy Bypass -File .\start_local.ps1

param(
    [int]$Port = 8000
)

Set-StrictMode -Off
$ErrorActionPreference = "Stop"

# Reload PATH so tools installed in this session (e.g. ngrok via winget) are found
$machinePath = [System.Environment]::GetEnvironmentVariable("PATH", "Machine")
$userPath    = [System.Environment]::GetEnvironmentVariable("PATH", "User")
$env:PATH    = "$machinePath;$userPath"

# --- Load .env ---
$envFile = Join-Path $PSScriptRoot ".env"
if (-not (Test-Path $envFile)) {
    Write-Host "ERROR: .env not found at $envFile" -ForegroundColor Red
    exit 1
}

$env_vars = @{}
foreach ($line in Get-Content $envFile) {
    if ($line -match '^\s*#' -or $line -notmatch '=') { continue }
    $parts = $line -split '=', 2
    $key   = $parts[0].Trim()
    $value = $parts[1].Trim() -replace '#.*$', '' | ForEach-Object { $_.Trim() }
    if ($key -and $value) {
        $env_vars[$key] = $value
        [System.Environment]::SetEnvironmentVariable($key, $value, "Process")
    }
}

$BOT_TOKEN   = $env_vars["TELEGRAM_BOT_TOKEN"]
$NGROK_TOKEN = $env_vars["NGROK_AUTHTOKEN"]

# --- 1. Check Redis ---
Write-Host ""
Write-Host "[1/5] Checking Redis..." -ForegroundColor Cyan
try {
    $pong = docker exec redis-local redis-cli ping 2>&1
    if ($pong -match "PONG") {
        Write-Host "      Redis OK (docker redis-local)" -ForegroundColor Green
    } else {
        throw "unexpected response: $pong"
    }
} catch {
    Write-Host "      Redis NOT running. Start it with:" -ForegroundColor Red
    Write-Host "      docker run -d --name redis-local -p 6379:6379 --restart always redis:7-alpine" -ForegroundColor Yellow
    exit 1
}

# --- 2. Configure ngrok auth token ---
Write-Host ""
Write-Host "[2/5] Configuring ngrok..." -ForegroundColor Cyan
if (-not $NGROK_TOKEN) {
    Write-Host "      NGROK_AUTHTOKEN not set in .env" -ForegroundColor Red
    Write-Host "      Get your token from: https://dashboard.ngrok.com/get-started/your-authtoken" -ForegroundColor Yellow
    Write-Host "      Then add to .env:  NGROK_AUTHTOKEN=your_token_here" -ForegroundColor Yellow
    exit 1
}
# Resolve full path to ngrok so Start-Process works even in nested shells
$ngrokCmd = Get-Command ngrok -ErrorAction SilentlyContinue
$ngrokExe = if ($ngrokCmd) { $ngrokCmd.Source } else { $null }
if (-not $ngrokExe) {
    # Fallback: search WinGet packages directory
    $wingetDir = "$env:LOCALAPPDATA\Microsoft\WinGet\Packages"
    $ngrokExe  = Get-ChildItem $wingetDir -Filter "ngrok.exe" -Recurse -Depth 3 -ErrorAction SilentlyContinue |
                 Select-Object -First 1 -ExpandProperty FullName
}
if (-not $ngrokExe) {
    Write-Host "      ERROR: ngrok.exe not found. Restart your terminal and try again." -ForegroundColor Red
    exit 1
}
Write-Host "      ngrok path: $ngrokExe" -ForegroundColor DarkGray

& $ngrokExe config add-authtoken $NGROK_TOKEN 2>&1 | Out-Null
Write-Host "      Auth token configured." -ForegroundColor Green

# --- 3. Start ngrok tunnel ---
Write-Host ""
Write-Host "[3/5] Starting ngrok tunnel on port $Port..." -ForegroundColor Cyan

Get-Process -Name "ngrok" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1

$ngrokLog = "$env:TEMP\ngrok_err.txt"
Start-Process -FilePath $ngrokExe -ArgumentList "http $Port" -PassThru -RedirectStandardError $ngrokLog | Out-Null

$PUBLIC_URL = $null
$attempts   = 0
while (-not $PUBLIC_URL -and $attempts -lt 15) {
    Start-Sleep -Seconds 1
    $attempts++
    try {
        $tunnels = Invoke-RestMethod -Uri "http://localhost:4040/api/tunnels" -ErrorAction SilentlyContinue
        $https   = $tunnels.tunnels | Where-Object { $_.proto -eq "https" } | Select-Object -First 1
        if ($https) { $PUBLIC_URL = $https.public_url }
    } catch { }
}

if (-not $PUBLIC_URL) {
    Write-Host "      ERROR: ngrok tunnel did not start within 15 seconds." -ForegroundColor Red
    Write-Host "      Check ngrok dashboard at http://localhost:4040" -ForegroundColor Yellow
    exit 1
}

Write-Host "      Tunnel: $PUBLIC_URL" -ForegroundColor Green

# --- 4. Register Telegram webhook ---
Write-Host ""
Write-Host "[4/5] Registering Telegram webhook..." -ForegroundColor Cyan

if (-not $BOT_TOKEN) {
    Write-Host "      TELEGRAM_BOT_TOKEN not set in .env - skipping." -ForegroundColor Yellow
} else {
    $webhookUrl = "$PUBLIC_URL/telegram/webhook"
    $apiUrl     = "https://api.telegram.org/bot${BOT_TOKEN}/setWebhook"

    try {
        $body     = @{ url = $webhookUrl } | ConvertTo-Json
        $response = Invoke-RestMethod -Method Post -Uri $apiUrl -Body $body -ContentType "application/json"
        if ($response.ok) {
            Write-Host "      Webhook set: $webhookUrl" -ForegroundColor Green
        } else {
            Write-Host "      Telegram error: $($response.description)" -ForegroundColor Red
        }
    } catch {
        Write-Host "      Failed to set webhook: $_" -ForegroundColor Red
    }
}

# --- Update PUBLIC_URL in .env ---
$envContent = Get-Content $envFile -Raw
if ($envContent -match "PUBLIC_URL=") {
    $envContent = $envContent -replace "PUBLIC_URL=[^\r\n]*", "PUBLIC_URL=$PUBLIC_URL"
} else {
    $envContent = $envContent.TrimEnd() + [System.Environment]::NewLine + "PUBLIC_URL=$PUBLIC_URL" + [System.Environment]::NewLine
}
[System.IO.File]::WriteAllText($envFile, $envContent, (New-Object System.Text.UTF8Encoding($false)))

# --- 5. Kite OAuth reminder (live mode only) ---
$USE_MOCK_KITE = $env_vars["USE_MOCK_KITE"]
if ($USE_MOCK_KITE -ne "true") {
    Write-Host ""
    Write-Host "[5/5] Kite OAuth Setup (live mode detected)" -ForegroundColor Cyan
    Write-Host "      USE_MOCK_KITE=false - real broker auth is required." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "      IMPORTANT: Complete these steps in order:" -ForegroundColor Yellow
    Write-Host "      1. Start the webhook server (Terminal 1 below)" -ForegroundColor White
    Write-Host "      2. Open your browser and visit:" -ForegroundColor White
    Write-Host "         http://127.0.0.1:8000/kite/login" -ForegroundColor Green
    Write-Host "      3. Log in with your Zerodha credentials" -ForegroundColor White
    Write-Host "      4. You will see: 'Authentication successful!'" -ForegroundColor White
    Write-Host "      5. THEN start the scheduler (Terminal 2 below)" -ForegroundColor White
    Write-Host ""
    Write-Host "      Verify auth: http://127.0.0.1:8000/kite/status" -ForegroundColor DarkGray
} else {
    Write-Host ""
    Write-Host "[5/5] Kite: running in MOCK mode - no OAuth needed." -ForegroundColor DarkGray
}

# --- Done ---
Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host " Local environment ready!" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host " Public URL : $PUBLIC_URL"
Write-Host " Webhook    : $PUBLIC_URL/telegram/webhook"
Write-Host " ngrok UI   : http://localhost:4040"
if ($USE_MOCK_KITE -ne "true") {
    Write-Host " Kite Auth  : http://127.0.0.1:8000/kite/login" -ForegroundColor Yellow
}
Write-Host ""
Write-Host " Now open TWO more terminals and run:" -ForegroundColor Yellow
Write-Host ""
Write-Host "   Terminal 1 - webhook server (start this FIRST):"
Write-Host "   venv\Scripts\activate"
Write-Host "   uvicorn webhook_server:app --host 0.0.0.0 --port $Port --reload"
Write-Host ""
Write-Host "   Terminal 2 - scheduler (start AFTER Kite auth):"
Write-Host "   venv\Scripts\activate"
Write-Host "   python scheduler.py"
if ($USE_MOCK_KITE -ne "true") {
    Write-Host ""
    Write-Host "   Kite Auth   : http://127.0.0.1:8000/kite/login" -ForegroundColor Yellow
    Write-Host "   (visit this in browser after starting Terminal 1)" -ForegroundColor DarkGray
}
Write-Host "==========================================" -ForegroundColor Cyan
