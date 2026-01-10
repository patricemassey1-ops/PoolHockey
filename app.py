# =====================================================
# app.py — PMS Pool (clean + requested improvements)
#   ✅ Retrait du mode mobile
#   ✅ Équipe cliquable dans Tableau (sync sidebar)
#   ✅ Level injecté depuis data/Hockey_Players.csv (ou Hockey.Players.csv)
#   ✅ Historique complet: season/pos/equipe/level visibles
#   ✅ Retrait auto-remplacement
#   ✅ Transactions: expéditeur + receveur + picks (1-7 échangeables) + salaire retenu (GC/CE)
# =====================================================

import os, io, re, json, html, secrets, hashlib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

# =====================================================
# STREAMLIT CONFIG
# =====================================================
st.set_page_config(page_title="PMS", layout="wide")

# =====================================================
# CONSTANTS / PATHS
# =====================================================
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

# players db: accepter les 2 noms
PLAYERS_DB_FILE_A = os.path.join(DATA_DIR, "Hockey_Players.csv")
PLAYERS_DB_FILE_B = os.path.join(DATA_DIR, "Hockey.Players.csv")

LOGO_POOL_FILE = os.path.join(DATA_DIR, "Logo_Pool.png")
INIT_MANIFEST_FILE = os.path.join(DATA_DIR, "init_manifest.json")

REQUIRED_COLS = ["Propriétaire","Joueur","Pos","Equipe","Salaire","Statut","Slot","IR Date","Level"]

# Slots / Statuts
SLOT_ACTIF = "Actif"
SLOT_BANC  = "Banc"
SLOT_IR    = "IR"

STATUT_GC  = "Grand Club"
STATUT_CE  = "Club École"

TZ_LOCAL = ZoneInfo("America/Montreal")

# =====================================================
# THEME (single injection)
# =====================================================
def apply_theme():
    st.markdown(
        """
        <style>
        :root{color-scheme:dark;}
        .stApp{background:#0f172a;color:#e5e7eb;}
        [data-testid="stSidebar"]{background:#111827;border-right:1px solid #1f2937;}
        h1,h2,h3,h4{color:#f9fafb;}
        /* compact selectbox text */
        div[data-baseweb="select"] > div {padding-top:2px;padding-bottom:2px;}
        /* compact buttons */
        div[data-testid="stButton"] > button{padding:0.25rem 0.55rem;font-weight:800;}
        </style>
        """,
        unsafe_allow_html=True,
    )

apply_theme()

# =====================================================
# BASIC HELPERS
# =====================================================
def do_rerun():
    try:
        st.rerun()
    except Exception:
        try:
            st.experimental_rerun()
        except Exception:
            pass

def money(v) -> str:
    try:
        return f"{int(v):,}".replace(",", " ") + " $"
    except Exception:
        return "0 $"

def normalize_pos(pos: str) -> str:
    p = str(pos or "").upper()
    if "G" in p: return "G"
    if "D" in p: return "D"
    return "F"

def pos_sort_key(pos: str) -> int:
    return {"F":0,"D":1,"G":2}.get(str(pos).upper(), 99)

def saison_auto() -> str:
    now = datetime.now(TZ_LOCAL)
    return f"{now.year}-{now.year+1}" if now.month >= 9 else f"{now.year-1}-{now.year}"

def saison_verrouillee(season: str) -> bool:
    try:
        return int(str(season)[:4]) < int(saison_auto()[:4])
    except Exception:
        return False

# =====================================================
# PLAYERS DB (Hockey.Players.csv) + INDEX NOM + Level
# =====================================================
def _norm_name(s: str) -> str:
    s = str(s or "").strip().lower()
    s = re.sub(r"[\.\-']", " ", s)          # enlève . - '
    s = re.sub(r"[^a-z0-9,\s]", " ", s)     # garde lettres/chiffres/virgule/espace
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _name_variants(name: str) -> list[str]:
    """
    Retourne plusieurs clés possibles pour matcher:
      - "last, first"  -> "last first" et "first last"
      - "first last"   -> "first last" et "last first"
    """
    n = _norm_name(name)
    if not n:
        return []

    variants = set()
    variants.add(n)

    # cas "last, first"
    if "," in n:
        parts = [p.strip() for p in n.split(",", 1)]
        last = parts[0].strip()
        first = parts[1].strip() if len(parts) > 1 else ""
        if last and first:
            variants.add(f"{last} {first}".strip())
            variants.add(f"{first} {last}".strip())
    else:
        # cas "first last"
        parts = n.split(" ")
        if len(parts) >= 2:
            first = parts[0].strip()
            last = parts[-1].strip()
            if first and last:
                variants.add(f"{first} {last}".strip())
                variants.add(f"{last} {first}".strip())

    return [v for v in variants if v]

