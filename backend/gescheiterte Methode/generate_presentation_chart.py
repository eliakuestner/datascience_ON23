import os
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
import pandas as pd
import seaborn as sns
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from scipy.stats import kruskal

# 1. Umgebung und Datenbankverbindung laden
load_dotenv()


def get_database_url() -> str:
    user = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD")
    host = os.getenv("DB_HOST")
    port = os.getenv("DB_PORT")
    name = os.getenv("DB_NAME")
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{name}"


# Engine initialisieren
engine = create_engine(get_database_url())

# 2. Daten abfragen (Nur Kacheln mit Einwohnern und berechnetem PAI)
query = """
    SELECT bevoelkerungs_klasse, pai, einwohner 
    FROM public.kachel_analytics 
    WHERE einwohner > 0 AND pai IS NOT NULL;
"""

with engine.connect() as conn:
    df = pd.read_sql_query(text(query), conn)

# 3. Wissenschaftliche Sortierung (X-Achse) - Exakt wie in deiner DB hinterlegt
klassen_reihenfolge = [
    "Ländliche Zone",
    "Aussenstädtische Zone",
    "Urbane Kernzone",
    "Metropolitane Kernzone",
]

# Filtern auf die korrekten Klassenbezeichnungen aus der DB
df = df[df["bevoelkerungs_klasse"].isin(klassen_reihenfolge)]

# 4. Styling für die wissenschaftliche Präsentation (Modern Minimalist)
plt.figure(figsize=(10, 6), dpi=300)
sns.set_theme(style="whitegrid")

# Farbpalette für die Boxen
palette = ["#f2a6a6", "#ffd1b3", "#d1ffd1", "#b3f0c2"]

# Boxplot zeichnen (Statistische Verteilung)
ax = sns.boxplot(
    x="bevoelkerungs_klasse",
    y="pai",
    data=df,
    order=klassen_reihenfolge,
    width=0.5,
    palette=palette,
    linewidth=1.5,
    fliersize=0,
    medianprops={"color": "#E3000B", "linewidth": 2.5},
)

# Stripplot überlagern
sns.stripplot(
    x="bevoelkerungs_klasse",
    y="pai",
    data=df,
    order=klassen_reihenfolge,
    color="#2d3748",
    size=3,
    alpha=0.4,
    jitter=0.2,
)

# 5. Achsenbeschriftungen und Typografie
plt.title(
    "Empirischer Nachweis der Takt-Asymmetrie nach Siedlungsstruktur",
    fontsize=14,
    fontweight="bold",
    pad=20,
    color="#1a1a1a",
)
plt.xlabel("Zensus Bevölkerungsdichteklasse", fontsize=11, fontweight="semibold", labelpad=10)
plt.ylabel(
    "Pendlerzeiten-Abhängigkeitsindex (PAI)\n[Peak: 6:30-8:30 & 16:00-18:30 | Off-Peak: 9:00-16:00]",
    fontsize=11,
    fontweight="semibold",
    labelpad=10,
)

# Y-Achsen-Prozentformatierung ohne Warnungen
ax.set_ylim(-0.05, 1.05)
ax.yaxis.set_major_formatter(mtick.PercentFormatter(1.0))

plt.tight_layout()

# Grafik speichern
output_path = "PAI_Siedlungsstruktur_Beweis.png"
plt.savefig(output_path, bbox_inches="tight")
print(f"📊 Präsentationsgrafik erfolgreich unter '{output_path}' generiert!")

# ==============================================================================
# --- STATISTISCHER SIGNIFIKANZTEST & LIVE-MEDIAN-BERECHNUNG ---
# ==============================================================================
print("\n--- Führe Kruskal-Wallis-Test mit korrigierten Fenstern durch ---")

# Aufteilen der PAI-Werte nach den 4 Klassen
g1 = df[df['bevoelkerungs_klasse'] == 'Ländliche Zone']['pai']
g2 = df[df['bevoelkerungs_klasse'] == 'Aussenstädtische Zone']['pai']
g3 = df[df['bevoelkerungs_klasse'] == 'Urbane Kernzone']['pai']
g4 = df[df['bevoelkerungs_klasse'] == 'Metropolitane Kernzone']['pai']

# Live-Ausgabe der exakten Gruppengrößen und der REALEN MEDIANE aus deiner DB
print(f"Datensätze in 'Ländliche Zone': {len(g1)} | Echter Median (PAI): {g1.median():.4f} ({g1.median()*100:.2f}%)")
print(f"Datensätze in 'Aussenstädtische Zone': {len(g2)} | Echter Median (PAI): {g2.median():.4f} ({g2.median()*100:.2f}%)")
print(f"Datensätze in 'Urbane Kernzone': {len(g3)} | Echter Median (PAI): {g3.median():.4f} ({g3.median()*100:.2f}%)")
print(f"Datensätze in 'Metropolitane Kernzone': {len(g4)} | Echter Median (PAI): {g4.median():.4f} ({g4.median()*100:.2f}%)")

# Test berechnen
if len(g1) > 0 and len(g2) > 0 and len(g3) > 0 and len(g4) > 0:
    stat, p_val = kruskal(g1, g2, g3, g4)
    print(f"\n-> Kruskal-Wallis-Statistik (H-Wert): {stat:.4f}")
    print(f"-> p-Wert: {p_val:.6f}")
    
    if p_val < 0.05:
        print("Ergebnis: STATISTISCH SIGNIFIKANT (p < 0.05). Die Verteilungen der Gruppen unterscheiden sich systematisch.")
    else:
        print("Ergebnis: NICHT SIGNIFIKANT (p >= 0.05). Es kann kein systematischer Unterschied mathematisch bewiesen werden.")
else:
    print("\n❌ Fehler: Eine oder mehrere Bevölkerungsklassen enthalten 0 Datensätze.")