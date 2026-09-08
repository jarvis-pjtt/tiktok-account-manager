@echo off
cd /d "%~dp0"
python -c "import playwright, requests" 2>nul || (
  echo Installing requirements...
  pip install -r requirements.txt
)
python main.py
pause