@st.cache_data(show_spinner=False)
def load_players_db(path: str) -> pd.DataFrame:
    if not path or not os.path.exists(path):
        return pd.DataFrame()
    try:
        dfp = pd.read_csv(path)
    except Exception:
        return pd.DataFrame()

    # colonnes minimales attendues
    if "Player" not in dfp.columns:
        # fallback: trouve une colonne nom
        for cand in ["Joueur", "Name", "Full Name", "fullname", "player"]:
            if cand in dfp.columns:
                dfp = dfp.rename(columns={cand: "Player"})
                break

    if "Player" not in dfp.columns:
        return pd.DataFrame()

    # s'assurer que Level existe
    if "Level" not in dfp.columns:
        dfp["Level"] = ""

    return dfp

def build_players_index(dfp: pd.DataFrame) -> dict:
    """
    Index: name_key -> Level (et on peut étendre plus tard)
    """
    idx = {}
    if dfp is None or not isinstance(dfp, pd.DataFrame) or dfp.empty:
        return idx

    for _, r in dfp.iterrows():
        nm = str(r.get("Player", "")).strip()
        lvl = str(r.get("Level", "")).strip()
        if not nm:
            continue
        for k in _name_variants(nm):
            # garde le 1er trouvé (ou remplace si le nouveau a un Level non vide)
            if k not in idx or (not idx[k] and lvl):
                idx[k] = lvl
    return idx

