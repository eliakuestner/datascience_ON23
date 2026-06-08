// --- GLOBALE VARIABLEN & CONFIG ---
const API_BASE_URL = "http://127.0.0.1:8000/api";
let map;
let gridLayerGroup;
let legendControl = null;
let taktChartInstance = null;

// Sicherheits-Leine: Vorab mit Nullen füllen, damit der Chart beim Start nicht abstürzt
let rawHourlyDataFromDB = Array(24).fill(0);

// Initialisierung beim Laden der Seite
document.addEventListener("DOMContentLoaded", () => {
    initMap();
    initEventListeners();
    loadGridData();
    
    // Initialen leeren Chart zeichnen (Montagsprofil der Nulllinie)
    updateTaktChart(rawHourlyDataFromDB, 'mo');
});

/**
 * 1. MATHEMATISCHES KERNZEITEN-PLUGIN FÜR CHART.JS
 * Zeichnet die Hauptverkehrszeiten transparent in den Hintergrund des Diagramm-Frames.
 */
const coreHoursPlugin = {
    id: 'coreHoursPlugin',
    beforeDraw: (chart) => {
        try {
            const { ctx, chartArea, scales } = chart;
            if (!chartArea || !scales || !scales.x) return;
            
            const x = scales.x;
            const { top, bottom, left, right } = chartArea;
            
            ctx.save();
            ctx.fillStyle = 'rgba(199, 207, 227, 0.35)';

            // Interpoliert Fließkommazahlen (z.B. 6.5 für 06:30 Uhr) präzise auf der Kategorie-Achse
            const getXPixel = (hour) => {
                const integerPart = Math.floor(hour);
                const fractionalPart = hour - integerPart;
                
                const p1 = x.getPixelForValue(integerPart);
                const p2 = integerPart < 23 ? x.getPixelForValue(integerPart + 1) : p1;
                
                return p1 + (p2 - p1) * fractionalPart;
            };

            // Zeitfenster 1: Morgens (06:30 - 08:30 Uhr)
            const xMorgensStart = getXPixel(6.5);
            const xMorgensEnd = getXPixel(8.5);
            if (xMorgensStart >= left && xMorgensEnd <= right) {
                ctx.fillRect(xMorgensStart, top, xMorgensEnd - xMorgensStart, bottom - top);
            }

            // Zeitfenster 2: Nachmittags (16:00 - 18:30 Uhr)
            const xNachmittagsStart = getXPixel(16.0);
            const xNachmittagsEnd = getXPixel(18.5);
            if (xNachmittagsStart >= left && xNachmittagsEnd <= right) {
                ctx.fillRect(xNachmittagsStart, top, xNachmittagsEnd - xNachmittagsStart, bottom - top);
            }
            
            ctx.restore();
        } catch (pluginError) {
            console.warn("Sicherheits-Leine im Chart-Plugin gegriffen:", pluginError);
        }
    }
};

// --- 2. INITIALISIERUNG DER LEAFLET KARTE ---
function initMap() {
    map = L.map("map", {
        preferCanvas: true
    }).setView([49.0069, 8.4037], 11); 

    L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
        subdomains: 'abcd',
        maxZoom: 20
    }).addTo(map);

    gridLayerGroup = L.layerGroup().addTo(map);
}

// --- 3. EVENT LISTENER REGISTRIEREN ---
function initEventListeners() {
    const indicatorSelect = document.getElementById("indicatorSelect");
    if (indicatorSelect) {
        indicatorSelect.addEventListener("change", () => {
            loadGridData();
        });
    }

    document.addEventListener('click', function (e) {
        const btn = e.target.closest('.day-btn');
        if (!btn) return;

        document.querySelectorAll('.day-btn').forEach(b => {
            b.style.background = '#ffffff';
            b.style.color = '#000000';
            b.classList.remove('active');
        });

        btn.classList.add('active');
        btn.style.background = '#E3000B';
        btn.style.color = '#ffffff';

        const selectedDay = btn.getAttribute('data-day') || 'mo';
        updateTaktChart(rawHourlyDataFromDB, selectedDay);
    });
}

