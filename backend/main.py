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

origins = [
    "http://localhost:5500",
    "http://127.0.0.1:5500",
    "http://localhost",
    "http://127.0.0.1",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Bereinigte Spaltenliste inklusive pai
DETAIL_COLUMNS = [
    "kachel_id", "adresse", "einwohner", "bevoelkerungs_klasse", "anzahl_haltestellen", "linien_liste", "pai",
    "p1_lat", "p1_lon", "p2_lat", "p2_lon", "p3_lat", "p3_lon", "p4_lat", "p4_lon",
    "takt_24h_mo", "takt_24h_di", "takt_24h_mi", "takt_24h_do", "takt_24h_fr", "takt_24h_sa", "takt_24h_so",
    "dist_hospital_km", "nearest_hospital_name", "hospital_lon", "hospital_lat",
    "dist_townhall_km", "nearest_townhall_name", "townhall_lon", "townhall_lat",
    "dist_bahnhof_km", "nearest_bahnhof_name", "bahnhof_lon", "bahnhof_lat",
    "dist_cinema_km", "nearest_cinema_name", "cinema_lon", "cinema_lat",
    "dist_theatre_km", "nearest_theatre_name", "theatre_lon", "theatre_lat",
    "dist_zoo_km", "nearest_zoo_name", "zoo_lon", "zoo_lat"
]


def _validate_indicator(indicator: str) -> str:
    mapping = {
        "einwohner": "einwohner",
        "anzahl_haltestellen": "anzahl_haltestellen",
        "pai": "pai"
    }
    if indicator not in mapping:
        raise HTTPException(status_code=400, detail=f"Ungültiger Indikator: {indicator}")
    return mapping[indicator]


# --- SYNCHRONE DATABASE WORKER ---

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
                continue
    return kacheln


# --- ASYNCHRONE API-ENDPUNKTE ---

@app.get("/api/kacheln")
async def get_kacheln(
    indicator: str = Query(default="einwohner", description="KPI für die Karte"),
) -> list[dict[str, Any]]:
    return await asyncio.to_thread(_fetch_kacheln_sync, indicator)


@app.get("/api/kachel/{kachel_id}")
async def get_kachel_details(kachel_id: int):
    """Liefert alle Sidebar-Details, POIs und das Takt-Array für die Grafik."""
    query = "SELECT * FROM public.kachel_analytics WHERE kachel_id = :id LIMIT 1"
    
    with ENGINE.connect() as conn:
        row = conn.execute(text(query), {"id": kachel_id}).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Kachel nicht gefunden")
        
        data = dict(row._mapping)
        clean_data = {}
        for key, val in data.items():
            if val is None:
                if "dist" in key:
                    clean_data[key] = 0.0
                elif "anzahl" in key or "einwohner" in key:
                    clean_data[key] = 0
                elif key == "pai":
                    clean_data[key] = 0.0
                else:
                    clean_data[key] = "-"
            else:
                clean_data[key] = val
        
        if "takt_24h_array" not in clean_data or not clean_data["takt_24h_array"]:
            clean_data["takt_24h_array"] = "0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0"
            
        return clean_data