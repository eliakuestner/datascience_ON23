@echo off
chcp 65001 >nul
echo 🚀 Starte ÖPNV-Analytics Karlsruhe...
echo --------------------------------------------------

:: 1. BACKEND STARTEN
echo 🚌 Öffne Backend-Server (FastAPI)...
start "ÖPNV Analytics - Backend" cmd /k "cd backend && ..\venv\Scripts\activate.bat && python main.py"

:: Kleine Pause, damit das Backend kurz vorglühen kann
timeout /t 2 >nul

:: 2. FRONTEND STARTEN
echo 💻 Öffne Frontend-Server (Python HTTP)...
start "ÖPNV Analytics - Frontend" cmd /k "cd frontend && python -m http.server 5500"

:: Kleine Pause, bis der Webserver bereit ist
timeout /t 1 >nul

:: 3. BROWSER ÖFFNEN
echo 🌍 Öffne Anwendung im Browser...
start http://localhost:5500/index.html

echo --------------------------------------------------
echo 🎉 Alles erfolgreich gestartet! 
echo Die Server-Logs laufen in den separaten Fenstern.
echo Dieses Fenster kann jetzt geschlossen werden.
timeout /t 3
exit