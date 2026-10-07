@echo off
setlocal
rem DupFinder launcher: find pythonw automatically
set "PYW="
if exist "%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\pythonw.exe" set "PYW=%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\pythonw.exe"
if not defined PYW if exist "%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe" set "PYW=%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if not defined PYW for /f "delims=" %%i in ('where pythonw 2^>nul') do if not defined PYW set "PYW=%%i"
if not defined PYW if exist "%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\pythonw.exe" set "PYW=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\pythonw.exe"
if not defined PYW for /f "delims=" %%i in ('where python 2^>nul') do if not defined PYW set "PYW=%%i"
if not defined PYW (
  echo [DupFinder] Python not found. Please install Python first.
  pause
  exit /b
)
start "DupFinder" "%PYW%" "%~dp0finder_app.py"
endlocal
