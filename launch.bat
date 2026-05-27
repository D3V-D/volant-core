@echo off
setlocal EnableExtensions EnableDelayedExpansion
pushd "%~dp0"
title Volant

:: Ensure freshly installed tools are reachable in this session.
set "PATH=%PATH%;%USERPROFILE%\.local\bin;C:\Program Files\Git\cmd"

set "VOLANT_HOST=127.0.0.1"
set "VOLANT_PORT=8501"
set "VOLANT_URL=http://%VOLANT_HOST%:%VOLANT_PORT%"

echo.
echo.
echo                         ,--,                               ___
echo        ,---.          ,--.'^|                             ,--.'^|_
echo       /__./^|   ,---.  ^|  ^| :                     ,---,   ^|  ^| :,'
echo  ,---.^;  ^; ^|  '   ,'\ :  : '                 ,-+-. /  ^|  :  : ' :
echo /___/ \  ^| ^| /   /   ^|^|  ' ^|     ,--.--.    ,--.'^|'   ^|.;__,'  /
echo \   ^;  \ ' ^|.   ^; ,. :'  ^| ^|    /       \  ^|   ^|  ,^"' ^|^|  ^|   ^|
echo  \   \  \: ^|'   ^| ^|: :^|  ^| :   .--.  .-. ^| ^|   ^| /  ^| ^|:__,'^| :
echo   ^;   \  ' .'   ^| .^; :'  : ^|__  \__\/: . . ^|   ^| ^|  ^| ^|  '  : ^|__
echo    \   \   '^|   :    ^|^|  ^| '.'^| ,^" .--.^; ^| ^|   ^| ^|  ^|/   ^|  ^| '.'^|
echo     \   `  ^; \   \  / ^;  :    ^;/  /  ,.  ^| ^|   ^| ^|--'    ^;  :    ^;
echo      :   \ ^|  `----'  ^|  ,   /^;  :   .'   \^|   ^|/        ^|  ,   /
echo       '---^"            ---`-' ^|  ,     .-./'---'          ---`-'
echo                                `--`---'
echo.
echo =================================
echo  Volant - UF Fly Data Analysis
echo =================================
echo.


where uv >nul 2>nul
if errorlevel 1 (
    echo [X] uv was not found on PATH.
    echo     Re-run volant-install.bat from the parent folder to set up dependencies.
    pause
    popd
    exit /b 1
)

echo [+] Preparing Python environment...
uv sync
if errorlevel 1 (
    echo [X] uv sync failed. Check the output above for details.
    pause
    popd
    exit /b 1
)

echo [+] Starting Volant on %VOLANT_URL% ...
echo     Your browser will open when the app is ready.
echo     This window will minimize a few seconds after that.

:: Detached watcher (not /b) so it does not share this console or stdin with Streamlit.
start "VolantReady" /MIN powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0scripts\when_ready.ps1" -Url "%VOLANT_URL%" -Port %VOLANT_PORT% -WindowTitle "Volant"

:: Run Streamlit in the foreground so this console doubles as the server log.
uv run streamlit run app.py --server.port %VOLANT_PORT% --server.headless true --browser.gatherUsageStats false
if errorlevel 1 (
    echo.
    echo [X] Volant stopped or failed to start. See the messages above.
    pause
)

popd
endlocal
