import streamlit as st
import pandas as pd
import io
import os
import tempfile
from datetime import datetime

from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors

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
    return f"{int(v):,}".replace(",", " ") + " $"

def season_file(season):
    return f"{DATA_DIR}/fantrax_{season}.csv"

# ======================================================
# 🔥 PARSER FANTRAX DÉFINITIF
# ======================================================
def parse_fantrax_file(uploaded_file):
    text = uploaded_file.read().decode("utf-8", errors="ignore")
    lines = text.splitlines()

    header_index = None
    for i, line in enumerate(lines):
        if line.startswith("ID") and "Player" in line and "Salary" in line:
            header_index = i
            break

    if header_index is None:
        raise ValueError("Ligne d’en-tête Fantrax introuvable")

    df = pd.read_csv(
        io.StringIO("\n".join(lines[header_index:])),
        sep="\t",
        engine="python"
    )

    df.columns = [c.strip() for c in df.columns]

    if "Player" not in df.columns or "Salary" not in df.columns:
        raise ValueError(f"Colonnes détectées : {list(df.columns)}")

    out = pd.DataFrame()
    out["Joueur"] = df["Player"].astype(str)

    out["Salaire"] = (
        df["Salary"]
        .astype(str)
        .str.replace(",", "")
        .replace("", "0")
        .astype(float) * 1000
    )

    out["Pos"] = df["Pos"] if "Pos" in df.columns else "N/A"

    if "Status" in df.columns:
        out["Statut"] = out["Status"].apply(
            lambda x: "Club École" if "min" in str(x).lower() else "Grand Club"
        )
    else:
        out["Statut"] = "Grand Club"

    return out.dropna(subset=["Joueur"])

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
    file = st.sidebar.file_uploader("Exporter Fantrax (Skaters / Goalies)", type=["csv", "txt"])
    if file:
        try:
            df = parse_fantrax_file(file)
            df["Propriétaire"] = file.name.replace(".csv", "").replace(".txt", "")

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
    st.sidebar.warning("🔒 Saison verrouillée")

# ======================================================
# PLAFOND SALARIAL LIVE
# ======================================================
def controle_plafond(df):
    rows = []
    for p in df["Propriétaire"].unique():
        d = df[df["Propriétaire"] == p]
        gc = d[d["Statut"] == "Grand Club"]["Salaire"].sum()
        ce = d[d["Statut"] == "Club École"]["Salaire"].sum()
        rows.append({
            "Propriétaire": p,
            "Grand Club": gc,
            "Restant GC": PLAFOND_GRAND_CLUB - gc,
            "Club École": ce,
            "Restant CE": PLAFOND_CLUB_ECOLE - ce
        })
    return pd.DataFrame(rows)

# ======================================================
# UI
# ======================================================
st.title("🏒 Fantrax – Gestion Salariale")

if st.session_state["data"].empty:
    st.info("Aucune donnée importée")
else:
    plafonds = controle_plafond(st.session_state["data"])
    for c in plafonds.columns[1:]:
        plafonds[c] = plafonds[c].apply(format_currency)
    st.dataframe(plafonds, use_container_width=True)
