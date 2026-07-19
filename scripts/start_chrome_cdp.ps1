# Launch Chrome with CDP so we can read cookies without DPAPI/ABE decrypt.
# Fully quit all chrome.exe first if using the main profile.

param(
    [int]$Port = 9222,
    [switch]$FreshProfile
)

$chrome = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $chrome) {
    Write-Error "Chrome not found"
    exit 1
}

if ($FreshProfile) {
    $userData = "C:\Users\amicu\chatgpt-live-bridge\re\chrome-cdp-profile"
    New-Item -ItemType Directory -Force -Path $userData | Out-Null
    Write-Host "Using FRESH profile: $userData"
    Write-Host "Log into https://chatgpt.com in the window that opens."
} else {
    $userData = "$env:LOCALAPPDATA\Google\Chrome\User Data"
    Write-Host "Using main profile: $userData"
    Write-Host "All Chrome windows must be closed first."
}

$running = Get-Process chrome -ErrorAction SilentlyContinue
if ($running -and -not $FreshProfile) {
    Write-Error "Chrome is running. Quit it fully (tray too) or re-run with -FreshProfile"
    exit 1
}

Start-Process -FilePath $chrome -ArgumentList @(
    "--remote-debugging-port=$Port",
    "--user-data-dir=$userData",
    "--no-first-run",
    "--no-default-browser-check",
    "https://chatgpt.com/"
)

Write-Host "CDP: http://127.0.0.1:$Port/json/version"
Write-Host "After login:  python scripts\extract_cookies_cdp.py --port $Port"
