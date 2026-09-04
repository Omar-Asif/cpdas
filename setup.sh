#!/usr/bin/env bash
# CPDAS one-shot setup for macOS/Linux.
# Creates a virtual environment, installs dependencies, generates the
# deterministic CSV data set, and builds the SQLite database from it.

set -e

if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi

source .venv/bin/activate

pip install -r requirements.txt

python scripts/generate_data.py
python scripts/seed.py

echo
echo "Setup complete. Run the app with:"
echo "  source .venv/bin/activate && python app.py"
