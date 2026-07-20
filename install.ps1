# Install btw standalone plugin for Grok Build
param([switch]$NoEnable)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot

Write-Host "=== btw plugin install (standalone Live) ==="

function Resolve-Uv {
    $c = Get-Command uv -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    $candidates = @(
        (Join-Path $env:USERPROFILE "AppData\Local\hermes\bin\uv.exe"),
        (Join-Path $env:USERPROFILE ".local\bin\uv.exe"),
        (Join-Path $env:USERPROFILE "AppData\Local\Programs\uv\uv.exe")
    )
    foreach ($p in $candidates) {
        if (Test-Path $p) { return $p }
    }
    return $null
}

function Ensure-BtwVenv {
    $venvPy = Join-Path $Root ".venv\Scripts\python.exe"
    if (-not (Test-Path $venvPy)) {
        $uv = Resolve-Uv
        if ($uv) {
            Write-Host "Creating plugin .venv with uv ($uv)..."
            & $uv venv (Join-Path $Root ".venv") --python 3.11
        } else {
            Write-Host "Creating plugin .venv with python -m venv..."
            $seed = Get-Command python -ErrorAction SilentlyContinue
            if (-not $seed) { throw "Need uv or python on PATH once to create .venv" }
            & $seed.Source -m venv (Join-Path $Root ".venv")
        }
    }
    if (-not (Test-Path $venvPy)) { throw "Failed to create $venvPy" }

    Write-Host "Installing btw deps into .venv..."
    $uv = Resolve-Uv
    if ($uv) {
        & $uv pip install --python $venvPy -e $Root
    } else {
        & $venvPy -m pip install -U pip -q
        & $venvPy -m pip install -e $Root -q
    }
    & $venvPy -c "import aiortc,sounddevice,av,curl_cffi,numpy,webview; from btw.version import __version__; print('venv ok', __version__)"
    return $venvPy
}

$venvPy = Ensure-BtwVenv
Write-Host "Pinned python: $venvPy"

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

function Sync-InstallTree {
    param([string]$InstallRoot)
    if (-not $InstallRoot -or -not (Test-Path $InstallRoot)) { return }
    if ((Resolve-Path $InstallRoot).Path -eq (Resolve-Path $Root).Path) { return }
    Write-Host "Syncing source into install tree: $InstallRoot"
    $pairs = @(
        @{ From = "src\btw"; To = "src\btw" },
        @{ From = "skills"; To = "skills" },
        @{ From = "sessions"; To = "sessions" },
        @{ From = "mcp"; To = "mcp" },
        @{ From = "assets"; To = "assets" },
        @{ From = ".claude-plugin"; To = ".claude-plugin" }
    )
    foreach ($p in $pairs) {
        $src = Join-Path $Root $p.From
        $dst = Join-Path $InstallRoot $p.To
        if (Test-Path $src) {
            New-Item -ItemType Directory -Force -Path $dst | Out-Null
            Copy-Item -Path (Join-Path $src "*") -Destination $dst -Recurse -Force
        }
    }
    foreach ($f in @("CHANGELOG.md", "pyproject.toml", "README.md", "LICENSE")) {
        $src = Join-Path $Root $f
        if (Test-Path $src) { Copy-Item $src (Join-Path $InstallRoot $f) -Force }
    }
}

$grok = Get-Command grok -ErrorAction SilentlyContinue
if ($grok) {
    & grok plugin install $Root --trust
    if (-not $NoEnable) { & grok plugin enable btw 2>$null }

    # After grok install (incl. "already installed"), force-sync source + .venv
    $launch = Get-BtwLaunchCmd
    if ($launch) {
        $installRoot = Split-Path (Split-Path $launch -Parent) -Parent
        if ($installRoot -and (Test-Path $installRoot)) {
            Sync-InstallTree -InstallRoot $installRoot
            Write-Host "Ensuring .venv on install tree: $installRoot"
            $prev = $Root
            $Root = $installRoot
            try { Ensure-BtwVenv | Out-Null } finally { $Root = $prev }
        }
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
Write-Host "Doctor:  $venvPy -m btw.runtime doctor"
Write-Host "Smoke:   $venvPy -m btw.runtime mint-smoke"
