import streamlit as st
import pandas as pd
import io, os, tempfile
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
# PARSER FANTRAX **ANTI-CRASH**
# ======================================================
def parse_fantrax_file(uploaded_file):
    raw = uploaded_file.read().decode("utf-8", errors="ignore")

    # on garde uniquement les lignes contenant Player
    lines = [l for l in raw.splitlines() if "Player" in l or l.startswith("*")]

    if not lines:
        raise ValueError("Aucune donnée Fantrax détectée")

    df = pd.read_csv(
        io.StringIO("\n".join(lines)),
        sep=None,                # détection auto
        engine="python",
        on_bad_lines="skip"      # IGNORE lignes cassées
    )

    df.columns = [c.strip() for c in df.columns]

    required = {"Player", "Salary"}
    if not required.issubset(df.columns):
        raise ValueError(f"Colonnes requises manquantes : {df.columns.tolist()}")

    df = df[df["Player"].notna()].copy()

    out = pd.DataFrame()
    out["Joueur"] = df["Player"].astype(str)

    out["Salaire"] = (
        df["Salary"]
        .astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("$", "", regex=False)
        .astype(float)
        * 1000
    )

    out["Pos"] = df["Pos"] if "Pos" in df.columns else "N/A"

    if "Status" in df.columns:
        out["Statut"] = df["Status"].apply(
            lambda x: "Club École" if "min" in str(x).lower() else "Grand Club"
        )
    else:
        out["Statut"] = "Grand Club"

    return out.reset_index(drop=True)

# ======================================================
# CONTROLE PLAFOND (SAFE)
# ======================================================
def controle_plafond(df):
    cols = ["Propriétaire", "GC", "CE", "RGC", "RCE"]
    if df.empty or "Propriétaire" not in df.columns:
        return pd.DataFrame(columns=cols)

    rows = []
    for p in df["Propriétaire"].dropna().unique():
        d = df[df["Propriétaire"] == p]
        gc = d[d["Statut"] == "Grand Club"]["Salaire"].sum()
        ce = d[d["Statut"] == "Club École"]["Salaire"].sum()
        rows.append({
            "Propriétaire": p,
            "GC": gc,
            "CE": ce,
            "RGC": PLAFOND_GRAND_CLUB - gc,
            "RCE": PLAFOND_CLUB_ECOLE - ce
        })

    return pd.DataFrame(rows, columns=cols)

# ======================================================
# IA RECOMMANDATIONS
# ======================================================
def ia_reco(df):
    recos = []
    plaf = controle_plafond(df)
    for _, r in plaf.iterrows():
        if r["RGC"] < 0:
            joueurs = df[
                (df["Propriétaire"] == r["Propriétaire"]) &
                (df["Statut"] == "Grand Club")
            ].sort_values("Salaire", ascending=False).head(2)
            for _, j in joueurs.iterrows():
                recos.append(
                    f"{r['Propriétaire']} : rétrograder {j['Joueur']} ({int(j['Salaire']):,}$)"
                )
    return recos

# ======================================================
# PDF
# ======================================================
def export_pdf(season, df):
    styles = getSampleStyleSheet()
    elements = [
        Paragraph(f"<b>Rapport Fantrax – Saison {season}</b>", styles["Title"]),
        Paragraph(datetime.now().strftime("%d/%m/%Y %H:%M"), styles["Normal"]),
        Paragraph("<br/>", styles["Normal"])
    ]

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
        st.success(f"✅ Import réussi : {len(df)} joueurs")
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
        st.download_button("⬇️ Télécharger le PDF", f, file_name=f"fantrax_{season}.pdf")
