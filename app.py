import streamlit as st
import pandas as pd
import os
import io
import re
import tempfile
from datetime import datetime

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
# PARSER FANTRAX (SKATERS + GOALIES)
# ======================================================
def extract_section(lines, keyword):
    start = None
    for i, l in enumerate(lines):
        if l.strip().lower() == keyword.lower():
            start = i
            break
    if start is None:
        return []

    for j in range(start + 1, len(lines)):
        if lines[j].strip().lower() in ["skaters", "goalies"]:
            return lines[start + 1 : j]
    return lines[start + 1 :]

def parse_section(lines):
    header_idx = None
    for i, l in enumerate(lines):
        if "player" in l.lower() and "salary" in l.lower():
            header_idx = i
            break
    if header_idx is None:
        return pd.DataFrame()

    df = pd.read_csv(
        io.StringIO("\n".join(lines[header_idx:])),
        sep="\t|,|;",
        engine="python"
    )

    df.columns = [c.strip().lower() for c in df.columns]

    def find_col(keys):
        for c in df.columns:
            for k in keys:
                if k in c:
                    return c
        return None

    col_player = find_col(["player"])
    col_salary = find_col(["salary"])
    col_status = find_col(["status", "eligible"])
    col_pos = find_col(["pos"])

    if not col_player or not col_salary:
        return pd.DataFrame()

    out = pd.DataFrame()
    out["Joueur"] = df[col_player]
    out["Salaire"] = (
        df[col_salary]
        .astype(str)
        .str.replace(r"[^\d.]", "", regex=True)
        .replace("", "0")
        .astype(float) * 1000
    )

    out["Statut"] = (
        df[col_status].apply(lambda x: "Club École" if "min" in str(x).lower() else "Grand Club")
        if col_status else "Grand Club"
    )

    out["Pos"] = df[col_pos] if col_pos else "N/A"
    return out

def parse_fantrax_csv(file):
    text = file.read().decode("utf-8", errors="ignore")
    lines = text.splitlines()

    skaters = parse_section(extract_section(lines, "Skaters"))
    goalies = parse_section(extract_section(lines, "Goalies"))

    df = pd.concat([skaters, goalies], ignore_index=True)
    if df.empty:
        raise ValueError("Aucune donnée Fantrax détectée")

    return df.dropna(subset=["Joueur"])

# ======================================================
# SIDEBAR – SAISON
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
            columns=["Propriétaire", "Joueur", "Salaire", "Statut", "Pos"]
        )
    st.session_state["season"] = season

# ======================================================
# IMPORT
# ======================================================
st.sidebar.header("📥 Import Fantrax")

if not LOCKED:
    file = st.sidebar.file_uploader("CSV Fantrax (Skaters + Goalies)", type=["csv", "txt"])
    if file:
        try:
            df = parse_fantrax_csv(file)
            df["Propriétaire"] = file.name.replace(".csv", "")

            st.session_state["data"] = pd.concat(
                [st.session_state["data"], df],
                ignore_index=True
            ).drop_duplicates(subset=["Propriétaire", "Joueur"])

            st.session_state["data"].to_csv(DATA_FILE, index=False)
            st.sidebar.success(f"✅ {len(df)} joueurs importés")

        except Exception as e:
            st.sidebar.error("❌ Import impossible")
            st.sidebar.code(str(e))
else:
    st.sidebar.info("Import désactivé")

# ======================================================
# CONTRÔLE PLAFOND TEMPS RÉEL
# ======================================================
def controle_plafond(df):
    res = []
    for p in df["Propriétaire"].unique():
        d = df[df["Propriétaire"] == p]
        gc = d[d["Statut"] == "Grand Club"]["Salaire"].sum()
        ce = d[d["Statut"] == "Club École"]["Salaire"].sum()

        res.append({
            "Propriétaire": p,
            "Grand Club": gc,
            "Restant GC": PLAFOND_GRAND_CLUB - gc,
            "Club École": ce,
            "Restant CE": PLAFOND_CLUB_ECOLE - ce
        })
    return pd.DataFrame(res)

# ======================================================
# IA
# ======================================================
def recommandations(df):
    recos = []
    for p in df["Propriétaire"].unique():
        d = df[df["Propriétaire"] == p]
        total = d[d["Statut"] == "Grand Club"]["Salaire"].sum()
        if total > PLAFOND_GRAND_CLUB:
            surplus = total - PLAFOND_GRAND_CLUB
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

    resume = controle_plafond(df)
    table_data = [["Propriétaire","Grand Club","Restant","Club École","Restant"]]

    for _, r in resume.iterrows():
        table_data.append([
            r["Propriétaire"],
            format_currency(r["Grand Club"]),
            format_currency(r["Restant GC"]),
            format_currency(r["Club École"]),
            format_currency(r["Restant CE"]),
        ])

    table = Table(table_data, colWidths=[6*cm,3*cm,3*cm,3*cm,3*cm])
    table.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),colors.darkblue),
        ("TEXTCOLOR",(0,0),(-1,0),colors.white),
        ("GRID",(0,0),(-1,-1),0.5,colors.grey),
        ("ALIGN",(1,1),(-1,-1),"RIGHT")
    ]))

    elements.append(table)
    elements.append(PageBreak())

    elements.append(Paragraph("<b>Recommandations IA</b>", styles["Heading2"]))
    for p,j,s,sur in recommandations(df):
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
tab1, tab2, tab3 = st.tabs(["📊 Plafonds Live","🧠 IA","📄 Export PDF"])

with tab1:
    if st.session_state["data"].empty:
        st.info("Aucune donnée")
    else:
        plafonds = controle_plafond(st.session_state["data"])
        for col in ["Grand Club","Restant GC","Club École","Restant CE"]:
            plafonds[col] = plafonds[col].apply(format_currency)
        st.dataframe(plafonds, use_container_width=True)

with tab2:
    recos = recommandations(st.session_state["data"])
    if not recos:
        st.success("✅ Tous les clubs respectent le plafond")
    for p,j,s,sur in recos:
        st.error(
            f"{p} dépasse de {format_currency(sur)} → "
            f"Descendre {j} ({format_currency(s)})"
        )

with tab3:
    if not st.session_state["data"].empty:
        if st.button("📥 Générer PDF"):
            path = export_pdf(season, st.session_state["data"])
            with open(path,"rb") as f:
                st.download_button(
                    "⬇️ Télécharger le PDF",
                    f,
                    file_name=f"fantrax_{season}.pdf",
                    mime="application/pdf"
                )
