#!/usr/bin/env fish
cd (dirname (status filename))
if not test -d .venv
    python -m venv .venv
end
source .venv/bin/activate.fish
pip install -r requirements.txt
python main.py
