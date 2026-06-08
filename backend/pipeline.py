import os
import pandas as pd
import geopandas as gpd
from shapely.geometry import Polygon, Point
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
    print("🚀 Starte finale raum-begrenzte High-Performance ETL-Pipeline...")

    # --- SCHRITT A: ERMITTLUNG DER KARLSRUHE BOUNDING BOX AUS POIS ---
    print("📍 Analysiere geografische Ausdehnung der Region Karlsruhe...")
    df_pois_raw = pd.read_sql("SELECT \"X\" as x, \"Y\" as y FROM karlsruhe_pois_datensatz LIMIT 10", engine)
    sample_x = df_pois_raw['x'].iloc[0]
    
    if sample_x < 180:
        poi_src_crs = "EPSG:4326"
    elif 4000000 < sample_x < 5000000:
        poi_src_crs = "EPSG:3035"
    elif 3000000 < sample_x < 4000000:
        poi_src_crs = "EPSG:31467"
    else:
        poi_src_crs = "EPSG:25832"

    df_pois_bounds = pd.read_sql("SELECT MIN(\"X\") as min_x, MAX(\"X\") as max_x, MIN(\"Y\") as min_y, MAX(\"Y\") as max_y FROM karlsruhe_pois_datensatz", engine)
    
    # In das metrische Zensus-System (EPSG:3035) transformieren um Grenzen festzulegen
    bounds_gdf = gpd.GeoDataFrame(
        geometry=[
            Point(df_pois_bounds['min_x'].iloc[0], df_pois_bounds['min_y'].iloc[0]),
            Point(df_pois_bounds['max_x'].iloc[0], df_pois_bounds['max_y'].iloc[0])
        ], 
        crs=poi_src_crs
    ).to_crs("EPSG:3035")
    
    # Bounding Box mit 20km Puffer erweitern, um das Karlsruher Umland komplett abzufangen
    x_min_bounds = bounds_gdf.geometry.iloc[0].x - 20000
    y_min_bounds = bounds_gdf.geometry.iloc[0].y - 20000
    x_max_bounds = bounds_gdf.geometry.iloc[1].x + 20000
    y_max_bounds = bounds_gdf.geometry.iloc[1].y + 20000

    # --- SCHRITT B: FILTERUNG DER ZENSUS-DATEN DIREKT IN DER DB ---
    print("📦 Lade Zensus-Daten (Exklusiv gefiltert auf Region Karlsruhe)...")
    df_zensus = pd.read_sql(f"""
        SELECT x_mp_1km, y_mp_1km, "Einwohner" as einwohner 
        FROM zensus2022_bevoelkerungszahl
        WHERE x_mp_1km BETWEEN {x_min_bounds} AND {x_max_bounds}
          AND y_mp_1km BETWEEN {y_min_bounds} AND {y_max_bounds}
    """, engine)
    
    # Grid-Berechnung (Abrundung auf 3000 Meter Kantenlänge)
    df_zensus['x_3k'] = (df_zensus['x_mp_1km'] // 3000) * 3000
    df_zensus['y_3k'] = (df_zensus['y_mp_1km'] // 3000) * 3000
    df_grid_base = df_zensus.groupby(['x_3k', 'y_3k']).agg({'einwohner': 'sum'}).reset_index()
    df_grid_base['kachel_id'] = df_grid_base.index + 1
    print(f"📊 Kacheln im erweiterten Raum Karlsruhe: {len(df_grid_base)}")

    # --- SCHRITT C: GEOMETRIEN & GPS BOUNDS FÜR LEAFLET ---
    print("🌍 Berechne räumliche Kacheln und GPS-Ecken...")
    points_min = [Point(r['x_3k'], r['y_3k']) for _, r in df_grid_base.iterrows()]
    points_max = [Point(r['x_3k'] + 3000, r['y_3k'] + 3000) for _, r in df_grid_base.iterrows()]
    
    gdf_min = gpd.GeoDataFrame(geometry=points_min, crs="EPSG:3035").to_crs("EPSG:4326")
    gdf_max = gpd.GeoDataFrame(geometry=points_max, crs="EPSG:3035").to_crs("EPSG:4326")
    
    df_grid_base['lon_min'] = gdf_min.geometry.x
    df_grid_base['lat_min'] = gdf_min.geometry.y
    df_grid_base['lon_max'] = gdf_max.geometry.x
    df_grid_base['lat_max'] = gdf_max.geometry.y
    
    polygons = [Polygon([(r['x_3k'], r['y_3k']), (r['x_3k'] + 3000, r['y_3k']), (r['x_3k'] + 3000, r['y_3k'] + 3000), (r['x_3k'], r['y_3k'] + 3000)]) for _, r in df_grid_base.iterrows()]
    gdf_grid = gpd.GeoDataFrame(df_grid_base, geometry=polygons, crs="EPSG:3035")

    # Eure exakte Definition der Einwohnerdichte-Klassen pro 9km² Kachel
    def classify_zone(e):
        if e == 0: return "Unbesiedelte Zone"
        elif e <= 4500: return "Ländliche Zone"
        elif e <= 13500: return "Aussenstädtische Zone"
        elif e <= 36000: return "Urbane Kernzone"
        else: return "Metropolitane Kernzone"
    gdf_grid['bevoelkerungs_klasse'] = gdf_grid['einwohner'].apply(classify_zone)

    # --- SCHRITT D: POI-DISTANZEN (KINO, THEATER, ZOO) ---
    print("🏥 Analysiere POI-Distanzen (Infrastruktur & Kultur)...")
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

    # --- SCHRITT E: GTFS-AGREGGATION MIT STRING-CAST-SCHUTZ ---
    print("🚌 Verarbeite GTFS-Komponenten aus der Datenbank...")
    df_stops = pd.read_sql("SELECT stop_id, stop_lat, stop_lon FROM stops", engine)
    gdf_stops = gpd.GeoDataFrame(df_stops, geometry=gpd.points_from_xy(df_stops.stop_lon, df_stops.stop_lat), crs="EPSG:4326").to_crs("EPSG:3035")
    gdf_stops['x_3k'] = (gdf_stops.geometry.x // 3000) * 3000
    gdf_stops['y_3k'] = (gdf_stops.geometry.y // 3000) * 3000

    df_trips = pd.read_sql("SELECT trip_id, route_id, service_id FROM trips", engine)
    df_routes = pd.read_sql("SELECT route_id, route_short_name FROM routes", engine)
    df_st = pd.read_sql("SELECT trip_id, stop_id, arrival_time FROM stop_times", engine)
    df_cal = pd.read_sql("SELECT service_id, monday, tuesday, wednesday, thursday, friday, saturday, sunday FROM calendar", engine)

    # Typbereinigung für fehlerfreie Verknüpfungen
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

        # Taktungen berechnen (Pendlerzeitfenster: Mo-Fr, 6:30-8:30 & 16:00-18:30 = 4.5h)
        m_start, m_end = 6*60 + 30, 8*60 + 30
        a_start, a_end = 16*60, 18*60 + 30
        
        df_pendler = df_fahrten[
            ((df_fahrten['monday'] == 1) | (df_fahrten['tuesday'] == 1) | (df_fahrten['wednesday'] == 1) | (df_fahrten['thursday'] == 1) | (df_fahrten['friday'] == 1)) & 
            (((df_fahrten['total_minutes'] >= m_start) & (df_fahrten['total_minutes'] <= m_end)) |
             ((df_fahrten['total_minutes'] >= a_start) & (df_fahrten['total_minutes'] <= a_end)))
        ]
        df_pendler_takt = df_pendler.groupby(['x_3k', 'y_3k']).size().reset_index(name='p_count')
        df_pendler_takt['takt_pendler_morgens'] = round(df_pendler_takt['p_count'] / (5.0 * 4.5), 2)

        df_we = fahrten = df_fahrten[(df_fahrten['saturday'] == 1) | (df_fahrten['sunday'] == 1)]
        df_we_takt = df_we.groupby(['x_3k', 'y_3k']).size().reset_index(name='we_count')
        df_we_takt['takt_wochenende'] = round(df_we_takt['we_count'] / 48.0, 2)

        df_wt_profile = df_fahrten[(df_fahrten['monday'] == 1) | (df_fahrten['tuesday'] == 1) | (df_fahrten['wednesday'] == 1) | (df_fahrten['thursday'] == 1) | (df_fahrten['friday'] == 1)]
        df_hourly = df_wt_profile.groupby(['x_3k', 'y_3k', 'stunde']).size().unstack(fill_value=0)
        df_hourly = df_hourly.reindex(columns=range(24), fill_value=0)
        df_hourly_avg = (df_hourly / 5.0).round(1)
        df_hourly_str = df_hourly_avg.apply(lambda row: ",".join(row.astype(str)), axis=1).reset_index(name='takt_24h_array')

        # Mergen an das räumlich begrenzte Hauptgrid
        gdf_grid = gdf_grid.merge(df_stops_count, on=['x_3k', 'y_3k'], how='left')
        gdf_grid = gdf_grid.merge(df_lines, on=['x_3k', 'y_3k'], how='left')
        gdf_grid = gdf_grid.merge(df_pendler_takt[['x_3k', 'y_3k', 'takt_pendler_morgens']], on=['x_3k', 'y_3k'], how='left')
        gdf_grid = gdf_grid.merge(df_we_takt[['x_3k', 'y_3k', 'takt_wochenende']], on=['x_3k', 'y_3k'], how='left')
        gdf_grid = gdf_grid.merge(df_hourly_str, on=['x_3k', 'y_3k'], how='left')

    # Spalten absichern
    gdf_grid['anzahl_haltestellen'] = gdf_grid['anzahl_haltestellen'].fillna(0).astype(int)
    gdf_grid['linien_liste'] = gdf_grid['linien_liste'].fillna("Keine Linien")
    gdf_grid['takt_pendler_morgens'] = gdf_grid['takt_pendler_morgens'].fillna(0.0)
    gdf_grid['takt_wochenende'] = gdf_grid['takt_wochenende'].fillna(0.0)
    gdf_grid['takt_24h_array'] = gdf_grid['takt_24h_array'].fillna(",".join(["0.0"]*24))

    max_einwohner = gdf_grid['einwohner'].max() if gdf_grid['einwohner'].max() > 0 else 1
    max_takt = gdf_grid['takt_pendler_morgens'].max() if gdf_grid['takt_pendler_morgens'].max() > 0 else 1
    gdf_grid['oepnv_score'] = gdf_grid.apply(lambda r: round(((r['einwohner'] / max_einwohner) * 40) + ((r['takt_pendler_morgens'] / max_takt) * 60), 1), axis=1)

    # Relevanzfilter für das Frontend
    gdf_grid = gdf_grid[(gdf_grid['einwohner'] > 0) | (gdf_grid['anzahl_haltestellen'] > 0)].reset_index(drop=True)
    print(f"📉 Finale Kachelanzahl exklusiv für Karlsruhe: {len(gdf_grid)}")

    # --- SCHRITT F: IN DIE DATENBANK SCHREIBEN ---
    print("💾 Befülle Tabelle 'kachel_analytics'...")
    df_final = pd.DataFrame(gdf_grid.drop(columns='geometry')).rename(columns={'x_3k': 'x_min', 'y_3k': 'y_min'})
    
    with engine.begin() as conn:
        conn.exec_driver_sql("TRUNCATE TABLE kachel_analytics;")
        
    df_final.to_sql("kachel_analytics", engine, if_exists="append", index=False)
    print("🎉 ETL-Pipeline erfolgreich beendet! Das Karlsruher Datenpaket steht perfekt.")

if __name__ == "__main__":
    run_etl_pipeline()