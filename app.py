import streamlit as st
import pandas as pd
import io
import os
import re
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
    "Canadiens": "Canadiens_Logo.png",
}
LOGO_SIZE = 55

# =====================================================
# STYLES CSS AMÉLIORÉS
# =====================================================
def inject_custom_css():
    st.markdown("""
    <style>
    /* Amélioration globale */
    .main .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
    }
    
    /* Headers stylisés */
    .custom-header {
        background: linear-gradient(90deg, #1e3a8a 0%, #3b82f6 100%);
        padding: 1.5rem;
        border-radius: 12px;
        margin-bottom: 1.5rem;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    
    /* Cards améliorées */
    .stat-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 1.5rem;
        border-radius: 12px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        transition: transform 0.2s, box-shadow 0.2s;
        margin-bottom: 1rem;
    }
    
    .stat-card:hover {
        transform: translateY(-4px);
        box-shadow: 0 8px 20px rgba(0,0,0,0.2);
    }
    
    .stat-card h3 {
        color: white;
        font-size: 1.1rem;
        margin: 0 0 0.5rem 0;
        font-weight: 600;
    }
    
    .stat-card .value {
        color: white;
        font-size: 2rem;
        font-weight: 700;
        margin: 0;
    }
    
    /* Tableaux modernisés */
    .stDataFrame {
        border-radius: 8px;
        overflow: hidden;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
    }
    
    /* Boutons améliorés */
    .stButton > button {
        border-radius: 8px;
        padding: 0.5rem 1.5rem;
        font-weight: 600;
        transition: all 0.2s;
        border: none;
    }
    
    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(0,0,0,0.2);
    }
    
    /* Section blessés */
    .injured-section {
        background: #1a1a1a;
        border: 2px solid #ff2d2d;
        border-radius: 12px;
        padding: 1.5rem;
        margin: 1.5rem 0;
        box-shadow: 0 4px 12px rgba(255,45,45,0.2);
    }
    
    .injured-header {
        color: #ff2d2d;
        font-size: 1.3rem;
        font-weight: 900;
        margin-bottom: 1rem;
        text-transform: uppercase;
        letter-spacing: 1px;
    }
    
    /* Badges de position */
    .pos-badge {
        display: inline-block;
        padding: 0.25rem 0.75rem;
        border-radius: 20px;
        font-weight: 700;
        font-size: 0.85rem;
        margin: 0.25rem;
    }
    
    .pos-F { background: #10b981; color: white; }
    .pos-D { background: #3b82f6; color: white; }
    .pos-G { background: #f59e0b; color: white; }
    
    /* Indicateurs de statut */
    .status-indicator {
        width: 12px;
        height: 12px;
        border-radius: 50%;
        display: inline-block;
        margin-right: 0.5rem;
        animation: pulse 2s infinite;
    }
    
    .status-active { background: #10b981; }
    .status-bench { background: #f59e0b; }
    .status-minor { background: #3b82f6; }
    .status-injured { background: #ef4444; }
    
    @keyframes pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.6; }
    }
    
    /* Responsive */
    @media (max-width: 768px) {
        .stat-card {
            padding: 1rem;
        }
        .stat-card .value {
            font-size: 1.5rem;
        }
        .main .block-container {
            padding-left: 1rem;
            padding-right: 1rem;
        }
    }
    
    /* Alert boxes */
    .alert-success {
        background: #d1fae5;
        border-left: 4px solid #10b981;
        padding: 1rem;
        border-radius: 8px;
        margin: 1rem 0;
    }
    
    .alert-warning {
        background: #fef3c7;
        border-left: 4px solid #f59e0b;
        padding: 1rem;
        border-radius: 8px;
        margin: 1rem 0;
    }
    
    .alert-danger {
        background: #fee2e2;
        border-left: 4px solid #ef4444;
        padding: 1rem;
        border-radius: 8px;
        margin: 1rem 0;
    }
    </style>
    """, unsafe_allow_html=True)

inject_custom_css()

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
# POSITIONS (F, D, G) + TRI
# =====================================================
def normalize_pos(pos: str) -> str:
    p = str(pos).upper()
    if "G" in p:
        return "G"
    if "D" in p:
        return "D"
    return "F"

def pos_sort_key(pos: str) -> int:
    return {"F": 0, "D": 1, "G": 2}.get(str(pos).upper(), 99)

def pos_badge(pos: str) -> str:
    """Retourne un badge HTML stylisé pour la position"""
    pos = normalize_pos(pos)
    return f'<span class="pos-badge pos-{pos}">{pos}</span>'

