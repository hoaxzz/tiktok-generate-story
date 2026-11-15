@echo off
title TikTok Story & Satisfying Clipper Studio
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    echo [*] Menjalankan server menggunakan virtual environment (.venv)...
    ".venv\Scripts\python.exe" run.py
) else (
    echo [*] Menjalankan server menggunakan Python sistem...
    python run.py
)
pause
