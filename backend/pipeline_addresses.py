import os
import sys
import time
import pandas as pd
import geopandas as gpd
from shapely.geometry import Polygon
from sqlalchemy import create_engine
from dotenv import load_dotenv
from geopy.geocoders import Nominatim

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

def run_address_pipeline():
    engine = get_db_engine()
    print("🚌 Berechne Haltestellen-Grid für Adress-Mapping...")
    df_stops = pd.read_sql("SELECT stop_id, stop_lat, stop_lon FROM public.stops", engine)
    gdf_stops = gpd.GeoDataFrame(df_stops, geometry=gpd.points_from_xy(df_stops.stop_lon, df_stops.stop_lat), crs="EPSG:4326").to_crs("EPSG:3035")
    
    gdf_stops['x_3k'] = (gdf_stops.geometry.x // 3000) * 3000
    gdf_stops['y_3k'] = (gdf_stops.geometry.y // 3000) * 3000
    df_master_grid = gdf_stops.groupby(['x_3k', 'y_3k']).size().reset_index(name='anzahl_haltestellen')
    
    polygons = [Polygon([(r['x_3k'], r['y_3k']), (r['x_3k']+3000, r['y_3k']), (r['x_3k']+3000, r['y_3k']+3000), (r['x_3k'], r['y_3k']+3000)]) for _, r in df_master_grid.iterrows()]
    gdf_grid = gpd.GeoDataFrame(df_master_grid, geometry=polygons, crs="EPSG:3035")
    gdf_grid['kachel_id'] = gdf_grid.index + 1
    
    print("🌍 Berechne Kachelmitten...")
    gdf_centroids_wgs84 = gpd.GeoDataFrame(geometry=gdf_grid.geometry.centroid, crs="EPSG:3035").to_crs("EPSG:4326")
    mitten_lats = [geom.y for geom in gdf_centroids_wgs84['geometry']]
    mitten_lons = [geom.x for geom in gdf_centroids_wgs84['geometry']]
    
    geolocator = Nominatim(user_agent="karlsruhe_opnv_analytics_platform_six_sem")
    adressen = []
    print("📍 Frage Kachel-Adressen via Reverse Geocoding ab (Das dauert etwas)...")
    
    for i, (lat, lon) in enumerate(zip(mitten_lats, mitten_lons)):
        time.sleep(1.1)
        try:
            location = geolocator.reverse((lat, lon), timeout=15, language="de")
            if location and location.raw and 'address' in location.raw:
                addr_details = location.raw['address']
                ort = addr_details.get('suburb') or addr_details.get('village') or addr_details.get('town') or addr_details.get('city') or "Region Karlsruhe"
                strasse = addr_details.get('road')
                anzeige_text = f"{ort}, {strasse}" if strasse else f"{ort}"
                adressen.append(anzeige_text)
            else:
                adressen.append(f"Bereich {round(lat, 3)} / {round(lon, 3)}")
        except Exception as e:
            print(f"   ⚠️ Fehler bei Kachel {i+1}: {str(e)}")
            adressen.append(f"Bereich {round(lat, 3)} / {round(lon, 3)}")
        
        if (i + 1) % 5 == 0 or (i + 1) == len(mitten_lats):
            print(f"   -> {i + 1} / {len(mitten_lats)} Adressen verarbeitet...")

    df_addresses = pd.DataFrame({'kachel_id': gdf_grid['kachel_id'], 'adresse': adressen})
    
    print("💾 Speichere Adressen in Hilfstabelle...")
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS public.kachel_adressen;")
    df_addresses.to_sql("kachel_adressen", engine, if_exists="replace", index=False)
    print("🎉 Adress-Tabelle erfolgreich erstellt!")

if __name__ == "__main__":
    run_address_pipeline()