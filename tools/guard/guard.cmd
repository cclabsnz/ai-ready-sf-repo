@echo off
rem Windows fallback wrapper (the registered hook is guard.sh via Git Bash): find an interpreter or FAIL CLOSED.
rem Claude Code treats any exit code other than 0/2 as a non-blocking warning, so only 0 and 2 may leave here.
set "DIR=%~dp0"
if not exist "%DIR%guard.py" (
  echo BLOCKED: tools/guard/guard.py not found or unreadable; failing closed 1>&2
  exit /b 2
)
rem Each branch runs the guard, then jumps to :done. Never "& exit /b %errorlevel%" in one block:
rem %errorlevel% would be expanded before the interpreter runs.
where py >nul 2>&1
if not errorlevel 1 ( py -3 -I "%DIR%guard.py" & goto :done )
where python >nul 2>&1
if not errorlevel 1 ( python -I "%DIR%guard.py" & goto :done )
where python3 >nul 2>&1
if not errorlevel 1 ( python3 -I "%DIR%guard.py" & goto :done )
echo BLOCKED: no Python interpreter found for the guard; failing closed 1>&2
exit /b 2
:done
rem Compare as text: crash codes are negative, which "if errorlevel" cannot test. 0 allows; 2 and anything else block.
set "RC=%errorlevel%"
if "%RC%"=="0" exit /b 0
exit /b 2
