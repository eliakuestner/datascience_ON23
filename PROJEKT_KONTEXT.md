# System- & Projektkontext: ÖPNV-Analytics Karlsruhe (Final Version)
Dieses Dokument dient als globaler Kontext für die automatisierte Code-Generierung des Web-Frontends und des FastAPI-Backends. Alle generierten Komponenten müssen sich strikt an die hier definierten Strukturen, Datenmodelle und Design-Vorgaben halten.

---

## 1. Projektübersicht & Wissenschaftlicher Kontext
Das System ist eine interaktive Data-Science-Webanwendung zur Analyse und Visualisierung der ÖPNV-Versorgungsqualität im Raum Karlsruhe. Die Anwendung basiert auf einer räumlichen Kachebene von 3x3-km-Rastern ($9 \text{ km}^2$), die mittels einer geografischen Bounding Box (inkl. 20 km Puffer) exakt auf das KVV-Einzugsgebiet zugeschnitten und berechnet wurden.

Das Projekt validiert drei Kernhypothesen:
* **Hypothese 1 (Infrastruktur):** Die euklidische Erreichbarkeit kritischer POIs (Krankenhäuser, Rathäuser, Fernbahnhöfe) sowie spezifischer Kultur-/Freizeiteinrichtungen (**Kino, Theater, Zoo**) im ländlichen Raum korreliert negativ mit der lokalen Bevölkerungsdichte.
* **Hypothese 2 (Pendler-Taktung):** Die ÖPNV-Abfahrtsdichte bricht in Wohngebieten außerhalb des Karlsruher Zentrums während der exakten Pendler-Stoßzeiten (**Montag–Freitag, morgens 06:30–08:30 Uhr und abends 16:00–18:30 Uhr**) ein.
* **Hypothese 3 (Freizeit-Taktung):** Das Wochenend-Szenario (Samstag–Sonntag, 48h-Schnitt) zeigt eine systematische Unterversorgung peripherer Kacheln im Vergleich zum urbanen Kernbereich.

---

## 2. Technische Systemarchitektur
Das Projekt ist strikt modular aufgebaut:

* **Datenbank:** PostgreSQL (Tabelle: `kachel_analytics`). Enthält alle vorberechneten raum-zeitlichen Indikatoren. Fehlerbereinigt bezüglich Datentypen (String-Harmonisierung der GTFS-IDs) und Koordinatenverzerrungen.
* **Backend:** Python 3.x mit **FastAPI**. Zuständig für performante, indizierte SQL-Abfragen und die Bereitstellung hoch-optimierter JSON-Schnittstellen.
* **Frontend:** Single Page Application (SPA) aus nativem **HTML5**, **CSS3** und modernem **JavaScript (ES6+)**.
    * *Karten-Engine:* **Leaflet.js** (Rendert die 3x3-km-Kacheln dynamisch via HTML5 Canvas-Modus für maximale Framerates).
    * *Charts:* **Chart.js** (Visualisierung des 24-Stunden-Taktverlaufs bei Kachel-Selektion).

---

## 3. Datenbank-Schema-Kontext (`kachel_analytics`)
Verwende bei SQL-Abfragen im Backend exakt diese Spaltennamen und Datentypen. Die Tabelle existiert bereits und ist vollständig befüllt:

| Spaltenname | Datentyp | Beschreibung / Format / Wertebereich |
| :--- | :--- | :--- |
| `kachel_id` | `INT` (PK) | Eindeutige ID der 3x3-km-Rasterzelle |
| `lat_min`, `lon_min` | `FLOAT8` | Geografische Süd-West-Ecke (WGS84 GPS) für Leaflet `L.rectangle` |
| `lat_max`, `lon_max` | `FLOAT8` | Geografische Nord-Ost-Ecke (WGS84 GPS) for Leaflet `L.rectangle` |
| `x_min`, `y_min` | `FLOAT8` | Metrische Koordinatenursprünge (EPSG:3035) |
| `einwohner` | `INT` | Aggregierte Einwohnerzahl der Kachel aus dem Zensus |
| `bevoelkerungs_klasse`| `VARCHAR` | Exakte Zonendefinition:<br>- `"Unbesiedelte Zone"` (0 Einw.)<br>- `"Ländliche Zone"` (1–4.500 Einw.)<br>- `"Aussenstädtische Zone"` (>4.500–13.500 Einw.)<br>- `"Urbane Kernzone"` (>13.500–36.000 Einw.)<br>- `"Metropolitane Kernzone"` (>36.000 Einw.) |
| `dist_hospital_km` <br> `nearest_hospital_name` | `FLOAT8` <br> `VARCHAR` | Euklidische Distanz in km + Name des nächsten Krankenhauses |
| `dist_townhall_km` <br> `nearest_townhall_name` | `FLOAT8` <br> `VARCHAR` | Euklidische Distanz in km + Name des nächsten Rathauses |
| `dist_bahnhof_km` <br> `nearest_bahnhof_name` | `FLOAT8` <br> `VARCHAR` | Euklidische Distanz in km + Name des nächsten Fernbahnhofs |
| `dist_cinema_km` <br> `nearest_cinema_name` | `FLOAT8` <br> `VARCHAR` | **Freizeit 1:** Euklidische Distanz in km + Name des nächsten Kinos |
| `dist_theatre_km` <br> `nearest_theatre_name` | `FLOAT8` <br> `VARCHAR` | **Freizeit 2:** Euklidische Distanz in km + Name des nächsten Theaters |
| `dist_zoo_km` <br> `nearest_zoo_name` | `FLOAT8` <br> `VARCHAR` | **Freizeit 3:** Euklidische Distanz in km + Name des nächsten Zoos |
| `anzahl_haltestellen` | `INT` | Anzahl der physisch in dieser Kachel liegenden GTFS-Stops |
| `linien_liste` | `TEXT` | Kommagetrennter String aller kreuzenden Linien (z. B. `"S1, S11, Bus 47"`) |
| `takt_pendler_morgens`| `FLOAT8` | Ø Abfahrten pro Std. während Pendlerzeiten (Mo-Fr, 06:30-08:30 & 16:00-18:30) |
| `takt_wochenende` | `FLOAT8` | Ø Abfahrten pro Stunde am Wochenende (Sa-So, 48h-Schnitt) |
| `takt_24h_array` | `TEXT` | Kommagetrennter String mit 24 floats (`"0.0,0.0,1.2,4.8..."`) für Chart.js |
| `oepnv_score` | `FLOAT8` | Berechneter Versorgungsindex von 0.0 bis 100.0 |

