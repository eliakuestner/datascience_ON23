// --- GLOBALE VARIABLEN & CONFIG ---
const API_BASE_URL = "http://127.0.0.1:8000/api";
let map;
let gridLayerGroup;
let taktChartInstance = null;

// Initialisierung beim Laden der Seite
document.addEventListener("DOMContentLoaded", () => {
    initMap();
    initEventListeners();
    loadGridData();
});

// --- 1. INITIALISIERUNG DER LEAFLET KARTE ---
function initMap() {
    // CRITICAL PERFORMANCE FIX: preferCanvas zwingend aktivieren
    map = L.map("map", {
        preferCanvas: true
    }).setView([49.0069, 8.4037], 11); // Zentriert auf Karlsruhe Hauptbereich

    // Muted Base-Map (CartoDB Positron) damit die Choroplethen-Farben perfekt wirken
    L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
        subdomains: 'abcd',
        maxZoom: 20
    }).addTo(map);

    // Layer-Gruppe für die dynamischen 3x3km Kacheln
    gridLayerGroup = L.layerGroup().addTo(map);
}

// --- 2. EVENT LISTENER REGISTRIEREN ---
function initEventListeners() {
    const indicatorSelect = document.getElementById("indicatorSelect");
    
    // Wenn ein anderer KPI ausgewählt wird, Karte sofort neu laden und umfärben
    indicatorSelect.addEventListener("change", () => {
        loadGridData();
    });
}

// --- 3. DATEN FÜR DIE KARTE ABRAFEN & ZEICHNEN ---
async function loadGridData() {
    const indicator = document.getElementById("indicatorSelect").value;
    gridLayerGroup.clearLayers(); // Alte Kacheln entfernen

    try {
        const response = await fetch(`${API_BASE_URL}/kacheln?indicator=${indicator}`);
        if (!response.ok) throw new Error("Fehler beim Abrufen der Kacheldaten");
        
        const kacheln = await response.getJson ? await response.getJson() : await response.json();

        // Extremwerte ermitteln für eine dynamische, relative Farbskala
        const values = kacheln.map(k => k.value);
        const maxVal = Math.max(...values, 1);

        kacheln.forEach(kachel => {
            // Leaflet benötigt [lat, lon] für die Ecken des Rechtecks
            const bounds = [
                [kachel.lat_min, kachel.lon_min],
                [kachel.lat_max, kachel.lon_max]
            ];

            // Farbwert relativ zum Maximalwert berechnen
            const normalizedValue = kachel.value / maxVal;
            const fillColor = getColorForScale(normalizedValue);

            // Kachel-Rechteck als Canvas-Objekt erzeugen
            const rect = L.rectangle(bounds, {
                color: "#C7CFE3",       // Standard-Rahmenfarbe (Muted Blaugrau)
                weight: 0.5,
                fillColor: fillColor,
                fillOpacity: 0.6,
                interactive: true
            });

            // Hover-Effekte (Striktes Corporate Design)
            rect.on("mouseover", (e) => {
                const layer = e.target;
                layer.setStyle({
                    color: "#E3000B",   // Signalroter Rahmen bei Hover
                    weight: 2,
                    fillOpacity: 0.85
                });
                layer.bringToFront();
            });

            rect.on("mouseout", (e) => {
                rect.setStyle({
                    color: "#C7CFE3",
                    weight: 0.5,
                    fillOpacity: 0.6
                });
            });

            // Klick-Event: Details der Kachel abfragen und Dashboard füllen
            rect.on("click", () => {
                loadKachelDetails(kachel.kachel_id);
            });

            // Schnelles Info-Tooltip beim Drüberfahren
            rect.bindTooltip(`Kachel ID: ${kachel.kachel_id}<br>Wert: ${kachel.value.toFixed(1)}`, {
                sticky: true,
                direction: "top"
            });

            gridLayerGroup.addLayer(rect);
        });

    } catch (error) {
        console.error("📊 Fehler in der Karten-Logik:", error);
    }
}

