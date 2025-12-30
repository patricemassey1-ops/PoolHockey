import streamlit as st
import pandas as pd
import io
import os
from datetime import datetime

# =====================================================
# CONFIG
# =====================================================
st.set_page_config("Fantrax Pool Hockey", layout="wide")

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

# =====================================================
# PLAFONDS (MODIFIABLES)
# =====================================================
if "PLAFOND_GC" not in st.session_state:
    st.session_state["PLAFOND_GC"] = 95_500_000
if "PLAFOND_CE" not in st.session_state:
    st.session_state["PLAFOND_CE"] = 47_750_000

# =====================================================
# LOGOS
# =====================================================
LOGOS = {
    "Nordiques": "Nordiques_Logo.png",
    "Cracheurs": "Cracheurs_Logo.png",  
    "Prédateurs": "Prédateurs_Logo.png",
    "Red Wings": "Red_Wings_Logo.png",
    "Whalers": "Whalers_Logo.png",
    "Canadiens": "Canadiens_Logo.png"
}


# =====================================================
# SAISON AUTO
# =====================================================
def saison_auto():
    now = datetime.now()
    return f"{now.year}-{now.year+1}" if now.month >= 9 else f"{now.year-1}-{now.year}"

def saison_verrouillee(season):
    return int(season[:4]) < int(saison_auto()[:4])

# =====================================================
# FORMAT $
# =====================================================
def money(v):
    return f"{int(v):,}".replace(",", " ") + " $"

# =====================================================
# PARSER FANTRAX
# =====================================================
def parse_fantrax(upload):
    raw = upload.read().decode("utf-8", errors="ignore").splitlines()
    csv_text = "\n".join(raw[1:])

    df = pd.read_csv(io.StringIO(csv_text), engine="python", on_bad_lines="skip")
    df.columns = [c.replace('"', '').strip() for c in df.columns]

    if "Player" not in df.columns or "Salary" not in df.columns:
        raise ValueError("Colonnes Fantrax non détectées")

    out = pd.DataFrame()
    out["Joueur"] = df["Player"].astype(str)
    out["Pos"] = df.get("Pos", "N/A")
    out["Equipe"] = df.get("Team", "N/A")

    sal = (
        df["Salary"]
        .astype(str)
        .str.replace(",", "", regex=False)
        .replace(["None", "nan", "NaN", ""], "0")
    )

    out["Salaire"] = pd.to_numeric(sal, errors="coerce").fillna(0) * 1000
    out["Statut"] = df.get("Status", "").apply(
        lambda x: "Club École" if "min" in str(x).lower() else "Grand Club"
    )

    return out[out["Joueur"].str.len() > 2]

# =====================================================
# SIDEBAR
# =====================================================
st.sidebar.header("📅 Saison")

saisons = ["2024-2025", "2025-2026", "2026-2027"]
auto = saison_auto()
if auto not in saisons:
    saisons.append(auto)
    saisons.sort()

season = st.sidebar.selectbox("Saison", saisons, index=saisons.index(auto))
LOCKED = saison_verrouillee(season)
DATA_FILE = f"{DATA_DIR}/fantrax_{season}.csv"

st.sidebar.divider()
st.sidebar.header("💰 Plafonds")

if st.sidebar.button("✏️ Modifier les plafonds"):
    st.session_state["edit_plafond"] = True

if st.session_state.get("edit_plafond"):
    st.session_state["PLAFOND_GC"] = st.sidebar.number_input(
        "Plafond Grand Club", value=st.session_state["PLAFOND_GC"], step=500_000
    )
    st.session_state["PLAFOND_CE"] = st.sidebar.number_input(
        "Plafond Club École", value=st.session_state["PLAFOND_CE"], step=250_000
    )

st.sidebar.metric("🏒 Grand Club", money(st.session_state["PLAFOND_GC"]))
st.sidebar.metric("🏫 Club École", money(st.session_state["PLAFOND_CE"]))

