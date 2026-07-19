@echo off
setlocal EnableExtensions
set "ROOT=%~dp0.."
rem Prefer plugin-local venv — never bare PATH python (Hermes etc.).
set "PY=%ROOT%\.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo btw: missing plugin .venv at "%ROOT%\.venv"
  echo btw: run install.ps1 from the plugin root once.
  exit /b 1
)
set "PYTHONPATH=%ROOT%\src;%PYTHONPATH%"
set "PYTHONUNBUFFERED=1"
set "BTW_PYTHON=%PY%"
"%PY%" -u "%~dp0server.py"
