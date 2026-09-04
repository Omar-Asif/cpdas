@echo off
REM CPDAS one-shot setup for Windows.
REM Creates a virtual environment, installs dependencies, generates the
REM deterministic CSV data set, and builds the SQLite database from it.

setlocal

if not exist ".venv" (
    python -m venv .venv
)

call .venv\Scripts\activate.bat

pip install -r requirements.txt

python scripts\generate_data.py
python scripts\seed.py

echo.
echo Setup complete. Run the app with:
echo   .venv\Scripts\activate.bat ^&^& python app.py

endlocal