---

## 4. UI/UX & Visuelle Design-Richtlinien
Die Benutzeroberfläche muss hochprofessionell, übersichtlich und visuell konsistent umgesetzt werden.

* **Design-Stil:** Konsequentes **Flat Design**. Absolut minimalistisch, modern und strukturiert.
* **Formensprache:** Keine abgerundeten Ecken! Jedes Element (`border-radius: 0px !important`), jeder Button und jedes Panel besitzt harte, präzise Kanten.
* **Typografie:** Serifenlose, klare Web-Schriftarten (bevorzugt `Titillium Web` oder standardmäßige System-Sans-Serif).
* **Farbpalette:**
    * *Primary/Accent-Color:* `#E3000B` (Kräftiges Signalrot für Highlights, aktive Zustände, primäre Buttons, Hover-Effekte).
    * *Secondary/Muted-Color:* `#C7CFE3` (Dezentes Blaugrau für Rahmen, Trennlinien, inaktive Elemente).
    * *Hintergründe:* Cleane weiße oder hellgraue UI-Panels im Kontrast zu einer dezenten Base-Map (z. B. *CartoDB Positron* oder *OpenStreetMap Muted*).
* **Layout:** Split-Screen-Ansicht. Links die vollflächige Leaflet-Karte mit zuschaltbaren Steuerungselementen (Layer-Control zur Auswahl des Anzeige-KPIs), rechts eine feste, scrollbare Dashboard-Sidebar für Metriken, Daten-Auswertungen und Diagramme.

---

## 5. Implementierungs-Anforderungen für Copilot

### Backend (`backend/main.py`)
1. Erstelle eine FastAPI-Instanz mit aktivierter CORS-Middleware (erlaube alle Origins für die lokale Entwicklung).
2. Erstelle einen performanten GET-Endpunkt `/api/kacheln`, der die Geometriedaten (`kachel_id`, `lat_min`, `lon_min`, `lat_max`, `lon_max`) sowie den vom Nutzer gewählten Indikator (`oepnv_score`, `einwohner`, `takt_pendler_morgens`, etc.) als flaches, komprimiertes JSON-Array ausgibt.
3. Erstelle einen GET-Endpunkt `/api/kachel/{kachel_id}`, der bei Klick alle Detaildaten (Infrastruktur-Namen, Distanzen, Linienliste) einer spezifischen Kachel für das Dashboard liefert.

### Frontend-Kartenlogik (`frontend/js/app.js`)
1. Initialisiere die Leaflet-Karte zentriert auf die Region Karlsruhe.
2. Nutze beim Initialisieren zwingend die Option `preferCanvas: true` in Leaflet, damit die Kacheln performant gezeichnet werden.
3. Implementiere eine Farbskala (Choroplethen-Karte), die die Kacheln je nach ausgewähltem KPI einfärbt. Bei Hover über eine Kachel erhält diese eine kräftige rote Umrandung (`#E3000B`).

### Frontend-Dashboard & Charts (`frontend/js/app.js` + `index.html`)
1. Binde Chart.js über ein CDN im Header ein.
2. Wenn eine Kachel angeklickt wird, fange das Event ab, lade die Details über die API und splitte den String aus `takt_24h_array` an den Kommas auf (`data.takt_24h_array.split(',')`).
3. Zeichne damit ein minimalistisches Liniendiagramm in der rechten Sidebar (X-Achse: 00:00 bis 23:00 Uhr, Y-Achse: Abfahrten). Verwende für die Linie die Akzentfarbe `#E3000B` ohne abgerundete Kurvenpunkte.
4. Bereite die POI-Namen und Distanzen im Dashboard strukturiert und tabellarisch auf. Verwende präzise Textphrasen wie: *"Nächstes Kino: [Name] ([Distanz] km)"*.