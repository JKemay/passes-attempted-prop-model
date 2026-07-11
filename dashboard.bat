@echo off
call .venv\Scripts\activate
start http://127.0.0.1:8710
python -m uvicorn webapp.main:app --port 8710
