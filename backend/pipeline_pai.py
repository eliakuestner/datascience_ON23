import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Pfade & .env Konfiguration laden
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def get_database_url() -> str:
    user = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD")
    host = os.getenv("DB_HOST")
    port = os.getenv("DB_PORT")
    name = os.getenv("DB_NAME")
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{name}"


def calculate_pai_values():
    url = get_database_url()
    engine = create_engine(url)

    print("Starte Berechnung des Pendlerzeiten-Abhängigkeitsindex (PAI)...")

    with engine.begin() as conn:
        # 1. Spalte hinzufügen, falls sie nicht existiert
        conn.execute(
            text(
                """
            ALTER TABLE public.kachel_analytics 
            ADD COLUMN IF NOT EXISTS pai DOUBLE PRECISION DEFAULT 0.0;
        """
            )
        )

        # 2. Alle relevanten Daten für die Berechnung laden
        result = conn.execute(
            text(
                "SELECT kachel_id, takt_24h_mo FROM public.kachel_analytics;"
            )
        ).fetchall()

        updated_count = 0
        for row in result:
            kachel_id = row[0]
            takt_string = row[1]

            if not takt_string:
                continue

            try:
                # String in Integer-Array parsen (24 Stunden)
                takt = [int(x) for x in takt_string.split(",")]
                if len(takt) != 24:
                    continue

                # Peak-Stunden: Morgens (06, 07, 08) & Nachmittags (16, 17, 18)
                peak_hours = [
                    takt[6],
                    takt[7],
                    takt[8],
                    takt[16],
                    takt[17],
                    takt[18],
                ]
                f_peak = sum(peak_hours) / len(peak_hours)

                # Off-Peak-Stunden (Mittagstal): 10, 11, 12, 13, 14
                off_peak_hours = [takt[10], takt[11], takt[12], takt[13], takt[14]]
                f_offpeak = sum(off_peak_hours) / len(off_peak_hours)

                # PAI Formel: (F_peak - F_offpeak) / F_peak
                if f_peak > 0:
                    pai = (f_peak - f_offpeak) / f_peak
                    # PAI mathematisch auf den Bereich [0.0, 1.0] begrenzen
                    pai = max(0.0, min(1.0, pai))
                else:
                    pai = 0.0

                # Wert in Datenbank schreiben
                conn.execute(
                    text(
                        "UPDATE public.kachel_analytics SET pai = :pai WHERE kachel_id = :id"
                    ),
                    {"pai": pai, "id": kachel_id},
                )
                updated_count += 1

            except Exception as e:
                print(f"Fehler bei Kachel ID {kachel_id}: {e}", file=sys.stderr)
                continue

        print(
            f"Erfolgreich beendet! {updated_count} Kacheln wurden mit PAI-Werten aktualisiert."
        )


if __name__ == "__main__":
    calculate_pai_values()