# =====================================================
# NETTOYAGE GLOBAL
# =====================================================
def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df

    for col in ["Propriétaire", "Joueur", "Salaire", "Statut", "Slot", "Pos", "Equipe"]:
        if col not in df.columns:
            df[col] = "" if col != "Salaire" else 0

    df["Propriétaire"] = df["Propriétaire"].astype(str).str.strip()
    df["Joueur"] = df["Joueur"].astype(str).str.strip()
    df["Pos"] = df["Pos"].astype(str).str.strip()
    df["Equipe"] = df["Equipe"].astype(str).str.strip()
    df["Statut"] = df["Statut"].astype(str).str.strip()
    df["Slot"] = df["Slot"].astype(str).str.strip()

    df["Slot"] = df["Slot"].replace(
        {"IR": "Blessé", "Blesse": "Blessé", "Blesses": "Blessé", "Injured": "Blessé"}
    )

    df["Salaire"] = (
        df["Salaire"]
        .astype(str)
        .str.replace("$", "", regex=False)
        .str.replace(" ", "", regex=False)
        .str.replace(",", "", regex=False)
        .replace(["None", "nan", "NaN", ""], "0")
    )
    df["Salaire"] = pd.to_numeric(df["Salaire"], errors="coerce").fillna(0).astype(int)

    df["Pos"] = df["Pos"].apply(normalize_pos)

    forbidden = {"none", "skaters", "goalies", "player", "null"}
    df = df[~df["Joueur"].str.lower().isin(forbidden)]
    df = df[df["Joueur"].str.len() > 2]

    df = df[
        ~(
            (df["Salaire"] <= 0)
            & (df["Equipe"].str.lower().isin(["none", "nan", "", "n/a"]))
        )
    ]

    mask_gc_default = (df["Statut"] == "Grand Club") & (df["Slot"].fillna("").eq(""))
    df.loc[mask_gc_default, "Slot"] = "Actif"

    mask_ce_not_inj = (df["Statut"] == "Club École") & (df["Slot"] != "Blessé")
    df.loc[mask_ce_not_inj, "Slot"] = ""

    df = df.drop_duplicates(subset=["Propriétaire", "Joueur"], keep="last")

    return df.reset_index(drop=True)

# =====================================================
# PARSER FANTRAX
# =====================================================
def parse_fantrax(upload):
    raw_lines = upload.read().decode("utf-8", errors="ignore").splitlines()
    raw_lines = [re.sub(r"[\x00-\x1f\x7f]", "", l) for l in raw_lines]

    def detect_sep(lines):
        for l in lines:
            low = l.lower()
            if "player" in low and "salary" in low:
                for d in [",", ";", "\t", "|"]:
                    if d in l:
                        return d
        return ","

    sep = detect_sep(raw_lines)

    header_idxs = [
        i for i, l in enumerate(raw_lines)
        if ("player" in l.lower() and "salary" in l.lower() and sep in l)
    ]
    if not header_idxs:
        raise ValueError("Aucune section Fantrax valide détectée (Player / Salary).")

    def read_section(start, end):
        lines = raw_lines[start:end]
        lines = [l for l in lines if l.strip() != ""]
        if len(lines) < 2:
            return None
        dfp = pd.read_csv(
            io.StringIO("\n".join(lines)),
            sep=sep,
            engine="python",
            on_bad_lines="skip",
        )
        dfp.columns = [c.strip().replace('"', "") for c in dfp.columns]
        return dfp

    parts = []
    for i, h in enumerate(header_idxs):
        end = header_idxs[i + 1] if i + 1 < len(header_idxs) else len(raw_lines)
        dfp = read_section(h, end)
        if dfp is not None and not dfp.empty:
            parts.append(dfp)

    if not parts:
        raise ValueError("Sections Fantrax détectées mais aucune donnée exploitable.")

    df = pd.concat(parts, ignore_index=True)

    def find_col(possibles):
        for p in possibles:
            for c in df.columns:
                if p in c.lower():
                    return c
        return None

    player_col = find_col(["player"])
    salary_col = find_col(["salary"])
    team_col = find_col(["team"])
    pos_col = find_col(["pos"])
    status_col = find_col(["status"])

    if not player_col or not salary_col:
        raise ValueError(f"Colonnes Player/Salary introuvables. Colonnes trouvées: {list(df.columns)}")

    out = pd.DataFrame()
    out["Joueur"] = df[player_col].astype(str).str.strip()
    out["Equipe"] = df[team_col].astype(str).str.strip() if team_col else "N/A"
    out["Pos"] = df[pos_col].astype(str).str.strip() if pos_col else "F"
    out["Pos"] = out["Pos"].apply(normalize_pos)

    sal = (
        df[salary_col]
        .astype(str)
        .str.replace(",", "", regex=False)
        .str.replace(" ", "", regex=False)
        .replace(["None", "nan", "NaN", ""], "0")
    )
    out["Salaire"] = pd.to_numeric(sal, errors="coerce").fillna(0).astype(int) * 1000

    if status_col:
        out["Statut"] = df[status_col].apply(
            lambda x: "Club École" if "min" in str(x).lower() else "Grand Club"
        )
    else:
        out["Statut"] = "Grand Club"

    out["Slot"] = out["Statut"].apply(lambda s: "Actif" if s == "Grand Club" else "")
    return clean_data(out)

