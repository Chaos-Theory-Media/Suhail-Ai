#!/bin/zsh
# Training / demo mode: a simulated studio (no hardware is touched). Uses its own data, so it never affects
# what Sawti learns about real shows. Opens on port 8766 so it can run next to the real Sawti.
export SAWTI_PORT=8766
export SAWTI_DATA="$HOME/Library/Application Support/Sawti/simulation"
"${0:A:h}/launch.sh" --simulate && print "\nSawti SIMULATION is running at http://127.0.0.1:8766 — press Quit on that page to stop it."
