@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
echo =============================================
echo    MEDIA SELECT PRO V7 - AUDIO + VIDEO
 echo =============================================
where py >nul 2>&1
if not errorlevel 1 (
  py -3 demarrage.py
) else (
  where python >nul 2>&1
  if not errorlevel 1 (
    python demarrage.py
  ) else (
    echo Python introuvable. Installer Python 3.11+ depuis python.org.
    echo Voir le guide README.md
  )
)
echo.
echo Programme ferme. En cas de probleme, voir diagnostic_demarrage.txt.
pause
