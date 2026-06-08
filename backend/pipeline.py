import os
import pandas as pd
import geopandas as gpd
from shapely.geometry import Polygon, Point
from sqlalchemy import create_engine
from dotenv import load_dotenv

# 1. .env laden
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(base_dir, '.env'))

def get_db_engine():
    db_url = f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
    return create_engine(db_url)

def run_etl_pipeline():
    engine = get_db_engine()
    print("🚀 Starte Data Science ETL-Pipeline für Karlsruhe...")

# --- SCHRITT A: ZENSUS-DATEN LADEN & 3x3KM GRID MATHEMATISCH BINDEN ---
    print("📦 Lade Zensus-Daten...")
    df_zensus = pd.read_sql("SELECT x_mp_1km, y_mp_1km, \"Einwohner\" as einwohner FROM zensus2022_bevoelkerungszahl", engine)
    
    # Mathematischer Grid-Trick: Wir runden die 1km-Zentren auf die nächste 3000m-Kante ab
    df_zensus['x_3k'] = (df_zensus['x_mp_1km'] // 3000) * 3000
    df_zensus['y_3k'] = (df_zensus['y_mp_1km'] // 3000) * 3000

    # Aggregieren: Einwohner pro 3x3km Kachel aufsummieren
    df_grid_base = df_zensus.groupby(['x_3k', 'y_3k']).agg({'einwohner': 'sum'}).reset_index()
    
    # Performance-Boost: Kacheln mit 0 Einwohnern vorab filtern
    df_grid_base = df_grid_base[df_grid_base['einwohner'] > 0].reset_index(drop=True)
    df_grid_base['kachel_id'] = df_grid_base.index + 1
    print(f"📊 Relevante bewohnte Kacheln nach Vorfilterung: {len(df_grid_base)}")

    # --- SCHRITT B: GEOMETRIEN & LEAFLET-GPS BOUNDS BERECHNEN ---
    print("🌍 Berechne räumliche Polygone und GPS-Ecken für Leaflet...")
    polygons = []
    lat_mins, lon_mins, lat_maxs, lon_maxs = [], [], [], []

    for _, row in df_grid_base.iterrows():
        x, y = row['x_3k'], row['y_3k']
        # EPSG:3035 Box erzeugen
        poly = Polygon([(x, y), (x + 3000, y), (x + 3000, y + 3000), (x, y + 3000)])
        polygons.append(poly)
        
        # Umrechnung in GPS-Koordinaten (WGS84) für Leaflet Bounds
        box_gdf = gpd.GeoDataFrame(geometry=[Point(x, y), Point(x + 3000, y + 3000)], crs="EPSG:3035").to_crs("EPSG:4326")
        lon_mins.append(box_gdf.geometry.iloc[0].x)
        lat_mins.append(box_gdf.geometry.iloc[0].y)
        lon_maxs.append(box_gdf.geometry.iloc[1].x)
        lat_maxs.append(box_gdf.geometry.iloc[1].y)

    gdf_grid = gpd.GeoDataFrame(df_grid_base, geometry=polygons, crs="EPSG:3035")
    gdf_grid['lat_min'], gdf_grid['lon_min'] = lat_mins, lon_mins
    gdf_grid['lat_max'], gdf_grid['lon_max'] = lat_maxs, lon_maxs

    # Bevölkerungsklasse zuweisen
    q25 = gdf_grid['einwohner'].quantile(0.25)
    q75 = gdf_grid['einwohner'].quantile(0.75)
    gdf_grid['bevoelkerungs_klasse'] = gdf_grid['einwohner'].apply(
        lambda e: "Hoch" if e > q75 else ("Gering" if e < q25 else "Mittel")
    )

    # --- SCHRITT C: HYPOTHESE 1 - POI DISTANZEN & NAMEN ERMITTELN ---
    print("🏥 Analysiere POIs (Krankenhäuser, Rathäuser, Bahnhöfe)...")
    df_pois = pd.read_sql("SELECT name, poi_type, \"X\" as x, \"Y\" as y FROM karlsruhe_pois_datensatz", engine)
    gdf_pois = gpd.GeoDataFrame(df_pois, geometry=gpd.points_from_xy(df_pois.x, df_pois.y), crs="EPSG:4326").to_crs("EPSG:3035")

    centroids = gdf_grid.geometry.centroid
    
    for p_type, prefix in [('hospital', 'hospital'), ('townhall', 'townhall'), ('station', 'bahnhof')]:
        sub_pois = gdf_pois[gdf_pois['poi_type'] == p_type]
        dists, names = [], []
        
        for centroid in centroids:
            if not sub_pois.empty:
                all_dists = sub_pois.distance(centroid)
                min_idx = all_dists.idxmin()
                dists.append(all_dists[min_idx] / 1000.0) # In Kilometer
                names.append(sub_pois.loc[min_idx, 'name'] if pd.notna(sub_pois.loc[min_idx, 'name']) else f"Unbekanntes {p_type}")
            else:
                dists.append(None)
                names.append("Kein Eintrag")
                
        gdf_grid[f'dist_{prefix}_km'] = dists
        gdf_grid[f'nearest_{prefix}_name'] = names

    # --- SCHRITT D: GTFS-DATEN AGGREGRIEREN (HYPOTHESE 2 & 3) ---
    print("🚌 Verarbeite GTFS-Fahrplandaten (Taktung & Linien)...")
    df_stops = pd.read_sql("SELECT stop_id, stop_name, stop_lat, stop_lon FROM stops", engine)
    gdf_stops = gpd.GeoDataFrame(df_stops, geometry=gpd.points_from_xy(df_stops.stop_lon, df_stops.stop_lat), crs="EPSG:4326").to_crs("EPSG:3035")
    
    # Haltestellen mathematisch den Kacheln zuordnen
    gdf_stops['x_3k'] = (gdf_stops.geometry.x // 3000) * 3000
    gdf_stops['y_3k'] = (gdf_stops.geometry.y // 3000) * 3000

    df_trips = pd.read_sql("SELECT trip_id, route_id, service_id FROM trips", engine)
    df_routes = pd.read_sql("SELECT route_id, route_short_name FROM routes", engine)
    df_st = pd.read_sql("SELECT trip_id, stop_id, arrival_time FROM stop_times", engine)
    df_cal = pd.read_sql("SELECT service_id, monday, tuesday, wednesday, thursday, friday, saturday, sunday FROM calendar", engine)

    df_fahrten = df_st.merge(gdf_stops[['stop_id', 'x_3k', 'y_3k']], on='stop_id')
    df_fahrten = df_fahrten.merge(df_trips, on='trip_id')
    df_fahrten = df_fahrten.merge(df_routes, on='route_id')
    df_fahrten = df_fahrten.merge(df_cal, on='service_id')

    df_fahrten['stunde'] = df_fahrten['arrival_time'].apply(lambda x: int(x.split(':')[0]) if pd.notna(x) else 0)
    df_fahrten['stunde'] = df_fahrten['stunde'].apply(lambda h: h % 24)

    kachel_haltestellen_anzahl = []
    kachel_linien = []
    kachel_takt_morgens = []
    kachel_takt_we = []
    kachel_arrays = []

    for _, row in gdf_grid.iterrows():
        x, y = row['x_3k'], row['y_3k']
        
        stops_in_kachel = gdf_stops[(gdf_stops['x_3k'] == x) & (gdf_stops['y_3k'] == y)]
        kachel_haltestellen_anzahl.append(len(stops_in_kachel))
        
        fahrten_in_kachel = df_fahrten[(df_fahrten['x_3k'] == x) & (df_fahrten['y_3k'] == y)]
        
        if not fahrten_in_kachel.empty:
            linien = sorted(fahrten_in_kachel['route_short_name'].unique().tolist())
            kachel_linien.append(", ".join(linien))
            
            # Hypothese 2: Pendler morgens (Di-Do, 6-9 Uhr) -> 3 Std
            pendler_fahrten = fahrten_in_kachel[
                (fahrten_in_kachel['tuesday'] == 1) & 
                (fahrten_in_kachel['stunde'].isin([6, 7, 8]))
            ]
            kachel_takt_morgens.append(round(len(pendler_fahrten) / 3.0, 2))
            
            # Hypothese 3: Wochenende (Sa-So, 24h-Schnitt) -> 48 Std
            we_fahrten = fahrten_in_kachel[
                (fahrten_in_kachel['saturday'] == 1) | (fahrten_in_kachel['sunday'] == 1)
            ]
            kachel_takt_we.append(round(len(we_fahrten) / 48.0, 2))
            
            # 24h-Array für Chart.js (Durchschnitt Montag)
            wochentag_fahrten = fahrten_in_kachel[fahrten_in_kachel['monday'] == 1]
            hours_count = wochentag_fahrten.groupby('stunde').size().reindex(range(24), fill_value=0).tolist()
            kachel_arrays.append(",".join(map(str, hours_count)))
        else:
            kachel_linien.append("Keine Linien")
            kachel_takt_morgens.append(0.0)
            kachel_takt_we.append(0.0)
            kachel_arrays.append(",".join(["0"]*24))

    gdf_grid['anzahl_haltestellen'] = kachel_haltestellen_anzahl
    gdf_grid['linien_liste'] = kachel_linien
    gdf_grid['takt_pendler_morgens'] = kachel_takt_morgens
    gdf_grid['takt_wochenende'] = kachel_takt_we
    gdf_grid['takt_24h_array'] = kachel_arrays

    # --- SCHRITT E: DATA-SCIENCE ÖPNV-SCORE BERECHNEN ---
    max_einwohner = gdf_grid['einwohner'].max() if gdf_grid['einwohner'].max() > 0 else 1
    max_takt = gdf_grid['takt_pendler_morgens'].max() if gdf_grid['takt_pendler_morgens'].max() > 0 else 1
    
    gdf_grid['oepnv_score'] = gdf_grid.apply(
        lambda r: round(((r['einwohner'] / max_einwohner) * 40) + ((r['takt_pendler_morgens'] / max_takt) * 60), 1),
        axis=1
    )

    # --- SCHRITT F: IN DIE DATENBANK SCHREIBEN ---
    print("💾 Schreibe berechnete Kennzahlen in Tabelle 'kachel_analytics'...")
    df_final = pd.DataFrame(gdf_grid.drop(columns='geometry'))
    
    # Spaltennamen exakt an SQL-Struktur anpassen (aus x_3k wird x_min etc.)
    df_final = df_final.rename(columns={'x_3k': 'x_min', 'y_3k': 'y_min'})
    
    # Daten hochladen
    df_final.to_sql("kachel_analytics", engine, if_exists="append", index=False)
    print("🎉 ETL-Pipeline erfolgreich beendet! Eure vorberechnete Tabelle ist voll.")

if __name__ == "__main__":
    run_etl_pipeline()