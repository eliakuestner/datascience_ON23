import os
import sys
from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import matplotlib.patches as mpatches
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

def generate_h1_combined_plot():
    url = get_database_url()
    engine = create_engine(url)

    print("[+] Lade Routing-Ergebnisse aus der Datenbank...")
    query = "SELECT * FROM public.kachel_routing_h1;"
    df = pd.read_sql_query(text(query), engine)

    if df.empty:
        print("[!] Keine Daten in kachel_routing_h1 gefunden.")
        return

    # 1. Absolute Reisezeit pro Zeile berechnen (Mittelwert über den Tag)
    df['zeit_abs_min'] = df[['zeit_morgens_min', 'zeit_mittags_min', 'zeit_abends_min']].mean(axis=1)

    # 2. Effizienz-Index auf POI-Ebene berechnen (Varianz für den Boxplot)
    df['effizienz_index'] = df['zeit_abs_min'] / (df['distanz_luftlinie_km'].replace(0, 0.1))

    # ========================================================================
    # STRATEGISCHE FILTER (Grenzartefakte & Ausreißer)
    # ========================================================================
    ignored_urban_ids = {29, 148, 266, 253, 324, 327, 340, 147}
    df = df[~((df['bevoelkerungs_klasse'].isin(["Urbane Kernzone", "Metropolitane Kernzone"])) & (df['kachel_id'].isin(ignored_urban_ids)))]
    
    rural_classes = ["Ländliche Zone", "Aussenstädtische Zone"]
    df = df[~((df['bevoelkerungs_klasse'].isin(rural_classes)) & (df['distanz_luftlinie_km'] > 30.0))]
    
    q_high = df['effizienz_index'].quantile(0.95)
    df_filtered = df[df['effizienz_index'] < q_high].copy()

    settlement_order = ["Ländliche Zone", "Aussenstädtische Zone", "Urbane Kernzone", "Metropolitane Kernzone"]
    df_filtered['bevoelkerungs_klasse'] = pd.Categorical(df_filtered['bevoelkerungs_klasse'], categories=settlement_order, ordered=True)
    df_filtered = df_filtered.dropna(subset=['bevoelkerungs_klasse']).sort_values('bevoelkerungs_klasse')

    # ========================================================================
    # 📋 STATISTISCHER OUTPUT (Konsolen-Ausgabe)
    # ========================================================================
    print("\n" + "="*80)
    print("📊 REALE STATISTIKEN (KONTRASTREICHE VISUALISIERUNG)")
    print("="*80)
    
    for zone in settlement_order:
        zone_data = df_filtered[df_filtered['bevoelkerungs_klasse'] == zone]
        if not zone_data.empty:
            unique_kacheln = zone_data['kachel_id'].nunique()
            print(f"\n📍 ZONE: {zone.upper()}")
            print(f"  ----------------------------------------------------------------------")
            print(f"  • Analysierte Kacheln in dieser Zone: {unique_kacheln}")
            print(f"  • Einzelne Datenpunkte für Boxplot : {len(zone_data)}")
            print(f"  • MEDIAN EFFIZIENZ-INDEX (Rot)     : {zone_data['effizienz_index'].median():.4f} Min/km")
            print(f"  • Ø Absolute Reisezeit (Blau)      : {zone_data['zeit_abs_min'].mean():.2f} Minuten")
            print(f"  • Ø Physische Entfernung           : {zone_data['distanz_luftlinie_km'].mean():.2f} km")
    print("\n" + "="*80 + "\n")

    print("[+] Generiere Kombi-Graph mit optimierter Farb-Trennung...")

    sns.set_theme(style="whitegrid")
    fig, ax1 = plt.subplots(figsize=(11, 6))

    color_box = sns.color_palette('Set2')[0] # Mintgrün
    box_data = [df_filtered[df_filtered['bevoelkerungs_klasse'] == zone]['effizienz_index'].values for zone in settlement_order]
    
    bp = ax1.boxplot(
        box_data, 
        positions=range(len(settlement_order)), 
        widths=0.4, 
        patch_artist=True, 
        showfliers=False, 
        medianprops=dict(color="red", linewidth=2.0) # Bleibt knallrot
    )
    
    for patch in bp['boxes']:
        patch.set_facecolor(color_box)
        patch.set_alpha(0.75)
        patch.set_edgecolor('#4d4d4d')

    ax1.set_xlabel("Siedlungsstruktur / Bevölkerungsklasse", fontsize=11, labelpad=10)
    ax1.set_ylabel("Effizienz-Index (Reisezeit in Min. pro km Luftlinie)", color='#333333', fontsize=11, labelpad=10)
    ax1.set_xticklabels(settlement_order)
    ax1.set_xlim(-0.5, len(settlement_order) - 0.5)

    # --- RECHTE ACHSE: Farbe zu Blau geändert für besseren Kontrast zu den Medianen ---
    ax2 = ax1.twinx()
    line_data = df_filtered.groupby('bevoelkerungs_klasse', observed=True)['zeit_abs_min'].mean().reindex(settlement_order)
    
    color_line = sns.color_palette('Set2')[2] # Blau aus Set2 Palette
    
    ax2.plot(
        range(len(settlement_order)), 
        line_data.values, 
        color=color_line, 
        marker='o', 
        linewidth=2.5, 
        markersize=8,
        label="Ø Absolute Reisezeit"
    )
    ax2.set_ylabel("Ø Tatsächliche Reisezeit (in Minuten)", color=color_line, fontsize=11, labelpad=10)
    ax2.tick_params(axis='y', labelcolor=color_line)
    ax2.grid(False)

    plt.title("Daseinsvorsorge: ÖPNV-Effizienz vs. Absolute Reisezeit (Hypothese 1 - Final)", fontsize=13, pad=15, fontweight='bold')
    plt.tight_layout()
    
    output_path = "ergebnis_hypothese_1_kombiniert.png"
    plt.savefig(output_path, dpi=300)
    plt.close()
    print(f"[+] Finaler Kombi-Graph mit blauem Linien-Kontrast unter '{output_path}' exportiert.")

if __name__ == "__main__":
    generate_h1_combined_plot()