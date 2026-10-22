@echo off
cd /d C:\Users\usama\Downloads\locust
python daily_qa\enterprise_runner.py --selection daily_qa\daily_enterprise_selection.json
exit /b %ERRORLEVEL%
