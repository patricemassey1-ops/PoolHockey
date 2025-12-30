import streamlit as st
import pandas as pd
import os
from datetime import datetime
from zoneinfo import ZoneInfo
import tempfile

from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Table, TableStyle, PageBreak
)
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
# SIDEBAR SAISON
# ======================================================
st.sidebar.header("📅 Saison")

saisons = ["2024-2025", "2025-2026", "2026-2027"]
default = saison_par_defaut()
if default not in saisons:
    saisons.append(default)
    saisons.sort()

season = st.sidebar.selectbox(
    "Choisir la saison",
    saisons,
    index=saisons.index(default)
)

LOCKED = saison_passee(season)
if LOCKED:
    st.sidebar.warning("🔒 Saison verrouillée")

DATA_FILE = season_file(season)

# ======================================================
# SESSION
# ======================================================
if "season" not in st.session_state or st.session_state["season"] != season:
    st.session_state["data"] = (
        pd.read_csv(DATA_FILE)
        if os.path.exists(DATA_FILE)
        else pd.DataFrame(columns=["Propriétaire","Joueur","Salaire","Statut"])
    )
    st.session_state["season"] = season

# ======================================================
# IMPORT
# ======================================================
st.sidebar.header("📥 Import Fantrax")

if not LOCKED:
    file = st.sidebar.file_uploader("CSV Fantrax", type="csv")
    if file:
        df = pd.read_csv(file)
        df["Salaire"] = (
            df["Salary"].astype(str)
            .str.replace(r"[\$, ]","", regex=True)
            .astype(float) * 1000
        )
        df["Statut"] = df["Status"].apply(
            lambda x: "Club École" if "MIN" in str(x) else "Grand Club"
        )
        df["Propriétaire"] = file.name.replace(".csv","")
        df = df[["Propriétaire","Player","Salaire","Statut"]]
        df.columns = ["Propriétaire","Joueur","Salaire","Statut"]

        st.session_state["data"] = pd.concat(
            [st.session_state["data"], df], ignore_index=True
        )
        st.session_state["data"].drop_duplicates().to_csv(DATA_FILE, index=False)
        st.sidebar.success("Import réussi")
else:
    st.sidebar.info("Import désactivé")

# ======================================================
# IA RECOMMANDATIONS
# ======================================================
def recommandations(df):
    recos = []
    for p in df["Propriétaire"].unique():
        d = df[df["Propriétaire"] == p]
        total = d[d["Statut"]=="Grand Club"]["Salaire"].sum()
        if total <= PLAFOND_GC:
            continue
        surplus = total - PLAFOND_GC
        tri = d[d["Statut"]=="Grand Club"].sort_values("Salaire", ascending=False)
        for _, r in tri.head(3).iterrows():
            recos.append((p, r["Joueur"], r["Salaire"], surplus))
    return recos

# ======================================================
# EXPORT PDF ULTRA
# ======================================================
def export_pdf(season, df):
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph(
        f"<b>Rapport Officiel Fantrax – Saison {season}</b>",
        styles["Title"]
    ))
    elements.append(Paragraph(
        f"Généré le {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        styles["Normal"]
    ))
    elements.append(Paragraph("<br/>", styles["Normal"]))

    # Résumé
    resume = df.groupby(["Propriétaire","Statut"])["Salaire"].sum().unstack(fill_value=0)

    table_data = [["Propriétaire","Grand Club","Club École"]]
    for p, r in resume.iterrows():
        table_data.append([
            p,
            format_currency(r.get("Grand Club",0)),
            format_currency(r.get("Club École",0))
        ])

    table = Table(table_data, colWidths=[7*cm,4*cm,4*cm])
    table.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),colors.darkblue),
        ("TEXTCOLOR",(0,0),(-1,0),colors.white),
        ("GRID",(0,0),(-1,-1),0.5,colors.grey),
        ("ALIGN",(1,1),(-1,-1),"RIGHT"),
        ("FONT",(0,0),(-1,0),"Helvetica-Bold")
    ]))

    elements.append(table)
    elements.append(PageBreak())

    # IA
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
    doc = SimpleDocTemplate(tmp.name, pagesize=A4)
    doc.build(elements)
    return tmp.name

# ======================================================
# TABS
# ======================================================
tab1, tab2, tab3 = st.tabs(
    ["📊 Dashboard","🧠 IA","📄 Export PDF"]
)

# ================= DASHBOARD =================
with tab1:
    st.header(f"📊 Dashboard – {season}")
    if st.session_state["data"].empty:
        st.info("Aucune donnée")
    else:
        g = st.session_state["data"].groupby(
            ["Propriétaire","Statut"]
        )["Salaire"].sum().unstack(fill_value=0)
        st.dataframe(g.applymap(format_currency), use_container_width=True)

# ================= IA =================
with tab2:
    st.header("🧠 Recommandations IA")
    recos = recommandations(st.session_state["data"])
    if not recos:
        st.success("Aucun dépassement")
    for p,j,s,sur in recos:
        st.warning(
            f"{p} dépasse de {format_currency(sur)} → "
            f"Descendre {j} ({format_currency(s)})"
        )

# ================= PDF =================
with tab3:
    st.header("📄 Export PDF Stylé")
    if not st.session_state["data"].empty:
        if st.button("📥 Générer PDF complet"):
            path = export_pdf(season, st.session_state["data"])
            with open(path,"rb") as f:
                st.download_button(
                    "⬇️ Télécharger le PDF",
                    f,
                    file_name=f"fantrax_{season}.pdf",
                    mime="application/pdf"
                )
