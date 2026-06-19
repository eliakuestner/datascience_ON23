import os
from pathlib import Path
import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# .env Konfiguration laden
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

def get_db_engine():
    user = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD")
    host = os.getenv("DB_HOST")
    port = os.getenv("DB_PORT")
    name = os.getenv("DB_NAME")
    db_url = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{name}"
    return create_engine(db_url)

def generate_fahrzeiten_matrizen():
    engine = get_db_engine()
    print("⏳ Lade Basisdaten aus public.kachel_analytics...")
    
    query = """
        SELECT 
            kachel_id, adresse, bevoelkerungs_klasse,
            nearest_hospital_name, dist_hospital_km,
            nearest_townhall_name, dist_townhall_km,
            nearest_bahnhof_name, dist_bahnhof_km,
            nearest_cinema_name, dist_cinema_km,
            nearest_theatre_name, dist_theatre_km,
            nearest_zoo_name, dist_zoo_km
        FROM public.kachel_analytics
        ORDER BY kachel_id;
    """
    df_analytics = pd.read_sql(query, engine)
    
    rows_daseinsvorsorge = []
    rows_freizeit = []
    
    print("🔄 Transformiere Daten in getrennte Matrizen (saubere POI-Trennung)...")
    for _, row in df_analytics.iterrows():
        k_id = int(row["kachel_id"])
        adr = row["adresse"]
        b_klasse = row["bevoelkerungs_klasse"]
        
        # 1. BEREICH: DASEINSVORSORGE (Nur Hospital, Townhall, Station)
        pois_dasein = [
            {"typ": "hospital", "name": row["nearest_hospital_name"], "dist": row["dist_hospital_km"]},
            {"typ": "townhall", "name": row["nearest_townhall_name"], "dist": row["dist_townhall_km"]},
            {"typ": "station", "name": row["nearest_bahnhof_name"], "dist": row["dist_bahnhof_km"]}
        ]
        for poi in pois_dasein:
            p_name = poi["name"] if poi["name"] and poi["name"] != "-" else "Kein Eintrag"
            distanz = poi["dist"] if pd.notna(poi["dist"]) else 0.0
            
            rows_daseinsvorsorge.append({
                "kachel_id": k_id,
                "adresse": adr,
                "bevoelkerungs_klasse": b_klasse,
                "poi_typ": poi["typ"],
                "poi_name": p_name,
                "distanz_luftlinie_km": distanz,
                "zeit_morgens_min": None,
                "zeit_mittags_min": None,
                "zeit_abends_min": None,
                "avg_zeit_pro_luftlinie_km": None
            })
            
        # 2. BEREICH: FREIZEIT & KULTUR (Nur Cinema, Theatre, Zoo)
        pois_freizeit = [
            {"typ": "cinema", "name": row["nearest_cinema_name"], "dist": row["dist_cinema_km"]},
            {"typ": "theatre", "name": row["nearest_theatre_name"], "dist": row["dist_theatre_km"]},
            {"typ": "zoo", "name": row["nearest_zoo_name"], "dist": row["dist_zoo_km"]}
        ]
        for poi in pois_freizeit:
            p_name = poi["name"] if poi["name"] and poi["name"] != "-" else "Kein Eintrag"
            distanz = poi["dist"] if pd.notna(poi["dist"]) else 0.0
            
            rows_freizeit.append({
                "kachel_id": k_id,
                "adresse": adr,
                "bevoelkerungs_klasse": b_klasse,
                "poi_typ": poi["typ"],
                "poi_name": p_name,
                "distanz_luftlinie_km": distanz,
                # Freitag
                "zeit_fr_abends_min": None,
                "heimfahrt_fr_spateste": None,
                # Samstag
                "zeit_sa_mittags_min": None,
                "zeit_sa_abends_min": None,
                "heimfahrt_sa_spateste": None,
                # Sonntag
                "zeit_so_mittags_min": None,
                "zeit_so_abends_min": None,
                "heimfahrt_so_spateste": None,
                # Auswertungen
                "avg_zeit_fr_pro_luftlinie_km": None,
                "avg_zeit_sa_pro_luftlinie_km": None,
                "avg_zeit_so_pro_luftlinie_km": None
            })

    # DataFrames erstellen und sortieren
    df_dasein = pd.DataFrame(rows_daseinsvorsorge).sort_values(by=["kachel_id", "poi_typ"]).reset_index(drop=True)
    df_freizeit = pd.DataFrame(rows_freizeit).sort_values(by=["kachel_id", "poi_typ"]).reset_index(drop=True)
    
    print("💾 Überschreibe Tabellen in der Datenbank...")
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS public.kachel_fahrzeiten_daseinsvorsorge;")
        conn.exec_driver_sql("DROP TABLE IF EXISTS public.kachel_fahrzeiten_freizeit;")
        
    df_dasein.to_sql("kachel_fahrzeiten_daseinsvorsorge", engine, if_exists="replace", index=False)
    df_freizeit.to_sql("kachel_fahrzeiten_freizeit", engine, if_exists="replace", index=False)
    
    print(f"🎉 Fertig! Daseinsvorsorge: {len(df_dasein)} Zeilen | Freizeit: {len(df_freizeit)} Zeilen.")

if __name__ == "__main__":
    generate_fahrzeiten_matrizen()