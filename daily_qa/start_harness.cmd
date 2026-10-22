@echo off
cd /d C:\Users\usama\Downloads\locust
start "reCheck360 QA Harness" /min python daily_qa\simple_harness.py
timeout /t 2 /nobreak >nul
start "" http://127.0.0.1:8765