def inject_level_into_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ajoute/Met à jour df['Level'] en matchant df['Joueur'] avec players_index.
    """
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return df
    if "Joueur" not in df.columns:
        return df

    df = df.copy()
    if "Level" not in df.columns:
        df["Level"] = ""

    pidx = st.session_state.get("players_index", {}) or {}
    if not pidx:
        return df

    def _lookup(jname: str) -> str:
        for k in _name_variants(jname):
            if k in pidx and str(pidx[k]).strip():
                return str(pidx[k]).strip()
        return ""

    # Inject seulement si vide (ou si tu veux forcer, enlève la condition)
    m = df["Level"].astype(str).str.strip().eq("")
    if m.any():
        df.loc[m, "Level"] = df.loc[m, "Joueur"].astype(str).map(_lookup)

    return df


def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame):
        return pd.DataFrame(columns=REQUIRED_COLS)

    out = df.copy()

    # colonnes requises
    for c in REQUIRED_COLS:
        if c not in out.columns:
            out[c] = "" if c not in {"Salaire"} else 0

    out["Propriétaire"] = out["Propriétaire"].astype(str).str.strip()
    out["Joueur"] = out["Joueur"].astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
    out["Pos"] = out["Pos"].astype(str).apply(normalize_pos)
    out["Equipe"] = out["Equipe"].astype(str).str.strip()
    out["Statut"] = out["Statut"].astype(str).str.strip().replace({"": STATUT_GC})
    out["Slot"] = out["Slot"].astype(str).str.strip()
    out["IR Date"] = out["IR Date"].astype(str).str.strip()
    out["Level"] = out["Level"].astype(str).str.strip()

    out["Salaire"] = pd.to_numeric(out["Salaire"], errors="coerce").fillna(0).astype(int)

    bad = {"", "none", "nan", "null"}
    out = out[~out["Joueur"].str.lower().isin(bad)].copy()
    return out.reset_index(drop=True)

# =====================================================
# PASSWORD GATE (optional)
# =====================================================
def _sha256(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()

def require_password():
    cfg = st.secrets.get("security", {}) or {}
    expected = str(cfg.get("password_sha256", "")).strip()
    if not expected:
        return
    if st.session_state.get("authed", False):
        return

    st.title("🔐 Accès sécurisé")
    pwd = st.text_input("Mot de passe", type="password")
    if st.button("Se connecter", type="primary"):
        if _sha256(pwd) == expected:
            st.session_state["authed"] = True
            do_rerun()
        else:
            st.error("❌ Mot de passe invalide")
    st.stop()

require_password()

# =====================================================
# PERSISTENCE (local; si tu sync Drive -> data/ est persisté côté Drive)
# =====================================================
def _path(season_lbl: str, kind: str) -> str:
    season_lbl = str(season_lbl or "").strip() or "season"
    return os.path.join(DATA_DIR, f"{kind}_{season_lbl}.csv")

def persist_df(df: pd.DataFrame, season_lbl: str, kind: str):
    try:
        df.to_csv(_path(season_lbl, kind), index=False)
    except Exception:
        pass

def load_df(season_lbl: str, kind: str, cols: list[str]) -> pd.DataFrame:
    path = _path(season_lbl, kind)
    try:
        if os.path.exists(path):
            d = pd.read_csv(path)
            if isinstance(d, pd.DataFrame):
                for c in cols:
                    if c not in d.columns:
                        d[c] = ""
                return d[cols].copy()
    except Exception:
        pass
    return pd.DataFrame(columns=cols)

# =====================================================
# PLAYERS DB -> inject Level dans data
# =====================================================
@st.cache_data(show_spinner=False)
def load_players_db() -> pd.DataFrame:
    path = PLAYERS_DB_FILE_A if os.path.exists(PLAYERS_DB_FILE_A) else PLAYERS_DB_FILE_B
    if not path or not os.path.exists(path):
        return pd.DataFrame()

    try:
        dfp = pd.read_csv(path)
    except Exception:
        return pd.DataFrame()

    # trouver colonne nom
    name_col = None
    for c in dfp.columns:
        if c.strip().lower() in {"player","joueur","name","full name","fullname"}:
            name_col = c
            break
    if not name_col:
        return pd.DataFrame()

    dfp["_name_key"] = dfp[name_col].astype(str).map(_norm_name)

    # niveau
    lvl_col = None
    for c in dfp.columns:
        if c.strip().lower() == "level":
            lvl_col = c
            break
    if not lvl_col:
        return dfp[["_name_key"]].dropna().drop_duplicates()

    return dfp[["_name_key", lvl_col]].rename(columns={lvl_col:"Level"}).dropna().drop_duplicates()

def inject_levels(df: pd.DataFrame, players_db: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    if players_db is None or players_db.empty:
        if "Level" not in df.columns:
            df["Level"] = ""
        return df

    out = df.copy()
    out["_name_key"] = out["Joueur"].astype(str).map(_norm_name)

    # merge only if needed
    if "Level" not in out.columns:
        out["Level"] = ""

    merged = out.merge(players_db, on="_name_key", how="left", suffixes=("", "_db"))
    merged["Level"] = merged["Level"].astype(str).str.strip()
    merged["Level_db"] = merged["Level_db"].astype(str).str.strip()

    merged["Level"] = merged["Level"].where(merged["Level"].ne(""), merged["Level_db"])
    merged = merged.drop(columns=["_name_key", "Level_db"])
    return merged

# =====================================================
# HISTORY (complete schema)
# =====================================================
HIST_COLS = [
    "id","timestamp","season",
    "proprietaire","joueur","pos","equipe","level",
    "from_statut","from_slot","to_statut","to_slot",
    "action","note",
]

def next_hist_id(h: pd.DataFrame) -> int:
    try:
        if h is None or h.empty or "id" not in h.columns:
            return 1
        v = pd.to_numeric(h["id"], errors="coerce").fillna(0)
        return int(v.max()) + 1
    except Exception:
        return 1

def log_history(owner, joueur, pos, equipe, level, from_statut, from_slot, to_statut, to_slot, action, note):
    h = st.session_state.get("history")
    h = h.copy() if isinstance(h, pd.DataFrame) else pd.DataFrame(columns=HIST_COLS)
    for c in HIST_COLS:
        if c not in h.columns:
            h[c] = ""

    row = {
        "id": next_hist_id(h),
        "timestamp": datetime.now(TZ_LOCAL).isoformat(timespec="seconds"),
        "season": str(st.session_state.get("season","") or ""),
        "proprietaire": str(owner or ""),
        "joueur": str(joueur or ""),
        "pos": str(pos or ""),
        "equipe": str(equipe or ""),
        "level": str(level or ""),
        "from_statut": str(from_statut or ""),
        "from_slot": str(from_slot or ""),
        "to_statut": str(to_statut or ""),
        "to_slot": str(to_slot or ""),
        "action": str(action or "MOVE"),
        "note": str(note or ""),
    }
    h = pd.concat([h, pd.DataFrame([row])], ignore_index=True)
    st.session_state["history"] = h
    persist_df(h, st.session_state["season"], "history")

# =====================================================
# MOVE + HISTORY (single function)
# =====================================================
def apply_move_with_history(owner: str, joueur: str, to_statut: str, to_slot: str, note: str = "", action: str = "MOVE") -> bool:
    df = st.session_state.get("data")
    if df is None or df.empty:
        st.error("Données manquantes.")
        return False

    owner_s = str(owner).strip()
    joueur_s = str(joueur).strip()

    m = (
        df["Propriétaire"].astype(str).str.strip().eq(owner_s)
        & df["Joueur"].astype(str).str.strip().eq(joueur_s)
    )
    if not m.any():
        st.warning(f"Joueur introuvable: {joueur_s} ({owner_s})")
        return False

    idx = df.index[m][0]
    from_statut = str(df.at[idx, "Statut"])
    from_slot   = str(df.at[idx, "Slot"])
    pos         = str(df.at[idx, "Pos"])
    equipe      = str(df.at[idx, "Equipe"])
    level       = str(df.at[idx, "Level"]) if "Level" in df.columns else ""

    df.at[idx, "Statut"] = str(to_statut)
    df.at[idx, "Slot"]   = str(to_slot)
    st.session_state["data"] = df

    persist_df(df, st.session_state["season"], "fantrax")
    log_history(owner_s, joueur_s, pos, equipe, level, from_statut, from_slot, to_statut, to_slot, action, note)
    return True

# =====================================================
# PICKS + RETAINED SALARY (transactions)
# =====================================================
PICKS_COLS = ["season","holder","round","locked"]
RETAIN_COLS = ["timestamp","season","owner_from","owner_to","bucket","amount","note"]

def load_picks(season: str, teams: list[str]) -> pd.DataFrame:
    p = load_df(season, "picks", PICKS_COLS)
    if p.empty:
        rows = []
        for t in teams:
            for r in range(1,9):
                rows.append({"season":season,"holder":t,"round":r,"locked":(r==8)})
        p = pd.DataFrame(rows, columns=PICKS_COLS)
        persist_df(p, season, "picks")
    # ensure all teams exist
    missing = []
    for t in teams:
        for r in range(1,9):
            if not ((p["holder"]==t) & (p["round"]==r)).any():
                missing.append({"season":season,"holder":t,"round":r,"locked":(r==8)})
    if missing:
        p = pd.concat([p, pd.DataFrame(missing)], ignore_index=True)
        persist_df(p, season, "picks")
    return p

def load_retained(season: str) -> pd.DataFrame:
    return load_df(season, "retained", RETAIN_COLS)

def retained_totals(retained: pd.DataFrame, owner: str):
    if retained is None or retained.empty:
        return 0,0
    r = retained[retained["owner_from"].astype(str).str.strip().eq(str(owner).strip())].copy()
    if r.empty:
        return 0,0
    r["amount"] = pd.to_numeric(r["amount"], errors="coerce").fillna(0).astype(int)
    gc = int(r[r["bucket"].astype(str).eq("GC")]["amount"].sum())
    ce = int(r[r["bucket"].astype(str).eq("CE")]["amount"].sum())
    return gc, ce

# =====================================================
# TEAM SELECTION (single source of truth)
# =====================================================
TEAMS = ["Nordiques","Cracheurs","Prédateurs","Red Wings","Whalers","Canadiens"]

def pick_team(team: str):
    team = str(team or "").strip()
    if not team: return
    st.session_state["selected_team"] = team
    do_rerun()

def get_selected_team() -> str:
    return str(st.session_state.get("selected_team") or "").strip()

def is_admin() -> bool:
    return get_selected_team().lower() == "whalers" or bool(st.session_state.get("IS_ADMIN", False))

# =====================================================
# LOAD SEASON + DATA
# =====================================================
if "season" not in st.session_state or not str(st.session_state["season"]).strip():
    st.session_state["season"] = saison_auto()

season = str(st.session_state["season"]).strip()

# load core files once per season
if st.session_state.get("_loaded_season") != season:
    df = load_df(season, "fantrax", REQUIRED_COLS)
    df = clean_data(df)

    # --- LOAD PLAYERS DB (Hockey.Players.csv)
    PLAYERS_DB_PATH = os.path.join("data", "Hockey.Players.csv")
    players_db = load_players_db(PLAYERS_DB_PATH)

    # --- BUILD INDEX (Nom ↔ Prénom)
    players_index = build_players_index(players_db)
    st.session_state["players_index"] = players_index
    st.session_state["players_db"] = players_db

    # --- INJECT LEVEL INTO DATA
    df = inject_level_into_data(df)

    st.session_state["data"] = clean_data(df)
    st.session_state["history"] = load_df(season, "history", HIST_COLS)

    st.session_state["_loaded_season"] = season

# safety: toujours réinjecter si data change (import, move, etc.)
df = clean_data(st.session_state.get("data", pd.DataFrame(columns=REQUIRED_COLS)))
df = inject_level_into_data(df)
st.session_state["data"] = df


# =====================================================
# SIDEBAR
# =====================================================
with st.sidebar:
    st.header("📅 Saison")
    saisons = sorted({season, "2024-2025","2025-2026","2026-2027"})
    season_pick = st.selectbox("Saison", saisons, index=saisons.index(season), key="sb_season")
    if season_pick != season:
        st.session_state["season"] = season_pick
        do_rerun()

    st.session_state["LOCKED"] = saison_verrouillee(st.session_state["season"])

    st.divider()
    st.header("💰 Plafonds")
    if "PLAFOND_GC" not in st.session_state: st.session_state["PLAFOND_GC"] = 95_500_000
    if "PLAFOND_CE" not in st.session_state: st.session_state["PLAFOND_CE"] = 47_750_000
    st.metric("🏒 Plafond GC", money(st.session_state["PLAFOND_GC"]))
    st.metric("🏫 Plafond CE", money(st.session_state["PLAFOND_CE"]))

    st.divider()
    st.header("🏒 Équipes")
    cur = get_selected_team() or TEAMS[0]
    chosen = st.selectbox("Choisir une équipe", TEAMS, index=TEAMS.index(cur), key="sb_team")
    if chosen != cur:
        pick_team(chosen)

# =====================================================
# NAV
# =====================================================
NAV_TABS = ["📊 Tableau","🧾 Alignement","🕘 Historique","⚖️ Transactions"]
if is_admin():
    NAV_TABS.append("🛠️ Gestion Admin")

if "active_tab" not in st.session_state or st.session_state["active_tab"] not in NAV_TABS:
    st.session_state["active_tab"] = NAV_TABS[0]

active_tab = st.radio("", NAV_TABS, horizontal=True, key="active_tab")
st.divider()

# =====================================================
# COMPUTE plafonds (with retained)
# =====================================================
def rebuild_plafonds(df: pd.DataFrame, retained: pd.DataFrame) -> pd.DataFrame:
    cap_gc = int(st.session_state.get("PLAFOND_GC", 0) or 0)
    cap_ce = int(st.session_state.get("PLAFOND_CE", 0) or 0)

    rows = []
    for t in TEAMS:
        d = df[df["Propriétaire"].astype(str).str.strip().eq(t)].copy()
        d = d[d["Slot"].astype(str).str.upper().ne("IR")].copy()

        total_gc = int(d[d["Statut"].astype(str).eq(STATUT_GC)]["Salaire"].sum()) if not d.empty else 0
        total_ce = int(d[d["Statut"].astype(str).eq(STATUT_CE)]["Salaire"].sum()) if not d.empty else 0

        r_gc, r_ce = retained_totals(retained, t)
        total_gc_adj = total_gc - r_gc
        total_ce_adj = total_ce - r_ce

        rows.append({
            "Propriétaire": t,
            "Total GC": total_gc_adj,
            "Reste GC": cap_gc - total_gc_adj,
            "Total CE": total_ce_adj,
            "Reste CE": cap_ce - total_ce_adj,
            "Retenu GC": r_gc,
            "Retenu CE": r_ce,
        })
    return pd.DataFrame(rows)

# =====================================================
# TAB: TABLEAU
# =====================================================
def render_tableau(plafonds: pd.DataFrame):
    selected = get_selected_team()
    header = st.columns([2.2,1.2,1.2,1.2,1.2])
    header[0].markdown("**Équipe**")
    header[1].markdown("**Total GC**")
    header[2].markdown("**Reste GC**")
    header[3].markdown("**Total CE**")
    header[4].markdown("**Reste CE**")

    for _, r in plafonds.iterrows():
        owner = str(r["Propriétaire"])
        row = st.columns([2.2,1.2,1.2,1.2,1.2], vertical_alignment="center")
        label = f"✅ {owner}" if owner == selected else owner
        if row[0].button(label, key=f"pick_{owner}", use_container_width=True):
            pick_team(owner)
            return
        row[1].write(money(r["Total GC"]))
        row[2].write(money(r["Reste GC"]))
        row[3].write(money(r["Total CE"]))
        row[4].write(money(r["Reste CE"]))

# =====================================================
# TAB: ALIGNEMENT (simple; click to move)
# =====================================================
def roster_click_list(df_src: pd.DataFrame, owner: str, source_key: str) -> str | None:
    if df_src is None or df_src.empty:
        st.info("Aucun joueur.")
        return None

    t = df_src.copy()
    t["Pos"] = t["Pos"].apply(normalize_pos)
    t["_pos"] = t["Pos"].apply(pos_sort_key)
    t = t.sort_values(by=["_pos","Salaire","Joueur"], ascending=[True, False, True], kind="mergesort").drop(columns=["_pos"])

    header = st.columns([0.8, 1.2, 3.6, 1.0, 1.4])
    header[0].markdown("**Pos**")
    header[1].markdown("**Équipe**")
    header[2].markdown("**Joueur**")
    header[3].markdown("**Lvl**")
    header[4].markdown("**Salaire**")

    clicked = None
    for _, r in t.iterrows():
        joueur = str(r["Joueur"])
        c = st.columns([0.8, 1.2, 3.6, 1.0, 1.4], vertical_alignment="center")
        c[0].write(r["Pos"])
        c[1].write(str(r["Equipe"]))
        if c[2].button(joueur, key=f"{source_key}_{owner}_{joueur}", use_container_width=True):
            clicked = joueur
        c[3].write(str(r.get("Level","") or "—"))
        c[4].write(money(int(r["Salaire"])))
    return clicked

def set_move_ctx(owner: str, joueur: str):
    st.session_state["move_ctx"] = {"owner": owner, "joueur": joueur, "nonce": int(st.session_state.get("nonce",0))+1}
    st.session_state["nonce"] = st.session_state["move_ctx"]["nonce"]

def clear_move_ctx():
    st.session_state["move_ctx"] = None

def open_move_dialog():
    ctx = st.session_state.get("move_ctx")
    if not ctx:
        return
    if st.session_state.get("LOCKED"):
        st.warning("🔒 Saison verrouillée.")
        clear_move_ctx()
        return

    owner = str(ctx["owner"])
    joueur = str(ctx["joueur"])
    nonce = int(ctx.get("nonce",0))

    df = st.session_state.get("data")
    m = (df["Propriétaire"].astype(str).str.strip().eq(owner.strip())
         & df["Joueur"].astype(str).str.strip().eq(joueur.strip()))
    if not m.any():
        st.error("Joueur introuvable.")
        clear_move_ctx()
        return
    idx = df.index[m][0]
    cur_statut = str(df.at[idx,"Statut"])
    cur_slot = str(df.at[idx,"Slot"])
    cur_pos = str(df.at[idx,"Pos"])
    cur_team = str(df.at[idx,"Equipe"])
    cur_lvl = str(df.at[idx,"Level"])
    cur_sal = int(df.at[idx,"Salaire"])

    @st.dialog(f"Déplacement — {joueur}", width="small")
    def _dlg():
        st.markdown(f"**{owner} • {joueur}**  \n{cur_statut}/{cur_slot or '-'} • {cur_pos} • {cur_team} • {money(cur_sal)} • Lvl: {cur_lvl or '—'}")
        st.divider()

        reason = st.radio("Type de changement", ["Normal","Changement demi-mois","Blessure"], horizontal=True, key=f"mv_reason_{nonce}")

        # destinations selon demande:
        if reason == "Changement demi-mois":
            opts = [("Grand Club", SLOT_BANC), ("Club École", "")]
        elif reason == "Blessure":
            opts = [("Blessé", SLOT_IR)]
        else:
            opts = [("Grand Club", SLOT_ACTIF), ("Grand Club", SLOT_BANC), ("Club École", ""), ("Blessé", SLOT_IR)]

        # map statut/slot
        def _map(o):
            if o[0] == "Grand Club": return (STATUT_GC, o[1])
            if o[0] == "Club École": return (STATUT_CE, o[1])
            return (cur_statut, o[1])

        labels = []
        mapping = {}
        for o in opts:
            to_s, to_sl = _map(o)
            # retirer current
            if (to_s, to_sl) == (cur_statut, cur_slot):
                continue
            lab = "🟢 Actif" if (to_s,to_sl)==(STATUT_GC,SLOT_ACTIF) else \
                  "🟡 Banc" if (to_s,to_sl)==(STATUT_GC,SLOT_BANC) else \
                  "🔵 Mineur" if to_s==STATUT_CE else \
                  "🩹 Blessé (IR)"
            labels.append(lab)
            mapping[lab] = (to_s, to_sl)

        choice = st.radio("Destination", labels, label_visibility="collapsed", key=f"mv_dest_{nonce}")
        to_statut, to_slot = mapping[choice]

        c1, c2 = st.columns(2)
        if c1.button("✅ Confirmer", type="primary", use_container_width=True, key=f"mv_ok_{nonce}"):
            note = f"{reason} — {cur_statut}/{cur_slot or '-'} → {to_statut}/{to_slot or '-'}"
            ok = apply_move_with_history(owner, joueur, to_statut, to_slot, note=note, action=reason)
            if ok:
                st.toast("✅ Déplacement effectué", icon="✅")
                clear_move_ctx()
                st.session_state["__rerun_once"] = True
                return
            st.toast("❌ Déplacement refusé", icon="❌")

        if c2.button("✖️ Annuler", use_container_width=True, key=f"mv_cancel_{nonce}"):
            clear_move_ctx()
            st.session_state["__rerun_once"] = True
            return

    _dlg()

# rerun once guard (prevents freezes)
if st.session_state.get("__rerun_once"):
    st.session_state["__rerun_once"] = False
    do_rerun()

# =====================================================
# ROUTING
# =====================================================
df = clean_data(st.session_state.get("data", pd.DataFrame(columns=REQUIRED_COLS)))
st.session_state["data"] = df

retained = load_retained(season)
plafonds = rebuild_plafonds(df, retained)

if active_tab == "📊 Tableau":
    st.subheader("📊 Tableau — Masses salariales")
    render_tableau(plafonds)

elif active_tab == "🧾 Alignement":
    st.subheader("🧾 Alignement")
    owner = get_selected_team()
    dprop = df[df["Propriétaire"].astype(str).str.strip().eq(owner)].copy()
    if dprop.empty:
        st.info("Aucun alignement pour cette équipe (Admin → Import).")
    else:
        ir = dprop[dprop["Slot"].astype(str).str.upper().eq("IR")].copy()
        ok = dprop[dprop["Slot"].astype(str).str.upper().ne("IR")].copy()
        gc = ok[ok["Statut"].astype(str).eq(STATUT_GC)].copy()
        ce = ok[ok["Statut"].astype(str).eq(STATUT_CE)].copy()

        st.markdown("### 🟢 Actifs/Banc (GC)")
        clicked = roster_click_list(gc, owner, "gc")
        if clicked:
            set_move_ctx(owner, clicked)
            do_rerun()

        st.divider()
        st.markdown("### 🔵 Club École (CE)")
        clicked = roster_click_list(ce, owner, "ce")
        if clicked:
            set_move_ctx(owner, clicked)
            do_rerun()

        st.divider()
        st.markdown("### 🩹 IR")
        clicked = roster_click_list(ir, owner, "ir")
        if clicked:
            set_move_ctx(owner, clicked)
            do_rerun()

        open_move_dialog()

elif active_tab == "🕘 Historique":
    st.subheader("🕘 Historique")
    h = st.session_state.get("history")
    h = h.copy() if isinstance(h, pd.DataFrame) else pd.DataFrame(columns=HIST_COLS)
    if h.empty:
        st.info("Aucune entrée d’historique.")
    else:
        owners = ["Tous"] + sorted(h["proprietaire"].dropna().astype(str).unique().tolist())
        owner_filter = st.selectbox("Filtrer par propriétaire", owners, key="hist_owner")
        if owner_filter != "Tous":
            h = h[h["proprietaire"].astype(str).eq(owner_filter)]
        h = h.sort_values(by="timestamp", ascending=False, kind="mergesort")
        st.dataframe(h[["timestamp","season","proprietaire","joueur","pos","equipe","level","from_statut","from_slot","to_statut","to_slot","action","note"]].head(500),
                     use_container_width=True, hide_index=True)

elif active_tab == "⚖️ Transactions":
    st.subheader("⚖️ Transactions")
    owners = TEAMS

    c1, c2 = st.columns(2)
    with c1:
        owner_from = st.selectbox("Propriétaire (envoie)", owners, key="tx_from")
    with c2:
        owner_to = st.selectbox("Propriétaire (reçoit)", owners, key="tx_to")

    if owner_to == owner_from:
        st.info("Choisis deux propriétaires différents pour une transaction.")

    st.divider()

    # Picks
    picks = load_picks(season, owners)
    # picks disponibles à donner par owner_from (round 1-7, locked=False)
    avail = picks[(picks["holder"].astype(str)==owner_from) & (~picks["locked"].astype(bool))].copy()
    avail = avail.sort_values("round")
    pick_opts = ["— Aucun —"] + [f"R{int(r)}" for r in avail["round"].tolist()]

    pick_choice = st.selectbox("Choix de repêchage envoyé", pick_opts, key="tx_pick")

    # Retained salary
    st.markdown("### 💸 Salaire retenu")
    bucket = st.radio("Déduire sur quel plafond ?", ["GC","CE"], horizontal=True, key="tx_bucket")
    amount = st.number_input("Montant retenu ( $ )", min_value=0, step=100_000, value=0, key="tx_ret_amount")
    note = st.text_input("Note (optionnel)", key="tx_note")

    # Preview info
    st.divider()
    st.markdown("### 📌 Résumé")
    st.write(f"**Envoie :** {owner_from}  →  **Reçoit :** {owner_to}")
    st.write(f"**Pick :** {pick_choice}")
    st.write(f"**Retenu :** {money(amount)} sur {bucket}")

    if st.button("✅ Enregistrer la transaction", type="primary", use_container_width=True, disabled=(owner_from==owner_to)):
        # 1) transfer pick (if any)
        if pick_choice != "— Aucun —":
            rnd = int(pick_choice.replace("R",""))
            # ensure not round 8
            rowmask = (picks["holder"].astype(str)==owner_from) & (picks["round"].astype(int)==rnd)
            if not rowmask.any():
                st.error("Pick introuvable / déjà échangé.")
                st.stop()
            if int(rnd) == 8:
                st.error("Le choix de 8e ronde ne peut pas être échangé.")
                st.stop()
            picks.loc[rowmask, "holder"] = owner_to
            persist_df(picks, season, "picks")

        # 2) retained salary record
        if int(amount) > 0:
            retained = load_retained(season)
            rec = {
                "timestamp": datetime.now(TZ_LOCAL).isoformat(timespec="seconds"),
                "season": season,
                "owner_from": owner_from,
                "owner_to": owner_to,
                "bucket": bucket,
                "amount": int(amount),
                "note": note or "",
            }
            retained = pd.concat([retained, pd.DataFrame([rec])], ignore_index=True)
            persist_df(retained, season, "retained")

        st.toast("✅ Transaction enregistrée", icon="✅")
        st.session_state["__rerun_once"] = True
        do_rerun()

    # Display picks + retained + caps summary
    st.divider()
    st.markdown("### 📊 Situation par équipe")
    retained = load_retained(season)
    plafonds2 = rebuild_plafonds(st.session_state["data"], retained)

    # picks remaining/acquired
    picks = load_picks(season, owners)
    # count by holder for R1-7 only (tradable)
    tradable = picks[~picks["locked"].astype(bool)]
    summary = []
    for o in owners:
        owned = tradable[tradable["holder"].astype(str)==o]["round"].astype(int).tolist()
        summary.append({
            "Équipe": o,
            "GC (après retenu)": money(int(plafonds2.loc[plafonds2["Propriétaire"]==o, "Total GC"].iloc[0])),
            "CE (après retenu)": money(int(plafonds2.loc[plafonds2["Propriétaire"]==o, "Total CE"].iloc[0])),
            "Choix détenus (R1-7)": ", ".join([f"R{r}" for r in sorted(owned)]) if owned else "—",
            "Choix 8e": "R8 (non échangeable)",
        })
    st.dataframe(pd.DataFrame(summary), use_container_width=True, hide_index=True)

elif active_tab == "🛠️ Gestion Admin":
    st.subheader("🛠️ Gestion Admin")
    if not is_admin():
        st.warning("Accès admin requis.")
        st.stop()

    st.markdown("### 📥 Import Fantrax (une équipe à la fois)")
    owner = st.selectbox("Importer dans quelle équipe ?", TEAMS, key="admin_team")
    clear_before = st.checkbox("Vider l’alignement de cette équipe avant import", value=True, key="admin_clear")

    upl = st.file_uploader("Fichier CSV Fantrax", type=["csv","txt"], key="admin_upl")
    if st.button("✅ Importer", type="primary", disabled=(upl is None), use_container_width=True):
        # parser minimal: on assume colonnes Player/Salary/Team/Pos/Status
        raw = upl.read().decode("utf-8", errors="ignore").splitlines()
        raw = [re.sub(r"[\x00-\x1f\x7f]", "", l) for l in raw]
        sep = "," if "," in raw[0] else ";"
        dfp = pd.read_csv(io.StringIO("\n".join(raw)), sep=sep, engine="python", on_bad_lines="skip")
        dfp.columns = [c.strip().replace('"',"") for c in dfp.columns]

        def find_col(keys):
            for k in keys:
                for c in dfp.columns:
                    if k in c.lower():
                        return c
            return None

        player_col = find_col(["player"])
        salary_col = find_col(["salary"])
        team_col = find_col(["team"])
        pos_col = find_col(["pos"])
        status_col = find_col(["status"])

        if not player_col or not salary_col:
            st.error("Colonnes Player/Salary introuvables.")
            st.stop()

        out = pd.DataFrame()
        out["Propriétaire"] = owner
        out["Joueur"] = dfp[player_col].astype(str).str.strip()
        out["Equipe"] = dfp[team_col].astype(str).str.strip() if team_col else ""
        out["Pos"] = dfp[pos_col].astype(str).str.strip() if pos_col else "F"
        out["Pos"] = out["Pos"].apply(normalize_pos)

        sal = dfp[salary_col].astype(str).str.replace(",", "", regex=False).str.replace(" ", "", regex=False)
        out["Salaire"] = pd.to_numeric(sal, errors="coerce").fillna(0).astype(int) * 1000

        if status_col:
            out["Statut"] = dfp[status_col].astype(str).apply(lambda x: STATUT_CE if "min" in str(x).lower() else STATUT_GC)
        else:
            out["Statut"] = STATUT_GC

        out["Slot"] = out["Statut"].apply(lambda s: SLOT_ACTIF if s == STATUT_GC else "")
        out["IR Date"] = ""
        out["Level"] = ""

        out = clean_data(out)
        out = inject_levels(out, st.session_state["players_db"])

        dfcur = clean_data(st.session_state.get("data"))
        if clear_before:
            dfcur = dfcur[dfcur["Propriétaire"].astype(str).str.strip().ne(owner)].copy()
        dfnew = pd.concat([dfcur, out], ignore_index=True)
        dfnew = clean_data(dfnew)

        st.session_state["data"] = dfnew
        persist_df(dfnew, season, "fantrax")
        st.toast("✅ Import OK", icon="✅")
        st.session_state["__rerun_once"] = True
        do_rerun()
