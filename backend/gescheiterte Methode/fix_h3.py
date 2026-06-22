import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
import pandas as pd

load_dotenv()

def get_database_url() -> str:
    user = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD")
    host = os.getenv("DB_HOST")
    port = os.getenv("DB_PORT")
    name = os.getenv("DB_NAME")
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{name}"

def parse_and_sum_takt(takt_str):
    """Splittet den komma-separierten String und summiert die Fahrten auf."""
    if not takt_str or pd.isna(takt_str):
        return 0
    try:
        # Entfernt eventuelle Leerzeichen und splittet nach Komma
        return sum(int(x.strip()) for x in str(takt_str).split(',') if x.strip().isdigit())
    except Exception:
        return 0

def update_h3_frequencies():
    engine = create_engine(get_database_url())
    
    # 1. Spalten in der Zieltabelle anlegen (für jeden Tag separat, um granulare Vergleiche zu ermöglichen)
    with engine.begin() as conn:
        print("[+] Erzeuge Taktfrequenz-Spalten in kachel_routing_h3...")
        conn.execute(text("ALTER TABLE public.kachel_routing_h3 ADD COLUMN IF NOT EXISTS fahrten_tag_di INT;"))
        conn.execute(text("ALTER TABLE public.kachel_routing_h3 ADD COLUMN IF NOT EXISTS fahrten_tag_fr INT;"))
        conn.execute(text("ALTER TABLE public.kachel_routing_h3 ADD COLUMN IF NOT EXISTS fahrten_tag_sa INT;"))
        conn.execute(text("ALTER TABLE public.kachel_routing_h3 ADD COLUMN IF NOT EXISTS fahrten_tag_so INT;"))

    # 2. Takt-Strings aus kachel_analytics laden
    print("[+] Lade 24h-Takt-Arrays aus der Analytics-Tabelle...")
    query = """
        SELECT kachel_id, takt_24h_di, takt_24h_fr, takt_24h_sa, takt_24h_so 
        FROM public.kachel_analytics;
    """
    df_analytics = pd.read_sql_query(text(query), engine)
    
    # 3. Summen berechnen
    print("[+] Berechne tägliche Gesamtfahrten aus den Stunden-Arrays...")
    df_analytics['fahrten_tag_di'] = df_analytics['takt_24h_di'].apply(parse_and_sum_takt)
    df_analytics['fahrten_tag_fr'] = df_analytics['takt_24h_fr'].apply(parse_and_sum_takt)
    df_analytics['fahrten_tag_sa'] = df_analytics['takt_24h_sa'].apply(parse_and_sum_takt)
    df_analytics['fahrten_tag_so'] = df_analytics['takt_24h_so'].apply(parse_and_sum_takt)

    # 4. Zeilenweise Updates in kachel_routing_h3 schreiben
    print("[+] Schreibe aggregierte Frequenzen in kachel_routing_h3...")
    with engine.begin() as conn:
        update_query = """
            UPDATE public.kachel_routing_h3
            SET 
                fahrten_tag_di = :fahrten_tag_di,
                fahrten_tag_fr = :fahrten_tag_fr,
                fahrten_tag_sa = :fahrten_tag_sa,
                fahrten_tag_so = :fahrten_tag_so
            WHERE kachel_id = :kachel_id;
        """
        
        # Konvertiert das DataFrame in ein Dictionary-Format für das Massen-Update
        data_to_update = df_analytics[['kachel_id', 'fahrten_tag_di', 'fahrten_tag_fr', 'fahrten_tag_sa', 'fahrten_tag_so']].to_dict(orient='records')
        conn.execute(text(update_query), data_to_update)
        
    print(f"[🎉] Taktfrequenzen für alle Zonentage erfolgreich übertragen!")

if __name__ == "__main__":
    update_h3_frequencies()