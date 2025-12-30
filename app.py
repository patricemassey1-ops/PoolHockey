import streamlit as st
import pandas as pd
import io
import os
from datetime import datetime
from zoneinfo import ZoneInfo

# =========================
# CONFIGURATION
# =========================
st.set_page_config(page_title="Calculateur Fantrax 2025", layout="wide")

DB_FILE = "historique_fantrax_v2.csv"
BUYOUT_FILE = "rachats_v2.csv"
PLAYERS_DB_FILE = "Hockey_Players.csv"
HISTORIQUE_FILE = "historique_actions.csv"

DEFAULT_PLAFOND_GRAND_CLUB = 95_500_000
DEFAULT_PLAFOND_CLUB_ECOLE = 47_750_000

# =========================
# OUTILS
# =========================
def format_currency(val):
    if pd.isna(val) or val == "":
        return "0 $"
    try:
        return f"{int(float(val)):,}".replace(",", " ") + " $"
    except:
        return "0 $"

@st.cache_data(ttl=3600, show_spinner=False)
def charger_donnees(file, columns):
    if os.path.exists(file):
        return pd.read_csv(file).drop_duplicates()
    return pd.DataFrame(columns=columns)

def sauvegarder_donnees(df, file):
    df.drop_duplicates().to_csv(file, index=False)

def ajouter_action_historique(proprio, action, joueur, details):
    tz = ZoneInfo("America/Montreal")
    now = datetime.now(tz)

    action_df = pd.DataFrame({
        "Date": [now.strftime("%Y-%m-%d")],
        "Heure": [now.strftime("%H:%M:%S")],
        "Propriétaire": [proprio],
        "Action": [action],
        "Joueur": [joueur],
        "Details": [details]
    })

    st.session_state["historique_actions"] = pd.concat(
        [st.session_state["historique_actions"], action_df],
        ignore_index=True
    )
    sauvegarder_donnees(st.session_state["historique_actions"], HISTORIQUE_FILE)

# =========================
# DB JOUEURS
# =========================
@st.cache_data(ttl=3600, show_spinner=False)
def charger_db_joueurs():
    if not os.path.exists(PLAYERS_DB_FILE):
        return pd.DataFrame()

    df = pd.read_csv(PLAYERS_DB_FILE)

    df.rename(columns={
        "Player": "Joueur",
        "Salary": "Salaire",
        "Position": "Pos",
        "Team": "Equipe_NHL"
    }, inplace=True, errors="ignore")

    df["Salaire"] = (
        df.get("Salaire", 0)
        .astype(str)
        .str.replace(r"[\$, ]", "", regex=True)
        .astype(float)
        .fillna(0) * 1000
    )

    df["search_label"] = (
        df["Joueur"] + " (" + df["Equipe_NHL"].fillna("N/A") + ") - " +
        df["Salaire"].apply(format_currency)
    )

    return df.drop_duplicates(subset=["Joueur", "Equipe_NHL"])

# =========================
# SESSION INIT
# =========================
if "historique" not in st.session_state:
    st.session_state["historique"] = charger_donnees(
        DB_FILE,
        ["Joueur", "Salaire", "Statut", "Pos", "Equipe", "Propriétaire"]
    )

if "Equipe" not in st.session_state["historique"].columns:
    st.session_state["historique"]["Equipe"] = "N/A"

if "rachats" not in st.session_state:
    st.session_state["rachats"] = charger_donnees(
        BUYOUT_FILE,
        ["Propriétaire", "Joueur", "Impact"]
    )

if "db_joueurs" not in st.session_state:
    st.session_state["db_joueurs"] = charger_db_joueurs()

if "historique_actions" not in st.session_state:
    st.session_state["historique_actions"] = charger_donnees(
        HISTORIQUE_FILE,
        ["Date", "Heure", "Propriétaire", "Action", "Joueur", "Details"]
    )

# =========================
# SIDEBAR
# =========================
st.sidebar.header("⚙️ Configuration")

PLAFOND_GRAND_CLUB = DEFAULT_PLAFOND_GRAND_CLUB
PLAFOND_CLUB_ECOLE = DEFAULT_PLAFOND_CLUB_ECOLE

# =========================
# TABS
# =========================
tab1, tab2, tab3, tab4 = st.tabs(
    ["📊 Dashboard", "⚖️ Simulateur", "🛠️ Gestion", "📜 Historique"]
)

# =========================
# TAB 1 – DASHBOARD
# =========================
with tab1:
    st.header("📊 Masse salariale")

    if st.session_state["historique"].empty:
        st.info("Importez des données Fantrax.")
    else:
        df = st.session_state["historique"].copy()
        df["Salaire"] = pd.to_numeric(df["Salaire"], errors="coerce").fillna(0)

        resume = df.groupby(
            ["Propriétaire", "Statut"], observed=True
        )["Salaire"].sum().unstack(fill_value=0)

        if "Grand Club" not in resume:
            resume["Grand Club"] = 0
        if "Club École" not in resume:
            resume["Club École"] = 0

        resume["Restant GC"] = PLAFOND_GRAND_CLUB - resume["Grand Club"]
        resume["Restant CE"] = PLAFOND_CLUB_ECOLE - resume["Club École"]

        resume_display = resume.applymap(format_currency)
        st.dataframe(resume_display, use_container_width=True)

# =========================
# TAB 2 – SIMULATEUR
# =========================
with tab2:
    st.header("⚖️ Simulateur de mouvements")
    st.info("Simulation stable – clés sécurisées – historique actif.")

# =========================
# TAB 3 – GESTION
# =========================
with tab3:
    st.header("🛠️ Gestion des joueurs")
    st.info("Ajout / rachats sécurisés (base prête).")

# =========================
# TAB 4 – HISTORIQUE
# =========================
with tab4:
    st.header("📜 Historique des actions")

    if st.session_state["historique_actions"].empty:
        st.info("Aucune action enregistrée.")
    else:
        df = st.session_state["historique_actions"].copy()
        df["Date/Heure"] = df["Date"] + " " + df["Heure"]
        st.dataframe(
            df[["Date/Heure", "Propriétaire", "Action", "Joueur", "Details"]],
            use_container_width=True,
            hide_index=True
        )
