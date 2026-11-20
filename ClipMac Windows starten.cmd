@echo off
rem ClipMac Windows starten (CM-012). Siehe docs\WINDOWS.md
cd /d "%~dp0"
set PY=.venv-windows\Scripts\python.exe
if not exist "%PY%" (
  echo Python-Umgebung fehlt. Bitte zuerst docs\WINDOWS.md Schritt 1 ausfuehren.
  pause
  exit /b 1
)
choice /c DL /m "Demo (D) oder Livebetrieb (L)?"
if errorlevel 2 (
  "%PY%" -m clipmac_windows
) else (
  "%PY%" -m clipmac_windows --demo
)
pause
