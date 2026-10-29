@echo off
rem Windows wrapper: find an interpreter or FAIL CLOSED (exit 2).
set DIR=%~dp0
where py >nul 2>&1 && ( py -3 -I "%DIR%guard.py" & exit /b %errorlevel% )
where python >nul 2>&1 && ( python -I "%DIR%guard.py" & exit /b %errorlevel% )
where python3 >nul 2>&1 && ( python3 -I "%DIR%guard.py" & exit /b %errorlevel% )
echo BLOCKED: no Python interpreter found for the guard; failing closed 1>&2
exit /b 2
