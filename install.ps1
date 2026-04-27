# install.ps1 — Windows installer for OpenChronicle
# Mirrors install.sh functionality for Windows environments.
#
# Usage: powershell -ExecutionPolicy Bypass -File install.ps1 [options]
#   --python <version>       Python version for managed runtime (default: 3.12)
#   --bin-dir <path>         Directory for the openchronicle shim script
#   --yes                    Auto-inject all detected MCP client configs
#   --no-client-config       Skip MCP client config prompts entirely
#   -h, --help               Show this help

param(
    [string]$Python = "3.12",
    [string]$BinDir = "",
    [switch]$Yes,
    [switch]$NoClientConfig,
    [switch]$Help
)

$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$InstallHome = if ($env:OPENCHRONICLE_INSTALL_HOME) { $env:OPENCHRONICLE_INSTALL_HOME } else { Join-Path $env:USERPROFILE ".openchronicle" }
$VenvDir = Join-Path $InstallHome "venv"
$UvBin = ""
$OpenChronicleBin = ""
$InstallBinDir = ""

function Log($msg) { Write-Host "[openchronicle-install] $msg" }
function Warn($msg) { Write-Warning "[openchronicle-install] $msg" }
function Die($msg) {
    Write-Error "[openchronicle-install] Error: $msg"
    exit 1
}

if ($Help) {
    @"
Usage: powershell -ExecutionPolicy Bypass -File install.ps1 [options]

Installs OpenChronicle into a dedicated virtualenv, creates an
`openchronicle` launcher, and optionally injects MCP config into
detected clients.

Options:
  -Python <version>        Python version to target (default: 3.12)
  -BinDir <path>           Directory to place the openchronicle launcher
  -Yes                     Auto-inject all detected MCP client configs
  -NoClientConfig          Skip MCP client config prompts entirely
  -Help                    Show this help
"@
    exit 0
}

function Require-RepoRoot {
    $pyprojectPath = Join-Path $RootDir "pyproject.toml"
    $srcPath = Join-Path (Join-Path $RootDir "src") "openchronicle"
    if (-not (Test-Path $pyprojectPath)) { Die "run this script from the repository root" }
    if (-not (Test-Path $srcPath)) { Die "repository layout looks incomplete" }
}

function Check-Platform {
    if ($env:OS -ne "Windows_NT") {
        Die "This installer is for Windows only. Use install.sh on macOS/Linux."
    }
    $ver = [System.Environment]::OSVersion.Version
    if ($ver.Major -lt 10) {
        Die "Windows 10 or later is required (found $($ver.ToString()))"
    }
}

function Ensure-UV {
    $uvCmd = Get-Command uv -ErrorAction SilentlyContinue
    if ($uvCmd) {
        $script:UvBin = $uvCmd.Source
        return
    }

    Log "uv not found; installing it"
    try {
        Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    } catch {
        Die "failed to install uv: $_"
    }

    # Refresh PATH and search again
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "User") + ";" + $env:PATH
    $uvCmd = Get-Command uv -ErrorAction SilentlyContinue
    if ($uvCmd) {
        $script:UvBin = $uvCmd.Source
        return
    }

    $candidates = @(
        (Join-Path (Join-Path (Join-Path $env:USERPROFILE ".local") "bin") "uv.exe"),
        (Join-Path (Join-Path (Join-Path $env:USERPROFILE ".cargo") "bin") "uv.exe")
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) {
            $script:UvBin = $c
            $env:PATH = (Split-Path $c) + ";" + $env:PATH
            return
        }
    }
    Die "uv installation finished but the binary was not found"
}

function Find-CompatiblePython {
    $pyCmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pyCmd) {
        $pyCmd = Get-Command python3 -ErrorAction SilentlyContinue
    }
    if (-not $pyCmd) { return $null }

    try {
        $ver = & $pyCmd.Source -c "import sys; print('.'.join(map(str, sys.version_info[:3])))"
        $parts = $ver.Split('.')
        if ([int]$parts[0] -ge 3 -and [int]$parts[1] -ge 11) {
            return $pyCmd.Source
        }
    } catch {}
    return $null
}

function Prepare-PythonTarget {
    $systemPython = Find-CompatiblePython
    if ($systemPython) {
        Log "using system Python at $systemPython"
        return $systemPython
    }

    Log "system Python < 3.11; installing managed Python $Python via uv"
    & $UvBin python install $Python
    if ($LASTEXITCODE -ne 0) { Die "failed to install Python $Python via uv" }
    return $Python
}

