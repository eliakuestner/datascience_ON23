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

    missing = [
        key
        for key, value in {
            "DB_USER": user,
            "DB_PASSWORD": password,
            "DB_HOST": host,
            "DB_PORT": port,
            "DB_NAME": name,
        }.items()
        if not value
    ]
    if missing:
        raise RuntimeError(f"Fehlende Umgebungsvariablen in der .env: {', '.join(missing)}")

    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{name}"


# 2. Synchronen Engine-Pool mit Verbindungs-Check aufbauen
ENGINE: Engine = create_engine(
    get_database_url(),
    pool_pre_ping=True,
    future=True,
)

app = FastAPI(title="ÖPNV-Analytics Karlsruhe API", version="1.0.0")

# 3. CORS-Schnittstelle für reibungslose Frontend-Schnittstellen öffnen
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Erlaubte Metriken für die Choroplethen-Karte (Schutz vor SQL-Injection)
ALLOWED_INDICATORS = {
    "oepnv_score",
    "einwohner",
    "takt_pendler_morgens",
    "takt_wochenende",
    "anzahl_haltestellen",
    "dist_hospital_km",
    "dist_townhall_km",
    "dist_bahnhof_km",
    "dist_cinema_km",
    "dist_theatre_km",
    "dist_zoo_km",
}

# Vollständiges Spaltenverzeichnis für das Klick-Dashboard in der Sidebar
DETAIL_COLUMNS = [
    "kachel_id",
    "x_min",
    "y_min",
    "einwohner",
    "bevoelkerungs_klasse",
    "dist_hospital_km",
    "nearest_hospital_name",
    "dist_townhall_km",
    "nearest_townhall_name",
    "dist_bahnhof_km",
    "nearest_bahnhof_name",
    "dist_cinema_km",
    "nearest_cinema_name",
    "dist_theatre_km",
    "nearest_theatre_name",
    "dist_zoo_km",
    "nearest_zoo_name",
    "anzahl_haltestellen",
    "linien_liste",
    "takt_pendler_morgens",
    "takt_wochenende",
    "takt_24h_array",
    "oepnv_score",
]


def _validate_indicator(indicator: str) -> str:
    # Erlaubte Mapping-Spaltennamen aus eurer Datenbank-Tabelle definieren
    allowed = {
        "einwohner": "einwohner",
        "anzahl_haltestellen": "anzahl_haltestellen"
    }
    if indicator not in allowed:
        raise HTTPException(status_code=400, detail="Ungültiger Indikator")
    return allowed[indicator]


def _rows_to_dicts(rows: list[Any]) -> list[dict[str, Any]]:
    return [dict(row._mapping) for row in rows]


# --- SYNCHRONE BACKGROUND-WORKER (Werden in Threads ausgelagert) ---

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
            {column} AS value
        FROM public.kachel_analytics
        ORDER BY kachel_id
        """
    )

    with ENGINE.connect() as connection:
        result = connection.execute(query)
        
        # _mapping sorgt dafür, dass die Spalten unbestechlich ausgelesen werden
        kacheln = [
            {
                "kachel_id": int(row._mapping["kachel_id"]),
                "p1_lat": float(row._mapping["p1_lat"]), "p1_lon": float(row._mapping["p1_lon"]),
                "p2_lat": float(row._mapping["p2_lat"]), "p2_lon": float(row._mapping["p2_lon"]),
                "p3_lat": float(row._mapping["p3_lat"]), "p3_lon": float(row._mapping["p3_lon"]),
                "p4_lat": float(row._mapping["p4_lat"]), "p4_lon": float(row._mapping["p4_lon"]),
                "value": float(row._mapping["value"]) if row._mapping["value"] is not None else 0.0
            }
            for row in result
        ]
        return kacheln


def _fetch_kachel_detail_sync(kachel_id: int) -> dict[str, Any] | None:
    query = text(
        f"""
        SELECT {", ".join(DETAIL_COLUMNS)}
        FROM public.kachel_analytics
        WHERE kachel_id = :kachel_id
        LIMIT 1
        """
    )

    with ENGINE.connect() as connection:
        row = connection.execute(query, {"kachel_id": kachel_id}).fetchone()

    if row is None:
        return None

    return dict(row._mapping)


# --- ASYNCHRONE API-ENDPUNKTE ---

@app.get("/api/kacheln")
async def get_kacheln(
    indicator: str = Query(default="oepnv_score", description="Ausgewählter KPI für die Karte"),
) -> list[dict[str, Any]]:
    """Gibt Geometrien und den gewählten Wert für alle Kacheln aus (Thread-safe optimiert)."""
    return await asyncio.to_thread(_fetch_kacheln_sync, indicator)


@app.get("/api/kachel/{kachel_id}")
async def get_kachel(kachel_id: int) -> dict[str, Any]:
    """Gibt das vollständige Indikatoren-Paket für die Sidebar-Details einer Kachel aus."""
    result = await asyncio.to_thread(_fetch_kachel_detail_sync, kachel_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Kachel nicht gefunden")
    return result


@app.get("/health")
async def healthcheck() -> dict[str, str]:
    """Prüfpunkt für den Server-Status."""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    # Nutzt den direkten Modulaufruf, um Startprobleme im venv zu vermeiden
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)