# =====================================================
# CAP HELPERS
# =====================================================
def counted_bucket(statut: str, slot: str):
    if str(slot).strip() == "Blessé":
        return None
    if statut == "Grand Club":
        return "GC"
    if statut == "Club École":
        return "CE"
    return None

def is_counted_label(statut: str, slot: str) -> str:
    return "✅ Compté" if counted_bucket(statut, slot) in ("GC", "CE") else "🩹 Non compté (Blessé)"

# =====================================================
# HISTORIQUE HELPERS
# =====================================================
def load_history(history_file: str) -> pd.DataFrame:
    if os.path.exists(history_file):
        h = pd.read_csv(history_file)
    else:
        h = pd.DataFrame(columns=[
            "id", "timestamp", "season",
            "proprietaire", "joueur", "pos", "equipe",
            "from_statut", "from_slot",
            "to_statut", "to_slot",
            "action"
        ])
    return h

def save_history(history_file: str, h: pd.DataFrame):
    h.to_csv(history_file, index=False)

def next_hist_id(h: pd.DataFrame) -> int:
    if h.empty or "id" not in h.columns:
        return 1
    return int(pd.to_numeric(h["id"], errors="coerce").fillna(0).max()) + 1

def log_history_row(proprietaire, joueur, pos, equipe,
                    from_statut, from_slot,
                    to_statut, to_slot,
                    action):
    h = st.session_state["history"].copy()
    row = {
        "id": next_hist_id(h),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "season": st.session_state["season"],
        "proprietaire": proprietaire,
        "joueur": joueur,
        "pos": pos,
        "equipe": equipe,
        "from_statut": from_statut,
        "from_slot": from_slot,
        "to_statut": to_statut,
        "to_slot": to_slot,
        "action": action,
    }
    h = pd.concat([h, pd.DataFrame([row])], ignore_index=True)
    st.session_state["history"] = h
    save_history(st.session_state.get("HISTORY_FILE", "history.csv"), h)

def apply_move_with_history(proprietaire: str, joueur: str, to_statut: str, to_slot: str, action_label: str):
    mask = (
        (st.session_state["data"]["Propriétaire"] == proprietaire)
        & (st.session_state["data"]["Joueur"] == joueur)
    )
    if st.session_state["data"][mask].empty:
        st.error("Joueur introuvable.")
        return False

    before = st.session_state["data"][mask].iloc[0]
    from_statut, from_slot = str(before["Statut"]), str(before["Slot"])
    pos0, equipe0 = str(before["Pos"]), str(before["Equipe"])

    st.session_state["data"].loc[mask, "Statut"] = to_statut
    st.session_state["data"].loc[mask, "Slot"] = to_slot if str(to_slot).strip() else ""
    st.session_state["data"] = clean_data(st.session_state["data"])
    st.session_state["data"].to_csv(st.session_state.get("DATA_FILE", "data.csv"), index=False)

    log_history_row(
        proprietaire, joueur, pos0, equipe0,
        from_statut, from_slot,
        to_statut, (to_slot if str(to_slot).strip() else ""),
        action=action_label
    )
    return True

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
HISTORY_FILE = f"{DATA_DIR}/history_{season}.csv"

st.session_state["DATA_FILE"] = DATA_FILE
st.session_state["HISTORY_FILE"] = HISTORY_FILE

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
# DATA LOAD
# =====================================================
if "season" not in st.session_state or st.session_state["season"] != season:
    if os.path.exists(DATA_FILE):
        st.session_state["data"] = pd.read_csv(DATA_FILE)
    else:
        st.session_state["data"] = pd.DataFrame(
            columns=["Propriétaire", "Joueur", "Salaire", "Statut", "Slot", "Pos", "Equipe"]
        )

    if "Slot" not in st.session_state["data"].columns:
        st.session_state["data"]["Slot"] = ""

    st.session_state["data"] = clean_data(st.session_state["data"])
    st.session_state["data"].to_csv(DATA_FILE, index=False)
    st.session_state["season"] = season

if "history_season" not in st.session_state or st.session_state["history_season"] != season:
    st.session_state["history"] = load_history(HISTORY_FILE)
    st.session_state["history_season"] = season

# =====================================================
# IMPORT FANTRAX
# =====================================================
st.sidebar.header("📥 Import Fantrax")
uploaded = st.sidebar.file_uploader(
    "CSV Fantrax",
    type=["csv", "txt"],
    help="Import autorisé seulement pour la saison courante ou future",
)

