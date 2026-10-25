#!/bin/zsh
# Removes Sawti. Recordings are never touched.
SUPPORT="$HOME/Library/Application Support/Sawti"
print "Sawti uninstaller — your recordings are NOT deleted."
read "a?Continue? [y/n]: "; [[ "$a" == [yY]* ]] || exit 0
for port in 8765 8766; do
  curl -fs --max-time 2 -X POST -H 'X-Sawti: 1' "http://127.0.0.1:$port/api/quit" >/dev/null 2>&1
done
sleep 1
if [[ -x "$SUPPORT/bin/sawti-audio" ]]; then
  read "a?Also remove the audio devices Sawti created (Sawti Show Input, Sawti Zoom Speaker)? [y/n]: "
  if [[ "$a" == [yY]* ]]; then
    "$SUPPORT/bin/sawti-audio" destroy --uid com.imi.sawti.show-input
    "$SUPPORT/bin/sawti-audio" destroy --uid com.imi.sawti.zoom-speaker
  fi
fi
rm -rf "$HOME/Applications/Sawti.app" "$HOME/Desktop/Sawti" "$HOME/Desktop/Sawti.app"
read "a?Delete Sawti's data (local AI model, learned habits, templates, settings)? [y/n]: "
[[ "$a" == [yY]* ]] && rm -rf "$SUPPORT" && print "Sawti data removed."
print "Done. You can now delete the Sawti folder."
read "?Press Return to close."
