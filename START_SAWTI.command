#!/bin/zsh
cd "${0:A:h}"
if [[ ! -f .venv/bin/activate ]]; then
 echo 'First run INSTALL_SAWTI.command'; read; exit 1
fi
source .venv/bin/activate
open 'http://127.0.0.1:8765'
python app.py
