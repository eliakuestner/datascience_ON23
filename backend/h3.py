import os
from pathlib import Path
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from matplotlib.ticker import FuncFormatter
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
# HILFSFUNKTIONEN
# ==========================================
def parse_and_sum_takt(takt_str):
    """Summiert die Fahrten aus dem komma-separierten 24h-Takt-String."""
    if pd.isna(takt_str) or not str(takt_str).strip(): return 0
    try: return sum(int(float(x.strip())) for x in str(takt_str).split(',') if x.strip() != '')
    except Exception: return 0

def parse_time_to_float(time_str):
    """Wandelt HH:MM in Dezimalstunden um. Zeiten nach Mitternacht werden 24+"""
    if pd.isna(time_str) or not str(time_str).strip(): return np.nan
    try:
        h_str, m_str = str(time_str).split(':')
        h, m = int(h_str), int(m_str)
        # Alles zwischen 00:00 und 04:59 wird als Nachtschicht zum Vortag addiert (24+)
        if h < 5:
            h += 24
        return h + (m / 60.0)
    except Exception:
        return np.nan

def format_time_label(x, pos):
    """Macht aus 25.5 wieder '01:30 Uhr' für die Achsenbeschriftung"""
    h = int(x) % 24
    m = int(round((x - int(x)) * 60))
    if m == 60:
        h = (h + 1) % 24
        m = 0
    return f"{h:02d}:{m:02d} Uhr"

