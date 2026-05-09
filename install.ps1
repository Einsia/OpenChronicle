param(
    [string]$Python = "3.12",
    [string]$InstallHome = "",
    [string]$BinDir = "",
    [switch]$Start,
    [switch]$NoPathUpdate
)

$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $InstallHome) {
    if (-not $env:LOCALAPPDATA) {
        throw "LOCALAPPDATA is not set; pass -InstallHome explicitly."
    }
    $InstallHome = Join-Path $env:LOCALAPPDATA "OpenChronicle"
}
$VenvDir = Join-Path $InstallHome "venv"

function Write-Log {
    param([string]$Message)
    Write-Host "[openchronicle-install] $Message"
}

function Die {
    param([string]$Message)
    Write-Error "[openchronicle-install] Error: $Message"
    exit 1
}

function Require-RepoRoot {
    if (-not (Test-Path (Join-Path $RootDir "pyproject.toml"))) {
        Die "run this script from the repository root"
    }
    if (-not (Test-Path (Join-Path $RootDir "src\openchronicle"))) {
        Die "repository layout looks incomplete"
    }
}

function Check-Windows11 {
    if ($PSVersionTable.Platform -and $PSVersionTable.Platform -ne "Win32NT") {
        Die "install.ps1 supports Windows 11 only"
    }
    $os = Get-CimInstance Win32_OperatingSystem
    $build = [int]$os.BuildNumber
    if ($build -lt 22000) {
        Die "Windows 11 required (found $($os.Caption), build $build)"
    }
}

function Resolve-Uv {
    $cmd = Get-Command uv -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }

    Write-Log "uv not found; installing it"
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression

    $candidates = @(
        (Join-Path $env:USERPROFILE ".local\bin\uv.exe"),
        (Join-Path $env:USERPROFILE ".cargo\bin\uv.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            $env:Path = "$(Split-Path -Parent $candidate);$env:Path"
            return $candidate
        }
    }
    Die "uv installation finished but uv.exe was not found"
}

function Install-Package {
    param([string]$UvBin)

    New-Item -ItemType Directory -Force -Path $InstallHome | Out-Null
    if (Test-Path $VenvDir) {
        Write-Log "removing existing virtualenv at $VenvDir"
        Remove-Item -Recurse -Force $VenvDir
    }

    Write-Log "installing Python $Python via uv if needed"
    & $UvBin python install $Python
    if ($LASTEXITCODE -ne 0) {
        Die "failed to install Python $Python via uv"
    }

    Write-Log "creating virtualenv at $VenvDir"
    & $UvBin venv $VenvDir --python $Python
    if ($LASTEXITCODE -ne 0) {
        Die "failed to create virtualenv"
    }

    $venvPython = Join-Path $VenvDir "Scripts\python.exe"
    Write-Log "installing OpenChronicle into the virtualenv"
    & $UvBin pip install --python $venvPython $RootDir
    if ($LASTEXITCODE -ne 0) {
        Die "failed to install OpenChronicle"
    }

    $openchronicleExe = Join-Path $VenvDir "Scripts\openchronicle.exe"
    if (-not (Test-Path $openchronicleExe)) {
        Die "expected CLI not found at $openchronicleExe"
    }
    return $openchronicleExe
}

function Resolve-BinDir {
    if ($BinDir) {
        New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
        return (Resolve-Path $BinDir).Path
    }
    $default = Join-Path $env:USERPROFILE ".local\bin"
    New-Item -ItemType Directory -Force -Path $default | Out-Null
    return $default
}

function Quote-PowerShellString {
    param([string]$Value)
    return "'" + $Value.Replace("'", "''") + "'"
}

function Install-Shims {
    param(
        [string]$OpenChronicleExe,
        [string]$TargetBinDir
    )

    $ps1Path = Join-Path $TargetBinDir "openchronicle.ps1"
    $cmdPath = Join-Path $TargetBinDir "openchronicle.cmd"
    $quotedExe = Quote-PowerShellString $OpenChronicleExe

    @"
`$OpenChronicleBin = $quotedExe
& `$OpenChronicleBin @args
exit `$LASTEXITCODE
"@ | Set-Content -Encoding UTF8 $ps1Path

    @"
@echo off
"$OpenChronicleExe" %*
"@ | Set-Content -Encoding ASCII $cmdPath

    Write-Log "installed openchronicle shims at $TargetBinDir"
}

function Ensure-Path {
    param([string]$TargetBinDir)
    $env:Path = "$TargetBinDir;$env:Path"
    if ($NoPathUpdate) {
        return
    }
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $parts = @()
    if ($userPath) {
        $parts = $userPath -split ";"
    }
    if ($parts -notcontains $TargetBinDir) {
        $newPath = if ($userPath) { "$userPath;$TargetBinDir" } else { $TargetBinDir }
        [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
        Write-Log "added $TargetBinDir to the user PATH"
    }
}

function Verify-Install {
    param([string]$TargetBinDir)
    $cli = Join-Path $TargetBinDir "openchronicle.cmd"
    $oldMock = $env:OPENCHRONICLE_LLM_MOCK
    $env:OPENCHRONICLE_LLM_MOCK = "1"
    try {
        & $cli status | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Die "installation verification failed ('openchronicle status' did not succeed)"
        }
    }
    finally {
        $env:OPENCHRONICLE_LLM_MOCK = $oldMock
    }
}

function Print-Summary {
    param([string]$TargetBinDir)
    Write-Host ""
    Write-Host "OpenChronicle installed successfully."
    Write-Host ""
    Write-Host "Data root   : $InstallHome"
    Write-Host "Virtualenv  : $VenvDir"
    Write-Host "CLI shim    : $(Join-Path $TargetBinDir 'openchronicle.cmd')"
    Write-Host ""
    Write-Host "Next steps:"
    Write-Host "  openchronicle start"
    Write-Host "  openchronicle status"
}

Require-RepoRoot
Check-Windows11
$uvBin = Resolve-Uv
$openchronicleExe = Install-Package $uvBin
$targetBinDir = Resolve-BinDir
Install-Shims $openchronicleExe $targetBinDir
Ensure-Path $targetBinDir
Verify-Install $targetBinDir

if ($Start) {
    $cli = Join-Path $targetBinDir "openchronicle.cmd"
    Write-Log "starting OpenChronicle daemon"
    & $cli start
    if ($LASTEXITCODE -ne 0) {
        Die "openchronicle start failed"
    }
}

Print-Summary $targetBinDir