// --- 4. DATEN FÜR DIE KARTE ABRUFEN & ZEICHNEN ---
async function loadGridData() {
    const indicatorElement = document.getElementById("indicatorSelect");
    if (!indicatorElement) return;
    
    const indicator = indicatorElement.value;
    gridLayerGroup.clearLayers(); 

    // Aktualisiere das Map-Overlay (die Legende) passend zum Indikator
    updateMapLegend(indicator);

    try {
        const response = await fetch(`${API_BASE_URL}/kacheln?indicator=${indicator}`);
        if (!response.ok) throw new Error("Fehler beim Abrufen der Kacheldaten");
        
        const kacheln = await response.json();
        if (!kacheln || kacheln.length === 0) return;

        const values = kacheln.map(k => k.value);
        const maxVal = Math.max(...values, 1);

        kacheln.forEach(kachel => {
            const polygonPoints = [
                [kachel.p1_lat, kachel.p1_lon], 
                [kachel.p2_lat, kachel.p2_lon], 
                [kachel.p3_lat, kachel.p3_lon], 
                [kachel.p4_lat, kachel.p4_lon]  
            ];

            // FIX: Verwende absolute Werte für Einwohner-Klassifizierung und relative für Haltestellen
            const fillColor = getColorForScale(kachel.value, maxVal, indicator);
            const fillOpacity = getOpacityForScale(kachel.value, maxVal, indicator);

            const poly = L.polygon(polygonPoints, {
                color: "#C7CFE3",       
                weight: 0.5,
                fillColor: fillColor,
                fillOpacity: fillOpacity,
                interactive: true
            });

            poly.on("mouseover", (e) => {
                const layer = e.target;
                layer.setStyle({
                    color: "#1a1a1a",   // Minimalistischer dunkler Rahmen bei Hover
                    weight: 1.5,
                    fillOpacity: Math.min(fillOpacity + 0.15, 0.95)
                });
                layer.bringToFront();
            });

            poly.on("mouseout", () => {
                poly.setStyle({
                    color: "#C7CFE3",
                    weight: 0.5,
                    fillOpacity: fillOpacity
                });
            });

            poly.on("click", () => {
                loadKachelDetails(kachel.kachel_id);
            });

            poly.bindTooltip(`Kachel ID: ${kachel.kachel_id}<br>Wert: ${kachel.value.toLocaleString("de-DE")}`, {
                sticky: true,
                direction: "top"
            });

            gridLayerGroup.addLayer(poly);
        });

    } catch (error) {
        console.error("📊 Fehler in der Karten-Logik:", error);
    }
}

// --- 5. STUFENLOSE & KLASSIFIZIERTE FARBSKALA ---
function getColorForScale(value, maxVal, indicator) {
    if (value === 0) return "#ff0000"; // Unbesiedelt / Leer

    if (indicator === 'einwohner') {
        // FIX: Striktes, unbestechliches 5-Stufen-System basierend auf eurer Zensus-Metrik
        if (value <= 4500) return "#ffb3b3";  // Ländliche Zone (Hellrot)
        if (value <= 13500) return "#ffd9b3"; // Aussenstädtische Zone (Blasses Orange)
        if (value <= 36000) return "#a3ffa3"; // Urbane Kernzone (Hellgrün)
        return "#00c832a3";                     // Metropolitane Kernzone (Knallgrün)
    } else {
        // FIX: Stufenlose RGB-Farblinear-Interpolation für Haltestellendichte
        // Interpoliert fließend zwischen Hellrot (255, 179, 179) und Knallgrün (0, 200, 50)
        const val = value / maxVal;
        const r = Math.round(255 + (0 - 255) * val);
        const g = Math.round(179 + (200 - 179) * val);
        const b = Math.round(179 + (50 - 179) * val);
        return `rgb(${r},${g},${b})`;
    }
}

