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

where git >nul 2>nul
if errorlevel 1 (
    echo [!] Git was not found on PATH. Skipping update check.
) else (
    if exist ".git\" (
        echo [+] Checking for Volant updates...
        git fetch --quiet
        if errorlevel 1 (
            echo [!] Could not check GitHub for updates. Continuing with the installed version.
        ) else (
            git rev-parse --abbrev-ref --symbolic-full-name @{upstream} >nul 2>nul
            if errorlevel 1 (
                echo [!] No upstream branch is configured. Skipping update check.
            ) else (
                set "GIT_DIRTY="
                for /f "delims=" %%A in ('git status --porcelain') do set "GIT_DIRTY=1"
                if defined GIT_DIRTY (
                    echo [!] Local changes were found. Skipping automatic update to avoid conflicts.
                ) else (
                    set "UPDATE_COUNT=0"
                    for /f "delims=" %%A in ('git rev-list --count HEAD..@{upstream}') do set "UPDATE_COUNT=%%A"
                    if "!UPDATE_COUNT!"=="0" (
                        echo [+] Volant is already up to date.
                    ) else (
                        echo [+] Found !UPDATE_COUNT! update^(s^). Pulling latest version...
                        git pull --ff-only
                        if errorlevel 1 (
                            echo [!] Update failed. Continuing with the installed version.
                        ) else (
                            echo [+] Volant updated successfully.
                        )
                    )
                )
            )
        )
    ) else (
        echo [!] This folder is not a Git checkout. Skipping update check.
    )
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
