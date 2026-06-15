import os
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

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

# 3. Wissenschaftliche Sortierung der X-Achsen-Klassen festlegen
# Passen Sie die Strings exakt an Ihre Bezeichnungen in der DB an
klassen_reihenfolge = [
    "Ländliche Zone",
    "Aussenstädtische Zone",
    "Urbane Kernzone",
    "Metropolitane Kernzone",
]

# Filtern, falls unerwartete Klassenbezeichnungen existieren
df = df[df["bevoelkerungs_klasse"].isin(klassen_reihenfolge)]

# 4. Styling für die wissenschaftliche Präsentation (Modern Minimalist)
plt.figure(figsize=(10, 6), dpi=300)
sns.set_theme(style="whitegrid")

# KVV-Rot als Akzentfarbe für den Median, gedämpftes Blaugrau für die Boxen
palette = ["#f2a6a6", "#ffd1b3", "#d1ffd1", "#b3f0c2"]

# Boxplot zeichnen (Verteilung)
ax = sns.boxplot(
    x="bevoelkerungs_klasse",
    y="pai",
    data=df,
    order=klassen_reihenfolge,
    width=0.5,
    palette=palette,
    linewidth=1.5,
    fliersize=0,  # Ausreißer-Punkte ausblenden, da wir alle Einzelpunkte zeichnen
    medianprops={"color": "#E3000B", "linewidth": 2.5},  # KVV-Rot für den Median
)

# Stripplot überlagern (Zeigt jede einzelne Kachel als kleinen Punkt)
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

# 5. Achsenbeschriftungen und typografische Hierarchie (Titillium Web-Ästhetik)
plt.title(
    "Empirischer Nachweis der Takt-Asymmetrie nach Siedlungsstruktur",
    fontsize=14,
    fontweight="bold",
    pad=20,
    color="#1a1a1a",
)
plt.xlabel("Zensus Bevölkerungsdichteklasse", fontsize=11, fontweight="semibold", labelpad=10)
plt.ylabel(
    "Pendlerzeiten-Abhängigkeitsindex (PAI)\n[0.0 = Homogen | 1.0 = Maximaler Einbruch im Off-Peak]",
    fontsize=11,
    fontweight="semibold",
    labelpad=10,
)

# Y-Achse auf Prozent-Skala anpassen (0% bis 100%)
ax.set_ylim(-0.05, 1.05)
vals = ax.get_yticks()
ax.set_yticklabels(["{:,.0%}".format(x) for x in vals])

# Layout-Anpassung, um Abschneiden zu verhindern
plt.tight_layout()

# Grafik als PNG für die Präsentation abspeichern
output_path = "PAI_Siedlungsstruktur_Beweis.png"
plt.savefig(output_path, bbox_inches="tight")
print(
    f"📊 Präsentationsgrafik erfolgreich unter '{output_path}' generiert!"
)