if uploaded:
    if LOCKED:
        st.sidebar.warning("🔒 Saison verrouillée : import désactivé.")
    else:
        try:
            df_import = parse_fantrax(uploaded)
            if df_import.empty:
                st.sidebar.error("❌ Import invalide : aucune donnée Fantrax exploitable.")
                st.stop()

            owner = os.path.splitext(uploaded.name)[0]
            df_import["Propriétaire"] = owner

            st.session_state["data"] = pd.concat([st.session_state["data"], df_import], ignore_index=True)
            st.session_state["data"] = clean_data(st.session_state["data"])
            st.session_state["data"].to_csv(DATA_FILE, index=False)

            st.sidebar.success("✅ Import réussi")
        except Exception as e:
            st.sidebar.error(f"❌ Import échoué : {e}")
            st.stop()

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
# CALCULS PLAFONDS
# =====================================================
resume = []
for p in df["Propriétaire"].unique():
    d = df[df["Propriétaire"] == p]
    gc_sum = d[(d["Statut"] == "Grand Club") & (d["Slot"] != "Blessé")]["Salaire"].sum()
    ce_sum = d[(d["Statut"] == "Club École") & (d["Slot"] != "Blessé")]["Salaire"].sum()

    logo = ""
    for k, v in LOGOS.items():
        if k.lower() in str(p).lower():
            logo = v

    resume.append(
        {
            "Propriétaire": p,
            "Logo": logo,
            "GC": int(gc_sum),
            "CE": int(ce_sum),
            "Restant GC": int(st.session_state["PLAFOND_GC"] - gc_sum),
            "Restant CE": int(st.session_state["PLAFOND_CE"] - ce_sum),
        }
    )

plafonds = pd.DataFrame(resume)

# =====================================================
# ONGLETS
# =====================================================
tab1, tabA, tabH, tab2, tab3 = st.tabs(
    ["📊 Tableau", "🧾 Alignement", "🕘 Historique", "⚖️ Transactions", "🧠 Recommandations"]
)

# =====================================================
# TABLEAU
# =====================================================
with tab1:
    headers = st.columns([4, 2, 2, 2, 2])
    headers[0].markdown("**Équipe**")
    headers[1].markdown("**Grand Club**")
    headers[2].markdown("**Restant GC**")
    headers[3].markdown("**Club École**")
    headers[4].markdown("**Restant CE**")

    for _, r in plafonds.iterrows():
        cols = st.columns([4, 2, 2, 2, 2])

        owner = str(r["Propriétaire"])
        logo_path = str(r["Logo"]).strip()

        with cols[0]:
            a, b = st.columns([1, 4])
            if logo_path and os.path.exists(logo_path):
                a.image(logo_path, width=LOGO_SIZE)
            else:
                a.markdown("—")
            b.markdown(f"**{owner}**")

        cols[1].markdown(money(r["GC"]))
        cols[2].markdown(money(r["Restant GC"]))
        cols[3].markdown(money(r["CE"]))
        cols[4].markdown(money(r["Restant CE"]))

