import os
import sys
from pathlib import Path
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import matplotlib.patches as mpatches
import scipy.stats as stats
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

def parse_and_sum_takt(takt_str):
    """Summiert die Fahrten aus dem komma-separierten 24h-Takt-String."""
    if pd.isna(takt_str) or not str(takt_str).strip(): return 0
    try: return sum(int(float(x.strip())) for x in str(takt_str).split(',') if x.strip() != '')
    except Exception: return 0

# ==========================================
# HAUPT-ANALYSE
# ==========================================
def generate_h1_combined_plot():
    url = get_database_url()
    engine = create_engine(url)

    print("[+] Lade Routing-Ergebnisse und Takt-Daten aus der Datenbank...")
    query = """
        SELECT 
            h1.*,
            a.takt_24h_di
        FROM public.kachel_routing_h1 h1
        JOIN public.kachel_analytics a ON h1.kachel_id = a.kachel_id;
    """
    df = pd.read_sql_query(text(query), engine)

    if df.empty:
        print("[!] Keine Daten gefunden.")
        return

    # --- 1. DATENVERARBEITUNG & INDEX-BERECHNUNG ---
    
    # A) Absolute Reisezeit (Fahrtzeit)
    df['zeit_abs_min'] = df[['zeit_morgens_min', 'zeit_mittags_min', 'zeit_abends_min']].mean(axis=1)

    # B) Fahrplanbedingte Anpassungszeit (Schedule Delay) für den Werktag
    OPERATING_MINUTES = 960.0 # 16 Stunden Betriebsfenster
    df['fahrten_di'] = df['takt_24h_di'].apply(parse_and_sum_takt)
    df['takt_intervall_di'] = OPERATING_MINUTES / df['fahrten_di'].replace(0, 0.5)
    df['anpassungszeit_min'] = df['takt_intervall_di'] / 2.0

    # C) Umstiegs-Malus (5 Minuten psychologische Strafzeit pro Umstieg)
    # Try-Catch Block für robuste Spaltenerkennung der Umstiege
    umstiege_cols = ['umstiege_morgens', 'umstiege_mittags', 'umstiege_abends']
    if all(col in df.columns for col in umstiege_cols):
        df['umstiege_avg'] = df[umstiege_cols].mean(axis=1)
    else:
        # Fallback: Suche alle Spalten, die 'umstieg' im Namen haben
        fallback_cols = [c for c in df.columns if 'umstieg' in c.lower()]
        df['umstiege_avg'] = df[fallback_cols].mean(axis=1) if fallback_cols else 0

    UMSTIEG_MALUS_MIN = 5.0
    df['umstiege_malus_min'] = df['umstiege_avg'] * UMSTIEG_MALUS_MIN

    # D) Gesamtaufwand = Reine Fahrtzeit + Anpassungszeit + Umstiegs-Malus
    df['gesamtaufwand_min'] = df['zeit_abs_min'] + df['anpassungszeit_min'] + df['umstiege_malus_min']

    # E) Erweiterter Effizienz-Index (Gesamtaufwand pro Kilometer)
    df['effizienz_index_erweitert'] = df['gesamtaufwand_min'] / (df['distanz_luftlinie_km'].replace(0, 0.1))

    # --- 2. FILTERN & BEREINIGEN ---
    ignored_urban_ids = {29, 148, 266, 253, 324, 327, 340, 147}
    df = df[~((df['bevoelkerungs_klasse'].isin(["Urbane Kernzone", "Metropolitane Kernzone"])) & (df['kachel_id'].isin(ignored_urban_ids)))]
    
    rural_classes = ["Ländliche Zone", "Aussenstädtische Zone"]
    df = df[~((df['bevoelkerungs_klasse'].isin(rural_classes)) & (df['distanz_luftlinie_km'] > 30.0))]
    
    # Ausreißer-Glättung über den neuen Index
    q_high = df['effizienz_index_erweitert'].quantile(0.95)
    df_filtered = df[df['effizienz_index_erweitert'] <= q_high].copy()

    settlement_order = ["Ländliche Zone", "Aussenstädtische Zone", "Urbane Kernzone", "Metropolitane Kernzone"]
    df_filtered['bevoelkerungs_klasse'] = pd.Categorical(df_filtered['bevoelkerungs_klasse'], categories=settlement_order, ordered=True)
    df_filtered = df_filtered.dropna(subset=['bevoelkerungs_klasse']).sort_values('bevoelkerungs_klasse')

    # --- 3. OUTPUT KONSOLE (DESKRIPTIV) ---
    print("\n" + "="*80)
    print("📊 FINALE STATISTIKEN (INKL. TAKTUNG & UMSTIEGE)")
    print("="*80)
    
    for zone in settlement_order:
        zone_data = df_filtered[df_filtered['bevoelkerungs_klasse'] == zone]
        if not zone_data.empty:
            unique_kacheln = zone_data['kachel_id'].nunique()
            print(f"\n📍 ZONE: {zone.upper()}")
            print(f"  ----------------------------------------------------------------------")
            print(f"  • Analysierte Kacheln               : {unique_kacheln}")
            print(f"  • MEDIAN NEUER EFFIZIENZ-INDEX      : {zone_data['effizienz_index_erweitert'].median():.2f} Min/km")
            print(f"  • Ø Gesamter Zeitaufwand            : {zone_data['gesamtaufwand_min'].mean():.2f} Minuten")
            print(f"    - Davon Ø reine Fahrtzeit         : {zone_data['zeit_abs_min'].mean():.2f} Minuten")
            print(f"    - Davon Ø Anpassungszeit (Takt)   : {zone_data['anpassungszeit_min'].mean():.2f} Minuten")
            print(f"    - Davon Ø Umstiegs-Malus          : {zone_data['umstiege_malus_min'].mean():.2f} Minuten")
            print(f"  • Ø Physische Entfernung            : {zone_data['distanz_luftlinie_km'].mean():.2f} km")

    # --- 4. SIGNIFIKANZTEST (KRUSKAL-WALLIS) ---
    print("\n" + "="*80)
    print("🔬 INFERENZSTATISTIK (KRUSKAL-WALLIS-TEST)")
    print("="*80)

    groups = []
    for zone in settlement_order:
        zone_data = df_filtered[df_filtered['bevoelkerungs_klasse'] == zone]['effizienz_index_erweitert'].dropna().values
        if len(zone_data) > 0:
            groups.append(zone_data)

    if len(groups) >= 2:
        h_stat, p_val = stats.kruskal(*groups)
        print(f"\n  • Kruskal-Wallis H-Statistik : {h_stat:.4f}")
        print(f"  • p-Wert                     : {p_val:.6f}")
        print(f"  • Freiheitsgrade (df)        : {len(groups) - 1}")
        
        if p_val < 0.05:
            print("\n  => ERGEBNIS: p < 0.05 (Signifikant). Die Nullhypothese wird verworfen.")
        else:
            print("\n  => ERGEBNIS: p >= 0.05 (Nicht signifikant). Die Nullhypothese wird beibehalten.")
    else:
        print("\n  [!] Nicht genügend Gruppen für einen Signifikanztest vorhanden.")
    print("\n" + "="*80 + "\n")

    # --- 5. VISUALISIERUNG (KOMBI-GRAPH) ---
    print("[+] Generiere Kombi-Graph mit finalem Index...")

    sns.set_theme(style="whitegrid")
    fig, ax1 = plt.subplots(figsize=(11, 6))

    color_box = sns.color_palette('Set2')[0] # Mintgrün
    box_data = [df_filtered[df_filtered['bevoelkerungs_klasse'] == zone]['effizienz_index_erweitert'].values for zone in settlement_order]
    
    bp = ax1.boxplot(
        box_data, 
        positions=range(len(settlement_order)), 
        widths=0.4, 
        patch_artist=True, 
        showfliers=False, 
        medianprops=dict(color="red", linewidth=2.0) 
    )
    
    for patch in bp['boxes']:
        patch.set_facecolor(color_box)
        patch.set_alpha(0.75)
        patch.set_edgecolor('#4d4d4d')

    ax1.set_xlabel("Siedlungsstruktur / Bevölkerungsklasse", fontsize=11, labelpad=10)
    # NEUES LABEL FÜR DIE LINKE ACHSE
    ax1.set_ylabel("Effizienz-Index in Minuten pro Kilometer\n(unter Berücksichtigung von Umstiegen und Taktung)", color='#333333', fontsize=11, labelpad=10)
    ax1.set_xticklabels(settlement_order)
    ax1.set_xlim(-0.5, len(settlement_order) - 0.5)

    ax2 = ax1.twinx()
    line_data = df_filtered.groupby('bevoelkerungs_klasse', observed=True)['gesamtaufwand_min'].mean().reindex(settlement_order)
    
    color_line = sns.color_palette('Set2')[2] # Blau
    
    ax2.plot(
        range(len(settlement_order)), 
        line_data.values, 
        color=color_line, 
        marker='o', 
        linewidth=2.5, 
        markersize=8,
        label="Ø Absolute Reisezeit"
    )
    # NEUES LABEL FÜR DIE RECHTE ACHSE
    ax2.set_ylabel("Absolute Reisezeit in Minuten", color=color_line, fontsize=11, labelpad=10)
    ax2.tick_params(axis='y', labelcolor=color_line)
    ax2.grid(False)

    # NEUER TITEL
    plt.title("H1: Reisezeit pro Strecke zu zentraler Infrastruktur", fontsize=13, pad=15, fontweight='bold')
    plt.tight_layout()
    
    output_path = "ergebnis_hypothese_1_final.png"
    plt.savefig(output_path, dpi=300)
    plt.close()
    print(f"[+] Finaler Graph exportiert unter '{output_path}'.")

if __name__ == "__main__":
    generate_h1_combined_plot()