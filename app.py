import streamlit as st
import pandas as pd
import os
from datetime import datetime
import tempfile
import re

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

PLAFOND_GC = 95_500_000
PLAFOND_CE = 47_750_000

# ======================================================
# SAISON AUTO
# ======================================================
def saison_par_defaut():
    now = datetime.now()
    return f"{now.year}-{now.year+1}" if now.month >= 9 else f"{now.year-1}-{now.year}"

def saison_passee(season):
    return int(season[:4]) < int(saison_par_defaut()[:4])

# ======================================================
# UTILS
# ======================================================
def format_currency(v):
    try:
        return f"{int(v):,}".replace(",", " ") + " $"
    except:
        return "0 $"

def season_file(season):
    return f"{DATA_DIR}/fantrax_{season}.csv"

# ======================================================
# FANTRAX AUTO PARSER
# ======================================================
def parse_fantrax_csv(file):
    df = pd.read_csv(
        file,
        sep=None,
        engine="python",
        encoding="utf-8",
        on_bad_lines="skip"
    )

    # Supprimer colonnes inutiles
    df = df.loc[:, ~df.columns.str.contains("^Unnamed", case=False)]

    # Cas colonne unique (Skaters compact)
    if df.shape[1] == 1:
        col = df.columns[0]
        df = df[col].astype(str).str.split(",", expand=True)
        df.columns = [f"col_{i}" for i in range(df.shape[1])]

    # Normaliser noms
    cols = {c: c.lower() for c in df.columns}
    df.rename(columns=cols, inplace=True)

    def find_col(keywords):
        for c in df.columns:
            for k in keywords:
                if k in c:
                    return c
        return None

    col_player = find_col(["player", "name", "skater"])
    col_salary = find_col(["salary", "cap", "$"])
    col_status = find_col(["status", "minor", "roster"])

    if not col_player or not col_salary:
        raise ValueError(f"Impossible de détecter les colonnes Fantrax : {list(df.columns)}")

    df["Joueur"] = df[col_player]

    df["Salaire"] = (
        df[col_salary]
        .astype(str)
        .str.replace(r"[^\d.]", "", regex=True)
        .replace("", "0")
        .astype(float) * 1000
    )

    if col_status:
        df["Statut"] = df[col_status].apply(
            lambda x: "Club École" if "min" in str(x).lower() else "Grand Club"
        )
    else:
        df["Statut"] = "Grand Club"

    return df[["Joueur", "Salaire", "Statut"]]

# ======================================================
# SIDEBAR SAISON
# ======================================================
st.sidebar.header("📅 Saison")

saisons = ["2024-2025", "2025-2026", "2026-2027"]
default = saison_par_defaut()
if default not in saisons:
    saisons.append(default)
    saisons.sort()

season = st.sidebar.selectbox("Choisir la saison", saisons, index=saisons.index(default))
LOCKED = saison_passee(season)

if LOCKED:
    st.sidebar.warning("🔒 Saison verrouillée")

DATA_FILE = season_file(season)

# ======================================================
# SESSION
# ======================================================
if "season" not in st.session_state or st.session_state["season"] != season:
    if os.path.exists(DATA_FILE):
        st.session_state["data"] = pd.read_csv(DATA_FILE)
    else:
        st.session_state["data"] = pd.DataFrame(
            columns=["Propriétaire", "Joueur", "Salaire", "Statut"]
        )
    st.session_state["season"] = season

# ======================================================
# IMPORT
# ======================================================
st.sidebar.header("📥 Import Fantrax")

if not LOCKED:
    file = st.sidebar.file_uploader("CSV Fantrax", type="csv")

    if file:
        try:
            parsed = parse_fantrax_csv(file)
            parsed["Propriétaire"] = file.name.replace(".csv", "")

            df = parsed[["Propriétaire", "Joueur", "Salaire", "Statut"]]

            st.session_state["data"] = pd.concat(
                [st.session_state["data"], df],
                ignore_index=True
            ).drop_duplicates()

            st.session_state["data"].to_csv(DATA_FILE, index=False)
            st.sidebar.success("✅ Import Fantrax réussi")

        except Exception as e:
            st.sidebar.error("❌ Import Fantrax impossible")
            st.sidebar.code(str(e))
else:
    st.sidebar.info("Import désactivé")

# ======================================================
# IA
# ======================================================
def recommandations(df):
    recos = []
    for p in df["Propriétaire"].unique():
        d = df[df["Propriétaire"] == p]
        total = d[d["Statut"] == "Grand Club"]["Salaire"].sum()
        if total > PLAFOND_GC:
            surplus = total - PLAFOND_GC
            for _, r in d.sort_values("Salaire", ascending=False).head(3).iterrows():
                recos.append((p, r["Joueur"], r["Salaire"], surplus))
    return recos

# ======================================================
# EXPORT PDF
# ======================================================
def export_pdf(season, df):
    styles = getSampleStyleSheet()
    elements = [
        Paragraph(f"<b>Rapport Fantrax – Saison {season}</b>", styles["Title"]),
        Paragraph(f"Généré le {datetime.now().strftime('%d/%m/%Y %H:%M')}", styles["Normal"]),
        Paragraph("<br/>", styles["Normal"])
    ]

    resume = df.groupby(["Propriétaire", "Statut"])["Salaire"].sum().unstack(fill_value=0)
    table_data = [["Propriétaire", "Grand Club", "Club École"]]

    for p, r in resume.iterrows():
        table_data.append([
            p,
            format_currency(r.get("Grand Club", 0)),
            format_currency(r.get("Club École", 0))
        ])

    table = Table(table_data, colWidths=[7*cm, 4*cm, 4*cm])
    table.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),colors.darkblue),
        ("TEXTCOLOR",(0,0),(-1,0),colors.white),
        ("GRID",(0,0),(-1,-1),0.5,colors.grey),
        ("ALIGN",(1,1),(-1,-1),"RIGHT")
    ]))

    elements.append(table)
    elements.append(PageBreak())

    elements.append(Paragraph("<b>Recommandations IA</b>", styles["Heading2"]))
    recos = recommandations(df)
    if not recos:
        elements.append(Paragraph("Aucun dépassement détecté.", styles["Normal"]))
    else:
        for p,j,s,sur in recos:
            elements.append(Paragraph(
                f"{p} → Descendre <b>{j}</b> ({format_currency(s)})",
                styles["Normal"]
            ))

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    SimpleDocTemplate(tmp.name, pagesize=A4).build(elements)
    return tmp.name

# ======================================================
# UI
# ======================================================
tab1, tab2, tab3 = st.tabs(["📊 Dashboard", "🧠 IA", "📄 Export PDF"])

with tab1:
    if st.session_state["data"].empty:
        st.info("Aucune donnée")
    else:
        g = st.session_state["data"].groupby(
            ["Propriétaire","Statut"]
        )["Salaire"].sum().unstack(fill_value=0)
        st.dataframe(g.applymap(format_currency), use_container_width=True)

with tab2:
    recos = recommandations(st.session_state["data"])
    if not recos:
        st.success("Aucun dépassement")
    for p,j,s,sur in recos:
        st.warning(
            f"{p} dépasse de {format_currency(sur)} → "
            f"Descendre {j} ({format_currency(s)})"
        )

with tab3:
    if not st.session_state["data"].empty:
        if st.button("📥 Générer PDF"):
            path = export_pdf(season, st.session_state["data"])
            with open(path, "rb") as f:
                st.download_button(
                    "⬇️ Télécharger le PDF",
                    f,
                    file_name=f"fantrax_{season}.pdf",
                    mime="application/pdf"
                )