# =====================================================
# ALIGNEMENT AMÉLIORÉ
# =====================================================
with tabA:
    st.subheader("🧾 Alignement")
    
    # Initialize move_player state
    if "move_player" not in st.session_state:
        st.session_state["move_player"] = None
    
    proprietaire = st.selectbox(
        "Propriétaire",
        sorted(st.session_state["data"]["Propriétaire"].unique()),
        key="align_owner",
    )

    st.session_state["data"] = clean_data(st.session_state["data"])
    data_all = st.session_state["data"]
    dprop = data_all[data_all["Propriétaire"] == proprietaire].copy()

    injured_all = dprop[dprop["Slot"] == "Blessé"].copy()
    dprop_not_inj = dprop[dprop["Slot"] != "Blessé"].copy()

    gc_all = dprop_not_inj[dprop_not_inj["Statut"] == "Grand Club"].copy()
    ce_all = dprop_not_inj[dprop_not_inj["Statut"] == "Club École"].copy()

    gc_actif = gc_all[gc_all["Slot"] == "Actif"].copy()
    gc_banc = gc_all[gc_all["Slot"] == "Banc"].copy()

    nb_F = int((gc_actif["Pos"] == "F").sum())
    nb_D = int((gc_actif["Pos"] == "D").sum())
    nb_G = int((gc_actif["Pos"] == "G").sum())
    total_actifs = nb_F + nb_D + nb_G

    total_gc = int(gc_all["Salaire"].sum())
    total_ce = int(ce_all["Salaire"].sum())
    restant_gc = int(st.session_state["PLAFOND_GC"] - total_gc)
    restant_ce = int(st.session_state["PLAFOND_CE"] - total_ce)

    # Stats cards
    cols_stats = st.columns(5)
    with cols_stats[0]:
        st.markdown(f"""
        <div class="stat-card">
            <h3>💰 GC Total</h3>
            <p class="value">{money(total_gc)}</p>
        </div>
        """, unsafe_allow_html=True)
    
    with cols_stats[1]:
        color = "linear-gradient(135deg, #10b981 0%, #059669 100%)" if restant_gc >= 0 else "linear-gradient(135deg, #ef4444 0%, #dc2626 100%)"
        st.markdown(f"""
        <div class="stat-card" style="background: {color};">
            <h3>📊 Restant GC</h3>
            <p class="value">{money(restant_gc)}</p>
        </div>
        """, unsafe_allow_html=True)
    
    with cols_stats[2]:
        st.markdown(f"""
        <div class="stat-card">
            <h3>🏫 CE Total</h3>
            <p class="value">{money(total_ce)}</p>
        </div>
        """, unsafe_allow_html=True)
    
    with cols_stats[3]:
        color = "linear-gradient(135deg, #10b981 0%, #059669 100%)" if restant_ce >= 0 else "linear-gradient(135deg, #ef4444 0%, #dc2626 100%)"
        st.markdown(f"""
        <div class="stat-card" style="background: {color};">
            <h3>📊 Restant CE</h3>
            <p class="value">{money(restant_ce)}</p>
        </div>
        """, unsafe_allow_html=True)
    
    with cols_stats[4]:
        st.markdown(f"""
        <div class="stat-card" style="background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%);">
            <h3>🩹 Blessés</h3>
            <p class="value">{len(injured_all)}</p>
        </div>
        """, unsafe_allow_html=True)

    st.caption(f"**Actifs:** F {nb_F}/12 • D {nb_D}/6 • G {nb_G}/2 • Total {total_actifs}/20")
    st.divider()

    def view_for_display(x: pd.DataFrame, show_buttons=True) -> pd.DataFrame:
        if x is None or x.empty:
            return pd.DataFrame(columns=["Joueur", "Pos", "Equipe", "Salaire"])
        y = x.copy()
        y["_pos_order"] = y["Pos"].apply(pos_sort_key)
        y = y.sort_values(["_pos_order", "Joueur"]).drop(columns=["_pos_order"])
        y["Salaire"] = y["Salaire"].apply(money)
        return y[["Joueur", "Pos", "Equipe", "Salaire"]].reset_index(drop=True)

    # Section des tableaux avec boutons
    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("### 🟢 Actifs")
        df_actifs_ui = view_for_display(gc_actif)
        if not df_actifs_ui.empty:
            for idx, row in df_actifs_ui.iterrows():
                cols_row = st.columns([3, 1, 1, 2, 1])
                cols_row[0].write(row["Joueur"])
                cols_row[1].markdown(pos_badge(row["Pos"]), unsafe_allow_html=True)
                cols_row[2].write(row["Equipe"])
                cols_row[3].write(row["Salaire"])
                if cols_row[4].button("⚙️", key=f"btn_actif_{idx}", help="Déplacer ce joueur"):
                    st.session_state["move_player"] = {
                        "joueur": row["Joueur"],
                        "source": "Actif",
                        "proprietaire": proprietaire
                    }
                    st.rerun()
        else:
            st.info("Aucun joueur actif")

    with col2:
        st.markdown("### 🟡 Banc")
        df_banc_ui = view_for_display(gc_banc)
        if not df_banc_ui.empty:
            for idx, row in df_banc_ui.iterrows():
                cols_row = st.columns([3, 1, 1, 2, 1])
                cols_row[0].write(row["Joueur"])
                cols_row[1].markdown(pos_badge(row["Pos"]), unsafe_allow_html=True)
                cols_row[2].write(row["Equipe"])
                cols_row[3].write(row["Salaire"])
                if cols_row[4].button("⚙️", key=f"btn_banc_{idx}", help="Déplacer ce joueur"):
                    st.session_state["move_player"] = {
                        "joueur": row["Joueur"],
                        "source": "Banc",
                        "proprietaire": proprietaire
                    }
                    st.rerun()
        else:
            st.info("Aucun joueur au banc")

    with col3:
        st.markdown("### 🔵 Mineur")
        df_min_ui = view_for_display(ce_all)
        if not df_min_ui.empty:
            for idx, row in df_min_ui.iterrows():
                cols_row = st.columns([3, 1, 1, 2, 1])
                cols_row[0].write(row["Joueur"])
                cols_row[1].markdown(pos_badge(row["Pos"]), unsafe_allow_html=True)
                cols_row[2].write(row["Equipe"])
                cols_row[3].write(row["Salaire"])
                if cols_row[4].button("⚙️", key=f"btn_min_{idx}", help="Déplacer ce joueur"):
                    st.session_state["move_player"] = {
                        "joueur": row["Joueur"],
                        "source": "Mineur",
                        "proprietaire": proprietaire
                    }
                    st.rerun()
        else:
            st.info("Aucun joueur au mineur")

    st.divider()

    # Section Blessés
    st.markdown('<div class="injured-section">', unsafe_allow_html=True)
    st.markdown('<div class="injured-header">🩹 JOUEURS BLESSÉS (IR)</div>', unsafe_allow_html=True)
    
    df_inj_ui = view_for_display(injured_all)
    if df_inj_ui.empty:
        st.info("Aucun joueur blessé")
    else:
        for idx, row in df_inj_ui.iterrows():
            cols_row = st.columns([3, 1, 1, 2, 1])
            cols_row[0].markdown(f"**{row['Joueur']}**")
            cols_row[1].markdown(pos_badge(row["Pos"]), unsafe_allow_html=True)
            cols_row[2].markdown(f"**{row['Equipe']}**")
            cols_row[3].markdown(f"**{row['Salaire']}**")
            if cols_row[4].button("⚙️", key=f"btn_inj_{idx}", help="Déplacer ce joueur"):
                st.session_state["move_player"] = {
                    "joueur": row["Joueur"],
                    "source": "Blessé",
                    "proprietaire": proprietaire
                }
                st.rerun()
    
    st.markdown('</div>', unsafe_allow_html=True)

    # Interface de déplacement
    if st.session_state.get("move_player"):
        move_info = st.session_state["move_player"]
        joueur_sel = move_info["joueur"]
        
        if LOCKED:
            st.warning("🔒 Saison verrouillée : aucun changement permis.")
            if st.button("Fermer"):
                st.session_state["move_player"] = None
                st.rerun()
        else:
            mask_sel = (
                (st.session_state["data"]["Propriétaire"] == proprietaire)
                & (st.session_state["data"]["Joueur"] == joueur_sel)
            )

            if st.session_state["data"][mask_sel].empty:
                st.error("Joueur introuvable")
                st.session_state["move_player"] = None
            else:
                cur = st.session_state["data"][mask_sel].iloc[0]
                cur_statut = str(cur["Statut"])
                cur_slot = str(cur["Slot"])
                cur_pos = str(cur["Pos"])
                cur_equipe = str(cur["Equipe"])
                cur_salaire = int(cur["Salaire"])

                st.markdown("---")
                st.markdown(f"### ⚙️ Déplacement de joueur")
                
                cols_info = st.columns([2, 1, 1, 2, 2])
                cols_info[0].markdown(f"**Joueur:** {joueur_sel}")
                cols_info[1].markdown(pos_badge(cur_pos), unsafe_allow_html=True)
                cols_info[2].markdown(f"**{cur_equipe}**")
                cols_info[3].markdown(f"**{money(cur_salaire)}**")
                cols_info[4].markdown(f"**{cur_statut}** • **{cur_slot if cur_slot else '—'}**")

                def can_add_to_actif(pos: str):
                    pos = normalize_pos(pos)
                    if pos == "F" and nb_F >= 12:
                        return False, "🚫 Déjà 12 F actifs."
                    if pos == "D" and nb_D >= 6:
                        return False, "🚫 Déjà 6 D actifs."
                    if pos == "G" and nb_G >= 2:
                        return False, "🚫 Déjà 2 G actifs."
                    return True, ""

                def projected_counts(cur_statut, cur_slot, pos, to_statut, to_slot):
                    f, d, g = nb_F, nb_D, nb_G
                    pos = normalize_pos(pos)

                    if cur_statut == "Grand Club" and cur_slot == "Actif":
                        if pos == "F":
                            f -= 1
                        elif pos == "D":
                            d -= 1
                        else:
                            g -= 1

                    if to_statut == "Grand Club" and to_slot == "Actif":
                        if pos == "F":
                            f += 1
                        elif pos == "D":
                            d += 1
                        else:
                            g += 1

                    return f, d, g

                def projected_totals(salaire_player, cur_statut, cur_slot, to_statut, to_slot):
                    pgc, pce = total_gc, total_ce
                    s = int(salaire_player)

                    from_bucket = counted_bucket(cur_statut, cur_slot)
                    to_bucket = counted_bucket(to_statut, to_slot)

                    if from_bucket == "GC":
                        pgc -= s
                    elif from_bucket == "CE":
                        pce -= s

                    if to_bucket == "GC":
                        pgc += s
                    elif to_bucket == "CE":
                        pce += s

                    return int(pgc), int(pce)

                # Options de déplacement
                options = []

                if cur_slot != "Blessé":
                    options.append(("🩹 Joueurs Blessés (IR)", (cur_statut, "Blessé", "→ Blessé (IR)")))

                ok_actif, _msg = can_add_to_actif(cur_pos)

                if cur_slot == "Blessé":
                    options.append(("🔵 Mineur", ("Club École", "", "Blessé → Mineur")))
                    options.append(("🟡 Grand Club / Banc", ("Grand Club", "Banc", "Blessé → GC (Banc)")))
                    if ok_actif:
                        options.append(("🟢 Grand Club / Actif", ("Grand Club", "Actif", "Blessé → GC (Actif)")))
                else:
                    if cur_statut == "Club École":
                        options.append(("🔵 Mineur", ("Club École", "", "Rester Mineur")))
                        options.append(("🟡 Grand Club / Banc", ("Grand Club", "Banc", "Mineur → GC (Banc)")))
                        if ok_actif:
                            options.append(("🟢 Grand Club / Actif", ("Grand Club", "Actif", "Mineur → GC (Actif)")))
                    else:
                        options.append(("🔵 Mineur", ("Club École", "", "GC → Mineur")))
                        if cur_slot == "Actif":
                            options.append(("🟡 Grand Club / Banc", ("Grand Club", "Banc", "Actif → Banc")))
                        elif cur_slot == "Banc":
                            if ok_actif:
                                options.append(("🟢 Grand Club / Actif", ("Grand Club", "Actif", "Banc → Actif")))

                seen = set()
                final = []
                for lbl, payload in options:
                    if lbl not in seen:
                        seen.add(lbl)
                        final.append((lbl, payload))
                options = final

                labels = [o[0] for o in options]
                choice = st.radio("Choisir la destination", labels, key="move_destination")
                to_statut, to_slot, action_label = dict(options)[choice]

                # Aperçu
                pf, pd_, pg = projected_counts(cur_statut, cur_slot, cur_pos, to_statut, to_slot)
                pgc, pce = projected_totals(cur_salaire, cur_statut, cur_slot, to_statut, to_slot)
                pr_gc = int(st.session_state["PLAFOND_GC"] - pgc)
                pr_ce = int(st.session_state["PLAFOND_CE"] - pce)

                st.markdown("**📊 Aperçu après le déplacement:**")
                cols_preview = st.columns(2)
                with cols_preview[0]:
                    st.markdown(f"**Actifs:** F {pf}/12 • D {pd_}/6 • G {pg}/2 • Total {pf+pd_+pg}/20")
                with cols_preview[1]:
                    st.markdown(f"**Cap:** GC {money(pgc)} (Restant: {money(pr_gc)}) • CE {money(pce)} (Restant: {money(pr_ce)})")

                if pr_gc < 0:
                    st.markdown('<div class="alert-danger">🚨 <strong>Attention:</strong> Plafond GC dépassé!</div>', unsafe_allow_html=True)
                if pr_ce < 0:
                    st.markdown('<div class="alert-danger">🚨 <strong>Attention:</strong> Plafond CE dépassé!</div>', unsafe_allow_html=True)

                cols_actions = st.columns([1, 1, 4])
                
                if cols_actions[0].button("✅ Confirmer", type="primary"):
                    if to_statut == "Grand Club" and to_slot == "Actif":
                        ok, msg = can_add_to_actif(cur_pos)
                        if not ok:
                            st.error(msg)
                        else:
                            ok2 = apply_move_with_history(
                                proprietaire=proprietaire,
                                joueur=joueur_sel,
                                to_statut=to_statut,
                                to_slot=to_slot,
                                action_label=action_label,
                            )
                            if ok2:
                                st.session_state["move_player"] = None
                                st.success("✅ Déplacement enregistré!")
                                st.rerun()
                    else:
                        ok2 = apply_move_with_history(
                            proprietaire=proprietaire,
                            joueur=joueur_sel,
                            to_statut=to_statut,
                            to_slot=to_slot,
                            action_label=action_label,
                        )
                        if ok2:
                            st.session_state["move_player"] = None
                            st.success("✅ Déplacement enregistré!")
                            st.rerun()

                if cols_actions[1].button("❌ Annuler"):
                    st.session_state["move_player"] = None
                    st.rerun()