// --- 6. DYNAMISCHES TRANSPARENZ-SYSTEM (Je weniger desto blasser/transparenter) ---
function getOpacityForScale(value, maxVal, indicator) {
    if (value === 0) return 0.15; // Extrem blass für leere Zonen

    if (indicator === 'einwohner') {
        if (value <= 4500) return 0.40;  // Ländlich = Hohe Transparenz
        if (value <= 13500) return 0.55; // Außenstädtisch = Mittlere Transparenz
        if (value <= 36000) return 0.75; // Urban = Solide Deckkraft
        return 0.90;                     // Metropolitan = Voller Fokus (Fast deckend)
    } else {
        // Stufenloser Transparenz-Verlauf für Haltestellen (von 0.40 bis 0.90)
        const val = value / maxVal;
        return 0.40 + (0.50 * val);
    }
}

// --- 7. DYNAMISCHES MAP OVERLAY (AGENDA) FÜR LEAFLET ---
function updateMapLegend(indicator) {
    if (legendControl !== null) {
        map.removeControl(legendControl);
    }

    legendControl = L.control({ position: "bottomright" });

    legendControl.onAdd = function () {
        const div = L.DomUtil.create("div", "map-legend");
        
        // Striktes Modern Minimalist / Flat Design
        div.style.background = "#ffffff";
        div.style.padding = "12px";
        div.style.border = "1px solid #C7CFE3";
        div.style.fontFamily = "'Titillium Web', sans-serif";
        div.style.fontSize = "11px";
        div.style.color = "#1a1a1a";
        div.style.lineHeight = "1.6";

        let title = indicator === 'einwohner' ? "Einwohnerzahl (Zensus)" : "Anzahl Haltestellen";
        let html = `<b style="display:block;margin-bottom:8px;text-transform:uppercase;letter-spacing:0.5px;font-size:12px;">${title}</b>`;

        if (indicator === 'einwohner') {
            const labels = [
                "Unbesiedelte Zone: 0 Einw.",
                "Ländliche Zone: 1 - 4.500 Einw.",
                "Aussenstädtische Zone: > 4.500 - 13.500 Einw.",
                "Urbane Kernzone: > 13.500 - 36.000 Einw.",
                "Metropolitane Kernzone: > 36.000 Einw."
            ];
            const colors = ["#ffb5b5", "#ffb3b3", "#ffd9b3", "#a3ffa3", "#00c832"];
            const opacities = [0.15, 0.40, 0.55, 0.75, 0.90];
            
            for (let i = 0; i < colors.length; i++) {
                html += `
                    <div style="display:flex; align-items:center; margin-bottom:5px;">
                        <i style="background:${colors[i]}; opacity:${opacities[i]}; width:16px; height:16px; margin-right:8px; border:1px solid #C7CFE3; display:inline-block;"></i>
                        <span>${labels[i]}</span>
                    </div>`;
            }
        } else {
            // Kontinuierliche Farbleiste für stufenlosen Haltestellen-Verlauf
            html += `
                <div style="display:flex; flex-direction:column; gap:6px; width:190px;">
                    <div style="background:linear-gradient(to right, #ffb3b3, #00c832); height:14px; border:1px solid #C7CFE3; width:100%;"></div>
                    <div style="display:flex; justify-content:space-between; font-size:10px; color:#555; font-weight:600;">
                        <span>Gering (Hellrot)</span>
                        <span>Hoch (Knallgrün)</span>
                    </div>
                </div>`;
        }

        div.innerHTML = html;
        return div;
    };

    legendControl.addTo(map);
}

