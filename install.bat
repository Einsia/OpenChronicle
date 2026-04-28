@echo off
setlocal EnableExtensions DisableDelayedExpansion

rem install.bat - CMD entry point for the Windows OpenChronicle installer.
rem
rem This file intentionally delegates the real install logic to install.ps1 so
rem the project keeps one source of truth. It only:
rem   1. finds PowerShell,
rem   2. maps familiar --long-options to the PowerShell script parameters,
rem   3. preserves a non-zero exit code for CI / scripts.

set "SCRIPT_DIR=%~dp0"
set "PS_SCRIPT=%SCRIPT_DIR%install.ps1"

if not exist "%PS_SCRIPT%" (
    echo [openchronicle-install] Error: install.ps1 not found next to install.bat
    exit /b 1
)

set "PS_EXE="
where pwsh.exe >nul 2>nul
if %ERRORLEVEL%==0 set "PS_EXE=pwsh.exe"
if not defined PS_EXE (
    where powershell.exe >nul 2>nul
    if %ERRORLEVEL%==0 set "PS_EXE=powershell.exe"
)
if not defined PS_EXE (
    if exist "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" (
        set "PS_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
    )
)
if not defined PS_EXE (
    echo [openchronicle-install] Error: PowerShell was not found on PATH.
    exit /b 1
)

set "PS_ARGS="

:parse_args
if "%~1"=="" goto run_installer

if /I "%~1"=="--python" goto opt_python
if /I "%~1"=="-Python" goto opt_python
if /I "%~1"=="--bin-dir" goto opt_bin_dir
if /I "%~1"=="-BinDir" goto opt_bin_dir
if /I "%~1"=="--yes" goto opt_yes
if /I "%~1"=="-Yes" goto opt_yes
if /I "%~1"=="--no-client-config" goto opt_no_client_config
if /I "%~1"=="-NoClientConfig" goto opt_no_client_config
if /I "%~1"=="--help" goto opt_help
if /I "%~1"=="-h" goto opt_help
if /I "%~1"=="-Help" goto opt_help

echo [openchronicle-install] Error: unknown option: %~1
echo.
call :print_usage
exit /b 1

:opt_python
if "%~2"=="" (
    echo [openchronicle-install] Error: %~1 requires a value.
    exit /b 1
)
call :append_arg -Python
call :append_arg "%~2"
shift
shift
goto parse_args

:opt_bin_dir
if "%~2"=="" (
    echo [openchronicle-install] Error: %~1 requires a value.
    exit /b 1
)
call :append_arg -BinDir
call :append_arg "%~2"
shift
shift
goto parse_args

:opt_yes
call :append_arg -Yes
shift
goto parse_args

:opt_no_client_config
call :append_arg -NoClientConfig
shift
goto parse_args

:opt_help
call :print_usage
exit /b 0

:run_installer
"%PS_EXE%" -NoProfile -ExecutionPolicy Bypass -File "%PS_SCRIPT%" %PS_ARGS%
exit /b %ERRORLEVEL%

:append_arg
rem Quote every forwarded argument so paths like "C:\Users\Me\My Bin" survive.
set "PS_ARGS=%PS_ARGS% "%~1""
exit /b 0

:print_usage
echo Usage: install.bat [options]
echo.
echo Installs OpenChronicle into a dedicated virtualenv, creates an
echo openchronicle launcher, and optionally injects MCP config into
echo detected clients.
echo.
echo Options:
echo   --python ^<version^>       Python version to target (default: 3.12)
echo   --bin-dir ^<path^>         Directory to place the openchronicle launcher
echo   --yes                    Auto-inject all detected MCP client configs
echo   --no-client-config       Skip MCP client config prompts entirely
echo   -h, --help               Show this help
exit /b 0
