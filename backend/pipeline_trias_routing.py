import os
import sys
import time
import xml.etree.ElementTree as ET
import requests
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
REQUESTOR_REF = "hQNQVLXmrPBT"  # <-- Deine offizielle Kennung eintragen

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

def call_trias_api(xml_payload, log_label="Route"):
    headers = {"Content-Type": "application/xml; charset=utf-8", "Accept": "application/xml"}
    max_retries = 3
    
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.post(TRIAS_URL, data=xml_payload.encode('utf-8'), headers=headers, timeout=15)
            
            if response.status_code != 200 or not response.text or response.text.strip() == "":
                time.sleep(5.0)  # Cooldown bei Server-Blockade
                continue
                
            root = ET.fromstring(response.text)
            
            error_block = root.find('.//trias:ErrorMessage', NAMESPACES)
            if error_block is not None:
                time.sleep(2.0)
                continue
                
            trips = root.findall('.//trias:Trip', NAMESPACES)
            if not trips:
                return None
                
            best_trip = trips[0]
            
            # Gesamtdauer parsen
            duration_min = 0
            dur_elem = best_trip.find('.//trias:Duration', NAMESPACES)
            if dur_elem is not None:
                duration_min = parse_xml_duration(dur_elem.text)
                
            # Abfahrtszeit parsen
            start_time_str = None
            st_elem = best_trip.find('.//trias:StartTime', NAMESPACES)
            if st_elem is not None:
                start_time_str = st_elem.text.split('T')[1][:5]

            # Umstiege über die Anzahl der gefahrenen Teilstrecken ermitteln
            legs = best_trip.findall('.//trias:TripLeg', NAMESPACES)
            timed_legs = [leg.find('.//trias:TimedLeg', NAMESPACES) for leg in legs if leg.find('.//trias:TimedLeg', NAMESPACES) is not None]
            umstiege = max(0, len(timed_legs) - 1)

            print(f"       ✔ {duration_min} Min | {umstiege} Umstiege (Start: {start_time_str} Uhr)")
            return {
                "duration": duration_min, 
                "departure": start_time_str, 
                "umstiege": umstiege
            }
            
        except Exception:
            time.sleep(4.0)
            
    print(f"   [!] {log_label} fehlgeschlagen nach {max_retries} Versuchen. Überspringe Wert sauber.")
    return None

def init_target_tables():
    with ENGINE.begin() as conn:
        print("[+] Bereinige und initialisiere Zieltabellen für das finale Routing...")
        conn.execute(text("DROP TABLE IF EXISTS public.kachel_routing_h1;"))
        conn.execute(text("DROP TABLE IF EXISTS public.kachel_routing_h3;"))
        
        conn.execute(text("""
            CREATE TABLE public.kachel_routing_h1 (
                kachel_id INT, poi_typ VARCHAR(50), poi_name VARCHAR(255), distanz_luftlinie_km DOUBLE PRECISION,
                zeit_morgens_min INT, umstiege_morgens INT,
                zeit_mittags_min INT, umstiege_mittags INT,
                zeit_abends_min INT, umstiege_abends INT,
                PRIMARY KEY (kachel_id, poi_typ)
            );
        """))
        conn.execute(text("""
            CREATE TABLE public.kachel_routing_h3 (
                kachel_id INT, poi_typ VARCHAR(50), poi_name VARCHAR(255), distanz_luftlinie_km DOUBLE PRECISION,
                zeit_fr_abends_min INT, umstiege_fr INT,
                zeit_sa_mittags_min INT, umstiege_sa_mi INT,
                zeit_sa_abends_min INT, umstiege_sa_ab INT,
                zeit_so_mittags_min INT, umstiege_so_mi INT,
                zeit_so_abends_min INT, umstiege_so_ab INT,
                heimfahrt_spateste VARCHAR(5),
                PRIMARY KEY (kachel_id, poi_typ)
            );
        """))

def build_trias_trip_xml(start_lat, start_lon, ziel_lat, ziel_lon, target_datetime, is_latest_search=False):
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    algorithm = "LatestTrip" if is_latest_search else "FastestTrip"
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
                    <Algorithm>{algorithm}</Algorithm>
                    <NumberOfResults>1</NumberOfResults>
                    <SearchWindowForward>180</SearchWindowForward>
                    <MaxWalkTime>30</MaxWalkTime>
                    <WalkSpeed>100</WalkSpeed>
                    <IncludeTrackSections>true</IncludeTrackSections>
                    <IncludeLegProjection>false</IncludeLegProjection>
                    <IncludeIntermediateStops>false</IncludeIntermediateStops>
                </Params>
            </TripRequest>
        </RequestPayload>
    </ServiceRequest>
