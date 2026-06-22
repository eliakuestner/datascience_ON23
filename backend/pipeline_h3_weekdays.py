import os
import sys
import time
import requests
import xml.etree.ElementTree as ET
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Umgebungsvariablen laden
load_dotenv()

def get_database_url() -> str:
    user = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD")
    host = os.getenv("DB_HOST")
    port = os.getenv("DB_PORT")
    name = os.getenv("DB_NAME")
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{name}"

ENGINE = create_engine(get_database_url())
TRIAS_URL = "https://projekte.kvv-efa.de/mariustrias/trias"
REQUESTOR_REF = "hQNQVLXmrPBT"

NAMESPACES = {
    'trias': 'http://www.vdv.de/trias',
    'siri': 'http://www.siri.org.uk/siri'
}

def parse_xml_duration(duration_str):
    if not duration_str: return 0
    try:
        minutes = 0
        if 'T' in duration_str:
            time_part = duration_str.split('T')[1]
            if 'H' in time_part:
                hours_part, time_part = time_part.split('H')
                minutes += int(hours_part) * 60
            if 'M' in time_part:
                minutes += int(time_part.split('M')[0])
        return minutes
    except Exception:
        return 0

def call_trias_api(xml_payload):
    headers = {"Content-Type": "application/xml; charset=utf-8", "Accept": "application/xml"}
    max_retries = 2  # Reduziert für maximale Geschwindigkeit
    
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.post(TRIAS_URL, data=xml_payload.encode('utf-8'), headers=headers, timeout=8)
            if response.status_code != 200 or not response.text:
                time.sleep(1.0)
                continue
                
            root = ET.fromstring(response.text)
            error_block = root.find('.//trias:ErrorMessage', NAMESPACES)
            if error_block is not None:
                time.sleep(0.5)
                continue
                
            trips = root.findall('.//trias:Trip', NAMESPACES)
            if not trips: return None
            
            best_trip = trips[0]
            duration_min = 0
            dur_elem = best_trip.find('.//trias:Duration', NAMESPACES)
            if dur_elem is not None:
                duration_min = parse_xml_duration(dur_elem.text)
                
            legs = best_trip.findall('.//trias:TripLeg', NAMESPACES)
            timed_legs = [leg.find('.//trias:TimedLeg', NAMESPACES) for leg in legs if leg.find('.//trias:TimedLeg', NAMESPACES) is not None]
            umstiege = max(0, len(timed_legs) - 1)

            return {"duration": duration_min, "umstiege": umstiege}
        except Exception:
            time.sleep(1.0)
    return None

def build_trias_trip_xml(start_lat, start_lon, ziel_lat, ziel_lon, target_datetime):
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Trias version="1.1" xmlns="http://www.vdv.de/trias" xmlns:siri="http://www.siri.org.uk/siri">
    <ServiceRequest>
        <siri:RequestTimeStamp>{timestamp}</siri:RequestTimeStamp>
        <siri:RequestorRef>{REQUESTOR_REF}</siri:RequestorRef>
        <RequestPayload>
            <TripRequest>
                <Origin><LocationRef><GeoPosition><Longitude>{start_lon}</Longitude><Latitude>{start_lat}</Latitude></GeoPosition></LocationRef><DepArrTime>{target_datetime}:00</DepArrTime></Origin>
                <Destination><LocationRef><GeoPosition><Longitude>{ziel_lon}</Longitude><Latitude>{ziel_lat}</Latitude></GeoPosition></LocationRef></Destination>
                <Params>
                    <Algorithm>FastestTrip</Algorithm>
                    <NumberOfResults>1</NumberOfResults>
                    <SearchWindowForward>180</SearchWindowForward>
                    <MaxWalkTime>30</MaxWalkTime>
                    <WalkSpeed>100</WalkSpeed>
                    <IncludeTrackSections>false</IncludeTrackSections>
                    <IncludeLegProjection>false</IncludeLegProjection>
                    <IncludeIntermediateStops>false</IncludeIntermediateStops>
                </Params>
            </TripRequest>
        </RequestPayload>
    </ServiceRequest>