# =====================================================
# HISTORIQUE
# =====================================================
with tabH:
    st.subheader("🕘 Historique des changements d'alignement")

    h = st.session_state["history"].copy()
    if h.empty:
        st.info("Aucune entrée d'historique pour cette saison.")
    else:
        owners = ["Tous"] + sorted(h["proprietaire"].dropna().astype(str).unique().tolist())
        owner_filter = st.selectbox("Filtrer par propriétaire", owners, key="hist_owner_filter")

        if owner_filter != "Tous":
            h = h[h["proprietaire"].astype(str) == owner_filter]

        if h.empty:
            st.info("Aucune entrée pour ce propriétaire.")
        else:
            h["timestamp_dt"] = pd.to_datetime(h["timestamp"], errors="coerce")
            h = h.sort_values("timestamp_dt", ascending=False).drop(columns=["timestamp_dt"])

            st.caption("↩️ = annuler ce changement • ❌ = supprimer l'entrée")

            head = st.columns([1.5, 1.4, 2.4, 1.0, 1.5, 1.5, 1.6, 0.8, 0.7])
            head[0].markdown("**Date/Heure**")
            head[1].markdown("**Propriétaire**")
            head[2].markdown("**Joueur**")
            head[3].markdown("**Pos**")
            head[4].markdown("**De**")
            head[5].markdown("**Vers**")
            head[6].markdown("**Action**")
            head[7].markdown("**↩️**")
            head[8].markdown("**❌**")

            for _, r in h.iterrows():
                rid = int(r["id"])
                cols = st.columns([1.5, 1.4, 2.4, 1.0, 1.5, 1.5, 1.6, 0.8, 0.7])

                cols[0].markdown(str(r["timestamp"]))
                cols[1].markdown(str(r["proprietaire"]))
                cols[2].markdown(str(r["joueur"]))
                cols[3].markdown(str(r["pos"]))

                de = f"{r['from_statut']}" + (f" ({r['from_slot']})" if str(r["from_slot"]).strip() else "")
                vers = f"{r['to_statut']}" + (f" ({r['to_slot']})" if str(r["to_slot"]).strip() else "")
                cols[4].markdown(de)
                cols[5].markdown(vers)
                cols[6].markdown(str(r.get("action", "")))

                if cols[7].button("↩️", key=f"undo_{rid}"):
                    if LOCKED:
                        st.error("🔒 Saison verrouillée : annulation impossible.")
                    else:
                        owner = str(r["proprietaire"])
                        joueur = str(r["joueur"])

                        mask = (
                            (st.session_state["data"]["Propriétaire"] == owner)
                            & (st.session_state["data"]["Joueur"] == joueur)
                        )

                        if st.session_state["data"][mask].empty:
                            st.error("Impossible d'annuler : joueur introuvable.")
                        else:
                            before = st.session_state["data"][mask].iloc[0]
                            cur_statut, cur_slot = str(before["Statut"]), str(before["Slot"])
                            pos0, equipe0 = str(before["Pos"]), str(before["Equipe"])

                            st.session_state["data"].loc[mask, "Statut"] = str(r["from_statut"])
                            st.session_state["data"].loc[mask, "Slot"] = str(r["from_slot"]) if str(r["from_slot"]).strip() else ""
                            st.session_state["data"] = clean_data(st.session_state["data"])
                            st.session_state["data"].to_csv(DATA_FILE, index=False)

                            log_history_row(
                                owner, joueur, pos0, equipe0,
                                cur_statut, cur_slot,
                                str(r["from_statut"]),
                                (str(r["from_slot"]) if str(r["from_slot"]).strip() else ""),
                                action=f"UNDO #{rid}"
                            )

                            st.success("✅ Annulation effectuée.")
                            st.rerun()

                if cols[8].button("❌", key=f"del_{rid}"):
                    h2 = st.session_state["history"].copy()
                    h2 = h2[h2["id"] != rid]
                    st.session_state["history"] = h2
                    save_history(HISTORY_FILE, h2)
                    st.success("🗑️ Entrée supprimée.")
                    st.rerun()

