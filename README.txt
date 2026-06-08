========================================================================
ÖPNV-ANALYTICS KARLSRUHE - SCHRITT-FÜR-SCHRITT INBETRIEBNAHME
========================================================================

Diese Anleitung führt Sie ohne Umwege durch die vollständige Einrichtung
und den Start der Anwendung. Bitte stellen Sie sicher, dass alle Schritte
in der vorgegebenen Reihenfolge ausgeführt werden.

VORAUSSETZUNGEN:
----------------
1. Python 3.11 oder höher installiert (inklusive pip).
2. Eine laufende PostgreSQL-Datenbankinstanz mit Schreibrechten.
3. Eine aktive Internetverbindung (für Leaflet- und Chart.js-CDNs).

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
SCHRITT 2: DATENBANK-KONFIGURATION (.env)
========================================================================
Erstellen Sie die Datei `.env` direkt im Hauptverzeichnis 
(Projektanwendung/) und tragen Sie Ihre PostgreSQL-Zugangsdaten von Moodle ein:

DB_HOST=127.0.0.1
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

4. Installieren Sie alle notwendigen Bibliotheken über pip:
   pip install fastapi uvicorn pandas geopandas shapely sqlalchemy psycopg2 python-dotenv

========================================================================
SCHRITT 4: AUSFÜHREN DER DATA-PIPELINE (ETL)
========================================================================
Bevor das Frontend Daten anzeigen kann, müssen die Kacheln berechnet
und in die Datenbank geschrieben werden. Führen Sie im aktivierten 
Terminal folgenden Befehl aus:

python backend/pipeline.py

Warten Sie, bis das Skript alle Phasen durchlaufen hat und die Erfolgsmeldung
ausgibt: "🎉 ETL-Pipeline erfolgreich beendet!". In Ihrer Datenbank wurde 
nun die Tabelle `kachel_analytics` mit exakt 221 bereinigten Zeilen angelegt.

========================================================================
SCHRITT 5: ANWENDUNG STARTEN
========================================================================
1. Sie können das geöffnete Terminal nun schließen.
2. Machen Sie im Windows-Explorer einen Doppelklick auf die Datei:
   start_project.bat

Diese Batch-Datei startet im Hintergrund den FastAPI-Uvicorn-Server 
unter `http://127.0.0.1:8000` und öffnet zeitgleich das Frontend 
automatisch in Ihrem Webbrowser.

========================================================================
WICHTIGER HINWEIS BEI FRONTEND-ÄNDERUNGEN:
========================================================================
Da Webbrowser JavaScript-Dateien extrem aggressiv im internen Speicher
halten, drücken Sie nach dem ersten Laden oder nach Code-Anpassungen 
im Browser unbedingt die Tastenkombination:

   Strg + F5 (Hard Reload / Erzwungenes Neuladen)

Dadurch wird der Cache gelöscht und das neue, passgenaue Gitter samt 
Wochentagsleiste und Selektionsrahmen fehlerfrei gerendert.
=========================================================================