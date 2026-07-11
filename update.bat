@echo off
call .venv\Scripts\activate
python scripts\update.py
python scripts\fit.py
python scripts\project.py
pause
