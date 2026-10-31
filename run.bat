@echo off
REM Double-click this file to set up (first time) and start Retrieval Duel.
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python 3.10 or newer from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH" during setup.
  pause
  exit /b 1
)

if not exist .venv (
  echo Creating a private Python environment in .venv ...
  python -m venv .venv
)
call .venv\Scripts\activate.bat

echo Installing or updating libraries ...
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt
python -m pip install -q fastembed || echo (fastembed could not be installed; the app will use simple word matching instead)

if not exist .env (
  copy .env.example .env >nul
  echo.
  echo Created a .env file. Open it in Notepad and paste your Anthropic API key after ANTHROPIC_API_KEY=
  echo The Larkspur demo works without a key.
  echo.
)

python -m rduel
pause
