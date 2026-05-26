@echo off
setlocal EnableExtensions EnableDelayedExpansion
pushd "%~dp0"
title Volant

:: Ensure freshly installed tools are reachable in this session.
set "PATH=%PATH%;%USERPROFILE%\.local\bin;C:\Program Files\Git\cmd"

set "VOLANT_PORT=8501"
set "VOLANT_URL=http://localhost:%VOLANT_PORT%"

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
echo     This window will minimize automatically once the server is ready.
echo   
echo     ^(Watcher diagnostics: %WATCHER_LOG%^)

:: Minimize terminal and open localhost once the port is active
start /b powershell -windowstyle minimized -command "$wait = 0; while($wait -lt 30) { try { $t = New-Object System.Net.Sockets.TcpClient('127.0.0.1', 8501); $t.Close(); start 'http://localhost:8501'; break } catch { Start-Sleep -s 1; $wait++ } }" 

:: Run Streamlit in the foreground so this console doubles as the server log.
uv run streamlit run app.py --server.port %VOLANT_PORT% --server.headless true --browser.gatherUsageStats false

popd
endlocal