</Trias>"""

def run_pipeline():
    init_target_tables()
    
    query = """
        SELECT kachel_id, adresse, 
               ((p1_lat + p3_lat) / 2.0) as s_lat, ((p1_lon + p3_lon) / 2.0) as s_lon,
               nearest_hospital_name, dist_hospital_km, hospital_lat, hospital_lon,
               nearest_townhall_name, dist_townhall_km, townhall_lat, townhall_lon,
               nearest_bahnhof_name, dist_bahnhof_km, bahnhof_lat, bahnhof_lon,
               nearest_cinema_name, dist_cinema_km, cinema_lat, cinema_lon,
               nearest_theatre_name, dist_theatre_km, theatre_lat, theatre_lon,
               nearest_zoo_name, dist_zoo_km, zoo_lat, zoo_lon
        FROM public.kachel_analytics
        WHERE einwohner > 0 AND anzahl_haltestellen > 0
        ORDER BY anzahl_haltestellen DESC;
    """
    df = pd.read_sql_query(text(query), ENGINE)
    total_kacheln = len(df)
    print(f"[+] Starte finalen Massendurchlauf für insgesamt {total_kacheln} Kacheln...")

    for idx, row in df.iterrows():
        k_id = int(row["kachel_id"])
        s_lat, s_lon = row["s_lat"], row["s_lon"]
        print(f"\n➔ [{idx + 1}/{total_kacheln}] Verarbeite KACHEL ID: {k_id} ({row['adresse']})")

        # --- HYPOTHESE 1 ---
        h1_pois = [
            {"typ": "Krankenhaus", "name": row["nearest_hospital_name"], "lat": row["hospital_lat"], "lon": row["hospital_lon"], "dist": row["dist_hospital_km"]},
            {"typ": "Rathaus", "name": row["nearest_townhall_name"], "lat": row["townhall_lat"], "lon": row["townhall_lon"], "dist": row["dist_townhall_km"]},
            {"typ": "Fernbahnhof", "name": row["nearest_bahnhof_name"], "lat": row["bahnhof_lat"], "lon": row["bahnhof_lon"], "dist": row["dist_bahnhof_km"]}
        ]

        for poi in h1_pois:
            if not poi["name"] or poi["name"] in ["Kein Eintrag", "-", ""]: continue
            print(f"   ➔ POI: {poi['typ']} ({poi['name']})")
            
            mo = call_trias_api(build_trias_trip_xml(s_lat, s_lon, poi["lat"], poi["lon"], "2026-06-23T07:30"), f"{poi['typ']} Morgen")
            time.sleep(1.5)
            mi = call_trias_api(build_trias_trip_xml(s_lat, s_lon, poi["lat"], poi["lon"], "2026-06-23T13:00"), f"{poi['typ']} Mittag")
            time.sleep(1.5)
            ab = call_trias_api(build_trias_trip_xml(s_lat, s_lon, poi["lat"], poi["lon"], "2026-06-23T18:00"), f"{poi['typ']} Abend")
            time.sleep(1.5)
            
            with ENGINE.begin() as conn:
                conn.execute(text("""
                    INSERT INTO public.kachel_routing_h1 (
                        kachel_id, poi_typ, poi_name, distanz_luftlinie_km,
                        zeit_morgens_min, umstiege_morgens,
                        zeit_mittags_min, umstiege_mittags,
                        zeit_abends_min, umstiege_abends
                    ) VALUES (
                        :id, :typ, :name, :dist, :z_mo, :u_mo, :z_mi, :u_mi, :z_ab, :u_ab
                    ) ON CONFLICT (kachel_id, poi_typ) DO UPDATE SET
                        zeit_morgens_min = EXCLUDED.zeit_morgens_min,
                        zeit_mittags_min = EXCLUDED.zeit_mittags_min,
                        zeit_abends_min = EXCLUDED.zeit_abends_min;
                """), {
                    "id": k_id, "typ": poi["typ"], "name": poi["name"], "dist": poi["dist"],
                    "z_mo": mo["duration"] if mo else None, "u_mo": mo["umstiege"] if mo else None,
                    "z_mi": mi["duration"] if mi else None, "u_mi": mi["umstiege"] if mi else None,
                    "z_ab": ab["duration"] if ab else None, "u_ab": ab["umstiege"] if ab else None
                })

        # --- HYPOTHESE 3 ---
        h3_pois = [
            {"typ": "Kino", "name": row["nearest_cinema_name"], "lat": row["cinema_lat"], "lon": row["cinema_lon"], "dist": row["dist_cinema_km"]},
            {"typ": "Theater", "name": row["nearest_theatre_name"], "lat": row["theatre_lat"], "lon": row["theatre_lon"], "dist": row["dist_theatre_km"]},
            # FIX: Hier stand vorher fälschlicherweise zweimal zoo_lon drin! Jetzt korrigiert auf zoo_lat.
            {"typ": "Zoo", "name": row["nearest_zoo_name"], "lat": row["zoo_lat"], "lon": row["zoo_lon"], "dist": row["dist_zoo_km"]}
        ]

        for poi in h3_pois:
            if not poi["name"] or poi["name"] in ["Kein Eintrag", "-", ""]: continue
            print(f"   ➔ POI: {poi['typ']} ({poi['name']})")
            
            fr = call_trias_api(build_trias_trip_xml(s_lat, s_lon, poi["lat"], poi["lon"], "2026-06-19T19:30"), "Fr-Abend")
            time.sleep(1.5)
            sam = call_trias_api(build_trias_trip_xml(s_lat, s_lon, poi["lat"], poi["lon"], "2026-06-20T14:00"), "Sa-Mittag")
            time.sleep(1.5)
            saa = call_trias_api(build_trias_trip_xml(s_lat, s_lon, poi["lat"], poi["lon"], "2026-06-20T19:30"), "Sa-Abend")
            time.sleep(1.5)
            som = call_trias_api(build_trias_trip_xml(s_lat, s_lon, poi["lat"], poi["lon"], "2026-06-21T11:00"), "So-Mittag")
            time.sleep(1.5)
            soa = call_trias_api(build_trias_trip_xml(s_lat, s_lon, poi["lat"], poi["lon"], "2026-06-21T16:30"), "So-Abend")
            time.sleep(1.5)
            
            heim = call_trias_api(build_trias_trip_xml(poi["lat"], poi["lon"], s_lat, s_lon, "2026-06-21T03:59", is_latest_search=True), "Heimfahrt")
            time.sleep(1.5)

            with ENGINE.begin() as conn:
                conn.execute(text("""
                    INSERT INTO public.kachel_routing_h3 (
                        kachel_id, poi_typ, poi_name, distanz_luftlinie_km,
                        zeit_fr_abends_min, umstiege_fr,
                        zeit_sa_mittags_min, umstiege_sa_mi,
                        zeit_sa_abends_min, umstiege_sa_ab,
                        zeit_so_mittags_min, umstiege_so_mi,
                        zeit_so_abends_min, umstiege_so_ab,
                        heimfahrt_spateste
                    ) VALUES (
                        :id, :typ, :name, :dist, :z_fr, :u_fr, :z_sm, :u_sm, :z_sa, :u_sa, :z_som, :u_som, :z_soa, :u_soa, :h_t
                    ) ON CONFLICT (kachel_id, poi_typ) DO UPDATE SET 
                        zeit_fr_abends_min = EXCLUDED.zeit_fr_abends_min,
                        zeit_sa_mittags_min = EXCLUDED.zeit_sa_mittags_min,
                        zeit_sa_abends_min = EXCLUDED.zeit_sa_abends_min,
                        zeit_so_mittags_min = EXCLUDED.zeit_so_mittags_min,
                        zeit_so_abends_min = EXCLUDED.zeit_so_abends_min,
                        heimfahrt_spateste = EXCLUDED.heimfahrt_spateste;
                """), {
                    "id": k_id, "typ": poi["typ"], "name": poi["name"], "dist": poi["dist"],
                    "z_fr": fr["duration"] if fr else None, "u_fr": fr["umstiege"] if fr else None,
                    "z_sm": sam["duration"] if sam else None, "u_sm": sam["umstiege"] if sam else None,
                    "z_sa": saa["duration"] if saa else None, "u_sa": saa["umstiege"] if saa else None,
                    "z_som": som["duration"] if som else None, "u_som": som["umstiege"] if som else None,
                    "z_soa": soa["duration"] if soa else None, "u_soa": soa["umstiege"] if soa else None,
                    "h_t": heim["departure"] if heim else None
                })
        print(f"   ✔ Kachel {k_id} erfolgreich weggeschrieben.")

    print(f"\n[🎉] PIPELINE BEENDET! Dein kompletter Datensatz steht jetzt sauber in PostgreSQL.")

if __name__ == "__main__":
    run_pipeline()