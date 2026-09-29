@echo off
setlocal
pushd "%~dp0"
if errorlevel 1 exit /b 1
if not exist ".venv\Scripts\python.exe" (
    echo Create .venv and install the project dependencies first. See README.md.
    popd
    exit /b 1
)
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"
set "DESKTOP_AI_RUN_LOOP=1"
:run
".venv\Scripts\python.exe" -u -m desktop_ai_assistant --settings %*
set "runExit=%ERRORLEVEL%"
if "%runExit%"=="75" goto run
popd
exit /b %runExit%
