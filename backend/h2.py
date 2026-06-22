import os
from pathlib import Path
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# ==========================================
# PFADE & KONFIGURATION
# ==========================================
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

def get_database_url() -> str:
    user = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD")
    host = os.getenv("DB_HOST")
    port = os.getenv("DB_PORT")
    name = os.getenv("DB_NAME")
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{name}"

# ==========================================
# LORENZ & GINI MATHEMATIK
# ==========================================
def calculate_gini_and_lorenz(pai_array):
    """Berechnet die Lorenz-Kurve und den Gini-Koeffizienten für ein Array von PAI-Werten."""
    # Negative Werte abfangen und Array aufsteigend sortieren
    y = np.array(pai_array, dtype=np.float64)
    y = np.clip(y, 0, None)
    y = np.sort(y)
    
    n = len(y)
    if n == 0 or np.sum(y) == 0:
        return [0], [0], 0.0
    
    # Gini-Koeffizient berechnen
    index = np.arange(1, n + 1)
    gini_coeff = ((np.sum((2 * index - n - 1) * y)) / (n * np.sum(y)))
    
    # Lorenz-Punkte berechnen (Kumulativer Anteil)
    lorenz_y = np.cumsum(y) / np.sum(y)
    lorenz_x = np.arange(1, n + 1) / n
    
    # Nullpunkt (0,0) hinzufügen, damit die Kurve unten links im Ursprung startet
    lorenz_x = np.insert(lorenz_x, 0, 0)
    lorenz_y = np.insert(lorenz_y, 0, 0)
    
    return lorenz_x, lorenz_y, gini_coeff

# ==========================================
# HAUPT-ANALYSE (H2)
# ==========================================
def run_h2_lorenz_analysis():
    engine = create_engine(get_database_url())
    
    print("[+] Lade PAI-Daten aus der Datenbank (kachel_analytics)...")
    query = """
        SELECT kachel_id, bevoelkerungs_klasse, pai 
        FROM public.kachel_analytics 
        WHERE pai IS NOT NULL;
    """
    df = pd.read_sql_query(text(query), engine)
    
    if df.empty:
        print("[!] Keine Daten gefunden. Skript bricht ab.")
        return

    # Kategorien sortieren
    settlement_order = ["Ländliche Zone", "Aussenstädtische Zone", "Urbane Kernzone", "Metropolitane Kernzone"]
    df['bevoelkerungs_klasse'] = pd.Categorical(df['bevoelkerungs_klasse'], categories=settlement_order, ordered=True)
    df = df.dropna(subset=['bevoelkerungs_klasse']).sort_values('bevoelkerungs_klasse')

    # --- KONSOLE & PLOT SETUP ---
    print("[+] Generiere Lorenzkurven und Gini-Koeffizienten...")
    
    sns.set_theme(style="whitegrid")
    plt.figure(figsize=(10, 8))
    
    # Diagonale für perfekte Gleichverteilung einzeichnen
    plt.plot([0, 1], [0, 1], color='black', linestyle='--', linewidth=2, label='Perfekte Gleichverteilung (Gini = 0.00)')
    
    colors = sns.color_palette("Set1", len(settlement_order))
    
    print("\n" + "="*80)
    print("📊 GINI-KOEFFIZIENTEN DER TAKT-ASYMMETRIE (PAI)")
    print("="*80)

    # Für jede Zone die Kurve berechnen und plotten
    for idx, zone in enumerate(settlement_order):
        zone_data = df[df['bevoelkerungs_klasse'] == zone]['pai'].dropna().values
        
        if len(zone_data) > 0:
            x, y, gini = calculate_gini_and_lorenz(zone_data)
            
            # Ausgabe in die Konsole
            print(f"📍 {zone.upper():<25} | N = {len(zone_data):<4} | Gini-Koeffizient = {gini:.3f}")
            
            # Linie in den Plot einzeichnen
            plt.plot(x, y, color=colors[idx], linewidth=3, label=f'{zone} (Gini: {gini:.2f})')

    print("="*80 + "\n")

    # --- PLOT FORMATIERUNG ---
    plt.xlabel("Kumulativer Anteil der Kacheln", fontsize=12, labelpad=10)
    plt.ylabel("Kumulativer Anteil der PAI-Last", fontsize=12, labelpad=10)
    plt.title("H2: Lorenzkurve der Takt-Asymmetrie (Ungleichverteilung der Isolation)", fontsize=14, fontweight='bold', pad=20)
    
    plt.legend(loc="upper left", fontsize=11, framealpha=0.9, edgecolor='black')
    plt.xlim([0, 1.0])
    plt.ylim([0, 1.0])
    
    # Prozent-Formatierung für die Achsen (0.5 wird zu 50%)
    plt.gca().xaxis.set_major_formatter(plt.FuncFormatter(lambda val, pos: f"{int(val*100)}%"))
    plt.gca().yaxis.set_major_formatter(plt.FuncFormatter(lambda val, pos: f"{int(val*100)}%"))
    
    plt.tight_layout()
    output_path = "ergebnis_hypothese_2_lorenz.png"
    plt.savefig(output_path, dpi=300)
    print(f"[+] Lorenzkurve exportiert unter '{output_path}'.")

# Dieser Block hat gefehlt! Er sagt Python, dass die Funktion ausgeführt werden soll.
if __name__ == "__main__":
    run_h2_lorenz_analysis()