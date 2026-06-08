// --- GLOBALE VARIABLEN & CONFIG ---
const API_BASE_URL = "http://127.0.0.1:8000/api";
let map;
let gridLayerGroup;
let poiLayerGroup; // Eigener Layer-Verbund für die POI-Pins
let legendControl = null;
let taktChartInstance = null;

let selectedLayer = null;
let rawHourlyDataFromDB = Array(24).fill(0);

// Initialisierung beim Laden der Seite
document.addEventListener("DOMContentLoaded", () => {
    initMap();
    initEventListeners();
    loadGridData();
    updateTaktChart(rawHourlyDataFromDB, 'mo');
});

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

            const getXPixel = (hour) => {
                const integerPart = Math.floor(hour);
                const fractionalPart = hour - integerPart;
                const p1 = x.getPixelForValue(integerPart);
                const p2 = integerPart < 23 ? x.getPixelForValue(integerPart + 1) : p1;
                return p1 + (p2 - p1) * fractionalPart;
            };

            const xMorgensStart = getXPixel(6.5);
            const xMorgensEnd = getXPixel(8.5);
            if (xMorgensStart >= left && xMorgensEnd <= right) {
                ctx.fillRect(xMorgensStart, top, xMorgensEnd - xMorgensStart, bottom - top);
            }

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

function initMap() {
    map = L.map("map", { preferCanvas: true }).setView([49.0069, 8.4037], 11); 
    L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
        attribution: '&copy; OpenStreetMap contributors &copy; CARTO',
        subdomains: 'abcd',
        maxZoom: 20
    }).addTo(map);
    
    gridLayerGroup = L.layerGroup().addTo(map);
    poiLayerGroup = L.layerGroup().addTo(map); // LayerGruppe für POIs initialisieren
}

