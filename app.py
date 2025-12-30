import streamlit as st
import pandas as pd
import io
import os
from datetime import datetime
import matplotlib.pyplot as plt

# =====================================================
# CONFIG
# =====================================================
st.set_page_config("Fantrax Pool Hockey", layout="wide")

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

PLAFOND_GC = 95_500_000
PLAFOND_CE = 47_750_000

# =====================================================
# SAISON AUTO
# =====================================================
def saison_auto():
    now = datetime.now()
    return f"{now.year}-{now.year+1}" if now.month >= 9 else f"{now.year-1}-{now.year}"

def saison_verrouillee(season):
    return int(season[:4]) < int(saison_auto()[:4])

# =====================================================
# FORMAT
# =====================================================
def money(v):
    try:
        return f"{int(v):,}".replace(",", " ") + " $"
    except:
        return "0 $"

# =====================================================
# PARSER FANTRAX (STABLE)
# =====================================================
def parse_fantrax(upload):
    raw = upload.read().decode("utf-8", errors="ignore").splitlines()
    csv_text = "\n".join(raw[1:])

    df = pd.read_csv(
        io.StringIO(csv_text),
        engine="python",
        on_bad_lines="skip"
    )

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
# SIDEBAR – SAISON
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

# =====================================================
# SESSION
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
        try:
            df = parse_fantrax(uploaded)
            df["Propriétaire"] = uploaded.name.replace(".csv", "")
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

# =====================================================
# CALCULS
# =====================================================
df = st.session_state["data"]
resume = []

for p in df["Propriétaire"].unique():
    d = df[df["Propriétaire"] == p]
    gc = d[d["Statut"] == "Grand Club"]["Salaire"].sum()
    ce = d[d["Statut"] == "Club École"]["Salaire"].sum()
    resume.append({
        "Propriétaire": p,
        "GC": gc,
        "CE": ce,
        "Restant GC": PLAFOND_GC - gc,
        "Restant CE": PLAFOND_CE - ce
    })

plafonds = pd.DataFrame(resume)

# =====================================================
# UI – ONGLETs
# =====================================================
st.title("🏒 Fantrax – Gestion Salariale")

tab1, tab2, tab3, tab4 = st.tabs([
    "📊 Tableau",
    "📈 Graphiques",
    "⚖️ Transactions",
    "🧠 Recommandations"
])

# =====================================================
# 📊 TABLEAU
# =====================================================
with tab1:
    display = plafonds.copy()
    for c in display.columns[1:]:
        display[c] = display[c].apply(money)
    st.dataframe(display, use_container_width=True)

# =====================================================
# 📈 GRAPHIQUES (PLUS PETIT)
# =====================================================
with tab2:
    st.subheader("Masse salariale – Grand Club")

    fig, ax = plt.subplots(figsize=(6, 4))  # 👈 taille réduite
    ax.bar(plafonds["Propriétaire"], plafonds["GC"])
    ax.axhline(PLAFOND_GC, linestyle="--")
    ax.set_ylabel("$")
    plt.xticks(rotation=30, ha="right")
    st.pyplot(fig, use_container_width=False)

# =====================================================
# ⚖️ TRANSACTIONS
# =====================================================
with tab3:
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
# 🧠 IA
# =====================================================
with tab4:
    for _, r in plafonds.iterrows():
        if r["Restant GC"] < 2_000_000:
            st.warning(f"{r['Propriétaire']} : rétrogradation recommandée")
        if r["Restant CE"] > 10_000_000:
            st.info(f"{r['Propriétaire']} : rappel possible")
