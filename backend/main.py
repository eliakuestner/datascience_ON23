import asyncio
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

# 1. Pfade & .env Konfiguration laden
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def get_database_url() -> str:
    user = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD")
    host = os.getenv("DB_HOST")
    port = os.getenv("DB_PORT")
    name = os.getenv("DB_NAME")
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{name}"


app = FastAPI(title="ÖPNV-Analytics Karlsruhe API")

DATABASE_URL = get_database_url()
ENGINE = create_engine(DATABASE_URL)
# HIER IST DIE UNZERSTÖRBARE CORS-LEINE:
# Wir erlauben explizit JEDE Variante, wie dein Frontend auf den PC zugreifen könnte!
origins = [
    "http://localhost:5500",
    "http://127.0.0.1:5500",
    "http://localhost",
    "http://127.0.0.1",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # <--- Erlaubt starr eure Frontend-Server-Ziele
    allow_credentials=True,
    allow_methods=["*"],    # Erlaubt GET, POST, etc.
    allow_headers=["*"],    # Erlaubt alle Header-Abfragen
)

# Das exakte Spaltenverzeichnis eurer Tabelle
# Das exakte Spaltenverzeichnis eurer Tabelle in backend/main.py
# Das exakte Spaltenverzeichnis eurer Tabelle in backend/main.py
DETAIL_COLUMNS = [
    "kachel_id", "x_min", "y_min", "einwohner", "bevoelkerungs_klasse", "adresse",
    "p1_lat", "p1_lon", "p2_lat", "p2_lon", "p3_lat", "p3_lon", "p4_lat", "p4_lon",
    "dist_hospital_km", "nearest_hospital_name",
    "dist_townhall_km", "nearest_townhall_name",
    "dist_bahnhof_km", "nearest_bahnhof_name",
    "dist_cinema_km", "nearest_cinema_name",
    "dist_theatre_km", "nearest_theatre_name",
    "dist_zoo_km", "nearest_zoo_name",
    "anzahl_haltestellen", "linien_liste",
    "takt_pendler_morgens", "takt_wochenende", "oepnv_score",
    # DIE NEUEN WOCHENTAGS-ARRAYS:
    "takt_24h_mo", "takt_24h_di", "takt_24h_mi", "takt_24h_do", "takt_24h_fr", "takt_24h_sa", "takt_24h_so"
]


def _validate_indicator(indicator: str) -> str:
    # Verknüpft die Dropdown-Werte aus app.js direkt mit euren DB-Spalten
    mapping = {
        "einwohner": "einwohner",
        "stops": "anzahl_haltestellen",
        "anzahl_haltestellen": "anzahl_haltestellen",
        "oepnv_score": "oepnv_score"
    }
    if indicator not in mapping:
        raise HTTPException(status_code=400, detail=f"Ungültiger Indikator: {indicator}")
    return mapping[indicator]


# --- SYNCHRONE DATABASE WORKER (ABGESICHERT GEGEN INT/FLOAT/NULL ABSTÜRZE) ---

def _fetch_kacheln_sync(indicator: str) -> list[dict[str, Any]]:
    column = _validate_indicator(indicator)
    query = text(
        f"""
        SELECT
            kachel_id,
            p1_lat, p1_lon,
            p2_lat, p2_lon,
            p3_lat, p3_lon,
            p4_lat, p4_lon,
            "{column}" AS value
        FROM public.kachel_analytics
        ORDER BY kachel_id
        """
    )

    kacheln = []
    with ENGINE.connect() as connection:
        result = connection.execute(query)
        for row in result:
            mapping = row._mapping
            
            # Sicherheitsfallbacks: Wenn Koordinaten oder Werte NULL sind, fangen wir es ab
            try:
                val = mapping["value"]
                kacheln.append({
                    "kachel_id": int(mapping["kachel_id"]) if mapping["kachel_id"] is not None else 0,
                    "p1_lat": float(mapping["p1_lat"]) if mapping["p1_lat"] is not None else 0.0,
                    "p1_lon": float(mapping["p1_lon"]) if mapping["p1_lon"] is not None else 0.0,
                    "p2_lat": float(mapping["p2_lat"]) if mapping["p2_lat"] is not None else 0.0,
                    "p2_lon": float(mapping["p2_lon"]) if mapping["p2_lon"] is not None else 0.0,
                    "p3_lat": float(mapping["p3_lat"]) if mapping["p3_lat"] is not None else 0.0,
                    "p3_lon": float(mapping["p3_lon"]) if mapping["p3_lon"] is not None else 0.0,
                    "p4_lat": float(mapping["p4_lat"]) if mapping["p4_lat"] is not None else 0.0,
                    "p4_lon": float(mapping["p4_lon"]) if mapping["p4_lon"] is not None else 0.0,
                    "value": float(val) if val is not None else 0.0
                })
            except Exception as e:
                # Überspringt eine defekte Zeile im Notfall, statt die ganze API zu killen
                continue
    return kacheln


def _fetch_kachel_detail_sync(kachel_id: int) -> dict[str, Any] | None:
    query = text(
        f"""
        SELECT {", ".join([f'"{c}"' for c in DETAIL_COLUMNS])}
        FROM public.kachel_analytics
        WHERE kachel_id = :kachel_id
        LIMIT 1
        """
    )
    with ENGINE.connect() as connection:
        row = connection.execute(query, {"kachel_id": kachel_id}).fetchone()
        if not row:
            return None
        
        # Rohe Daten säubern, damit Javascript keine 'null'-Fehler wirft
        raw_data = dict(row._mapping)
        clean_data = {}
        for key, val in raw_data.items():
            if val is None:
                if "dist" in key: clean_data[key] = 0.0
                elif "anzahl" in key or "einwohner" in key: clean_data[key] = 0
                else: clean_data[key] = "-"
            else:
                clean_data[key] = val
        return clean_data


# --- ASYNCHRONE API-ENDPUNKTE ---

@app.get("/api/kacheln")
async def get_kacheln(
    indicator: str = Query(default="einwohner", description="KPI für die Karte"),
) -> list[dict[str, Any]]:
    return await asyncio.to_thread(_fetch_kacheln_sync, indicator)


@app.get("/api/kachel/{kachel_id}")
async def get_kachel(kachel_id: int) -> dict[str, Any]:
    result = await asyncio.to_thread(_fetch_kachel_detail_sync, kachel_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Kachel nicht gefunden")
    return result


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)