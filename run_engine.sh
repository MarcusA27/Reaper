#!/bin/bash
# Start the REAPER engine the app connects to. Export your keys first:
#   export XAI_API_KEY="..."
#   export FISH_API_KEY="..."
#   ./run_engine.sh
cd "$(dirname "$0")"

[ -z "$XAI_API_KEY" ]   && echo "warning: XAI_API_KEY not set — brain will be OFFLINE"
[ -z "$FISH_API_KEY" ]  && echo "warning: FISH_API_KEY not set — voice will be MUTED"
[ -z "$BRAVE_API_KEY" ] && echo "warning: BRAVE_API_KEY not set — ADJUTANT web search disabled"

exec python3 -m reaper.server
