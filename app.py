import streamlit as st
import pandas as pd
import os, tempfile, csv
from datetime import datetime
import matplotlib.pyplot as plt

from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, PageBreak
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm

# ======================================================
# CONFIG
# ======================================================
st.set_page_config("Fantrax Ultimate", layout="wide")

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

PLAFOND_GRAND_CLUB = 95_500_000
PLAFOND_CLUB_ECOLE = 47_750_000

# ======================================================
# SAISON
# ======================================================
def saison_par_defaut():
    now = datetime.now()
    return f"{now.year}-{now.year+1}" if now.month >= 9 else f"{now.year-1}-{now.year}"

def season_file(season):
    return f"{DATA_DIR}/fantrax_{season}.csv"

# ======================================================
# PARSER FANTRAX — AUTO FORMAT (LA CLE)
# ======================================================
def parse_fantrax_file(uploaded_file):
    text = uploaded_file.read().decode("utf-8", errors="ignore")
    lines = [l for l in text.splitlines() if l.strip()]

    if not lines:
        raise ValueError("Fichier vide")

    # on teste les séparateurs possibles Fantrax
    for sep in ["\t", ",", ";"]:
        reader = csv.reader(lines, delimiter=sep)
        rows = list(reader)

        header_idx = None
        for i, row in enumerate(rows):
            if "Player" in row and "Salary" in row:
                header_idx = i
                header = row
                break

        if header_idx is None:
            continue  # mauvais séparateur

        idx = {name: header.index(name) for name in header}

        joueurs = []
        for r in rows[header_idx + 1:]:
            if len(r) <= max(idx.values()):
                continue
            if not r[idx["Player"]].strip():
                continue

            try:
                salaire = float(
                    r[idx["Salary"]]
                    .replace(",", "")
                    .replace("$", "")
                    .strip()
                ) * 1000
            except:
                salaire = 0

            joueurs.append({
                "Joueur": r[idx["Player"]],
                "Salaire": salaire,
                "Pos": r[idx["Pos"]] if "Pos" in idx else "N/A",
                "Statut": (
                    "Club École"
                    if "min" in r[idx.get("Status", "")].lower()
                    else "Grand Club"
                )
            })

        if joueurs:
            return pd.DataFrame(joueurs)

    # si aucun séparateur ne fonctionne
    raise ValueError("Format Fantrax non reconnu (séparateur inconnu)")

# ======================================================
# PLAFOND SALARIAL
# ======================================================
def controle_plafond(df):
    cols = ["Propriétaire", "GC", "CE", "RGC", "RCE"]
    if df.empty:
        return pd.DataFrame(columns=cols)

    rows = []
    for gm in df["Propriétaire"].unique():
        d = df[df["Propriétaire"] == gm]
        gc = d[d["Statut"] == "Grand Club"]["Salaire"].sum()
        ce = d[d["Statut"] == "Club École"]["Salaire"].sum()
        rows.append({
            "Propriétaire": gm,
            "GC": gc,
            "CE": ce,
            "RGC": PLAFOND_GRAND_CLUB - gc,
            "RCE": PLAFOND_CLUB_ECOLE - ce
        })
    return pd.DataFrame(rows, columns=cols)

# ======================================================
# IA
# ======================================================
def ia_reco(df):
    recos = []
    plaf = controle_plafond(df)
    for _, r in plaf.iterrows():
        if r["RGC"] < 0:
            top = df[
                (df["Propriétaire"] == r["Propriétaire"]) &
                (df["Statut"] == "Grand Club")
            ].sort_values("Salaire", ascending=False).head(2)
            for _, j in top.iterrows():
                recos.append(
                    f"{r['Propriétaire']} : rétrograder {j['Joueur']} ({int(j['Salaire']):,}$)"
                )
    return recos

# ======================================================
# PDF
# ======================================================
def export_pdf(season, df):
    styles = getSampleStyleSheet()
    elements = [Paragraph(f"<b>Rapport Fantrax – Saison {season}</b>", styles["Title"])]

    plaf = controle_plafond(df)
    table_data = [["GM", "GC", "RGC", "CE", "RCE"]]

    for _, r in plaf.iterrows():
        table_data.append([
            r["Propriétaire"],
            f"{int(r['GC']):,}$",
            f"{int(r['RGC']):,}$",
            f"{int(r['CE']):,}$",
            f"{int(r['RCE']):,}$"
        ])

    table = Table(table_data, colWidths=[4*cm]*5)
    table.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),colors.darkblue),
        ("TEXTCOLOR",(0,0),(-1,0),colors.white),
        ("GRID",(0,0),(-1,-1),0.5,colors.grey)
    ]))

    elements.append(table)
    elements.append(PageBreak())
    elements.append(Paragraph("<b>Recommandations IA</b>", styles["Heading2"]))

    for r in ia_reco(df):
        elements.append(Paragraph(r, styles["Normal"]))

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    SimpleDocTemplate(tmp.name, pagesize=A4).build(elements)
    return tmp.name

# ======================================================
# UI
# ======================================================
st.title("🏒 Fantrax – Gestion Salariale Ultimate")

season = saison_par_defaut()
DATA_FILE = season_file(season)

if os.path.exists(DATA_FILE):
    data = pd.read_csv(DATA_FILE)
else:
    data = pd.DataFrame(columns=["Propriétaire", "Joueur", "Salaire", "Statut", "Pos"])

uploaded = st.file_uploader("📥 Importer CSV Fantrax", type=["csv", "txt"])
if uploaded:
    try:
        df = parse_fantrax_file(uploaded)
        df["Propriétaire"] = uploaded.name.replace(".csv", "")
        data = pd.concat([data, df], ignore_index=True)
        data.to_csv(DATA_FILE, index=False)
        st.success(f"✅ Import réussi ({len(df)} joueurs)")
    except Exception as e:
        st.error(f"❌ Import impossible : {e}")

plafonds = controle_plafond(data)
st.dataframe(plafonds, use_container_width=True)

if not plafonds.empty:
    fig, ax = plt.subplots()
    ax.bar(plafonds["Propriétaire"], plafonds["GC"])
    ax.axhline(PLAFOND_GRAND_CLUB)
    ax.set_title("Masse salariale – Grand Club")
    st.pyplot(fig)

st.subheader("🧠 Recommandations IA")
for r in ia_reco(data):
    st.error(r)

if st.button("📄 Export PDF stylé"):
    path = export_pdf(season, data)
    with open(path, "rb") as f:
        st.download_button("Télécharger PDF", f, file_name=f"fantrax_{season}.pdf")
