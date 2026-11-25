@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Lance d'abord OUVRIR_WINDOWS.cmd pour préparer l'environnement.
  pause
  exit /b 1
)

echo Installation de PyInstaller...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check pyinstaller
if errorlevel 1 goto :error

echo Construction de MediaSelectPro.exe...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --console --name MediaSelectPro --add-data "interface.html;." --collect-all yt_dlp serveur.py
if errorlevel 1 goto :error

echo.
echo EXE créé : dist\MediaSelectPro.exe
pause
exit /b 0

:error
echo.
echo La construction a échoué.
pause
exit /b 1