# ==========================================
# HAUPT-ANALYSE
# ==========================================
def run_curfew_rwi_analysis():
    engine = create_engine(get_database_url())

    print("[+] Lade und verknüpfe H3-Daten inkl. Curfew-Zeiten...")
    query = """
        SELECT 
            h3.kachel_id, h3.poi_typ, h3.bevoelkerungs_klasse, h3.distanz_luftlinie_km,
            h3.zeit_di_mittags_min, h3.zeit_di_abends_min,
            h3.zeit_sa_mittags_min, h3.zeit_sa_abends_min,
            h3.zeit_so_mittags_min, h3.zeit_so_abends_min,
            h3.umstiege_di_mi, h3.umstiege_di_ab,
            h3.umstiege_sa_mi, h3.umstiege_sa_ab,
            h3.umstiege_so_mi, h3.umstiege_so_ab,
            h3.heimfahrt_spateste,
            a.takt_24h_di, a.takt_24h_sa, a.takt_24h_so
        FROM public.kachel_routing_h3 h3
        JOIN public.kachel_analytics a ON h3.kachel_id = a.kachel_id;
    """
    df = pd.read_sql_query(text(query), engine)

    if df.empty: 
        print("[!] Keine Daten gefunden. Skript bricht ab.")
        return

    # --- 1. GRUNDLAGEN AGGREGIEREN & CURFEW PARSEN ---
    df['fahrten_di'] = df['takt_24h_di'].apply(parse_and_sum_takt)
    df['fahrten_we_avg'] = (df['takt_24h_sa'].apply(parse_and_sum_takt) + df['takt_24h_so'].apply(parse_and_sum_takt)) / 2.0

    df['zeit_di_avg'] = df[['zeit_di_mittags_min', 'zeit_di_abends_min']].mean(axis=1)
    df['zeit_we_avg'] = df[['zeit_sa_mittags_min', 'zeit_sa_abends_min', 'zeit_so_mittags_min', 'zeit_so_abends_min']].mean(axis=1)
    
    df['umstiege_di_avg'] = df[['umstiege_di_mi', 'umstiege_di_ab']].mean(axis=1)
    df['umstiege_we_avg'] = df[['umstiege_sa_mi', 'umstiege_sa_ab', 'umstiege_so_mi', 'umstiege_so_ab']].mean(axis=1)

    df['curfew_float'] = df['heimfahrt_spateste'].apply(parse_time_to_float)

    # --- 2. UMWANDLUNG IN MINUTEN (RWI) ---
    OPERATING_MINUTES = 960.0  # 16 Stunden Freizeit-Fenster
    UMSTIEG_MALUS_MIN = 5.0    # 5 Min psychologischer Widerstand pro Umstieg

    df['takt_intervall_di'] = OPERATING_MINUTES / df['fahrten_di'].replace(0, 0.5)
    df['takt_intervall_we'] = OPERATING_MINUTES / df['fahrten_we_avg'].replace(0, 0.5)
    
    # Die verdeckte Anpassungszeit ist die Hälfte des Taktintervalls
    df['delta_anpassungszeit'] = (df['takt_intervall_we'] / 2.0) - (df['takt_intervall_di'] / 2.0)
    df['delta_fahrtzeit'] = df['zeit_we_avg'] - df['zeit_di_avg']
    df['delta_umstiege_min'] = (df['umstiege_we_avg'] - df['umstiege_di_avg']) * UMSTIEG_MALUS_MIN
    
    # Der Gesamte Reisewiderstand
    df['rwi_minuten'] = df['delta_fahrtzeit'] + df['delta_anpassungszeit'] + df['delta_umstiege_min']

    df = df.dropna(subset=['rwi_minuten'])

    # --- 3. FILTERN & BEREINIGEN ---
    ignored_urban_ids = {29, 148, 266, 253, 324, 327, 340, 147}
    df = df[~((df['bevoelkerungs_klasse'].isin(["Urbane Kernzone", "Metropolitane Kernzone"])) & (df['kachel_id'].isin(ignored_urban_ids)))]
    
    rural_classes = ["Ländliche Zone", "Aussenstädtische Zone"]
    df = df[~((df['bevoelkerungs_klasse'].isin(rural_classes)) & (df['distanz_luftlinie_km'] > 30.0))]
    
    q_high = df['rwi_minuten'].quantile(0.95)
    df_filtered = df[df['rwi_minuten'] <= q_high].copy()

    settlement_order = ["Ländliche Zone", "Aussenstädtische Zone", "Urbane Kernzone", "Metropolitane Kernzone"]
    df_filtered['bevoelkerungs_klasse'] = pd.Categorical(df_filtered['bevoelkerungs_klasse'], categories=settlement_order, ordered=True)
    df_filtered = df_filtered.sort_values('bevoelkerungs_klasse')

    # --- 4. BERECHNUNG DER MITTELWERTE ---
    df_plot = df_filtered.groupby('bevoelkerungs_klasse', observed=True).agg({
        'rwi_minuten': 'mean',
        'delta_anpassungszeit': lambda x: np.mean(np.maximum(x, 0)),
        'delta_fahrtzeit': lambda x: np.mean(np.maximum(x, 0)),
        'delta_umstiege_min': lambda x: np.mean(np.maximum(x, 0)),
        'curfew_float': 'mean' 
    }).reindex(settlement_order)

    # --- 5. OUTPUT KONSOLE ---
    print("\n" + "="*80)
    print("📊 TRANSPARENTER RWI-INDEX INKLUSIVE CURFEW (MITTELWERTE)")
    print("="*80)
    
    for zone in settlement_order:
        curfew_val = df_plot.loc[zone, 'curfew_float']
        curfew_str = format_time_label(curfew_val, None) if pd.notna(curfew_val) else "N/A"

        print(f"\n📍 {zone.upper()}")
        print(f"  • Ø Gesamter Zeitverlust (RWI)      : +{df_plot.loc[zone, 'rwi_minuten']:.1f} Minuten")
        print(f"    - Durch fahrplanb. Anpassungszeit : +{df_plot.loc[zone, 'delta_anpassungszeit']:.1f} Min")
        print(f"  • 🕒 Ø Späteste Heimfahrt am So.    : {curfew_str}")
    print("\n" + "="*80 + "\n")

    # ========================================================================
    # 🎨 ERSTELLUNG DER GRAFIK
    # ========================================================================
    print("[+] Generiere Kombi-Graph...")
    sns.set_theme(style="whitegrid")
    
    # Standard Layout-Größe (kein extra Platz rechts mehr nötig)
    fig, ax1 = plt.subplots(figsize=(11, 7))

    # Die gestapelten Balken (Reisewiderstand) - zorder=3 bringt sie VOR das Grid
    df_plot[['delta_anpassungszeit', 'delta_fahrtzeit', 'delta_umstiege_min']].plot(
        kind='bar', 
        stacked=True, 
        ax=ax1,
        color=['#FF6B6B', '#4ECDC4', '#45B7D1'], 
        edgecolor='black',
        width=0.6,
        legend=False,
        zorder=3 
    )

    # Grid der linken Achse explizit nach hinten schieben
    ax1.grid(axis='y', zorder=0)
    ax1.set_axisbelow(True)

    ax1.set_xlabel("Siedlungsstruktur / Bevölkerungsklasse", fontsize=11, labelpad=10)
    ax1.set_xticklabels(settlement_order, rotation=0, fontsize=11)
    ax1.set_ylabel("Ø Zusätzlicher Reisewiderstand am Wochenende (in Minuten)", fontsize=11, labelpad=10)
    
    # Zweite Achse für die Curfew-Linie
    ax2 = ax1.twinx()
    
    # Z-Order-Management: Rechte Achse über die linke legen, aber ihr Grid abschalten!
    ax2.set_zorder(ax1.get_zorder() + 1)
    ax1.patch.set_visible(False) 
    ax2.grid(False) 

    # Farbe für Linie und Achse (Gold-Orange)
    curfew_color = '#d35400' 

    x_positions = range(len(settlement_order))
    
    # Linie zeichnen
    line_plot = ax2.plot(
        x_positions, 
        df_plot['curfew_float'], 
        color=curfew_color, 
        linewidth=3, 
        marker='o', 
        markersize=10, 
        label="Ø Späteste Rückfahrt",
        zorder=5 
    )

    ax2.set_ylabel("Ø Späteste Verbindungszeit (Curfew)", fontsize=11, labelpad=10, color=curfew_color, fontweight='bold')
    
    # Achsen-Formatierer anwenden (Macht aus 25.5 -> 01:30 Uhr)
    ax2.yaxis.set_major_formatter(FuncFormatter(format_time_label))
    ax2.tick_params(axis='y', colors=curfew_color)

    # Achsen-Limits leicht puffern
    min_curfew = df_plot['curfew_float'].min() - 1
    max_curfew = df_plot['curfew_float'].max() + 1
    ax2.set_ylim([min_curfew, max_curfew])

    # Gemeinsame Legende INNERHALB des Plots rechts platzieren
    bars_handles, bars_labels = ax1.get_legend_handles_labels()
    line_handle, line_label = ax2.get_legend_handles_labels()
    
    ax1.legend(
        bars_handles + line_handle, 
        ["Taktverlust (Anpassungszeit)", "Reisezeit-Verlängerung", "Umstiegs-Zuwachs", "Ø Späteste Rückfahrt"],
        loc='center right', # Platziert die Legende rechtsbündig innerhalb der Achsen
        ncol=1, 
        framealpha=0.95,
        edgecolor='black'
    )

    plt.title("Freizeit-Infrastruktur: Reisewiderstand vs. Betriebsschluss am Wochenende (H3)", fontsize=13, pad=20, fontweight='bold')
    
    plt.tight_layout()
    output_path = "ergebnis_hypothese_3_stacked_curfew.png"
    plt.savefig(output_path, dpi=300)
    print(f"\n[+] Bereinigtes Diagramm inkl. Layout-Fix exportiert unter '{output_path}'")

if __name__ == "__main__":
    run_curfew_rwi_analysis()