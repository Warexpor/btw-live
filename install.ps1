# Install btw standalone plugin for Grok Build
param([switch]$NoEnable)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot

Write-Host "=== btw plugin install (standalone Live) ==="
python -m pip install -e "$Root" -q

$data = Join-Path $env:USERPROFILE ".grok\btw"
New-Item -ItemType Directory -Force -Path $data | Out-Null

function Get-BtwLaunchCmd {
    $regPath = Join-Path $env:USERPROFILE ".grok\installed-plugins\registry.json"
    if (Test-Path $regPath) {
        $reg = Get-Content $regPath -Raw | ConvertFrom-Json
        foreach ($prop in $reg.repos.PSObject.Properties) {
            $repo = $prop.Value
            if ($null -ne $repo.plugins.btw) {
                $candidate = Join-Path $repo.path "mcp\launch.cmd"
                if (Test-Path $candidate) { return (Resolve-Path $candidate).Path }
            }
        }
    }
    $fallback = Join-Path $Root "mcp\launch.cmd"
    if (Test-Path $fallback) { return (Resolve-Path $fallback).Path }
    return $null
}

$grok = Get-Command grok -ErrorAction SilentlyContinue
if ($grok) {
    & grok plugin install $Root --trust
    if (-not $NoEnable) { & grok plugin enable btw 2>$null }

    # Plugin .mcp.json uses relative mcp/launch.cmd; Grok often spawns without
    # plugin cwd -> "The system cannot find the path specified."
    # Pin absolute path in user config (same pattern as wrath).
    $launch = Get-BtwLaunchCmd
    if ($launch) {
        & grok mcp add btw -- $launch
        Write-Host "MCP btw pinned: $launch"
    } else {
        Write-Warning "Could not find mcp\launch.cmd - add [mcp_servers.btw] manually with absolute path."
    }
    Write-Host "Plugin installed. Restart Grok (or reconnect MCP) to load tools."
} else {
    $dest = Join-Path $env:USERPROFILE ".grok\plugins\btw"
    if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
    Copy-Item -Recurse -Force $Root $dest
    Write-Host "Copied to $dest"
}

Write-Host "Data:    $data"
Write-Host "Cookies: $data\cookie_header.txt"
Write-Host "Doctor:  python -m btw.runtime doctor"
Write-Host "Smoke:   python -m btw.runtime mint-smoke"
