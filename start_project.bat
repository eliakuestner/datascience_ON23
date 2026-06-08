@echo off
chcp 65001 >nul
echo 🚀 Starte ÖPNV-Analytics Karlsruhe...
echo --------------------------------------------------

:: Falls das Skript in einem Unterordner gestartet wurde, springe ins Hauptverzeichnis
if "%CD:~-7%"=="\backend" cd ..
if "%CD:~-9%"=="\frontend" cd ..

:: 1. BACKEND STARTEN (Zwingt Uvicorn auf localhost)
echo 🚌 Öffne Backend-Server (FastAPI)...
start "ÖPNV Analytics - Backend" cmd /k "python -m uvicorn backend.main:app --host localhost --port 8000"
:: 2. FRONTEND STARTEN (Zwingt den Python HTTP Server explizit auf localhost, damit er nicht auf [::] springt!)
echo 💻 Öffne Frontend-Server (Python HTTP)...
start "ÖPNV Analytics - Frontend" cmd /k "cd frontend && python -m http.server 5500 --bind localhost"

:: Kleine Pause, bis der Webserver bereit ist
timeout /t 1 >nul

:: 3. BROWSER ÖFFNEN
echo 🌍 Öffne Anwendung im Browser...
start http://localhost:5500/index.html

echo --------------------------------------------------
echo 🎉 Alles erfolgreich gestartet! 
echo Dieses Fenster schließt sich automatisch.
timeout /t 3 >nul
exit