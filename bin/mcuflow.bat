@echo off
rem mcuflow - Windows CLI entry point. Add this bin\ folder to PATH, then run `mcuflow ...`.
rem Prefers the project's uv-managed .venv interpreter; falls back to python.
setlocal
set "ROOT=%~dp0.."
if exist "%ROOT%\.venv\Scripts\python.exe" (
  "%ROOT%\.venv\Scripts\python.exe" "%ROOT%\src\mcuflow\mcuflow.py" %*
) else (
  python "%ROOT%\src\mcuflow\mcuflow.py" %*
)
