========================================================================
ÖPNV-ANALYTICS KARLSRUHE - SCHRITT-FÜR-SCHRITT INBETRIEBNAHME
========================================================================

Diese Anleitung führt Sie ohne Umwege durch die vollständige Einrichtung
und den Start der Anwendung. Bitte stellen Sie sicher, dass alle Schritte
in der vorgegebenen Reihenfolge ausgeführt werden.

VORAUSSETZUNGEN:
----------------
1. Python 3.11 oder höher installiert (inklusive pip).
2. Eine lauffähige DBeaver-Installation (oder ein vergleichbarer DB-Client).
3. Eine aktive Internetverbindung (für Leaflet- und Chart.js-CDNs).

========================================================================
SCHRITT 0: CAMPUS-NETZWERKRECHTE (DHBW-VPN)
========================================================================
Da der PostgreSQL-Server, auf dem die Forschungsdaten liegen, innerhalb 
des geschützten Hochschulnetzwerks der DHBW Mosbach gehostet wird, ist ein 
externer Zugriff ohne verschlüsselten Tunnel blockiert.

1. Starten Sie Ihren installierten VPN-Client (z. B. Cisco Secure Client).
2. Verbinden Sie sich explizit mit dem Gateway der Lehre:
   Vpn.mosbach.dhbw.de/Lehre
3. Authentifizieren Sie sich mit Ihren persönlichen DHBW-Dual3-Zugangsdaten.

Erst wenn der VPN-Tunnel aktiv steht, sind die Ports für die nachfolgenden 
Datenbank-Abfragen physisch erreichbar.

========================================================================
SCHRITT 1: PRÜFUNG DER VERZEICHNISSTRUKTUR
========================================================================
Stellen Sie sicher, dass Ihr Projektverzeichnis exakt so aufgebaut ist:

Projektanwendung/
├── .env
├── start_project.bat
├── backend/
│   ├── main.py
│   └── pipeline.py
└── frontend/
    ├── index.html
    ├── css/
    │   └── style.css
    └── js/
        └── app.js

========================================================================
SCHRITT 2: INFRASTRUKTUR-TEST & UMFELD-VARIABLEN (.env)
========================================================================
Um sicherzustellen, dass die PostgreSQL-Instanz fehlerfrei antwortet, 
wird dringend empfohlen, die Verbindung vorab manuell zu prüfen:

1. Öffnen Sie DBeaver.
2. Erstellen Sie eine neue PostgreSQL-Verbindung mit den Host-Daten aus Moodle.
3. Klicken Sie auf "Verbindung testen". Schlägt dieser fehl, prüfen Sie 
   erneut den VPN-Status aus Schritt 0. Lassen Sie DBeaver geöffnet, falls 
   Sie die Tabellenstrukturen live einsehen möchten.

Erstellen Sie nun die Datei `.env` direkt im Hauptverzeichnis 
(Projektanwendung/) und tragen Sie die Zugangsdaten ein:

DB_HOST=ihr_moodle_server_host
DB_PORT=5432
DB_NAME=ihr_datenbankname
DB_USER=ihr_benutzername
DB_PASSWORD=ihr_passwort

Speichern Sie die Datei ab.

========================================================================
SCHRITT 3: VIRTUAL ENVIRONMENT & PAKETINSTALLATION
========================================================================
1. Öffnen Sie ein Terminal (z.B. PowerShell oder Eingabeaufforderung)
   und navigieren Sie in den Hauptordner des Projekts:
   cd C:\...\Projektanwendung

2. Erstellen Sie eine virtuelle Python-Umgebung:
   python -m venv venv

3. Aktivieren Sie die virtuelle Umgebung unter Windows:
   .\venv\Scripts\activate
   (Nach der Aktivierung steht ein "(venv)" ganz vorne in Ihrer Zeile.)

4. Installieren Sie alle notwendigen Bibliotheken über die requirements.txt im backend-Ordner:
   pip install -r backend/requirements.txt

========================================================================
SCHRITT 4: ANWENDUNG STARTEN
========================================================================
1. Sie können das geöffnete Terminal nun schließen.
2. Machen Sie im Windows-Explorer einen Doppelklick auf die Datei:
   start_project.bat

Diese Batch-Datei startet im Hintergrund den FastAPI-Uvicorn-Server 
unter `http://127.0.0.1:8000` und öffnet zeitgleich das Frontend 
automatisch in Ihrem Webbrowser.