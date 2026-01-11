import streamlit as st
import pandas as pd
import os

# =====================================================
# CONFIG
# =====================================================
st.set_page_config(page_title="Pool Hockey – Alignement", layout="wide")

DATA_DIR = "/tmp/poolhockey_data"
os.makedirs(DATA_DIR, exist_ok=True)

ROSTER_FILE = os.path.join(DATA_DIR, "roster.csv")
PLAYERS_FILE = "hockey.players.csv"   # doit contenir la colonne Level (STD / ELC)

# =====================================================
# HELPERS
# =====================================================
def money(x):
    try:
        return f"{int(x):,} $".replace(",", " ")
    except Exception:
        return "—"

def pos_rank(pos):
    p = str(pos or "").upper()
    if "F" in p: return 0
    if "D" in p: return 1
    if "G" in p: return 2
    return 9

def style_level(val):
    v = str(val or "").upper()
    if v == "ELC":
        return "color:#a78bfa; font-weight:800;"   # violet
    if v == "STD":
        return "color:#60a5fa; font-weight:800;"   # bleu
    return "color:#9ca3af;"

def pill(label, kind="ok"):
    colors = {
        "ok": "#22c55e",
        "warn": "#f59e0b",
        "danger": "#ef4444",
    }
    c = colors.get(kind, "#9ca3af")
    return f"""
    <span style="
        display:inline-flex;
        align-items:center;
        gap:.4rem;
        padding:.25rem .55rem;
        border-radius:999px;
        font-size:.8rem;
        border:1px solid {c};
        color:{c};
        margin-right:.4rem;
    ">
        ● {label}
    </span>
    """

# =====================================================
# LOAD DATA
# =====================================================
@st.cache_data(show_spinner=False)
def load_players():
    return pd.read_csv(PLAYERS_FILE)

def load_roster():
    if os.path.exists(ROSTER_FILE):
        return pd.read_csv(ROSTER_FILE)
    return pd.DataFrame()

def save_roster(df):
    df.to_csv(ROSTER_FILE, index=False)

players = load_players()
df = load_roster()

st.session_state.setdefault("data", df)

# =====================================================
# SIDEBAR — IMPORT
# =====================================================
st.sidebar.title("⚙️ Importation")

uploaded = st.sidebar.file_uploader("Importer alignement (CSV)", type=["csv"])
if uploaded:
    df = pd.read_csv(uploaded)
    save_roster(df)
    st.session_state["data"] = df
    st.sidebar.success("Importation réussie.")
    st.rerun()

df = st.session_state["data"]

if df.empty:
    st.info("Importe un fichier d’alignement pour commencer.")
    st.stop()

# =====================================================
# MERGE LEVEL (STD / ELC) — SOURCE: hockey.players.csv
# =====================================================
if "Level" not in df.columns:
    df = df.merge(
        players[["Joueur", "Level"]],
        on="Joueur",
        how="left"
    )

# =====================================================
# FILTRES
# =====================================================
owner = st.selectbox(
    "Propriétaire",
    sorted(df["Propriétaire"].astype(str).unique())
)

d = df[df["Propriétaire"] == owner].copy()

# =====================================================
# COUNTS FOR PILLS
# =====================================================
nb_actifs = len(d[(d["Statut"] == "GC") & (d["Slot"] == "Actifs")])
nb_banc   = len(d[(d["Statut"] == "GC") & (d["Slot"] == "Banc")])
nb_min    = len(d[d["Statut"] == "CE"])
nb_ir     = len(d[d["Statut"] == "IR"])

st.markdown(
    pill(f"Actifs {nb_actifs}", "ok")
    + pill(f"Banc {nb_banc}", "warn" if nb_banc else "ok")
    + pill(f"Mineur {nb_min}", "ok")
    + pill(f"IR {nb_ir}", "danger" if nb_ir else "ok"),
    unsafe_allow_html=True,
)

st.divider()

# =====================================================
# RENDER SECTION
# =====================================================
def render_section(title, data):
    st.markdown(
        f"""
        <div style="
            background:#e5e7eb;
            color:#111827;
            padding:8px 12px;
            border-radius:10px;
            font-weight:800;
            margin-top:12px;
        ">
            {title}
        </div>
        """,
        unsafe_allow_html=True,
    )

    if data.empty:
        st.caption("Aucun joueur.")
        return

    data["_pos"] = data["Pos"].astype(str)
    data["_rank"] = data["_pos"].apply(pos_rank)
    data["_sal"] = pd.to_numeric(data["Salaire"], errors="coerce").fillna(0)

    data = data.sort_values(
        ["_rank", "_sal"],
        ascending=[True, False]
    )

    view = pd.DataFrame({
        "Pos": data["Pos"],
        "Éq.": data["Équipe"],
        "Nom": data["Joueur"],
        "Lev.": data["Level"].str.upper(),
        "Sal": data["Salaire"].apply(money),
    })

    styled = view.style.applymap(style_level, subset=["Lev."])
    st.dataframe(styled, use_container_width=True, hide_index=True)

# =====================================================
# SECTIONS
# =====================================================
render_section("JOUEURS ACTIFS", d[(d["Statut"] == "GC") & (d["Slot"] == "Actifs")])
render_section("JOUEURS DE RÉSERVE (BANC)", d[(d["Statut"] == "GC") & (d["Slot"] == "Banc")])
render_section("JOUEURS MINEURS", d[d["Statut"] == "CE"])
render_section("JOUEURS BLESSÉS (IR)", d[d["Statut"] == "IR"])