# =====================================================
# DATA
# =====================================================
if "season" not in st.session_state or st.session_state["season"] != season:
    if os.path.exists(DATA_FILE):
        st.session_state["data"] = pd.read_csv(DATA_FILE)
    else:
        st.session_state["data"] = pd.DataFrame(
            columns=["Propriétaire", "Joueur", "Salaire", "Statut", "Pos", "Equipe"]
        )
    st.session_state["season"] = season

# =====================================================
# IMPORT
# =====================================================
st.sidebar.header("📥 Import Fantrax")
if not LOCKED:
    uploaded = st.sidebar.file_uploader("CSV Fantrax", type=["csv", "txt"])
    if uploaded:
        df = parse_fantrax(uploaded)
        df["Propriétaire"] = uploaded.name.replace(".csv", "")
        st.session_state["data"] = pd.concat(
            [st.session_state["data"], df],
            ignore_index=True
        ).drop_duplicates(subset=["Propriétaire", "Joueur"])
        st.session_state["data"].to_csv(DATA_FILE, index=False)
        st.sidebar.success("✅ Import réussi")

# =====================================================
# HEADER
# =====================================================
st.image("Logo_Pool.png", use_container_width=True)
st.title("🏒 Fantrax – Gestion Salariale")

df = st.session_state["data"]
if df.empty:
    st.info("Aucune donnée")
    st.stop()

# =====================================================
# CALCULS
# =====================================================
resume = []
for p in df["Propriétaire"].unique():
    d = df[df["Propriétaire"] == p]
    gc = d[d["Statut"] == "Grand Club"]["Salaire"].sum()
    ce = d[d["Statut"] == "Club École"]["Salaire"].sum()

    logo = ""
    for k, v in LOGOS.items():
        if k.lower() in p.lower():
            logo = v

    resume.append({
        "Propriétaire": p,
        "Logo": logo,
        "GC": gc,
        "CE": ce,
        "Restant GC": st.session_state["PLAFOND_GC"] - gc,
        "Restant CE": st.session_state["PLAFOND_CE"] - ce
    })

plafonds = pd.DataFrame(resume)

# =====================================================
# ONGLETs
# =====================================================
tab1, tab2, tab3 = st.tabs(["📊 Tableau", "⚖️ Transactions", "🧠 Recommandations"])

# =====================================================
# TABLEAU AVEC LOGOS (CORRIGÉ)
# =====================================================
with tab1:
    headers = st.columns([1.2, 2.5, 2, 2, 2, 2])
    headers[0].markdown("**Logo**")
    headers[1].markdown("**Propriétaire**")
    headers[2].markdown("**Grand Club**")
    headers[3].markdown("**Club École**")
    headers[4].markdown("**Restant GC**")
    headers[5].markdown("**Restant CE**")

    for _, r in plafonds.iterrows():
        cols = st.columns([1.2, 2.5, 2, 2, 2, 2])

        if r["Logo"] and os.path.exists(r["Logo"]):
            cols[0].image(r["Logo"], width=55)
        else:
            cols[0].markdown("—")

        cols[1].markdown(r["Propriétaire"])
        cols[2].markdown(money(r["GC"]))
        cols[3].markdown(money(r["CE"]))
        cols[4].markdown(money(r["Restant GC"]))
        cols[5].markdown(money(r["Restant CE"]))

# =====================================================
# TRANSACTIONS
# =====================================================
with tab2:
    p = st.selectbox("Propriétaire", plafonds["Propriétaire"])
    salaire = st.number_input("Salaire du joueur", min_value=0, step=100000)
    statut = st.radio("Statut", ["Grand Club", "Club École"])

    ligne = plafonds[plafonds["Propriétaire"] == p].iloc[0]
    reste = ligne["Restant GC"] if statut == "Grand Club" else ligne["Restant CE"]

    if salaire > reste:
        st.error("🚨 Dépassement du plafond")
    else:
        st.success("✅ Transaction valide")

# =====================================================
# IA
# =====================================================
with tab3:
    for _, r in plafonds.iterrows():
        if r["Restant GC"] < 2_000_000:
            st.warning(f"{r['Propriétaire']} : rétrogradation recommandée")
        if r["Restant CE"] > 10_000_000:
            st.info(f"{r['Propriétaire']} : rappel possible")
