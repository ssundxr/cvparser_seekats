@echo off
echo Starting AI CV Parser Server...
call venv\Scripts\activate
uvicorn main:app --reload