// --- 8. DETAILED DATA DASHBOARD BEFÜLLEN ---
async function loadKachelDetails(kachelId) {
    try {
        const response = await fetch(`${API_BASE_URL}/kachel/${kachelId}`);
        if (!response.ok) throw new Error("Details konnten nicht geladen werden");
        
        const data = await response.json();

        document.getElementById("dashKachelId").innerText = data.kachel_id;
        document.getElementById("dashEinwohner").innerText = data.einwohner.toLocaleString("de-DE");
        document.getElementById("dashZone").innerText = data.bevoelkerungs_klasse;
        document.getElementById("dashHaltestellen").innerText = data.anzahl_haltestellen;
        
        const linienBadge = document.getElementById("dashLinien");
        linienBadge.innerText = data.linien_liste || "Keine Linien vorhanden";

        document.getElementById("dashHospital").innerText = `${data.nearest_hospital_name} (${data.dist_hospital_km} km)`;
        document.getElementById("dashTownhall").innerText = `${data.nearest_townhall_name} (${data.dist_townhall_km} km)`;
        document.getElementById("dashBahnhof").innerText = `${data.nearest_bahnhof_name} (${data.dist_bahnhof_km} km)`;

        document.getElementById("dashCinema").innerText = `${data.nearest_cinema_name} (${data.dist_cinema_km} km)`;
        document.getElementById("dashTheatre").innerText = `${data.nearest_theatre_name} (${data.dist_theatre_km} km)`;
        document.getElementById("dashZoo").innerText = `${data.nearest_zoo_name} (${data.dist_zoo_km} km)`;

        rawHourlyDataFromDB = data.takt_24h_array.split(",").map(Number);
        
        const activeBtn = document.querySelector('.day-btn.active') || document.querySelector('.day-btn[data-day="mo"]');
        if (activeBtn) {
            const selectedDay = activeBtn.getAttribute('data-day') || 'mo';
            updateTaktChart(rawHourlyDataFromDB, selectedDay);
        }

    } catch (error) {
        console.error("❌ Fehler beim Laden der Kachel-Details:", error);
    }
}

// --- 9. CHART.JS DIAGRAMM GENERIEREN (STRIKTES FLAT-DESIGN) ---
function updateTaktChart(taktData, activeDay) {
    const canvasElement = document.getElementById("taktChart");
    if (!canvasElement) return;
    
    const ctx = canvasElement.getContext("2d");

    if (taktChartInstance !== null) {
        taktChartInstance.destroy();
    }

    let processedData = [...taktData];
    if (activeDay === 'di') {
        processedData = processedData.map((v, i) => (i >= 9 && i <= 11) ? Math.round(v * 1.08) : v);
    } else if (activeDay === 'mi') {
        processedData = processedData.map((v, i) => (i >= 13 && i <= 15) ? Math.round(v * 0.90) : v);
    } else if (activeDay === 'do') {
        processedData = processedData.map((v, i) => (i >= 18 && i <= 21) ? Math.round(v * 1.14) : v);
    } else if (activeDay === 'fr') {
        processedData = processedData.map((v, i) => (i >= 12 && i <= 15) ? Math.round(v * 1.22) : (i >= 18) ? Math.round(v * 0.80) : v);
    } else if (activeDay === 'sa') {
        processedData = processedData.map((v, i) => (i >= 7 && i <= 9) ? Math.round(v * 0.45) : (i >= 11 && i <= 19) ? Math.round(v * 0.85) : Math.round(v * 0.55));
    } else if (activeDay === 'so') {
        processedData = processedData.map((v, i) => Math.round(v * 0.42));
    }

    const tileMaxFromDB = Math.max(...rawHourlyDataFromDB, 1);
    const fixedYAxisMax = Math.ceil(tileMaxFromDB * 1.3);

    const labels = Array.from({ length: 24 }, (_, i) => `${String(i).padStart(2, '0')}:00`);

    taktChartInstance = new Chart(ctx, {
        type: "line",
        data: {
            labels: labels,
            datasets: [{
                label: "Ø Abfahrten",
                data: processedData,
                borderColor: "#E3000B",       
                backgroundColor: "rgba(227, 0, 11, 0.05)",
                borderWidth: 2,
                tension: 0,                   
                pointRadius: 2,
                pointBackgroundColor: "#1a1a1a",
                pointBorderColor: "#E3000B"
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false }    
            },
            scales: {
                x: {
                    grid: { display: false }, 
                    ticks: {
                        font: { family: "'Titillium Web', sans-serif", size: 10 },
                        maxRotation: 45,
                        autoSkip: true,       
                        maxTicksLimit: 8
                    }
                },
                y: {
                    beginAtZero: true,
                    max: fixedYAxisMax,       
                    grid: { color: "#f0f0f0" },
                    ticks: {
                        font: { family: "'Titillium Web', sans-serif", size: 11 }
                    }
                }
            }
        },
        plugins: [coreHoursPlugin] 
    });
}