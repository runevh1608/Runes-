@echo off
chcp 65001 >nul
cd /d "%~dp0.."
title Likviditet

py -3 --version >nul 2>nul
if errorlevel 1 (
  echo.
  echo  Python er ikke installeret.
  echo  Hent det fra https://www.python.org/downloads/ og installer det.
  echo  Saet flueben i "Add python.exe to PATH" under installationen.
  echo  Dobbeltklik derefter paa start-filen igen.
  echo.
  start "" https://www.python.org/downloads/
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Forbereder appen foerste gang. Det tager et par minutter ...
  py -3 -m venv .venv || goto :fejl
)
".venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check -r requirements.txt || goto :fejl

set "NY=0"
if not exist "%DATA_DIR%\likviditet.sqlite3" set "NY=1"
".venv\Scripts\python.exe" manage.py migrate --noinput -v 0 || goto :fejl

if "%NY%"=="1" (
  if "%DEMO%"=="1" (
    ".venv\Scripts\python.exe" manage.py demodata
  ) else (
    echo.
    echo  Opret jeres foerste bruger. Den anden bruger kan oprettes inde i appen under Administration.
    echo  Mailadresse kan springes over med Enter. Adgangskoden vises ikke, mens du skriver.
    echo.
    ".venv\Scripts\python.exe" manage.py createsuperuser || goto :fejl
  )
)

echo.
echo  Appen koerer nu paa http://127.0.0.1:8000
echo  Lad dette vindue vaere aabent, mens I bruger appen. Luk vinduet for at stoppe den.
echo.
start "" http://127.0.0.1:8000
".venv\Scripts\python.exe" manage.py runserver 127.0.0.1:8000 --noreload
goto :eof

:fejl
echo.
echo  Noget gik galt. Tag et skaermbillede af dette vindue og send det til den, der hjaelper jer.
pause
exit /b 1
