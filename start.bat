@echo off
pip install -r requirements.txt
echo.
echo username:
set /p username=
echo password:
set /p password=
python main.py "%username%" "%password%"
pause