import os
import pandas as pd
import geopandas as gpd
from shapely.geometry import Polygon, Point, MultiPoint
from sqlalchemy import create_engine
from dotenv import load_dotenv

# .env Konfiguration laden
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(base_dir, '.env'))

def get_db_engine():
    db_url = f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
    return create_engine(db_url)

def time_to_minutes(t_str):
    """Konvertiert GTFS HH:MM:SS sicher in Minuten seit Mitternacht."""
    if pd.isna(t_str) or not t_str: 
        return None
    try:
        parts = str(t_str).strip().split(':')
        return int(parts[0]) * 60 + int(parts[1])
    except:
        return None

def run_etl_pipeline():
    engine = get_db_engine()
    print("🚀 Starte mathematisch exakte High-Performance ETL-Pipeline für Karlsruhe...")

    # --- SCHRITT A: CRS-DETEKTION FÜR LOKALE POIs ---
    df_pois_raw = pd.read_sql("SELECT \"X\" as x, \"Y\" as y FROM karlsruhe_pois_datensatz LIMIT 10", engine)
    sample_x = df_pois_raw['x'].iloc[0]
    if sample_x < 180: poi_src_crs = "EPSG:4326"
    elif 4000000 < sample_x < 5000000: poi_src_crs = "EPSG:3035"
    elif 3000000 < sample_x < 4000000: poi_src_crs = "EPSG:31467"
    else: poi_src_crs = "EPSG:25832"

    # --- SCHRITT B: GEOMETRISCHE HÜLLE AUS REALEN DATENPUNKTEN ---
    print("🎯 Berechne lückenlose Netzhülle aus Haltestellen und POIs...")
    
    # Haltestellen im Zielgebiet laden (Reale Punktgeometrien)
    df_stops_mask = pd.read_sql("""
        SELECT stop_lat, stop_lon FROM stops 
        WHERE stop_lat BETWEEN 48.70 AND 49.32
          AND stop_lon BETWEEN 8.15 AND 8.85
    """, engine)
    
    gdf_stops_mask = gpd.GeoDataFrame(
        df_stops_mask, 
        geometry=gpd.points_from_xy(df_stops_mask.stop_lon, df_stops_mask.stop_lat), 
        crs="EPSG:4326"
    ).to_crs("EPSG:3035")
    
    # Mathematisch exaktes Snapping für reale Punkte
    gdf_stops_mask['x_3k'] = (gdf_stops_mask.geometry.x // 3000) * 3000
    gdf_stops_mask['y_3k'] = (gdf_stops_mask.geometry.y // 3000) * 3000
    cells_stops = gdf_stops_mask[['x_3k', 'y_3k']].drop_duplicates()

    # POIs laden (Reale Punktgeometrien)
    df_pois_mask = pd.read_sql("SELECT \"X\" as x, \"Y\" as y FROM karlsruhe_pois_datensatz", engine)
    gdf_pois_mask = gpd.GeoDataFrame(
        df_pois_mask, 
        geometry=gpd.points_from_xy(df_pois_mask.x, df_pois_mask.y), 
        crs=poi_src_crs
    ).to_crs("EPSG:3035")
    
    gdf_pois_mask['x_3k'] = (gdf_pois_mask.geometry.x // 3000) * 3000
    gdf_pois_mask['y_3k'] = (gdf_pois_mask.geometry.y // 3000) * 3000
    cells_pois = gdf_pois_mask[['x_3k', 'y_3k']].drop_duplicates()

    df_valid_cells = pd.concat([cells_stops, cells_pois]).drop_duplicates().reset_index(drop=True)
    
    # Erzeuge eine solide, geschlossene Hülle (Convex Hull) um das reale Versorgungsgebiet
    valid_points = [Point(r['x_3k'] + 1500, r['y_3k'] + 1500) for _, r in df_valid_cells.iterrows()]
    region_mantel = MultiPoint(valid_points).convex_hull

    # Abfragefenster für die Datenbank ermitteln
    x_min_q, x_max_q = df_valid_cells['x_3k'].min() - 6000, df_valid_cells['x_3k'].max() + 6000
    y_min_q, y_max_q = df_valid_cells['y_3k'].min() - 6000, df_valid_cells['y_3k'].max() + 6000

    # --- SCHRITT C: ZENSUS-DATEN KORRIGIEREN & LADEN ---
    print("📦 Transformiere Zensus-Mittelpunkte auf Kachel-Unterkanten...")
    df_zensus = pd.read_sql(f"""
        SELECT x_mp_1km, y_mp_1km, "Einwohner" as einwohner 
        FROM zensus2022_bevoelkerungszahl
        WHERE x_mp_1km BETWEEN {x_min_q} AND {x_max_q}
          AND y_mp_1km BETWEEN {y_min_q} AND {y_max_q}
    """, engine)
    
    # DER MATHEMATISCHE FIX: 500m Subtraktion korrigiert den Mittelpunkt-Versatz exakt!
    df_zensus['x_left'] = df_zensus['x_mp_1km'] - 500
    df_zensus['y_bottom'] = df_zensus['y_mp_1km'] - 500
    
    df_zensus['x_3k'] = (df_zensus['x_left'] // 3000) * 3000
    df_zensus['y_3k'] = (df_zensus['y_bottom'] // 3000) * 3000
    df_grid_base = df_zensus.groupby(['x_3k', 'y_3k']).agg({'einwohner': 'sum'}).reset_index()

    # Erzeuge das geometrische Grid im EPSG:3035 System
    polygons = [Polygon([(r['x_3k'], r['y_3k']), (r['x_3k'] + 3000, r['y_3k']), (r['x_3k'] + 3000, r['y_3k'] + 3000), (r['x_3k'], r['y_3k'] + 3000)]) for _, r in df_grid_base.iterrows()]
    gdf_grid_all = gpd.GeoDataFrame(df_grid_base, geometry=polygons, crs="EPSG:3035")

    # Filterung über die solide Hülle -> Schließt alle inneren Löcher komplett!
    gdf_grid = gdf_grid_all[gdf_grid_all.geometry.intersects(region_mantel)].reset_index(drop=True)
    gdf_grid['kachel_id'] = gdf_grid.index + 1

    # --- SCHRITT D: GPS-TRANSFORMATION (PROJEKTIONSTREU) ---
    print("🌍 Projiziere Kachel-Ecken fehlerfrei nach WGS84 (Leaflet)...")
    p1 = gpd.GeoDataFrame(geometry=[Point(r['x_3k'], r['y_3k']) for _, r in gdf_grid.iterrows()], crs="EPSG:3035").to_crs("EPSG:4326")
    p2 = gpd.GeoDataFrame(geometry=[Point(r['x_3k'] + 3000, r['y_3k']) for _, r in gdf_grid.iterrows()], crs="EPSG:3035").to_crs("EPSG:4326")
    p3 = gpd.GeoDataFrame(geometry=[Point(r['x_3k'] + 3000, r['y_3k'] + 3000) for _, r in gdf_grid.iterrows()], crs="EPSG:3035").to_crs("EPSG:4326")
    p4 = gpd.GeoDataFrame(geometry=[Point(r['x_3k'], r['y_3k'] + 3000) for _, r in gdf_grid.iterrows()], crs="EPSG:3035").to_crs("EPSG:4326")
    
    gdf_grid['p1_lat'], gdf_grid['p1_lon'] = p1.geometry.y, p1.geometry.x
    gdf_grid['p2_lat'], gdf_grid['p2_lon'] = p2.geometry.y, p2.geometry.x
    gdf_grid['p3_lat'], gdf_grid['p3_lon'] = p3.geometry.y, p3.geometry.x
    gdf_grid['p4_lat'], gdf_grid['p4_lon'] = p4.geometry.y, p4.geometry.x

    def classify_zone(e):
        if e == 0: return "Unbesiedelte Zone"
        elif e <= 4500: return "Ländliche Zone"
        elif e <= 13500: return "Aussenstädtische Zone"
        elif e <= 36000: return "Urbane Kernzone"
        else: return "Metropolitane Kernzone"
    gdf_grid['bevoelkerungs_klasse'] = gdf_grid['einwohner'].apply(classify_zone)

    # --- SCHRITT E: POI-DISTANZEN ---
    print("🏥 Analysiere POI-Distanzen...")
    df_pois = pd.read_sql("SELECT name, poi_type, \"X\" as x, \"Y\" as y FROM karlsruhe_pois_datensatz", engine)
    gdf_pois = gpd.GeoDataFrame(df_pois, geometry=gpd.points_from_xy(df_pois.x, df_pois.y), crs=poi_src_crs).to_crs("EPSG:3035")

    gdf_centroids = gpd.GeoDataFrame(gdf_grid[['kachel_id']], geometry=gdf_grid.geometry.centroid, crs="EPSG:3035")
    poi_targets = [
        ('hospital', 'hospital'), ('townhall', 'townhall'), ('station', 'bahnhof'),
        ('cinema', 'cinema'), ('theatre', 'theatre'), ('zoo', 'zoo')
    ]
    
    for p_type, prefix in poi_targets:
        sub_pois = gdf_pois[gdf_pois['poi_type'] == p_type].copy()
        if not sub_pois.empty:
            joined = gpd.sjoin_nearest(gdf_centroids, sub_pois, how='left', distance_col='dist_m')
            joined = joined.drop_duplicates(subset=['kachel_id'], keep='first')
            joined[f'dist_{prefix}_km'] = round(joined['dist_m'] / 1000.0, 2)
            joined = joined.rename(columns={'name': f'nearest_{prefix}_name'})
            gdf_grid = gdf_grid.merge(joined[['kachel_id', f'dist_{prefix}_km', f'nearest_{prefix}_name']], on='kachel_id', how='left')
        else:
            gdf_grid[f'dist_{prefix}_km'] = None
            gdf_grid[f'nearest_{prefix}_name'] = "Kein Eintrag"

    # --- SCHRITT F: GTFS AGGREGATION ---
    print("🚌 Verarbeite GTFS-Komponenten...")
    df_stops = pd.read_sql("SELECT stop_id, stop_lat, stop_lon FROM stops", engine)
    gdf_stops = gpd.GeoDataFrame(df_stops, geometry=gpd.points_from_xy(df_stops.stop_lon, df_stops.stop_lat), crs="EPSG:4326").to_crs("EPSG:3035")
    
    # Identische metrische Zuordnung für die Haltestellen
    gdf_stops['x_3k'] = (gdf_stops.geometry.x // 3000) * 3000
    gdf_stops['y_3k'] = (gdf_stops.geometry.y // 3000) * 3000

    df_trips = pd.read_sql("SELECT trip_id, route_id, service_id FROM trips", engine)
    df_routes = pd.read_sql("SELECT route_id, route_short_name FROM routes", engine)
    df_st = pd.read_sql("SELECT trip_id, stop_id, arrival_time FROM stop_times", engine)
    df_cal = pd.read_sql("SELECT service_id, monday, tuesday, wednesday, thursday, friday, saturday, sunday FROM calendar", engine)

    for df in [df_st, gdf_stops]: df['stop_id'] = df['stop_id'].astype(str).str.strip()
    for df in [df_st, df_trips]: df['trip_id'] = df['trip_id'].astype(str).str.strip()
    for df in [df_trips, df_routes]: df['route_id'] = df['route_id'].astype(str).str.strip()
    for df in [df_trips, df_cal]: df['service_id'] = df['service_id'].astype(str).str.strip()

    df_fahrten = df_st.merge(gdf_stops[['stop_id', 'x_3k', 'y_3k']], on='stop_id')
    df_fahrten = df_fahrten.merge(df_trips, on='trip_id')
    df_fahrten = df_fahrten.merge(df_routes, on='route_id')
    df_fahrten = df_fahrten.merge(df_cal, on='service_id')

    df_stops_count = gdf_stops.groupby(['x_3k', 'y_3k']).size().reset_index(name='anzahl_haltestellen')

    if not df_fahrten.empty:
        df_fahrten['total_minutes'] = df_fahrten['arrival_time'].apply(time_to_minutes)
        df_fahrten['stunde'] = df_fahrten['total_minutes'].apply(lambda m: int((m // 60) % 24) if m is not None else 0)

        df_lines = df_fahrten.groupby(['x_3k', 'y_3k'])['route_short_name'].apply(
            lambda x: ", ".join(sorted(x.dropna().unique().astype(str)))
        ).reset_index(name='linien_liste')

        m_start, m_end = 6*60 + 30, 8*60 + 30
        a_start, a_end = 16*60, 18*60 + 30
        
        df_pendler = df_fahrten[
            ((df_fahrten['monday'] == 1) | (df_fahrten['tuesday'] == 1) | (df_fahrten['wednesday'] == 1) | (df_fahrten['thursday'] == 1) | (df_fahrten['friday'] == 1)) & 
            (((df_fahrten['total_minutes'] >= m_start) & (df_fahrten['total_minutes'] <= m_end)) |
             ((df_fahrten['total_minutes'] >= a_start) & (df_fahrten['total_minutes'] <= a_end)))
        ]
        df_pendler_takt = df_pendler.groupby(['x_3k', 'y_3k']).size().reset_index(name='p_count')
        df_pendler_takt['takt_pendler_morgens'] = round(df_pendler_takt['p_count'] / (5.0 * 4.5), 2)

        df_we = df_fahrten[(df_fahrten['saturday'] == 1) | (df_fahrten['sunday'] == 1)]
        df_we_takt = df_we.groupby(['x_3k', 'y_3k']).size().reset_index(name='we_count')
        df_we_takt['takt_wochenende'] = round(df_we_takt['we_count'] / 48.0, 2)

        df_wt_profile = df_fahrten[(df_fahrten['monday'] == 1) | (df_fahrten['tuesday'] == 1) | (df_fahrten['wednesday'] == 1) | (df_fahrten['thursday'] == 1) | (df_fahrten['friday'] == 1)]
        df_hourly = df_wt_profile.groupby(['x_3k', 'y_3k', 'stunde']).size().unstack(fill_value=0)
        df_hourly = df_hourly.reindex(columns=range(24), fill_value=0)
        df_hourly_avg = (df_hourly / 5.0).round(1)
        df_hourly_str = df_hourly_avg.apply(lambda row: ",".join(row.astype(str)), axis=1).reset_index(name='takt_24h_array')

        gdf_grid = gdf_grid.merge(df_stops_count, on=['x_3k', 'y_3k'], how='left')
        gdf_grid = gdf_grid.merge(df_lines, on=['x_3k', 'y_3k'], how='left')
        gdf_grid = gdf_grid.merge(df_pendler_takt[['x_3k', 'y_3k', 'takt_pendler_morgens']], on=['x_3k', 'y_3k'], how='left')
        gdf_grid = gdf_grid.merge(df_we_takt[['x_3k', 'y_3k', 'takt_wochenende']], on=['x_3k', 'y_3k'], how='left')
        gdf_grid = gdf_grid.merge(df_hourly_str, on=['x_3k', 'y_3k'], how='left')

    gdf_grid['anzahl_haltestellen'] = gdf_grid['anzahl_haltestellen'].fillna(0).astype(int)
    gdf_grid['linien_liste'] = gdf_grid['linien_liste'].fillna("Keine Linien")
    gdf_grid['takt_pendler_morgens'] = gdf_grid['takt_pendler_morgens'].fillna(0.0)
    gdf_grid['takt_wochenende'] = gdf_grid['takt_wochenende'].fillna(0.0)
    gdf_grid['takt_24h_array'] = gdf_grid['takt_24h_array'].fillna(",".join(["0.0"]*24))

    max_einwohner = gdf_grid['einwohner'].max() if gdf_grid['einwohner'].max() > 0 else 1
    max_takt = gdf_grid['takt_pendler_morgens'].max() if gdf_grid['takt_pendler_morgens'].max() > 0 else 1
    gdf_grid['oepnv_score'] = gdf_grid.apply(lambda r: round(((r['einwohner'] / max_einwohner) * 40) + ((r['takt_pendler_morgens'] / max_takt) * 60), 1), axis=1)

    print(f"📉 Finale Kachelanzahl (Solides, lückenloses Verbundnetz): {len(gdf_grid)}")

    # --- SCHRITT G: SPEICHERN ---
    print("💾 Befülle Tabelle 'kachel_analytics'...")
    df_final = pd.DataFrame(gdf_grid.drop(columns='geometry')).rename(columns={'x_3k': 'x_min', 'y_3k': 'y_min'})
    
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS kachel_analytics;")
        
    df_final.to_sql("kachel_analytics", engine, if_exists="replace", index=False)
    print("🎉 ETL-Pipeline erfolgreich beendet!")

if __name__ == "__main__":
    run_etl_pipeline()