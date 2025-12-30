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

def saison_passee(season):
    return int(season[:4]) < int(saison_par_defaut()[:4])

def season_file(season):
    return f"{DATA_DIR}/fantrax_{season}.csv"

# ======================================================
# UTILS
# ======================================================
def format_currency(v):
    try:
        return f"{int(v):,}".replace(",", " ") + " $"
    except:
        return "0 $"

# ======================================================
# PARSER FANTRAX (SKATERS + GOALIES ROBUSTE)
# ======================================================
def parse_fantrax_file(uploaded_file):
    text = uploaded_file.read().decode("utf-8", errors="ignore")
    lines = text.splitlines()

    header = None
    for i, l in enumerate(lines):
        if "Player" in l and "Salary" in l:
            header = i
            break

    if header is None:
        raise ValueError("Aucune donnée Fantrax détectée")

    df = pd.read_csv(io.StringIO("\n".join(lines[header:])), engine="python")
    df.columns = [c.strip() for c in df.columns]

    df = df[df["Player"].notna()].copy()

    out = pd.DataFrame()
    out["Joueur"] = df["Player"]
    out["Salaire"] = (
        df["Salary"]
        .astype(str)
        .str.replace(",", "", regex=False)
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

    return out.dropna(subset=["Joueur"])

# ======================================================
# SIDEBAR
# ======================================================
st.sidebar.header("📅 Saison")

saisons = ["2024-2025", "2025-2026", "2026-2027"]
default = saison_par_defaut()
if default not in saisons:
    saisons.append(default)
    saisons.sort()

season = st.sidebar.selectbox("Choisir la saison", saisons, index=saisons.index(default))
LOCKED = saison_passee(season)
DATA_FILE = season_file(season)

# ======================================================
# SESSION INIT
# ======================================================
if "season" not in st.session_state or st.session_state["season"] != season:
    if os.path.exists(DATA_FILE):
        st.session_state["data"] = pd.read_csv(DATA_FILE)
    else:
        st.session_state["data"] = pd.DataFrame(
            columns=["Propriétaire", "Joueur", "Salaire", "Statut", "Pos"]
        )
    st.session_state["season"] = season

# ======================================================
# IMPORT
# ======================================================
st.sidebar.header("📥 Import Fantrax")

if not LOCKED:
    file = st.sidebar.file_uploader("CSV Fantrax", type=["csv", "txt"])
    if file:
        try:
            df = parse_fantrax_file(file)
            df["Propriétaire"] = file.name.replace(".csv", "")
            st.session_state["data"] = pd.concat(
                [st.session_state["data"], df],
                ignore_index=True
            ).drop_duplicates(subset=["Propriétaire", "Joueur"])
            st.session_state["data"].to_csv(DATA_FILE, index=False)
            st.sidebar.success(f"✅ {len(df)} joueurs importés")
        except Exception as e:
            st.sidebar.error(f"❌ Import impossible : {e}")

# ======================================================
# PLAFONDS
# ======================================================
def controle_plafond(df):
    if df.empty:
        return pd.DataFrame(
            columns=["Propriétaire", "GC", "CE", "RGC", "RCE"]
        )

    rows = []
    for p in df["Propriétaire"].unique():
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
    return pd.DataFrame(rows)

# ======================================================
# IA RECOMMANDATIONS
# ======================================================
def ia_reco(df):
    recos = []
    plaf = controle_plafond(df)
    if plaf.empty:
        return recos

    for _, r in plaf.iterrows():
        if r["RGC"] < 0:
            joueurs = df[
                (df["Propriétaire"] == r["Propriétaire"]) &
                (df["Statut"] == "Grand Club")
            ].sort_values("Salaire", ascending=False)
            for _, j in joueurs.head(2).iterrows():
                recos.append(
                    f"{r['Propriétaire']} : descendre {j['Joueur']} ({format_currency(j['Salaire'])})"
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

    table_data = [["GM", "Grand Club", "Restant", "Club École", "Restant"]]
    for _, r in plaf.iterrows():
        table_data.append([
            r["Propriétaire"],
            format_currency(r["GC"]),
            format_currency(r["RGC"]),
            format_currency(r["CE"]),
            format_currency(r["RCE"])
        ])

    table = Table(table_data, colWidths=[4*cm]*5)
    table.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),colors.darkblue),
        ("TEXTCOLOR",(0,0),(-1,0),colors.white),
        ("GRID",(0,0),(-1,-1),0.5,colors.grey),
        ("ALIGN",(1,1),(-1,-1),"RIGHT")
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

tab1, tab2, tab3, tab4 = st.tabs([
    "📊 Plafonds & Graphiques",
    "🧠 IA",
    "⚖️ Transactions",
    "📄 Export PDF"
])

with tab1:
    plafonds = controle_plafond(st.session_state["data"])
    st.dataframe(plafonds, use_container_width=True)

    if not plafonds.empty:
        fig, ax = plt.subplots()
        ax.bar(plafonds["Propriétaire"], plafonds["GC"])
        ax.axhline(PLAFOND_GRAND_CLUB)
        ax.set_title("Masse salariale Grand Club")
        st.pyplot(fig)
    else:
        st.info("Aucune donnée pour afficher le graphique")

with tab2:
    recos = ia_reco(st.session_state["data"])
    if not recos:
        st.success("✅ Aucun dépassement détecté")
    for r in recos:
        st.error(r)

with tab3:
    if st.session_state["data"].empty:
        st.info("Aucune donnée importée")
    else:
        gm = st.selectbox("GM", st.session_state["data"]["Propriétaire"].unique())
        joueurs = st.session_state["data"][
            st.session_state["data"]["Propriétaire"] == gm
        ]["Joueur"]

        joueur = st.selectbox("Joueur à monter en Grand Club", joueurs)

        test = st.session_state["data"].copy()
        test.loc[
            (test["Propriétaire"] == gm) &
            (test["Joueur"] == joueur),
            "Statut"
        ] = "Grand Club"

        r = controle_plafond(test)
        reste = r[r["Propriétaire"] == gm]["RGC"].values[0]

        if reste < 0:
            st.error(f"❌ Transaction invalide (dépassement {format_currency(-reste)})")
        else:
            st.success(f"✅ Transaction valide – restant {format_currency(reste)}")

with tab4:
    if st.button("📥 Générer PDF"):
        path = export_pdf(season, st.session_state["data"])
        with open(path, "rb") as f:
            st.download_button(
                "⬇️ Télécharger le PDF",
                f,
                file_name=f"fantrax_{season}.pdf"
            )
