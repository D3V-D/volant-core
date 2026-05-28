#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
printf '\033]0;Volant\007'

# Ensure freshly installed tools are reachable in this session.
export PATH="$PATH:$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin"

VOLANT_HOST="127.0.0.1"
VOLANT_PORT="8501"
VOLANT_URL="http://$VOLANT_HOST:$VOLANT_PORT"

cat <<'EOF'


                        ,--,                               ___
       ,---.          ,--.'|                             ,--.'|_
      /__./|   ,---.  |  | :                     ,---,   |  | :,'
 ,---.;  ; |  '   ,'\ :  : '                 ,-+-. /  |  :  : ' :
/___/ \  | | /   /   ||  ' |     ,--.--.    ,--.'|'   |.;__,'  /
\   ;  \ ' |.   ; ,. :'  | |    /       \  |   |  ,"' ||  |   |
 \   \  \: |'   | |: :|  | :   .--.  .-. | |   | /  | |:__,'| :
  ;   \  ' .'   | .; :'  : |__  \__\/: . . |   | |  | |  '  : |__
   \   \   '|   :    ||  | '.'| ," .--.; | |   | |  |/   |  | '.'|
    \   `  ; \   \  / ;  :    ;/  /  ,.  | |   | |--'    ;  :    ;
     :   \ |  `----'  |  ,   /;  :   .'   \|   |/        |  ,   /
      '---"            ---`-' |  ,     .-./'---'          ---`-'
                               `--`---'

=================================
 Volant - UF Fly Data Analysis
=================================

EOF

if ! command -v uv >/dev/null 2>&1; then
    echo "[X] uv was not found on PATH."
    echo "    Re-run volant-install-mac.command from the parent folder to set up dependencies."
    read -r -p "Press Enter to close..."
    exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
    echo "[X] curl was not found on PATH."
    echo "    Install curl, then re-run this launcher."
    read -r -p "Press Enter to close..."
    exit 1
fi

echo "[+] Preparing Python environment..."
if ! uv sync; then
    echo "[X] uv sync failed. Check the output above for details."
    read -r -p "Press Enter to close..."
    exit 1
fi

wait_for_streamlit() {
    local deadline
    deadline=$((SECONDS + 180))

    while (( SECONDS < deadline )); do
        if curl -fsS --max-time 5 -A "VolantLauncher/1.0" "$VOLANT_URL" >/dev/null 2>&1; then
            return 0
        fi
        sleep 0.5
    done

    return 1
}

minimize_terminal() {
    osascript >/dev/null 2>&1 <<'OSA' || true
tell application "Terminal"
    try
        set miniaturized of windows whose name contains "Volant" to true
    end try
end tell
tell application "iTerm2"
    try
        set minimized of windows whose name contains "Volant" to true
    end try
end tell
OSA
}

echo "[+] Starting Volant on $VOLANT_URL ..."
echo "    Your browser will open when the app is ready."
echo "    This window will minimize a few seconds after that."

(
    if wait_for_streamlit; then
        open "$VOLANT_URL"
        sleep 4
        minimize_terminal
    fi
) &

# Run Streamlit in the foreground so this terminal doubles as the server log.
if ! uv run streamlit run app.py --server.port "$VOLANT_PORT" --server.headless true --browser.gatherUsageStats false; then
    echo
    echo "[X] Volant stopped or failed to start. See the messages above."
    read -r -p "Press Enter to close..."
fi