function Install-Package($pythonTarget) {
    if (Test-Path $VenvDir) {
        Remove-Item -Recurse -Force $VenvDir
    }
    New-Item -ItemType Directory -Path $InstallHome -Force | Out-Null

    Log "creating virtualenv at $VenvDir"
    & $UvBin venv $VenvDir --python $pythonTarget
    if ($LASTEXITCODE -ne 0) { Die "failed to create virtualenv" }

    $venvPython = Join-Path (Join-Path $VenvDir "Scripts") "python.exe"

    Log "installing OpenChronicle into the virtualenv"
    & $UvBin pip install --python $venvPython $RootDir
    if ($LASTEXITCODE -ne 0) { Die "failed to install OpenChronicle into $VenvDir" }

    $script:OpenChronicleBin = Join-Path (Join-Path $VenvDir "Scripts") "openchronicle.exe"
    if (-not (Test-Path $OpenChronicleBin)) {
        Die "expected CLI not found at $OpenChronicleBin"
    }
}

function Choose-InstallBinDir {
    if ($BinDir) {
        New-Item -ItemType Directory -Path $BinDir -Force | Out-Null
        return $BinDir
    }

    $localBin = Join-Path (Join-Path $env:USERPROFILE ".local") "bin"
    New-Item -ItemType Directory -Path $localBin -Force | Out-Null
    return $localBin
}

function Install-Launcher {
    $script:InstallBinDir = Choose-InstallBinDir
    $launcherPath = Join-Path $InstallBinDir "openchronicle.cmd"
    $content = "@echo off`r`n`"$OpenChronicleBin`" %*"
    Set-Content -Path $launcherPath -Value $content -Encoding ASCII
    $env:PATH = "$InstallBinDir;$env:PATH"
    Log "installed openchronicle launcher at $launcherPath"
}

function Verify-Install {
    & (Join-Path $InstallBinDir "openchronicle.cmd") status 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Warn "installation verification returned non-zero (this is expected on first run)"
    }
}

function Prompt-YesNo($prompt) {
    if ($Yes) { return $true }
    if ($NoClientConfig) { return $false }

    $reply = Read-Host "$prompt [Y/n]"
    if ([string]::IsNullOrWhiteSpace($reply) -or $reply -match '^[Yy]') {
        return $true
    }
    return $false
}

function Maybe-InjectClient($client, $label) {
    if ($NoClientConfig) { return }

    if (-not $Yes) {
        if (-not (Prompt-YesNo "Detected $label. Inject OpenChronicle MCP config now?")) {
            return
        }
    } else {
        Log "injecting MCP config into $label"
    }

    & (Join-Path $InstallBinDir "openchronicle.cmd") install $client
    if ($LASTEXITCODE -ne 0) {
        Warn "failed to inject MCP config for $label; retry later with 'openchronicle install $client'"
    }
}

function Inject-DetectedClients {
    $codexCfg = Join-Path (Join-Path $env:USERPROFILE ".codex") "config.toml"
    $claudeCodeCfg = Join-Path $env:USERPROFILE ".claude.json"
    $claudeDesktopCfg = Join-Path (Join-Path $env:APPDATA "Claude") "claude_desktop_config.json"
    $opencodeCfg = Join-Path (Join-Path (Join-Path $env:USERPROFILE ".config") "opencode") "opencode.json"

    if (Test-Path $codexCfg) {
        if (Get-Command codex -ErrorAction SilentlyContinue) {
            Maybe-InjectClient "codex" "Codex CLI"
        } else {
            Warn "found $codexCfg, but codex is not on PATH; skipping"
        }
    }

    if (Test-Path $claudeCodeCfg) {
        if (Get-Command claude -ErrorAction SilentlyContinue) {
            Maybe-InjectClient "claude-code" "Claude Code"
        } else {
            Warn "found $claudeCodeCfg, but claude is not on PATH; skipping"
        }
    }

    if (Test-Path $claudeDesktopCfg) {
        Maybe-InjectClient "claude-desktop" "Claude Desktop"
    }

    if ((Test-Path $opencodeCfg) -or (Test-Path "$opencodeCfg`c")) {
        Maybe-InjectClient "opencode" "opencode"
    }
}

function Print-Summary {
    @"

OpenChronicle installed successfully.

Install root : $InstallHome
Virtualenv   : $VenvDir
CLI launcher : $(Join-Path $InstallBinDir 'openchronicle.cmd')

Next steps:
  1. Start the daemon:
     openchronicle start
  2. Check status:
     openchronicle status
  3. (Optional) Add $InstallBinDir to your PATH if not already present.
"@
}

# ─── Main ──────────────────────────────────────────────────────────────

Require-RepoRoot
Check-Platform
Ensure-UV

$pythonTarget = Prepare-PythonTarget
if (-not $pythonTarget) { Die "failed to determine a Python target" }

Install-Package $pythonTarget
Install-Launcher
Verify-Install
Inject-DetectedClients
Print-Summary
