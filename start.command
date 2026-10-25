#!/bin/zsh
cd "${0:A:h}"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv || { echo 'Install Python 3.11+ from python.org and try again'; read; exit 1; }
fi
source .venv/bin/activate
python -m pip install -r requirements.txt || { echo 'Dependency installation failed'; read; exit 1; }
open 'http://127.0.0.1:8765'
python app.py
