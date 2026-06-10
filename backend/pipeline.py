import os
import sys
import time
import pandas as pd
import geopandas as gpd
from shapely.geometry import Polygon
from sqlalchemy import create_engine
from dotenv import load_dotenv

# .env laden - Absolut und unfehlbar basierend auf dem Projekt-Hauptverzeichnis
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))

def get_db_engine():
    db_user = os.getenv("DB_USER")
    db_pass = os.getenv("DB_PASSWORD")
    db_host = os.getenv("DB_HOST")
    db_port = os.getenv("DB_PORT")
    db_name = os.getenv("DB_NAME")
    db_url = f"postgresql+psycopg2://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"
    return create_engine(db_url)

def classify_zone(einwohner):
    if einwohner == 0: return "Unbesiedelte Zone"
    if einwohner <= 4500: return "Ländliche Zone"
    if einwohner <= 13500: return "Aussenstädtische Zone"
    if einwohner <= 36000: return "Urbane Kernzone"
    return "Metropolitane Kernzone"

def run_etl_pipeline():
    engine = get_db_engine()
    print("🚀 Starte empirische Wochentags-Pipeline (Unique Trips & POI-Fix)...")

    # --- SCHRITT A & B: GRID GENERIERUNG ---
    df_stops_raw = pd.read_sql("SELECT stop_id, stop_lat, stop_lon FROM public.stops", engine)
    gdf_stops_raw = gpd.GeoDataFrame(df_stops_raw, geometry=gpd.points_from_xy(df_stops_raw.stop_lon, df_stops_raw.stop_lat), crs="EPSG:4326").to_crs("EPSG:3035")
    gdf_stops_raw['x_3k'] = (gdf_stops_raw.geometry.x // 3000) * 3000
    gdf_stops_raw['y_3k'] = (gdf_stops_raw.geometry.y // 3000) * 3000
    df_master_grid = gdf_stops_raw.groupby(['x_3k', 'y_3k']).size().reset_index(name='anzahl_haltestellen')

    polygons = [Polygon([(r['x_3k'], r['y_3k']), (r['x_3k']+3000, r['y_3k']), (r['x_3k']+3000, r['y_3k']+3000), (r['x_3k'], r['y_3k']+3000)]) for _, r in df_master_grid.iterrows()]
    gdf_grid = gpd.GeoDataFrame(df_master_grid, geometry=polygons, crs="EPSG:3035")
    gdf_grid['kachel_id'] = gdf_grid.index + 1

    # --- SCHRITT C: BEVÖLKERUNGSDATEN ---
    df_zensus_base = pd.read_sql("SELECT x_mp_1km, y_mp_1km, \"Einwohner\" as einwohner FROM public.zensus2022_bevoelkerungszahl", engine)
    df_zensus_base['x_3k'] = ((df_zensus_base['x_mp_1km'] - 500) // 3000) * 3000
    df_zensus_base['y_3k'] = ((df_zensus_base['y_mp_1km'] - 500) // 3000) * 3000
    df_zensus_agg = df_zensus_base.groupby(['x_3k', 'y_3k']).agg({'einwohner': 'sum'}).reset_index()
    gdf_grid = gdf_grid.merge(df_zensus_agg, on=['x_3k', 'y_3k'], how='left')
    gdf_grid['einwohner'] = gdf_grid['einwohner'].fillna(0).astype(int)

    # --- SCHRITT D: GEOMETRIE-ECKPKUNTE BERECHNEN ---
    gdf_grid_wgs84 = gdf_grid.to_crs("EPSG:4326")
    p1_lats, p1_lons, p2_lats, p2_lons, p3_lats, p3_lons, p4_lats, p4_lons = [], [], [], [], [], [], [], []
    for geom in gdf_grid_wgs84['geometry']:
        coords = list(geom.exterior.coords)
        p1_lats.append(coords[0][1]); p1_lons.append(coords[0][0])
        p2_lats.append(coords[1][1]); p2_lons.append(coords[1][0])
        p3_lats.append(coords[2][1]); p3_lons.append(coords[2][0])
        p4_lats.append(coords[3][1]); p4_lons.append(coords[3][0])
    gdf_grid['p1_lat'] = p1_lats; gdf_grid['p1_lon'] = p1_lons
    gdf_grid['p2_lat'] = p2_lats; gdf_grid['p2_lon'] = p2_lons
    gdf_grid['p3_lat'] = p3_lats; gdf_grid['p3_lon'] = p3_lons
    gdf_grid['p4_lat'] = p4_lats; gdf_grid['p4_lon'] = p4_lons

    gdf_grid['bevoelkerungs_klasse'] = gdf_grid['einwohner'].apply(classify_zone)

    # --- SCHRITT E: POI-INTEGRATION (FIXED KOORDINATEN) ---
    print("📍 Integriere POIs mit ECHTEN Geokoordinaten...")
    df_pois = pd.read_sql("SELECT name, poi_type, \"X\" as x_lon, \"Y\" as y_lat FROM public.karlsruhe_pois_datensatz", engine)
    gdf_pois_metric = gpd.GeoDataFrame(df_pois, geometry=gpd.points_from_xy(df_pois.x_lon, df_pois.y_lat), crs="EPSG:4326").to_crs("EPSG:3035")
    gdf_centroids = gpd.GeoDataFrame(gdf_grid[['kachel_id']], geometry=gdf_grid.geometry.centroid, crs="EPSG:3035")
    
    for p_type, prefix in [('hospital', 'hospital'), ('townhall', 'townhall'), ('station', 'bahnhof'), ('cinema', 'cinema'), ('theatre', 'theatre'), ('zoo', 'zoo')]:
        sub_pois = gdf_pois_metric[gdf_pois_metric['poi_type'] == p_type].copy()
        if not sub_pois.empty:
            joined = gpd.sjoin_nearest(gdf_centroids, sub_pois, how='left', distance_col='dist_m').drop_duplicates(subset=['kachel_id'], keep='first')
            joined[f'dist_{prefix}_km'] = round(joined['dist_m'] / 1000.0, 2)
            joined = joined.rename(columns={'name': f'nearest_{prefix}_name', 'x_lon': f'{prefix}_lon', 'y_lat': f'{prefix}_lat'})
            
            gdf_grid = gdf_grid.merge(joined[['kachel_id', f'dist_{prefix}_km', f'nearest_{prefix}_name', f'{prefix}_lon', f'{prefix}_lat']], on='kachel_id', how='left')
        else:
            gdf_grid[f'dist_{prefix}_km'] = 0.0
            gdf_grid[f'nearest_{prefix}_name'] = "Kein Eintrag"
            gdf_grid[f'{prefix}_lon'] = 0.0
            gdf_grid[f'{prefix}_lat'] = 0.0

    # --- SCHRITT F: LINIEN-AGGREGATION ---
    df_fahrten = pd.read_sql("SELECT DISTINCT st.stop_id, r.route_short_name FROM public.stop_times st INNER JOIN public.trips t ON st.trip_id = t.trip_id INNER JOIN public.routes r ON t.route_id = r.route_id", engine)
    df_fahrten = df_fahrten.merge(gdf_stops_raw[['stop_id', 'x_3k', 'y_3k']], on='stop_id', how='inner')
    df_lines = df_fahrten.groupby(['x_3k', 'y_3k'])['route_short_name'].apply(lambda x: ", ".join(sorted(x.dropna().unique()))).reset_index(name='linien_liste')
    gdf_grid = gdf_grid.merge(df_lines, on=['x_3k', 'y_3k'], how='left')
    gdf_grid['linien_liste'] = gdf_grid['linien_liste'].fillna("Keine Linien")

    # --- SCHRITT G: EMPIRISCHE 24H-FAHRPLANDATEN BERECHNEN ---
    print("📊 Berechne physische Fahrzeug-Frequenzen via Unique-Trip-ID...")
    query_takt = """
        SELECT st.stop_id, 
               t.trip_id,
               EXTRACT(HOUR FROM st.departure_time::interval) as abfahrts_stunde,
               c.monday, c.tuesday, c.wednesday, c.thursday, c.friday, c.saturday, c.sunday
        FROM public.stop_times st
        INNER JOIN public.trips t ON st.trip_id = t.trip_id
        INNER JOIN public.calendar c ON t.service_id = c.service_id
    """
    try:
        df_real_takt = pd.read_sql(query_takt, engine)
        df_real_takt = df_real_takt.merge(gdf_stops_raw[['stop_id', 'x_3k', 'y_3k']], on='stop_id', how='inner')
        
        days_mapping = {
            'mo': 'monday', 'di': 'tuesday', 'mi': 'wednesday', 
            'do': 'thursday', 'fr': 'friday', 'sa': 'saturday', 'so': 'sunday'
        }
        wochen_arrays = {tag: [] for tag in days_mapping.keys()}
        
        for _, row in gdf_grid.iterrows():
            x, y = row['x_3k'], row['y_3k']
            kachel_data = df_real_takt[(df_real_takt['x_3k'] == x) & (df_real_takt['y_3k'] == y)]
            
            for tag, db_spalte in days_mapping.items():
                active_trips = kachel_data[kachel_data[db_spalte] == 1]
                active_unique_vehicles = active_trips.drop_duplicates(subset=['abfahrts_stunde', 'trip_id'])
                counts = active_unique_vehicles.groupby('abfahrts_stunde').size().to_dict()
                
                hours_profile = [0] * 24
                for raw_h, count in counts.items():
                    real_h = int(raw_h) % 24
                    hours_profile[real_h] += int(count)
                    
                hours_profile_strs = [str(x) for x in hours_profile]
                wochen_arrays[tag].append(",".join(hours_profile_strs))
                
        for tag in days_mapping.keys():
            gdf_grid[f'takt_24h_{tag}'] = wochen_arrays[tag]
            
        print("   -> Methodisch bereinigte Fahrzeugfrequenzen erfolgreich ermittelt.")
    except Exception as e:
        print(f"❌ Kritischer Fehler in Schritt G: {e}")
        for tag in ['mo', 'di', 'mi', 'do', 'fr', 'sa', 'so']:
            gdf_grid[f'takt_24h_{tag}'] = ",".join(["0"] * 24)

    gdf_grid['takt_pendler_morgens'] = gdf_grid['anzahl_haltestellen'] * 2.5 
    gdf_grid['takt_wochenende'] = gdf_grid['anzahl_haltestellen'] * 1.2

    # --- SCHRITT H: ADRESSEN AUS KACHEL_ADRESSEN JOINEN ---
    print("🔄 Verknüpfe Adressen aus public.kachel_adressen...")
    df_source_addresses = pd.read_sql("SELECT kachel_id, adresse FROM public.kachel_adressen", engine)
    gdf_grid = gdf_grid.merge(df_source_addresses, on='kachel_id', how='left')
    gdf_grid['adresse'] = gdf_grid['adresse'].fillna("Bereich Karlsruhe")

    # --- SCHRITT I: SPEICHERN ---
    print("💾 Überschreibe public.kachel_analytics...")
    
    export_columns = [
        'kachel_id', 'x_min', 'y_min', 'anzahl_haltestellen', 'einwohner', 'bevoelkerungs_klasse', 'adresse', 'linien_liste',
        'p1_lat', 'p1_lon', 'p2_lat', 'p2_lon', 'p3_lat', 'p3_lon', 'p4_lat', 'p4_lon',
        'takt_24h_mo', 'takt_24h_di', 'takt_24h_mi', 'takt_24h_do', 'takt_24h_fr', 'takt_24h_sa', 'takt_24h_so',
        'takt_pendler_morgens', 'takt_wochenende',
        'dist_hospital_km', 'nearest_hospital_name', 'hospital_lon', 'hospital_lat',
        'dist_townhall_km', 'nearest_townhall_name', 'townhall_lon', 'townhall_lat',
        'dist_bahnhof_km', 'nearest_bahnhof_name', 'bahnhof_lon', 'bahnhof_lat',
        'dist_cinema_km', 'nearest_cinema_name', 'cinema_lon', 'cinema_lat',
        'dist_theatre_km', 'nearest_theatre_name', 'theatre_lon', 'theatre_lat',
        'dist_zoo_km', 'nearest_zoo_name', 'zoo_lon', 'zoo_lat'
    ]
    
    df_final = pd.DataFrame(gdf_grid).rename(columns={'x_3k': 'x_min', 'y_3k': 'y_min'})
    
    # =======================================================
    # CRITICAL FIX: Säubert kachel_id Duplikate vor dem Export!
    # =======================================================
    df_final = df_final.drop_duplicates(subset=['kachel_id'], keep='first')
    
    # Berechne den Score
    max_einwohner = df_final['einwohner'].max() if df_final['einwohner'].max() > 0 else 1
    max_takt = df_final['takt_pendler_morgens'].max() if df_final['takt_pendler_morgens'].max() > 0 else 1
    df_final['oepnv_score'] = df_final.apply(lambda r: round(((r['einwohner'] / max_einwohner) * 40) + ((r['takt_pendler_morgens'] / max_takt) * 60), 1), axis=1)
    
    export_columns.append('oepnv_score')
    df_final = df_final[[col for col in export_columns if col in df_final.columns]]

    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS public.kachel_analytics;")
    df_final.to_sql("kachel_analytics", engine, if_exists="replace", index=False)
    print("🎉 ETL-Pipeline erfolgreich beendet! Alle Datensätze sind bereinigt und eindeutig.")

if __name__ == "__main__":
    run_etl_pipeline()