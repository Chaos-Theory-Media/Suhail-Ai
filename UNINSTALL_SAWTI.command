#!/bin/zsh
# Native dialogs; no running Sawti server or application packages required.
set -eu
HERE="${0:A:h}"
[[ "$(uname -s)" == "Darwin" ]] || { print "This launcher is macOS-only; use unit tests on Linux."; exit 1; }
exec /usr/bin/osascript -l JavaScript "$HERE/helpers/uninstall-ui.js" "$HERE"
