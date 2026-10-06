#!/bin/bash
# Run the engine and auto-restart it whenever a Python/core file changes.
# YOU run this once in a terminal that has the API keys exported:
#   export XAI_API_KEY=...; export FISH_API_KEY=...; export BRAVE_API_KEY=...
#   ./watch_engine.sh
# After that, every engine change Claude makes restarts it automatically —
# the app reconnects on its own.
cd "$(dirname "$0")" || exit 1

checksum() {
    find reaper cores -type f \( -name '*.py' -o -name '*.toml' \) \
        -exec stat -f '%m %N' {} + 2>/dev/null | md5
}

[ -z "$XAI_API_KEY" ]   && echo "warning: XAI_API_KEY not set — brain OFFLINE"
[ -z "$FISH_API_KEY" ]  && echo "warning: FISH_API_KEY not set — voice MUTED"
[ -z "$BRAVE_API_KEY" ] && echo "warning: BRAVE_API_KEY not set — web search OFF"

while true; do
    python3 -m reaper.server &
    PID=$!
    SUM=$(checksum)
    while kill -0 "$PID" 2>/dev/null; do
        sleep 1
        if [ "$(checksum)" != "$SUM" ]; then
            echo "── change detected, restarting engine ──"
            kill "$PID" 2>/dev/null
            break
        fi
    done
    wait "$PID" 2>/dev/null
    sleep 0.5
done