# =====================================================
# TRANSACTIONS
# =====================================================
with tab2:
    st.subheader("⚖️ Simulateur de transactions")
    
    p = st.selectbox("Propriétaire", plafonds["Propriétaire"], key="tx_owner")
    salaire = st.number_input("Salaire du joueur", min_value=0, step=100000, key="tx_salary")
    statut = st.radio("Statut", ["Grand Club", "Club École"], key="tx_statut")

    ligne = plafonds[plafonds["Propriétaire"] == p].iloc[0]
    reste = ligne["Restant GC"] if statut == "Grand Club" else ligne["Restant CE"]

    if salaire > reste:
        st.markdown('<div class="alert-danger">🚨 <strong>Transaction invalide:</strong> Dépassement du plafond</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="alert-success">✅ <strong>Transaction valide:</strong> Espace disponible</div>', unsafe_allow_html=True)

# =====================================================
# RECOMMANDATIONS
# =====================================================
with tab3:
    st.subheader("🧠 Recommandations")
    
    has_recommendations = False
    
    for _, r in plafonds.iterrows():
        if r["Restant GC"] < 2_000_000:
            st.markdown(f'<div class="alert-warning">⚠️ <strong>{r["Propriétaire"]}:</strong> Espace salarial GC limité - rétrogradation recommandée</div>', unsafe_allow_html=True)
            has_recommendations = True
        if r["Restant CE"] > 10_000_000:
            st.markdown(f'<div class="alert-success">💡 <strong>{r["Propriétaire"]}:</strong> Espace CE disponible - rappel possible</div>', unsafe_allow_html=True)
            has_recommendations = True
    
    if not has_recommendations:
        st.info("Aucune recommandation pour le moment. Tous les plafonds sont bien gérés! 👍")
