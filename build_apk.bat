@echo off
cd /d "%~dp0"
python -m pip install -r requirements.txt
flet build apk --permissions camera
if errorlevel 1 (echo BUILD FAILED & pause & exit /b 1)
echo APK build completed. Check build
for /r %%F in (*.apk) do echo %%F
pause
