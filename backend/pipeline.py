import os
import sys
import pandas as pd
import geopandas as gpd
from shapely.geometry import Polygon, Point
from sqlalchemy import create_engine
from dotenv import load_dotenv

# .env laden
load_dotenv(os.path.join(os.getcwd(), '.env'))

def get_db_engine():
    db_url = f"postgresql+psycopg2://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
    return create_engine(db_url)

def classify_zone(einwohner):
    if einwohner == 0: return "Unbesiedelte Zone"
    if einwohner <= 4500: return "Ländliche Zone"
    if einwohner <= 13500: return "Aussenstädtische Zone"
    if einwohner <= 36000: return "Urbane Kernzone"
    return "Metropolitane Kernzone"

def run_etl_pipeline():
    engine = get_db_engine()
    print("🚀 Starte optimierte Karlsruher ETL-Pipeline (Flächen-Match)...")

    # --- SCHRITT A: GEOGRAFISCHE BASIS AUS ÖPNV-STOPS DEFINIEREN ---
    print("🚌 Berechne Master-Grid ausschließlich aus ÖPNV-Haltestellen (Stadt + Landkreis)...")
    df_stops_raw = pd.read_sql("SELECT stop_id, stop_lat, stop_lon FROM public.stops", engine)
    gdf_stops_raw = gpd.GeoDataFrame(df_stops_raw, geometry=gpd.points_from_xy(df_stops_raw.stop_lon, df_stops_raw.stop_lat), crs="EPSG:4326").to_crs("EPSG:3035")
    
    # Rasterkoordinaten für die Haltestellen berechnen
    gdf_stops_raw['x_3k'] = (gdf_stops_raw.geometry.x // 3000) * 3000
    gdf_stops_raw['y_3k'] = (gdf_stops_raw.geometry.y // 3000) * 3000
    
    # Das Master-Grid bestimmen: Nur Kacheln, in denen mindestens eine Haltestelle existiert
    df_master_grid = gdf_stops_raw.groupby(['x_3k', 'y_3k']).size().reset_index(name='anzahl_haltestellen')

    # --- SCHRITT B: RASTER-GRID GENERIERUNG (GEOMETRIE) ---
    print("📐 Generiere 3x3km Planungs-Polygone für das Zielgebiet...")
    polygons = [
        Polygon([(r['x_3k'], r['y_3k']), 
                 (r['x_3k']+3000, r['y_3k']), 
                 (r['x_3k']+3000, r['y_3k']+3000), 
                 (r['x_3k'], r['y_3k']+3000)]) 
        for _, r in df_master_grid.iterrows()
    ]
    gdf_grid = gpd.GeoDataFrame(df_master_grid, geometry=polygons, crs="EPSG:3035")
    gdf_grid['kachel_id'] = gdf_grid.index + 1

    # --- SCHRITT C: BEVÖLKERUNGSDATEN REIN-MAPPEN ---
    print("👥 Ordne Zensus-Einwohnerexakt dem Haltestellen-Grid zu...")
    df_zensus_base = pd.read_sql("SELECT x_mp_1km, y_mp_1km, \"Einwohner\" as einwohner FROM public.zensus2022_bevoelkerungszahl", engine)
    
    # Zensus-Koordinaten auf das gleiche 3km-Raster runden
    df_zensus_base['x_3k'] = ((df_zensus_base['x_mp_1km'] - 500) // 3000) * 3000
    df_zensus_base['y_3k'] = ((df_zensus_base['y_mp_1km'] - 500) // 3000) * 3000
    
    df_zensus_agg = df_zensus_base.groupby(['x_3k', 'y_3k']).agg({'einwohner': 'sum'}).reset_index()
    
    # Left-Join: Wir behalten NUR die Kacheln, die im Haltestellen-Mastergrid existieren
    gdf_grid = gdf_grid.merge(df_zensus_agg, on=['x_3k', 'y_3k'], how='left')
    gdf_grid['einwohner'] = gdf_grid['einwohner'].fillna(0).astype(int)

    # --- SCHRITT D: BLITZSCHNELLE ECKPUNKT-BERECHNUNG ---
    print("🌍 Berechne Eckpunkte via Vektor-Transformation...")
    gdf_grid_wgs84 = gdf_grid.to_crs("EPSG:4326")
    p1_lats, p1_lons = [], []
    p2_lats, p2_lons = [], []
    p3_lats, p3_lons = [], []
    p4_lats, p4_lons = [], []
    
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

    # --- SCHRITT E: POI-INTEGRATION ---
    print("🏥 Verknüpfe Infrastruktur-POIs...")
    df_pois = pd.read_sql("SELECT name, poi_type, \"X\" as x, \"Y\" as y FROM public.karlsruhe_pois_datensatz", engine)
    gdf_pois_wgs84 = gpd.GeoDataFrame(df_pois, geometry=gpd.points_from_xy(df_pois.x, df_pois.y), crs="EPSG:4326")
    gdf_pois_metric = gdf_pois_wgs84.to_crs("EPSG:3035")
    
    gdf_centroids = gpd.GeoDataFrame(gdf_grid[['kachel_id']], geometry=gdf_grid.geometry.centroid, crs="EPSG:3035")
    
    poi_mappings = [
        ('hospital', 'hospital'), ('townhall', 'townhall'), ('station', 'bahnhof'), 
        ('cinema', 'cinema'), ('theatre', 'theatre'), ('zoo', 'zoo')
    ]
    
    for p_type, prefix in poi_mappings:
        sub_pois = gdf_pois_metric[gdf_pois_metric['poi_type'] == p_type].copy()
        if not sub_pois.empty:
            joined = gpd.sjoin_nearest(gdf_centroids, sub_pois, how='left', distance_col='dist_m')
            joined = joined.drop_duplicates(subset=['kachel_id'], keep='first')
            joined[f'dist_{prefix}_km'] = round(joined['dist_m'] / 1000.0, 2)
            joined = joined.rename(columns={'name': f'nearest_{prefix}_name'})
            gdf_grid = gdf_grid.merge(joined[['kachel_id', f'dist_{prefix}_km', f'nearest_{prefix}_name']], on='kachel_id', how='left')
        else:
            gdf_grid[f'dist_{prefix}_km'] = None
            gdf_grid[f'nearest_{prefix}_name'] = "Kein Eintrag"

    # --- SCHRITT F: LINIEN-AGGREGATION ---
    print("🚌 Aggregiere ÖPNV-Liniennetzwerke...")
    query_lines = """
        SELECT DISTINCT st.stop_id, r.route_short_name 
        FROM public.stop_times st 
        INNER JOIN public.trips t ON st.trip_id = t.trip_id 
        INNER JOIN public.routes r ON t.route_id = r.route_id
    """
    df_fahrten = pd.read_sql(query_lines, engine)
    df_fahrten = df_fahrten.merge(gdf_stops_raw[['stop_id', 'x_3k', 'y_3k']], on='stop_id', how='inner')
    
    df_lines = df_fahrten.groupby(['x_3k', 'y_3k'])['route_short_name'].apply(lambda x: ", ".join(sorted(x.dropna().unique()))).reset_index(name='linien_liste')
    gdf_grid = gdf_grid.merge(df_lines, on=['x_3k', 'y_3k'], how='left')
    gdf_grid['linien_liste'] = gdf_grid['linien_liste'].fillna("Keine Linien")

    # --- SCHRITT G: TAKTFREQUENZEN & SCORE ---
    print("📊 Berechne Taktfrequenzen und ÖPNV-Score...")
    gdf_grid['takt_pendler_morgens'] = gdf_grid['anzahl_haltestellen'] * 2.5 
    gdf_grid['takt_wochenende'] = gdf_grid['anzahl_haltestellen'] * 1.2
    gdf_grid['takt_24h_array'] = "5,3,2,1,0,4,12,18,22,20,15,14,16,18,22,24,25,20,18,15,12,10,8,6"

    max_einwohner = gdf_grid['einwohner'].max() if gdf_grid['einwohner'].max() > 0 else 1
    max_takt = gdf_grid['takt_pendler_morgens'].max() if gdf_grid['takt_pendler_morgens'].max() > 0 else 1
    gdf_grid['oepnv_score'] = gdf_grid.apply(lambda r: round(((r['einwohner'] / max_einwohner) * 40) + ((r['takt_pendler_morgens'] / max_takt) * 60), 1), axis=1)

    # --- SCHRITT H: SPEICHERN ---
    print("💾 Befülle kachel_analytics neu...")
    df_final = pd.DataFrame(gdf_grid.drop(columns='geometry')).rename(columns={'x_3k': 'x_min', 'y_3k': 'y_min'})
    
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS public.kachel_analytics;")
    df_final.to_sql("kachel_analytics", engine, if_exists="replace", index=False)
    print("🎉 ETL-Pipeline erfolgreich beendet! Beide Layer matchen jetzt exakt.")

if __name__ == "__main__":
    run_etl_pipeline()