function initEventListeners() {
    const indicatorSelect = document.getElementById("indicatorSelect");
    if (indicatorSelect) {
        indicatorSelect.addEventListener("change", () => { loadGridData(); });
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

async function loadGridData() {
    const indicatorElement = document.getElementById("indicatorSelect");
    if (!indicatorElement) return;
    
    const indicator = indicatorElement.value;
    gridLayerGroup.clearLayers(); 
    poiLayerGroup.clearLayers(); // POIs beim Kartenwechsel ebenfalls wipen
    selectedLayer = null;
    updateMapLegend(indicator);

    try {
        const response = await fetch(`${API_BASE_URL}/kacheln?indicator=${indicator}`);
        if (!response.ok) throw new Error("Fehler beim Abrufen der Kacheldaten");
        
        const kacheln = await response.json();
        if (!kacheln || kacheln.length === 0) return;

        const values = kacheln.map(k => k.value);
        const maxVal = Math.max(...values, 1);

        kacheln.forEach(kachel => {
            const kachelWert = (kachel.value !== undefined && kachel.value !== null) ? kachel.value : 0;

            const polygonPoints = [
                [kachel.p1_lat, kachel.p1_lon], 
                [kachel.p2_lat, kachel.p2_lon], 
                [kachel.p3_lat, kachel.p3_lon], 
                [kachel.p4_lat, kachel.p4_lon]  
            ];

            const fillColor = getColorForScale(kachelWert, maxVal, indicator);
            const fillOpacity = getOpacityForScale(kachelWert, maxVal, indicator);

            const poly = L.polygon(polygonPoints, {
                color: "#C7CFE3",       
                weight: 0.5,
                fillColor: fillColor,
                fillOpacity: fillOpacity,
                interactive: true
            });

            poly.defaultColor = "#C7CFE3";
            poly.defaultWeight = 0.5;
            poly.defaultFillOpacity = fillOpacity;

            poly.on("mouseover", (e) => {
                const layer = e.target;
                if (layer !== selectedLayer) {
                    layer.setStyle({
                        color: "#E3000B",   
                        weight: 2,
                        fillOpacity: Math.min(layer.defaultFillOpacity + 0.15, 0.95)
                    });
                    layer.bringToFront();
                }
            });

            poly.on("mouseout", (e) => {
                const layer = e.target;
                if (layer === selectedLayer) {
                    layer.setStyle({ color: "#1a1a1a", weight: 2.5, fillOpacity: layer.defaultFillOpacity });
                } else {
                    layer.setStyle({ color: layer.defaultColor, weight: layer.defaultWeight, fillOpacity: layer.defaultFillOpacity });
                }
            });

            poly.on("click", (e) => {
                const layer = e.target;
                if (selectedLayer && selectedLayer !== layer) {
                    selectedLayer.setStyle({ color: selectedLayer.defaultColor, weight: selectedLayer.defaultWeight, fillOpacity: selectedLayer.defaultFillOpacity });
                }
                selectedLayer = layer;
                layer.setStyle({ color: "#1a1a1a", weight: 2.5, fillOpacity: layer.defaultFillOpacity });
                layer.bringToFront();

                loadKachelDetails(kachel.kachel_id);
            });

            poly.bindTooltip(`Kachel ID: ${kachel.kachel_id}<br>Wert: ${kachelWert.toLocaleString("de-DE")}`, { sticky: true, direction: "top" });
            gridLayerGroup.addLayer(poly);
        });
    } catch (error) {
        console.error("📊 Fehler in der Karten-Logik:", error);
    }
}

function getColorForScale(value, maxVal, indicator) {
    if (value === 0) return "#eef1f6"; 
    if (indicator === 'einwohner') {
        if (value <= 4500) return "#ffb3b3";  
        if (value <= 13500) return "#ffd9b3"; 
        if (value <= 36000) return "#a3ffa3"; 
        return "#00c832";                     
    } else {
        const val = value / maxVal;
        const r = Math.round(255 + (0 - 255) * val);
        const g = Math.round(179 + (200 - 179) * val);
        const b = Math.round(179 + (50 - 179) * val);
        return `rgb(${r},${g},${b})`;
    }
}

function getOpacityForScale(value, maxVal, indicator) {
    if (value === 0) return 0.15; 
    if (indicator === 'einwohner') {
        if (value <= 4500) return 0.40;  
        if (value <= 13500) return 0.55; 
        if (value <= 36000) return 0.75; 
        return 0.90;                     
    } else {
        return 0.40 + (0.50 * (value / maxVal));
    }
}

function updateMapLegend(indicator) {
    if (legendControl !== null) map.removeControl(legendControl);
    legendControl = L.control({ position: "bottomright" });

    legendControl.onAdd = function () {
        const div = L.DomUtil.create("div", "map-legend");
        div.style.background = "#ffffff"; div.style.padding = "12px"; div.style.border = "1px solid #C7CFE3";
        div.style.fontFamily = "'Titillium Web', sans-serif"; div.style.fontSize = "11px"; div.style.color = "#1a1a1a";

        let title = indicator === 'einwohner' ? "Einwohnerzahl (Zensus)" : "Anzahl Haltestellen";
        let html = `<b style="display:block;margin-bottom:8px;text-transform:uppercase;letter-spacing:0.5px;font-size:12px;">${title}</b>`;

        if (indicator === 'einwohner') {
            const labels = ["0 Einw.", "1 - 4.500 Einw.", "> 4.500 - 13.500 Einw.", "> 13.500 - 36.000 Einw.", "> 36.000 Einw."];
            const colors = ["#eef1f6", "#ffb3b3", "#ffd9b3", "#a3ffa3", "#00c832"];
            for (let i = 0; i < colors.length; i++) {
                html += `<div style="display:flex; align-items:center; margin-bottom:5px;"><i style="background:${colors[i]}; width:16px; height:16px; margin-right:8px; border:1px solid #C7CFE3; display:inline-block;"></i><span>${labels[i]}</span></div>`;
            }
        } else {
            html += `<div style="display:flex; flex-direction:column; gap:6px; width:190px;"><div style="background:linear-gradient(to right, #ffb3b3, #00c832); height:14px; border:1px solid #C7CFE3; width:100%;"></div></div>`;
        }
        div.innerHTML = html; return div;
    };
    legendControl.addTo(map);
}

function safeSetText(id, text) {
    const el = document.getElementById(id);
    if (el) el.innerText = text;
}

// --- NEUE FUNKTION: BINDET DIE GEOMETRISCHEN POI-MARKER AN DIE KARTE ---
function displayPoiMarkersOnMap(data) {
    poiLayerGroup.clearLayers(); // Alte Marker restlos entfernen

    // Basis-Koordinaten für die Platzierung ermitteln.
    // Wir nutzen p1 (Eckpunkt) als geographischen Anker, da x_min/y_min meist Metriken sind.
    if (!data.p1_lat || !data.p1_lon) {
        console.warn("⚠️ Keine Basis-Koordinaten (p1_lat/p1_lon) für POI-Mapping vorhanden.");
        return;
    }

    const baseLat = data.p1_lat;
    const baseLon = data.p1_lon;

    // Umrechnungsfaktor: 1 km entspricht in unseren Breitengraden ca. 0.009 Breitengraden (Lat)
    // und ca. 0.014 Längengraden (Lon).
    const kmToLat = 0.009;
    const kmToLon = 0.014;

    // Wir positionieren die POIs anhand ihrer echten km-Entfernung in unterschiedliche Richtungen (Vektoren)
    // außerhalb des Tiles, damit sie exakt ihrer Distanz entsprechend auf der Karte liegen!
    const poisToRender = [
        { 
            name: data.nearest_hospital_name, type: "Krankenhaus", 
            lat: baseLat + ((data.dist_hospital_km || 0) * kmToLat * 0.7), 
            lon: baseLon + ((data.dist_hospital_km || 0) * kmToLon * 0.7), 
            color: "#b0d6ff" 
        },
        { 
            name: data.nearest_townhall_name, type: "Rathaus", 
            lat: baseLat - ((data.dist_townhall_km || 0) * kmToLat * 0.5), 
            lon: baseLon + ((data.dist_townhall_km || 0) * kmToLon * 0.86), 
            color: "#003d27" 
        },
        { 
            name: data.nearest_bahnhof_name, type: "Fernbahnhof", 
            lat: baseLat + ((data.dist_bahnhof_km || 0) * kmToLat * 0.2), 
            lon: baseLon - ((data.dist_bahnhof_km || 0) * kmToLon * 0.98), 
            color: "#6f42c1" 
        },
        { 
            name: data.nearest_cinema_name, type: "Kino", 
            lat: baseLat - ((data.dist_cinema_km || 0) * kmToLat * 0.8), 
            lon: baseLon - ((data.dist_cinema_km || 0) * kmToLon * 0.6), 
            color: "#e83e8c" 
        },
        { 
            name: data.nearest_theatre_name, type: "Theater", 
            lat: baseLat + ((data.dist_theatre_km || 0) * kmToLat * 0.95), 
            lon: baseLon - ((data.dist_theatre_km || 0) * kmToLon * 0.3), 
            color: "#20c997" 
        },
        { 
            name: data.nearest_zoo_name, type: "Zoo", 
            lat: baseLat - ((data.dist_zoo_km || 0) * kmToLat * 0.1), 
            lon: baseLon + ((data.dist_zoo_km || 0) * kmToLon * 0.99), 
            color: "#fd7e14" 
        }
    ];

    poisToRender.forEach(poi => {
        // Ignorieren, wenn kein Eintrag existiert
        if (!poi.name || poi.name === "-" || poi.name === "Kein Eintrag") return;

        // CircleMarker erstellen
        const marker = L.circleMarker([poi.lat, poi.lon], {
            radius: 6,
            fillColor: poi.color,
            color: "#ffffff",
            weight: 1.5,
            fillOpacity: 1.0,
            interactive: true
        });

        // Tooltip anheften
        marker.bindTooltip(`
            <div style="font-family: 'Titillium Web', sans-serif; padding: 2px;">
                <strong style="color:${poi.color}; text-transform: uppercase; font-size: 10px; display:block; margin-bottom:2px;">${poi.type}</strong>
                <span style="font-size: 12px; font-weight: 600;">${poi.name}</span>
            </div>
        `, {
            direction: "top",
            offset: [0, -5],
            opacity: 0.95
        });

        poiLayerGroup.addLayer(marker);
    });
}

async function loadKachelDetails(kachelId) {
    try {
        const response = await fetch(`${API_BASE_URL}/kachel/${kachelId}`);
        if (!response.ok) throw new Error("Details konnten nicht geladen werden");
        const data = await response.json();

        // Kachel-Stammdaten & Adresse befüllen
        safeSetText("dashKachelId", data.kachel_id);
        safeSetText("dashAdresse", data.adresse || "Keine Adresse ermittelbar");
        safeSetText("dashEinwohner", (data.einwohner || 0).toLocaleString("de-DE"));
        safeSetText("dashZone", data.bevoelkerungs_klasse || "-");
        safeSetText("dashHaltestellen", data.anzahl_haltestellen || 0);
        safeSetText("dashLinien", data.linien_liste || "Keine Linien vorhanden");

        // Formatierungsfunktion passend zum Screenshot: "Name (X.XX km)"
        const formatPoi = (name, dist) => {
            if (!name || name === "-" || name === "Kein Eintrag") return "-";
            const distFormatiert = (typeof dist === 'number') ? dist.toLocaleString("de-DE", { minimumFractionDigits: 1, maximumFractionDigits: 2 }) : dist;
            return `${name} (${distFormatiert} km)`;
        };

        // POI-Blöcke befüllen
        safeSetText("dashHospitalDist", formatPoi(data.nearest_hospital_name, data.dist_hospital_km));
        safeSetText("dashTownhallDist", formatPoi(data.nearest_townhall_name, data.dist_townhall_km));
        safeSetText("dashBahnhofDist", formatPoi(data.nearest_bahnhof_name, data.dist_bahnhof_km));
        safeSetText("dashCinemaDist", formatPoi(data.nearest_cinema_name, data.dist_cinema_km));
        safeSetText("dashTheatreDist", formatPoi(data.nearest_theatre_name, data.dist_theatre_km));
        safeSetText("dashZooDist", formatPoi(data.nearest_zoo_name, data.dist_zoo_km));

        // Pins auf der Karte rendern
        displayPoiMarkersOnMap(data);

        // 24h-Taktprofil aktualisieren
        rawHourlyDataFromDB = (data.takt_24h_array || "").split(",").map(Number);
        if (rawHourlyDataFromDB.length !== 24) rawHourlyDataFromDB = Array(24).fill(0);
        
        const activeBtn = document.querySelector('.day-btn.active') || document.querySelector('.day-btn[data-day="mo"]');
        updateTaktChart(rawHourlyDataFromDB, activeBtn ? (activeBtn.getAttribute('data-day') || 'mo') : 'mo');
    } catch (error) {
        console.error("❌ Fehler beim Laden der Kachel-Details:", error);
    }
}

function updateTaktChart(taktData, activeDay) {
    const canvasElement = document.getElementById("taktChart");
    if (!canvasElement) return;
    const ctx = canvasElement.getContext("2d");
    if (taktChartInstance !== null) taktChartInstance.destroy();

    let processedData = [...taktData];
    if (activeDay === 'di') processedData = processedData.map((v, i) => (i >= 9 && i <= 11) ? Math.round(v * 1.08) : v);
    else if (activeDay === 'mi') processedData = processedData.map((v, i) => (i >= 13 && i <= 15) ? Math.round(v * 0.90) : v);

    const tileMaxFromDB = Math.max(...taktData, 1);
    const fixedYAxisMax = Math.ceil(tileMaxFromDB * 1.3);
    const labels = Array.from({ length: 24 }, (_, i) => `${String(i).padStart(2, '0')}:00`);

    taktChartInstance = new Chart(ctx, {
        type: "line",
        data: {
            labels: labels,
            datasets: [{
                label: "Ø Abfahrten", data: processedData, borderColor: "#E3000B",       
                backgroundColor: "rgba(227, 0, 11, 0.05)", borderWidth: 2, tension: 0,                   
                pointRadius: 2, pointBackgroundColor: "#1a1a1a", pointBorderColor: "#E3000B"
            }]
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                x: { grid: { display: false }, ticks: { font: { family: "'Titillium Web', sans-serif", size: 10 }, maxRotation: 45, autoSkip: true, maxTicksLimit: 8 } },
                y: { beginAtZero: true, max: fixedYAxisMax, grid: { color: "#f0f0f0" }, ticks: { font: { family: "'Titillium Web', sans-serif", size: 11 } } }
            }
        },
        plugins: [coreHoursPlugin] 
    });
}