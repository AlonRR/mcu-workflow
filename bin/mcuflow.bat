@echo off
rem mcuflow - Windows CLI entry point. Add this bin\ folder to PATH, then run `mcuflow ...`.
python "%~dp0..\src\mcuflow\mcuflow.py" %*