// --- 4. DYNAMISCHE FARBSKALA (Grau-Blau zu Signalrot) ---
function getColorForScale(val) {
    // Interpolation von dezentem Blaugrau (#C7CFE3) zu kräftigem Signalrot (#E3000B)
    if (val === 0) return "#eef1f6"; // Fast weiß für absolut unbesiedelte/unversorgte Bereiche
    if (val < 0.25) return "#C7CFE3";
    if (val < 0.5)  return "#fca5a5";
    if (val < 0.75) return "#ef4444";
    return "#E3000B"; // Voller Ausschlag (Maximum)
}

// --- 5. DETAILED DATA DASHBOARD BEFÜLLEN ---
async function loadKachelDetails(kachelId) {
    try {
        const response = await fetch(`${API_BASE_URL}/kachel/${kachelId}`);
        if (!response.ok) throw new Error("Details konnten nicht geladen werden");
        
        const data = await response.getJson ? await response.getJson() : await response.json();

        // Stammdaten-Panel aktualisieren
        document.getElementById("dashKachelId").innerText = data.kachel_id;
        document.getElementById("dashEinwohner").innerText = data.einwohner.toLocaleString("de-DE");
        document.getElementById("dashZone").innerText = data.bevoelkerungs_klasse;
        document.getElementById("dashHaltestellen").innerText = data.anzahl_haltestellen;
        
        const linienBadge = document.getElementById("dashLinien");
        linienBadge.innerText = data.linien_liste || "Keine Linien vorhanden";

        // Hypothese 1: Basis-Infrastruktur
        document.getElementById("dashHospital").innerText = `${data.nearest_hospital_name} (${data.dist_hospital_km} km)`;
        document.getElementById("dashTownhall").innerText = `${data.nearest_townhall_name} (${data.dist_townhall_km} km)`;
        document.getElementById("dashBahnhof").innerText = `${data.nearest_bahnhof_name} (${data.dist_bahnhof_km} km)`;

        // Hypothese 1: Kultur- & Freizeit-Säulen
        document.getElementById("dashCinema").innerText = `${data.nearest_cinema_name} (${data.dist_cinema_km} km)`;
        document.getElementById("dashTheatre").innerText = `${data.nearest_theatre_name} (${data.dist_theatre_km} km)`;
        document.getElementById("dashZoo").innerText = `${data.nearest_zoo_name} (${data.dist_zoo_km} km)`;

        // Hypothese 2 & 3: Takt-Array splitten und Chart zeichnen
        const taktArray = data.takt_24h_array.split(",").map(Number);
        updateTaktChart(taktArray);

    } catch (error) {
        console.error("❌ Fehler beim Laden der Kachel-Details:", error);
    }
}

// --- 6. CHART.JS DIAGRAMM GENERIEREN (STRIKTES FLAT-DESIGN) ---
function updateTaktChart(taktData) {
    const ctx = document.getElementById("taktChart").getContext("2d");

    // Falls bereits ein Diagramm existiert, dieses vor dem Neuzeichnen zerstören (Verhindert Render-Glitches)
    if (taktChartInstance !== null) {
        taktChartInstance.destroy();
    }

    // 24-Stunden X-Achsen-Labels erzeugen ("00:00", "01:00", etc.)
    const labels = Array.from({ length: 24 }, (_, i) => `${String(i).padStart(2, '0')}:00`);

    taktChartInstance = new Chart(ctx, {
        type: "line",
        data: {
            labels: labels,
            datasets: [{
                label: "Ø Abfahrten",
                data: taktData,
                borderColor: "#E3000B",       // Eure Akzentfarbe (Signalrot)
                backgroundColor: "rgba(227, 0, 11, 0.05)",
                borderWidth: 2,
                tension: 0,                   // STRIKTES FLAT DESIGN: Keine abgerundeten Kurven!
                pointRadius: 2,
                pointBackgroundColor: "#1a1a1a",
                pointBorderColor: "#E3000B"
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false }    // Minimalistisch ohne redundante Legende
            },
            scales: {
                x: {
                    grid: { display: false }, // Horizontale Cleanliness
                    ticks: {
                        font: { family: "'Titillium Web', sans-serif", size: 10 },
                        maxRotation: 45,
                        autoSkip: true,       // Verhindert Text-Überlagerungen
                        maxTicksLimit: 8
                    }
                },
                y: {
                    beginAtZero: true,
                    grid: { color: "#f0f0f0" },
                    ticks: {
                        font: { family: "'Titillium Web', sans-serif", size: 11 }
                    }
                }
            }
        }
    });
}