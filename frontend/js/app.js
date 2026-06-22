// --- GLOBALE VARIABLEN & CONFIG ---
const API_BASE_URL = "http://127.0.0.1:8000/api";
let map;
let gridLayerGroup;
let poiLayerGroup; 
let legendControl = null;
let taktChartInstance = null;

let selectedLayer = null;
let rawHourlyDataFromDB = Array(24).fill(0);

// Initialisierung beim Laden der Seite
document.addEventListener("DOMContentLoaded", () => {
    initMap();
    initEventListeners();
    loadGridData();
    updateTaktChart('mo');
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
    poiLayerGroup = L.layerGroup().addTo(map); 
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
        updateTaktChart(selectedDay);
    });
}

async function loadGridData() {
    const indicatorElement = document.getElementById("indicatorSelect");
    if (!indicatorElement) return;
    
    const indicator = indicatorElement.value;
    gridLayerGroup.clearLayers(); 
    poiLayerGroup.clearLayers(); 
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
                    
                    // FIX: SetZIndexOffset statt bringToFront für L.marker
                    poiLayerGroup.eachLayer(marker => {
                        if(marker.setZIndexOffset) marker.setZIndexOffset(1000);
                    });
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
                
                // FIX: SetZIndexOffset statt bringToFront für L.marker
                poiLayerGroup.eachLayer(marker => {
                    if(marker.setZIndexOffset) marker.setZIndexOffset(1000);
                });

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
    if (indicator === 'pai') {
        const val = Math.max(0, Math.min(1, value)); 
        const r = Math.round(0 + (227 - 0) * val);
        const g = Math.round(200 + (0 - 200) * val);
        const b = Math.round(50 + (11 - 50) * val);
        return `rgb(${r},${g},${b})`;
    }
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
    if (indicator === 'pai') return 0.70;
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

        let title = indicator === 'einwohner' ? "Einwohnerzahl (Zensus)" : (indicator === 'pai' ? "Pendler-Abhängigkeit (PAI)" : "Anzahl Haltestellen");
        let html = `<b style="display:block;margin-bottom:8px;text-transform:uppercase;letter-spacing:0.5px;font-size:12px;">${title}</b>`;

        if (indicator === 'einwohner') {
            const labels = ["0 Einw.", "1 - 4.500 Einw.", "> 4.500 - 13.500 Einw.", "> 13.500 - 36.000 Einw.", "> 36.000 Einw."];
            const colors = ["#eef1f6", "#ffb3b3", "#ffd9b3", "#a3ffa3", "#00c832"];
            for (let i = 0; i < colors.length; i++) {
                html += `<div style="display:flex; align-items:center; margin-bottom:5px;"><i style="background:${colors[i]}; width:16px; height:16px; margin-right:8px; border:1px solid #C7CFE3; display:inline-block;"></i><span>${labels[i]}</span></div>`;
            }
        } else if (indicator === 'pai') {
            html += `
                <div style="display: flex; flex-direction: column; gap: 5px;">
                    <div style="display:flex; align-items:center;"><i style="background:rgb(227,0,11); width:16px; height:16px; margin-right:8px; border:1px solid #C7CFE3; display:inline-block; opacity:0.7;"></i><span>Hohe Takt-Asymmetrie (Rot)</span></div>
                    <div style="display:flex; align-items:center;"><i style="background:rgb(0,200,50); width:16px; height:16px; margin-right:8px; border:1px solid #C7CFE3; display:inline-block; opacity:0.7;"></i><span>Homogener Ganztagstakt (Grün)</span></div>
                </div>`;
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

function displayPoiMarkersOnMap(data) {
    poiLayerGroup.clearLayers(); 

    // Double Encoding Setup: 2 Farben, 2-Buchstaben-Labels
    const poisToRender = [
        // Daseinsvorsorge (Blau)
        { name: data.nearest_hospital_name, type: "Krankenhaus", label: "Kr", category: "Daseinsvorsorge", lat: parseFloat(data.hospital_lat), lon: parseFloat(data.hospital_lon), color: "#2980b9" },
        { name: data.nearest_townhall_name, type: "Rathaus", label: "Ra", category: "Daseinsvorsorge", lat: parseFloat(data.townhall_lat), lon: parseFloat(data.townhall_lon), color: "#2980b9" },
        { name: data.nearest_bahnhof_name, type: "Fernbahnhof", label: "Bh", category: "Daseinsvorsorge", lat: parseFloat(data.bahnhof_lat), lon: parseFloat(data.bahnhof_lon), color: "#2980b9" },
        // Freizeit & Kultur (Orange)
        { name: data.nearest_cinema_name, type: "Kino", label: "Ki", category: "Freizeit", lat: parseFloat(data.cinema_lat), lon: parseFloat(data.cinema_lon), color: "#e67e22" },
        { name: data.nearest_theatre_name, type: "Theater", label: "Th", category: "Freizeit", lat: parseFloat(data.theatre_lat), lon: parseFloat(data.theatre_lon), color: "#e67e22" },
        { name: data.nearest_zoo_name, type: "Zoo", label: "Zo", category: "Freizeit", lat: parseFloat(data.zoo_lat), lon: parseFloat(data.zoo_lon), color: "#e67e22" }
    ];

    // OVERPLOTTING-SCHUTZ: Wir merken uns belegte Koordinaten und fächern sie auf
    const seenLocations = {};
    const offsetStep = 0.0035; // Distanz der Verschiebung (ca. 250 Meter nach Osten)

    poisToRender.forEach(poi => {
        if (!poi.name || poi.name === "-" || poi.name === "Kein Eintrag" || isNaN(poi.lat) || isNaN(poi.lon) || poi.lat === 0) return;

        // Prüfen, ob diese exakte Koordinate schon belegt ist (auf 4 Nachkommastellen genau)
        const locKey = `${poi.lat.toFixed(4)}_${poi.lon.toFixed(4)}`;
        
        let finalLat = poi.lat;
        let finalLon = poi.lon;

        if (seenLocations[locKey]) {
            // Wenn der Platz belegt ist, verschieben wir den Marker horizontal nach rechts
            finalLon += (offsetStep * seenLocations[locKey]);
            seenLocations[locKey]++; // Zähler erhöhen für den nächsten, der denselben Platz will
        } else {
            // Platz ist frei, wir blockieren ihn für die nächsten
            seenLocations[locKey] = 1;
        }

        // HTML-Marker generieren: Ein Quadrat mit abgerundeten Ecken und einem CSS-Dreieck als Spitze
        const customIcon = L.divIcon({
            className: 'custom-poi-pin',
            html: `
            <div style="display: flex; flex-direction: column; align-items: center; filter: drop-shadow(0px 3px 3px rgba(0,0,0,0.3));">
                <div style="
                    background-color: ${poi.color};
                    color: #ffffff;
                    width: 26px;
                    height: 26px;
                    border-radius: 4px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    font-size: 11px;
                    font-weight: 700;
                    font-family: 'Titillium Web', sans-serif;
                    border: 1px solid #ffffff;
                ">${poi.label}</div>
                <div style="
                    width: 0;
                    height: 0;
                    border-left: 6px solid transparent;
                    border-right: 6px solid transparent;
                    border-top: 8px solid ${poi.color};
                    margin-top: -1px;
                "></div>
            </div>`,
            iconSize: [26, 34], // Breite 26, Höhe 26 + 8 (Dreieck)
            iconAnchor: [13, 34] // Verankert die SPITZE des Dreiecks exakt auf der Koordinate
        });

        const marker = L.marker([finalLat, finalLon], {
            icon: customIcon,
            interactive: true 
        });

        marker.bindTooltip(`
            <div style="font-family: 'Titillium Web', sans-serif; padding: 2px;">
                <strong style="color:${poi.color}; text-transform: uppercase; font-size: 10px; display:block; margin-bottom:2px;">${poi.category}: ${poi.type}</strong>
                <span style="font-size: 12px; font-weight: 600;">${poi.name}</span>
            </div>
        `, {
            direction: "top",
            offset: [0, -34], // Tooltip über die Box schieben
            opacity: 0.95,
            sticky: false 
        });

        poiLayerGroup.addLayer(marker);
    });

    poiLayerGroup.eachLayer(marker => {
        if(marker.setZIndexOffset) marker.setZIndexOffset(1000);
    });
}

let currentTileTaktData = null;

const formatPoi = (poiType, name, dist) => {
    if (!name || name === "-" || name === "Kein Eintrag") return "-";
    const distFormatiert = (typeof dist === 'number') ? dist.toLocaleString("de-DE", { minimumFractionDigits: 1, maximumFractionDigits: 2 }) : dist;
    return `${name} (${distFormatiert} km)`;
};

async function loadKachelDetails(kachelId) {
    try {
        const response = await fetch(`${API_BASE_URL}/kachel/${kachelId}`);
        if (!response.ok) throw new Error("Details konnten nicht geladen werden");
        const data = await response.json();

        currentTileTaktData = data;

        safeSetText("dashKachelId", data.kachel_id);
        safeSetText("dashAdresse", data.adresse || "Keine Adresse ermittelbar");
        safeSetText("dashEinwohner", (data.einwohner || 0).toLocaleString("de-DE"));
        safeSetText("dashZone", data.bevoelkerungs_klasse || "-");
        safeSetText("dashHaltestellen", data.anzahl_haltestellen || 0);
        safeSetText("dashLinien", data.linien_liste || "Keine Linien vorhanden");

        safeSetText("dashHospitalDist", formatPoi("Hospital", data.nearest_hospital_name, data.dist_hospital_km));
        safeSetText("dashTownhallDist", formatPoi("Townhall", data.nearest_townhall_name, data.dist_townhall_km));
        safeSetText("dashBahnhofDist", formatPoi("Bahnhof", data.nearest_bahnhof_name, data.dist_bahnhof_km));
        safeSetText("dashCinemaDist", formatPoi("Cinema", data.nearest_cinema_name, data.dist_cinema_km));
        safeSetText("dashTheatreDist", formatPoi("Theatre", data.nearest_theatre_name, data.dist_theatre_km));
        safeSetText("dashZooDist", formatPoi("Zoo", data.nearest_zoo_name, data.dist_zoo_km));
        
        displayPoiMarkersOnMap(data);

        // --- PAI ERKLÄRUNGSBOX LOGIK (Mathematisch entkoppelte, empirische Erklärung) ---
        const paiBox = document.getElementById("pai-explanation-box");
        const paiValDisplay = document.getElementById("pai-value-display");
        const paiTxtDisplay = document.getElementById("pai-text-display");
        
        if (data.pai !== undefined && data.pai !== null) {
            const paiVal = parseFloat(data.pai) || 0.0;
            const prozentualerEinbruch = Math.round(paiVal * 100);
            
            if (paiBox) paiBox.style.display = "block";
            if (paiValDisplay) paiValDisplay.innerText = `Indexwert: ${paiVal.toFixed(2)} (${prozentualerEinbruch}% Takt-Reduktion)`;
            
            if (paiTxtDisplay) {
                paiTxtDisplay.innerHTML = `Der PAI misst das relationale Delta zwischen den Hauptverkehrszeiten (Peak) und dem Mittags-Nebental (Off-Peak). <br><br>Ein Wert von <strong>${paiVal.toFixed(2)}</strong> belegt empirisch, dass das ÖPNV-Angebot in dieser Kachel außerhalb der Stoßzeiten um exakt <strong>${prozentualerEinbruch}%</strong> ausgedünnt wird. Je höher dieser Prozentsatz ist, desto isolierter operiert die Kachel außerhalb der reinen Pendler-Kernzeiten.`;
            }
        } else {
            if (paiBox) paiBox.style.display = "none";
        }

        const activeBtn = document.querySelector('.day-btn.active') || document.querySelector('.day-btn[data-day="mo"]');
        const selectedDay = activeBtn ? (activeBtn.getAttribute('data-day') || 'mo') : 'mo';
        
        updateTaktChart(selectedDay);
    } catch (error) {
        console.error("❌ Fehler beim Laden der Kachel-Details:", error);
    }
}

function updateTaktChart(activeDay) {
    const canvasElement = document.getElementById("taktChart");
    if (!canvasElement || !currentTileTaktData) return;
    const ctx = canvasElement.getContext("2d");
    if (taktChartInstance !== null) taktChartInstance.destroy();

    let globalMax = 0;
    ['mo', 'di', 'mi', 'do', 'fr', 'sa', 'so'].forEach(tag => {
        const rawString = currentTileTaktData[`takt_24h_${tag}`] || currentTileTaktData[`takt_24h_array`] || "";
        const arr = rawString.split(",").map(Number);
        if (arr.length === 24) {
            globalMax = Math.max(globalMax, ...arr);
        }
    });

    const fixedYAxisMax = globalMax > 2 ? Math.ceil(globalMax * 1.2) : 10;

    const dbSpaltenName = `takt_24h_${activeDay}`;
    const valString = currentTileTaktData[dbSpaltenName] || currentTileTaktData[`takt_24h_array`] || "";
    let processedData = valString.split(",").map(Number);
    if (processedData.length !== 24) processedData = Array(24).fill(0);

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
            plugins: { legend: { display: false } },
            scales: {
                x: { 
                    grid: { display: false }, 
                    ticks: { font: { family: "'Titillium Web', sans-serif", size: 10 }, maxRotation: 45, autoSkip: true, maxTicksLimit: 8 } 
                },
                y: { 
                    beginAtZero: true, 
                    max: fixedYAxisMax,
                    grid: { color: "#f0f0f0" }, 
                    ticks: { font: { family: "'Titillium Web', sans-serif", size: 11 } } 
                }
            }
        },
        plugins: [coreHoursPlugin] 
    });
}