</Trias>"""

def init_baseline_table():
    with ENGINE.begin() as conn:
        print("[+] Erstelle Hilfstabelle kachel_routing_h3_baseline...")
        conn.execute(text("DROP TABLE IF EXISTS public.kachel_routing_h3_baseline;"))
        conn.execute(text("""
            CREATE TABLE public.kachel_routing_h3_baseline (
                kachel_id INT,
                poi_typ VARCHAR(50),
                zeit_di_mittags_min INT,
                umstiege_di_mi INT,
                zeit_di_abends_min INT,
                umstiege_di_ab INT,
                PRIMARY KEY (kachel_id, poi_typ)
            );
        """))

def run_baseline_pipeline():
    init_baseline_table()
    
    # Wir holen uns die Geo-Koordinaten direkt über den Join aus kachel_analytics
    query = """
        SELECT h3.kachel_id, h3.poi_typ, h3.poi_name,
               ((a.p1_lat + a.p3_lat) / 2.0) as s_lat, ((a.p1_lon + a.p3_lon) / 2.0) as s_lon,
               CASE 
                   WHEN h3.poi_typ = 'Kino' THEN a.cinema_lat
                   WHEN h3.poi_typ = 'Theater' THEN a.theatre_lat
                   WHEN h3.poi_typ = 'Zoo' THEN a.zoo_lat
               END as poi_lat,
               CASE 
                   WHEN h3.poi_typ = 'Kino' THEN a.cinema_lon
                   WHEN h3.poi_typ = 'Theater' THEN a.theatre_lon
                   WHEN h3.poi_typ = 'Zoo' THEN a.zoo_lon
               END as poi_lon
        FROM public.kachel_routing_h3 h3
        JOIN public.kachel_analytics a ON h3.kachel_id = a.kachel_id;
    """
    df = pd.read_sql_query(text(query), ENGINE)
    total_pairs = len(df)
    print(f"[+] Starte Baseline-Routing für insgesamt {total_pairs} Paare...")

    for idx, row in df.iterrows():
        k_id = int(row["kachel_id"])
        p_typ = row["poi_typ"]
        s_lat, s_lon = row["s_lat"], row["s_lon"]
        p_lat, p_lon = row["poi_lat"], row["poi_lon"]
        
        if not p_lat or not p_lon: continue
        
        print(f"   ➔ [{idx + 1}/{total_pairs}] Kachel {k_id} | POI: {p_typ}")
        
        # 1. Dienstag Mittag (Analog zu Sa-Mittag um 14:00 Uhr)
        di_mi = call_trias_api(build_trias_trip_xml(s_lat, s_lon, p_lat, p_lon, "2026-06-23T14:00"))
        time.sleep(0.2) # Drastisch verkürztes Timeout für maximalen Speed
        
        # 2. Dienstag Abend (Analog zu Fr/Sa-Abend um 19:30 Uhr)
        di_ab = call_trias_api(build_trias_trip_xml(s_lat, s_lon, p_lat, p_lon, "2026-06-23T19:30"))
        time.sleep(0.2)

        with ENGINE.begin() as conn:
            conn.execute(text("""
                INSERT INTO public.kachel_routing_h3_baseline (
                    kachel_id, poi_typ, 
                    zeit_di_mittags_min, umstiege_di_mi,
                    zeit_di_abends_min, umstiege_di_ab
                ) VALUES (
                    :id, :typ, :z_mi, :u_mi, :z_ab, :u_ab
                );
            """), {
                "id": k_id, "typ": p_typ,
                "z_mi": di_mi["duration"] if di_mi else None, "u_mi": di_mi["umstiege"] if di_mi else None,
                "z_ab": di_ab["duration"] if di_ab else None, "u_ab": di_ab["umstiege"] if di_ab else None
            })
            
    print("[🎉] Baseline-Messung abgeschlossen!")

if __name__ == "__main__":
    run_baseline_pipeline()