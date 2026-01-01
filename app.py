# app.py — Fantrax Pool Hockey (COMPLET OPTIMISÉ)
# ✅ Logos propriétaires dans /data
# ✅ Tableau: colonnes renommées
# ✅ Alignement: 3 tableaux (Actifs/Banc/Mineur) + IR cliquable
# ✅ Gestion: Ajouter/Retirer joueurs
# ✅ Déplacement vers Blessé: salaire exclu des plafonds + IR Date
# ✅ Historique + Undo + Delete
# ✅ Import Fantrax robuste
# ✅ Joueurs (data/Hockey.Players.csv) filtres + comparaison
# ✅ Optimisations: cache plafonds, code allégé

# =====================================================
# IMPORTS
# =====================================================
import os
import io
import re
import html
import textwrap
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import quote, unquote

import pandas as pd
import streamlit as st

# =====================================================
# CONFIG STREAMLIT
# =====================================================
st.set_page_config("Fantrax Pool Hockey", layout="wide")

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

PLAYERS_DB_FILE = "data/Hockey.Players.csv"
LOGO_POOL_FILE = "data/Logo_Pool.png"

# =====================================================
# LOGOS (dans /data)
# =====================================================
LOGOS = {
    "Nordiques": "data/Nordiques_Logo.png",
    "Cracheurs": "data/Cracheurs_Logo.png",
    "Prédateurs": "data/Prédateurs_Logo.png",
    "Red Wings": "data/Red_Wings_Logo.png",
    "Whalers": "data/Whalers_Logo.png",
    "Canadiens": "data/Canadiens_Logo.png",
}

LOGO_SIZE = 55

def find_logo_for_owner(owner: str) -> str:
    o = str(owner or "").strip().lower()
    for key, path in LOGOS.items():
        if key.lower() in o and os.path.exists(path):
            return path
    return ""

# =====================================================
# UTILS / HELPERS
# =====================================================
def do_rerun():
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()

def money(v):
    try:
        return f"{int(v):,}".replace(",", " ") + " $"
    except Exception:
        return "0 $"

def normalize_pos(pos: str) -> str:
    p = str(pos or "").upper()
    if "G" in p:
        return "G"
    if "D" in p:
        return "D"
    return "F"

def pos_sort_key(pos: str) -> int:
    return {"F": 0, "D": 1, "G": 2}.get(str(pos).upper(), 99)

def saison_auto():
    now = datetime.now()
    return f"{now.year}-{now.year+1}" if now.month >= 9 else f"{now.year-1}-{now.year}"

def saison_verrouillee(season):
    return int(season[:4]) < int(saison_auto()[:4])

def _count_badge(n, limit):
    if n > limit:
        color = "#ef4444"
        icon = " ⚠️"
    else:
        color = "#22c55e"
        icon = ""
    return f"<span style='color:{color};font-weight:1000'>{n}</span>/{limit}{icon}"

def set_move_ctx(owner: str, joueur: str):
    st.session_state["move_nonce"] = st.session_state.get("move_nonce", 0) + 1
    st.session_state["move_ctx"] = {
        "owner": str(owner).strip(),
        "joueur": str(joueur).strip(),
        "nonce": st.session_state["move_nonce"],
    }

def clear_move_ctx():
    st.session_state["move_ctx"] = None

# =====================================================
# STREAMLIT TABLE SELECTION
# =====================================================
SELECTION_KEYS_ALIGN = ["sel_actifs", "sel_banc", "sel_min", "sel_ir"]

def clear_other_selections(keep_key: str):
    for k in SELECTION_KEYS_ALIGN:
        if k == keep_key:
            continue
        ss = st.session_state.get(k)
        if not isinstance(ss, dict):
            continue
        sel = ss.get("selection")
        if isinstance(sel, dict):
            rows = sel.get("rows")
            if isinstance(rows, list):
                rows.clear()
            else:
                sel["rows"] = []
        else:
            ss["selection"] = {"rows": []}

def pick_from_df(df_ui: pd.DataFrame, key: str):
    ss = st.session_state.get(key)
    if not isinstance(ss, dict):
        return None
    sel = ss.get("selection", {})
    rows = sel.get("rows", [])
    if not rows:
        return None
    idx = int(rows[0])
    if df_ui is None or df_ui.empty:
        return None
    if idx < 0 or idx >= len(df_ui):
        return None
    return str(df_ui.iloc[idx]["Joueur"]).strip()

# =====================================================
# PLAYERS DB
# =====================================================
def _norm_key(s: str) -> str:
    s = str(s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[^\w\s-]", "", s)
    s = s.replace(" jr", "").replace(" sr", "")
    return s.strip()

@st.cache_data(show_spinner=False)
def load_players_db(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        return pd.DataFrame()
    dfp = pd.read_csv(path)
    
    name_col = None
    for c in dfp.columns:
        cl = c.strip().lower()
        if cl in {"player", "joueur", "name", "full name", "fullname"}:
            name_col = c
            break
    if name_col is None:
        return dfp
    
    dfp["_name_key"] = dfp[name_col].astype(str).map(_norm_key)
    return dfp

players_db = load_players_db(PLAYERS_DB_FILE)

# =====================================================
# CLEAN DATA
# =====================================================
REQUIRED_COLS = ["Propriétaire", "Joueur", "Salaire", "Statut", "Slot", "Pos", "Equipe", "IR Date"]

def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    if df is None:
        return pd.DataFrame(columns=REQUIRED_COLS)
    
    df = df.copy()
    
    for c in REQUIRED_COLS:
        if c not in df.columns:
            df[c] = ""
    
    for c in ["Propriétaire", "Joueur", "Statut", "Slot", "Pos", "Equipe", "IR Date"]:
        df[c] = df[c].astype(str).fillna("").map(lambda x: re.sub(r"\s+", " ", x).strip())
    
    def _to_int(x):
        s = str(x).strip().replace(",", "").replace(" ", "")
        s = re.sub(r"[^\d]", "", s)
        return int(s) if s.isdigit() else 0
    
    df["Salaire"] = df["Salaire"].apply(_to_int).astype(int)
    
    df["Statut"] = df["Statut"].replace({
        "GC": "Grand Club",
        "CE": "Club École",
        "Club Ecole": "Club École",
        "GrandClub": "Grand Club",
    })
    
    df["Slot"] = df["Slot"].replace({
        "Active": "Actif",
        "Bench": "Banc",
        "IR": "Blessé",
        "Injured": "Blessé",
    })
    
    df["Pos"] = df["Pos"].apply(normalize_pos)
    
    def _fix_row(r):
        statut = r["Statut"]
        slot = r["Slot"]
        if statut == "Club École":
            if slot not in {"", "Blessé"}:
                r["Slot"] = ""
        else:
            if slot not in {"Actif", "Banc", "Blessé"}:
                r["Slot"] = "Actif"
        return r
    
    df = df.apply(_fix_row, axis=1)
    df = df.drop_duplicates(subset=["Propriétaire", "Joueur"], keep="last").reset_index(drop=True)
    return df

# =====================================================
# SESSION DEFAULTS
# =====================================================
if "uploader_nonce" not in st.session_state:
    st.session_state["uploader_nonce"] = 0
if "PLAFOND_GC" not in st.session_state:
    st.session_state["PLAFOND_GC"] = 95_500_000
if "PLAFOND_CE" not in st.session_state:
    st.session_state["PLAFOND_CE"] = 47_750_000
if "move_ctx" not in st.session_state:
    st.session_state["move_ctx"] = None
if "move_nonce" not in st.session_state:
    st.session_state["move_nonce"] = 0

# =====================================================
# HISTORY
# =====================================================
def load_history(history_file: str) -> pd.DataFrame:
    if os.path.exists(history_file):
        return pd.read_csv(history_file)
    return pd.DataFrame(columns=[
        "id", "timestamp", "season", "proprietaire", "joueur", "pos", "equipe",
        "from_statut", "from_slot", "to_statut", "to_slot", "action"
    ])

def save_history(history_file: str, h: pd.DataFrame):
    h.to_csv(history_file, index=False)

def next_hist_id(h: pd.DataFrame) -> int:
    if h.empty or "id" not in h.columns:
        return 1
    return int(pd.to_numeric(h["id"], errors="coerce").fillna(0).max()) + 1

def log_history_row(proprietaire, joueur, pos, equipe,
                    from_statut, from_slot, to_statut, to_slot, action):
    h = st.session_state["history"].copy()
    row_hist = {
        "id": next_hist_id(h),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "season": st.session_state.get("season", ""),
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
    h = pd.concat([h, pd.DataFrame([row_hist])], ignore_index=True)
    st.session_state["history"] = h
    save_history(st.session_state["HISTORY_FILE"], h)

# =====================================================
# APPLY MOVE (avec IR Date)
# =====================================================
def apply_move_with_history(proprietaire: str, joueur: str, to_statut: str, to_slot: str, action_label: str) -> bool:
    st.session_state["last_move_error"] = ""
    
    if st.session_state.get("LOCKED"):
        st.session_state["last_move_error"] = "🔒 Saison verrouillée"
        return False
    
    df0 = st.session_state.get("data")
    if df0 is None or df0.empty:
        st.session_state["last_move_error"] = "Aucune donnée"
        return False
    
    df0 = df0.copy()
    
    if "IR Date" not in df0.columns:
        df0["IR Date"] = ""
    
    proprietaire = str(proprietaire).strip()
    joueur = str(joueur).strip()
    to_statut = str(to_statut).strip()
    to_slot = str(to_slot).strip()
    
    allowed_slots_gc = {"Actif", "Banc", "Blessé"}
    allowed_slots_ce = {"", "Blessé"}
    
    if to_statut == "Grand Club" and to_slot not in allowed_slots_gc:
        st.session_state["last_move_error"] = f"Slot invalide pour GC: {to_slot}"
        return False
    if to_statut == "Club École" and to_slot not in allowed_slots_ce:
        st.session_state["last_move_error"] = f"Slot invalide pour CE: {to_slot}"
        return False
    
    mask = (
        df0["Propriétaire"].astype(str).str.strip().eq(proprietaire)
        & df0["Joueur"].astype(str).str.strip().eq(joueur)
    )
    
    if df0.loc[mask].empty:
        st.session_state["last_move_error"] = "Joueur introuvable"
        return False
    
    before = df0.loc[mask].iloc[0]
    from_statut = str(before.get("Statut", "")).strip()
    from_slot = str(before.get("Slot", "")).strip()
    pos0 = str(before.get("Pos", "F")).strip()
    equipe0 = str(before.get("Equipe", "")).strip()
    
    df0.loc[mask, "Statut"] = to_statut
    df0.loc[mask, "Slot"] = (to_slot if to_slot else "")
    
    entering_ir = (to_slot == "Blessé") and (from_slot != "Blessé")
    leaving_ir = (from_slot == "Blessé") and (to_slot != "Blessé")
    
    if entering_ir:
        now_tor = datetime.now(ZoneInfo("America/Toronto"))
        df0.loc[mask, "IR Date"] = now_tor.strftime("%Y-%m-%d %H:%M")
    elif leaving_ir:
        df0.loc[mask, "IR Date"] = ""
    
    df0 = clean_data(df0)
    st.session_state["data"] = df0
    
    try:
        data_file = st.session_state.get("DATA_FILE")
        if data_file:
            df0.to_csv(data_file, index=False)
    except Exception as e:
        st.session_state["last_move_error"] = f"Erreur CSV: {e}"
        return False
    
    try:
        log_history_row(
            proprietaire=proprietaire,
            joueur=joueur,
            pos=pos0,
            equipe=equipe0,
            from_statut=from_statut,
            from_slot=from_slot,
            to_statut=to_statut,
            to_slot=(to_slot if to_slot else ""),
            action=action_label,
        )
    except Exception as e:
        st.warning(f"⚠️ Déplacement OK, historique non écrit: {e}")
    
    return True

# =====================================================
# FANTRAX PARSER
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
    header_idxs = [i for i, l in enumerate(raw_lines) if ("player" in l.lower() and "salary" in l.lower() and sep in l)]
    
    if not header_idxs:
        raise ValueError("Colonnes Fantrax non détectées")
    
    def read_section(start, end):
        lines = [l for l in raw_lines[start:end] if l.strip() != ""]
        if len(lines) < 2:
            return None
        dfp = pd.read_csv(io.StringIO("\n".join(lines)), sep=sep, engine="python", on_bad_lines="skip")
        dfp.columns = [c.strip().replace('"', "") for c in dfp.columns]
        return dfp
    
    parts = []
    for i, h in enumerate(header_idxs):
        end = header_idxs[i + 1] if i + 1 < len(header_idxs) else len(raw_lines)
        dfp = read_section(h, end)
        if dfp is not None and not dfp.empty:
            parts.append(dfp)
    
    if not parts:
        raise ValueError("Aucune donnée exploitable")
    
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
        raise ValueError(f"Colonnes Player/Salary introuvables")
    
    out = pd.DataFrame()
    out["Joueur"] = df[player_col].astype(str).str.strip()
    out["Equipe"] = df[team_col].astype(str).str.strip() if team_col else "N/A"
    out["Pos"] = df[pos_col].astype(str).str.strip() if pos_col else "F"
    out["Pos"] = out["Pos"].apply(normalize_pos)
    
    sal = (
        df[salary_col].astype(str)
        .str.replace(",", "", regex=False)
        .str.replace(" ", "", regex=False)
        .replace(["None", "nan", "NaN", ""], "0")
    )
    out["Salaire"] = pd.to_numeric(sal, errors="coerce").fillna(0).astype(int) * 1000
    
    if status_col:
        out["Statut"] = df[status_col].apply(lambda x: "Club École" if "min" in str(x).lower() else "Grand Club")
    else:
        out["Statut"] = "Grand Club"
    
    out["Slot"] = out["Statut"].apply(lambda s: "Actif" if s == "Grand Club" else "")
    out["IR Date"] = ""
    return clean_data(out)

# =====================================================
# POP-UP DÉPLACEMENT
# =====================================================
def open_move_dialog():
    ctx = st.session_state.get("move_ctx")
    if not ctx:
        return
    
    owner = str(ctx.get("owner", "")).strip()
    joueur = str(ctx.get("joueur", "")).strip()
    nonce = int(ctx.get("nonce", 0))
    
    df_all = st.session_state.get("data")
    if df_all is None or df_all.empty:
        clear_move_ctx()
        return
    
    row = df_all[(df_all["Propriétaire"] == owner) & (df_all["Joueur"] == joueur)]
    
    if row.empty:
        clear_move_ctx()
        return
    
    row = row.iloc[0]
    cur_slot = row["Slot"]
    from_ir = (cur_slot == "Blessé")
    
    def _close():
        clear_move_ctx()
    
    @st.dialog(f"Déplacement — {joueur}", width="small")
    def _dlg():
        st.markdown(f"### {joueur}")
        st.caption(f"Slot actuel : {cur_slot}")
        
        if from_ir:
            st.caption("Sortie de IR")
            c1, c2, c3 = st.columns(3)
            
            if c1.button("🟢 Actifs", key=f"ir_actif_{nonce}"):
                ok = apply_move_with_history(owner, joueur, "Grand Club", "Actif", "IR → Actif")
                if ok:
                    _close()
                    do_rerun()
                else:
                    st.error(st.session_state.get("last_move_error", "Erreur"))
            
            if c2.button("🟡 Banc", key=f"ir_banc_{nonce}"):
                ok = apply_move_with_history(owner, joueur, "Grand Club", "Banc", "IR → Banc")
                if ok:
                    _close()
                    do_rerun()
                else:
                    st.error(st.session_state.get("last_move_error", "Erreur"))
            
            if c3.button("🔵 Mineur", key=f"ir_min_{nonce}"):
                ok = apply_move_with_history(owner, joueur, "Club École", "", "IR → Mineur")
                if ok:
                    _close()
                    do_rerun()
                else:
                    st.error(st.session_state.get("last_move_error", "Erreur"))
            
            st.divider()
            if st.button("✖️ Annuler", key=f"ir_cancel_{nonce}"):
                _close()
                do_rerun()
            
            return
        
        st.info("Mode normal (non IR)")
        if st.button("✖️ Annuler", key=f"cancel_{nonce}"):
            _close()
            do_rerun()
    
    _dlg()

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
st.session_state["LOCKED"] = LOCKED

st.sidebar.divider()
st.sidebar.header("💰 Plafonds")

if st.sidebar.button("✏️ Modifier les plafonds"):
    st.session_state["edit_plafond"] = True

if st.session_state.get("edit_plafond"):
    st.session_state["PLAFOND_GC"] = st.sidebar.number_input(
        "Plafond Grand Club",
        value=int(st.session_state["PLAFOND_GC"]),
        step=500_000
    )
    st.session_state["PLAFOND_CE"] = st.sidebar.number_input(
        "Plafond Club École",
        value=int(st.session_state["PLAFOND_CE"]),
        step=250_000
    )

st.sidebar.metric("🏒 Plafond Grand Club", money(st.session_state["PLAFOND_GC"]))
st.sidebar.metric("🏫 Plafond Club École", money(st.session_state["PLAFOND_CE"]))

# =====================================================
# LOAD DATA / HISTORY
# =====================================================
if "season" not in st.session_state or st.session_state["season"] != season:
    if os.path.exists(DATA_FILE):
        st.session_state["data"] = pd.read_csv(DATA_FILE)
    else:
        st.session_state["data"] = pd.DataFrame(columns=REQUIRED_COLS)
    
    st.session_state["data"] = clean_data(st.session_state["data"])
    data_all = st.session_state["data"]  # ✅ Plus clair
    dprop = df[df["Propriétaire"] == proprietaire].copy()
    
    injured_all = dprop[dprop.get("Slot", "") == "Blessé"].copy()
    dprop_ok = dprop[dprop.get("Slot", "") != "Blessé"].copy()
    
    gc_all = dprop_ok[dprop_ok["Statut"] == "Grand Club"].copy()
    ce_all = dprop_ok[dprop_ok["Statut"] == "Club École"].copy()
    
    gc_actif = gc_all[gc_all.get("Slot", "") == "Actif"].copy()
    gc_banc = gc_all[gc_all.get("Slot", "") == "Banc"].copy()
    
    # Comptage positions
    tmp = gc_actif.copy()
    tmp["Pos"] = tmp["Pos"].apply(normalize_pos)
    nb_F = int((tmp["Pos"] == "F").sum())
    nb_D = int((tmp["Pos"] == "D").sum())
    nb_G = int((tmp["Pos"] == "G").sum())
    
    # Plafonds
    cap_gc = int(st.session_state["PLAFOND_GC"])
    cap_ce = int(st.session_state["PLAFOND_CE"])
    used_gc = int(gc_all["Salaire"].sum())
    used_ce = int(ce_all["Salaire"].sum())
    remain_gc = int(cap_gc - used_gc)
    remain_ce = int(cap_ce - used_ce)
    
    # Metrics
    top = st.columns([1, 1, 1, 1, 1])
    top[0].metric("Total GC", money(used_gc))
    top[1].metric("Disponible GC", money(remain_gc))
    top[2].metric("Total CE", money(used_ce))
    top[3].metric("Disponible CE", money(remain_ce))
    top[4].metric("Blessés", f"{len(injured_all)}")
    
    st.markdown(
        f"**Actifs** — F {_count_badge(nb_F,12)} • D {_count_badge(nb_D,6)} • G {_count_badge(nb_G,2)}",
        unsafe_allow_html=True
    )
    
    st.divider()
    
    # Helper pour tables
    def view_plain(x: pd.DataFrame) -> pd.DataFrame:
        if x is None or x.empty:
            return pd.DataFrame(columns=["Joueur", "Pos", "Equipe", "Salaire"])
        y = x.copy()
        for c in ["Joueur", "Equipe", "Pos", "Salaire"]:
            if c not in y.columns:
                y[c] = "" if c != "Salaire" else 0
        y["Pos"] = y["Pos"].apply(normalize_pos)
        y["_sort"] = y["Pos"].apply(pos_sort_key)
        y = y.sort_values(["_sort", "Joueur"]).drop(columns=["_sort"])
        y["Salaire"] = y["Salaire"].apply(money)
        return y[["Joueur", "Pos", "Equipe", "Salaire"]].reset_index(drop=True)
    
    df_actifs_ui = view_plain(gc_actif)
    df_banc_ui = view_plain(gc_banc)
    df_min_ui = view_plain(ce_all)
    
    t1, t2, t3 = st.columns(3)
    
    with t1:
        st.markdown("### 🟢 Actifs")
        st.dataframe(df_actifs_ui, use_container_width=True, hide_index=True,
                     selection_mode="single-row", on_select="rerun", key="sel_actifs")
    
    with t2:
        st.markdown("### 🟡 Banc")
        st.dataframe(df_banc_ui, use_container_width=True, hide_index=True,
                     selection_mode="single-row", on_select="rerun", key="sel_banc")
    
    with t3:
        st.markdown("### 🔵 Mineur")
        st.dataframe(df_min_ui, use_container_width=True, hide_index=True,
                     selection_mode="single-row", on_select="rerun", key="sel_min")
    
    # IR
    st.divider()
    st.markdown("## 🩹 Joueurs Blessés (IR)")
    
    df_ir_ui = None
    if injured_all.empty:
        st.info("Aucun joueur blessé.")
    else:
        ir_show = injured_all.copy()
        if "IR Date" in ir_show.columns:
            ir_show["IR Date"] = ir_show["IR Date"].astype(str).str.strip().replace("", "—")
        
        df_ir_ui = view_plain(ir_show)
        if "IR Date" in ir_show.columns:
            df_ir_ui = df_ir_ui.merge(
                ir_show[["Joueur", "IR Date"]].drop_duplicates(),
                on="Joueur", how="left"
            )
            df_ir_ui["IR Date"] = df_ir_ui["IR Date"].fillna("—")
            df_ir_ui = df_ir_ui[["Joueur", "Pos", "Equipe", "IR Date", "Salaire"]]
        
        st.dataframe(df_ir_ui, use_container_width=True, hide_index=True,
                     selection_mode="single-row", on_select="rerun", key="sel_ir")
    
    # Sélection
    popup_open = st.session_state.get("move_ctx") is not None
    
    if not popup_open:
        picked = None
        picked_key = None
        
        for k, df_ui in [("sel_actifs", df_actifs_ui), ("sel_banc", df_banc_ui),
                         ("sel_min", df_min_ui), ("sel_ir", df_ir_ui)]:
            if df_ui is None or df_ui.empty:
                continue
            p = pick_from_df(df_ui, k)
            if p:
                picked = str(p).strip()
                picked_key = k
                break
        
        if picked and picked_key:
            cur_pick = (str(proprietaire).strip(), picked)
            ctx = st.session_state.get("move_ctx") or {}
            ctx_owner = str(ctx.get("owner", "")).strip()
            ctx_joueur = str(ctx.get("joueur", "")).strip()
            
            if (ctx_owner, ctx_joueur) != cur_pick:
                set_move_ctx(cur_pick[0], cur_pick[1])
                clear_other_selections(picked_key)
                do_rerun()
    
    open_move_dialog()

# =====================================================
# TAB G — GESTION
# =====================================================
with tabG:
    st.subheader("⚙️ Gestion des joueurs")
    
    if LOCKED:
        st.error("🔒 Saison verrouillée")
        st.stop()
    
    sub1, sub2 = st.tabs(["➕ Ajouter un joueur", "🗑️ Retirer un joueur"])
    
    with sub1:
        st.markdown("### ➕ Ajouter un nouveau joueur")
        
        with st.form("add_player_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            
            with c1:
                prop_add = st.selectbox("Propriétaire *",
                    sorted(st.session_state["data"]["Propriétaire"].unique()), key="add_prop")
                joueur_add = st.text_input("Nom du joueur *", placeholder="ex: Connor McDavid", key="add_joueur")
                equipe_add = st.text_input("Équipe NHL", placeholder="ex: EDM", key="add_equipe")
                pos_add = st.selectbox("Position *", ["F", "D", "G"], key="add_pos")
            
            with c2:
                salaire_add = st.number_input("Salaire *", min_value=0, max_value=20_000_000,
                    step=100_000, value=1_000_000, format="%d", key="add_salaire")
                statut_add = st.radio("Statut *", ["Grand Club", "Club École"],
                    horizontal=True, key="add_statut")
                
                if statut_add == "Grand Club":
                    slot_add = st.selectbox("Slot *", ["Actif", "Banc", "Blessé"], key="add_slot")
                else:
                    slot_add = st.selectbox("Slot", ["", "Blessé"], index=0, key="add_slot_ce")
            
            st.divider()
            submitted = st.form_submit_button("✅ Ajouter le joueur", use_container_width=True, type="primary")
            
            if submitted:
                if not joueur_add or not joueur_add.strip():
                    st.error("❌ Le nom du joueur est obligatoire.")
                else:
                    df_current = st.session_state["data"]
                    exists = ((df_current["Propriétaire"] == prop_add) &
                             (df_current["Joueur"].str.strip().str.lower() == joueur_add.strip().lower())).any()
                    
                    if exists:
                        st.error(f"❌ {joueur_add} existe déjà dans l'équipe de {prop_add}.")
                    else:
                        new_row = pd.DataFrame([{
                            "Propriétaire": prop_add,
                            "Joueur": joueur_add.strip(),
                            "Equipe": equipe_add.strip() if equipe_add else "N/A",
                            "Pos": pos_add,
                            "Salaire": int(salaire_add),
                            "Statut": statut_add,
                            "Slot": slot_add if slot_add else "",
                            "IR Date": "",
                        }])
                        
                        st.session_state["data"] = pd.concat([st.session_state["data"], new_row], ignore_index=True)
                        st.session_state["data"] = clean_data(st.session_state["data"])
                        st.session_state["data"].to_csv(DATA_FILE, index=False)
                        
                        try:
                            log_history_row(prop_add, joueur_add.strip(), pos_add,
                                equipe_add.strip() if equipe_add else "N/A",
                                "", "", statut_add, slot_add if slot_add else "", "AJOUT MANUEL")
                        except Exception as e:
                            st.warning(f"⚠️ Joueur ajouté mais historique non écrit: {e}")
                        
                        st.success(f"✅ {joueur_add} ajouté à l'équipe de {prop_add} !")
                        st.toast(f"➕ {joueur_add} ajouté", icon="✅")
                        do_rerun()
        
        st.divider()
        st.markdown("### 📋 Derniers joueurs ajoutés")
        h = st.session_state.get("history", pd.DataFrame())
        if not h.empty and "action" in h.columns:
            recent = h[h["action"] == "AJOUT MANUEL"].sort_values("timestamp", ascending=False).head(5)
            if not recent.empty:
                for _, r in recent.iterrows():
                    st.caption(f"• **{r.get('joueur', 'N/A')}** ({r.get('pos', 'N/A')}) → {r.get('proprietaire', 'N/A')} • {r.get('timestamp', 'N/A')}")
            else:
                st.info("Aucun joueur ajouté manuellement.")
        else:
            st.info("Aucun historique disponible.")
    
    with sub2:
        st.markdown("### 🗑️ Retirer un joueur")
        
        prop_del = st.selectbox("Propriétaire",
            sorted(st.session_state["data"]["Propriétaire"].unique()), key="del_prop")
        
        df_prop = st.session_state["data"][st.session_state["data"]["Propriétaire"] == prop_del].copy()
        
        if df_prop.empty:
            st.info(f"Aucun joueur dans l'équipe de {prop_del}.")
        else:
            df_prop["Pos"] = df_prop["Pos"].apply(normalize_pos)
            df_prop["_sort"] = df_prop["Pos"].apply(pos_sort_key)
            df_prop = df_prop.sort_values(["_sort", "Joueur"]).drop(columns=["_sort"])
            
            joueurs_list = df_prop["Joueur"].tolist()
            joueur_del = st.selectbox("Joueur à retirer", joueurs_list, key="del_joueur")
            
            row_del = df_prop[df_prop["Joueur"] == joueur_del].iloc[0]
            
            st.divider()
            st.markdown("#### Informations du joueur")
            info_cols = st.columns(4)
            info_cols[0].metric("Position", row_del["Pos"])
            info_cols[1].metric("Équipe", row_del["Equipe"])
            info_cols[2].metric("Salaire", money(row_del["Salaire"]))
            info_cols[3].metric("Statut", f"{row_del['Statut']} / {row_del['Slot']}")
            
            st.divider()
            st.warning("⚠️ Cette action est irréversible !")
            
            col1, col2 = st.columns([1, 1])
            
            if col1.button("🗑️ Confirmer le retrait", type="primary", use_container_width=True):
                mask = (st.session_state["data"]["Propriétaire"] == prop_del) & (st.session_state["data"]["Joueur"] == joueur_del)
                st.session_state["data"] = st.session_state["data"][~mask].reset_index(drop=True)
                st.session_state["data"].to_csv(DATA_FILE, index=False)
                
                try:
                    log_history_row(prop_del, joueur_del, row_del["Pos"], row_del["Equipe"],
                        row_del["Statut"], row_del["Slot"], "", "", "RETRAIT MANUEL")
                except Exception as e:
                    st.warning(f"⚠️ Joueur retiré mais historique non écrit: {e}")
                
                st.success(f"✅ {joueur_del} a été retiré.")
                st.toast(f"🗑️ {joueur_del} retiré", icon="🗑️")
                do_rerun()
            
            if col2.button("❌ Annuler", use_container_width=True):
                st.info("Opération annulée.")

# =====================================================
# TAB J — JOUEURS
# =====================================================
with tabJ:
    st.subheader("👤 Base de données joueurs")
    
    if players_db is None or players_db.empty:
        st.error(f"❌ Impossible de charger : {PLAYERS_DB_FILE}")
        st.stop()
    
    df_db = players_db.copy()
    
    if "Player" not in df_db.columns:
        for cand in ["Joueur", "Name", "Full Name"]:
            if cand in df_db.columns:
                df_db = df_db.rename(columns={cand: "Player"})
                break
        if "Player" not in df_db.columns:
            st.error(f"Colonne 'Player' introuvable")
            st.stop()
    
    def _cap_to_int(v) -> int:
        s = str(v or "").strip().replace("$", "").replace(",", "").replace(" ", "")
        s = re.sub(r"[^\d]", "", s)
        return int(s) if s.isdigit() else 0
    
    c1, c2, c3 = st.columns([2, 1, 1])
    
    with c1:
        q_name = st.text_input("Nom / Prénom", placeholder="ex: Connor McDavid", key="j_name")
    
    with c2:
        teams = sorted(df_db["Team"].dropna().unique()) if "Team" in df_db.columns else []
        q_team = st.selectbox("Équipe", ["Toutes"] + teams, key="j_team")
    
    with c3:
        levels = sorted(df_db["Level"].dropna().unique()) if "Level" in df_db.columns else []
        q_level = st.selectbox("Level", ["Tous"] + levels, key="j_level")
    
    st.divider()
    cap_col = next((c for c in ["Cap Hit", "CapHit", "AAV"] if c in df_db.columns), None)
    
    if cap_col:
        df_db["_cap_int"] = df_db[cap_col].apply(_cap_to_int)
        cap_enabled = st.checkbox("Activer filtre Cap Hit", key="cap_filter")
        
        if cap_enabled:
            cap_min, cap_max = st.slider("Plage Cap Hit", 0, 30_000_000,
                (0, 30_000_000), step=250_000, key="cap_slider")
            st.caption(f"{money(cap_min)} → {money(cap_max)}")
        else:
            cap_min = cap_max = 0
    else:
        cap_enabled = False
        cap_min = cap_max = 0
    
    has_filter = bool(q_name.strip()) or (q_team != "Toutes") or (q_level != "Tous") or cap_enabled
    
    if not has_filter:
        st.info("Entre au moins un filtre.")
    else:
        dff = df_db.copy()
        
        if q_name.strip():
            dff = dff[dff["Player"].str.contains(q_name, case=False, na=False)]
        if q_team != "Toutes":
            dff = dff[dff["Team"] == q_team]
        if q_level != "Tous":
            dff = dff[dff["Level"] == q_level]
        if cap_enabled and cap_col:
            dff = dff[(dff["_cap_int"] >= cap_min) & (dff["_cap_int"] <= cap_max)]
        
        if dff.empty:
            st.warning("Aucun résultat.")
        else:
            dff = dff.head(100).reset_index(drop=True)
            show_cols = [c for c in ["Player", "Team", "Position", cap_col, "Level"] if c in dff.columns]
            df_show = dff[show_cols].copy()
            
            if cap_col in df_show.columns:
                df_show[cap_col] = df_show[cap_col].apply(lambda x: money(_cap_to_int(x)))
                df_show = df_show.rename(columns={cap_col: "Cap Hit"})
            
            st.markdown(f"### 📋 Résultats ({len(df_show)} joueurs)")
            st.dataframe(df_show, use_container_width=True, hide_index=True, height=400)
    
    st.divider()
    st.markdown("### 📊 Comparer 2 joueurs")
    
    players_list = sorted(df_db["Player"].unique())
    c1, c2 = st.columns(2)
    with c1:
        p1 = st.selectbox("Joueur A", ["—"] + players_list, key="cmp_p1")
    with c2:
        p2 = st.selectbox("Joueur B", ["—"] + players_list, key="cmp_p2")
    
    if p1 != "—" and p2 != "—" and p1 != p2:
        r1 = df_db[df_db["Player"] == p1].head(1)
        r2 = df_db[df_db["Player"] == p2].head(1)
        
        if not r1.empty and not r2.empty:
            df_cmp = pd.concat([r1, r2], ignore_index=True)
            show_cols = [c for c in ["Player", "Team", "Position", cap_col, "Level"] if c in df_cmp.columns]
            df_cmp_show = df_cmp[show_cols].copy()
            
            if cap_col in df_cmp_show.columns:
                df_cmp_show[cap_col] = df_cmp_show[cap_col].apply(lambda x: money(_cap_to_int(x)))
                df_cmp_show = df_cmp_show.rename(columns={cap_col: "Cap Hit"})
            
            st.dataframe(df_cmp_show, use_container_width=True, hide_index=True)

# =====================================================
# TAB H — HISTORIQUE
# =====================================================
with tabH:
    st.subheader("🕘 Historique")
    
    h = st.session_state["history"].copy()
    if h.empty:
        st.info("Aucune entrée d'historique.")
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
            
            st.caption("↩️ = annuler • ❌ = supprimer")
            
            head = st.columns([1.5, 1.4, 2.4, 1.0, 1.6, 1.6, 2.0, 0.8, 0.7])
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
                cols = st.columns([1.5, 1.4, 2.4, 1.0, 1.6, 1.6, 2.0, 0.8, 0.7])
                
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
                        st.error("🔒 Saison verrouillée")
                    else:
                        owner = str(r["proprietaire"])
                        joueur = str(r["joueur"])
                        mask = (st.session_state["data"]["Propriétaire"] == owner) & (st.session_state["data"]["Joueur"] == joueur)
                        
                        if st.session_state["data"][mask].empty:
                            st.error("Joueur introuvable")
                        else:
                            before = st.session_state["data"][mask].iloc[0]
                            cur_statut = str(before.get("Statut", ""))
                            cur_slot = str(before.get("Slot", "")).strip()
                            pos0 = str(before.get("Pos", "F"))
                            equipe0 = str(before.get("Equipe", ""))
                            
                            st.session_state["data"].loc[mask, "Statut"] = str(r["from_statut"])
                            st.session_state["data"].loc[mask, "Slot"] = str(r["from_slot"]) if str(r["from_slot"]).strip() else ""
                            
                            if cur_slot == "Blessé" and str(r["from_slot"]).strip() != "Blessé":
                                st.session_state["data"].loc[mask, "IR Date"] = ""
                            
                            st.session_state["data"] = clean_data(st.session_state["data"])
                            st.session_state["data"].to_csv(DATA_FILE, index=False)
                            
                            log_history_row(owner, joueur, pos0, equipe0, cur_statut, cur_slot,
                                str(r["from_statut"]), str(r["from_slot"]) if str(r["from_slot"]).strip() else "",
                                action=f"UNDO #{rid}")
                            
                            st.toast("↩️ Changement annulé", icon="↩️")
                            do_rerun()
                
                if cols[8].button("❌", key=f"del_{rid}"):
                    h2 = st.session_state["history"].copy()
                    h2 = h2[h2["id"] != rid]
                    st.session_state["history"] = h2
                    save_history(HISTORY_FILE, h2)
                    st.toast("🗑️ Entrée supprimée", icon="🗑️")
                    do_rerun()

# =====================================================
# TAB 2 — TRANSACTIONS
# =====================================================
with tab2:
    p = st.selectbox("Propriétaire", plafonds["Propriétaire"], key="tx_owner")
    salaire = st.number_input("Salaire du joueur", min_value=0, step=100000, key="tx_salary")
    statut = st.radio("Statut", ["Grand Club", "Club École"], key="tx_statut")
    
    ligne = plafonds[plafonds["Propriétaire"] == p].iloc[0]
    reste = ligne["Montant Disponible GC"] if statut == "Grand Club" else ligne["Montant Disponible CE"]
    
    if salaire > reste:
        st.error("🚨 Dépassement du plafond")
    else:
        st.success("✅ Transaction valide")

# =====================================================
# TAB 3 — RECOMMANDATIONS
# =====================================================
with tab3:
    for _, r in plafonds.iterrows():
        if r["Montant Disponible GC"] < 2_000_000:
            st.warning(f"{r['Propriétaire']} : rétrogradation recommandée")
        if r["Montant Disponible CE"] > 10_000_000:
            st.info(f"{r['Propriétaire']} : rappel possible")(st.session_state["data"])
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
    key=f"fantrax_uploader_{st.session_state['uploader_nonce']}",
)

if uploaded is not None:
    if LOCKED:
        st.sidebar.warning("🔒 Saison verrouillée")
    else:
        try:
            df_import = parse_fantrax(uploaded)
            if df_import is None or df_import.empty:
                st.sidebar.error("❌ Import invalide")
            else:
                owner = os.path.splitext(uploaded.name)[0]
                df_import["Propriétaire"] = owner
                
                st.session_state["data"] = pd.concat([st.session_state["data"], df_import], ignore_index=True)
                st.session_state["data"] = clean_data(st.session_state["data"])
                st.session_state["data"].to_csv(DATA_FILE, index=False)
                
                st.sidebar.success("✅ Import réussi")
                st.session_state["uploader_nonce"] += 1
                do_rerun()
        except Exception as e:
            st.sidebar.error(f"❌ Import échoué : {e}")

# =====================================================
# HEADER
# =====================================================
if os.path.exists(LOGO_POOL_FILE):
    st.image(LOGO_POOL_FILE, use_container_width=True)

st.title("🏒 Pool de Hockey — Gestion Salariale")

df = st.session_state["data"]  # ❌ Conflit
if df.empty:
    st.info("Aucune donnée")
    st.stop()

# =====================================================
# CALCULS PLAFONDS (CACHE)
# =====================================================
@st.cache_data(ttl=60, show_spinner=False)
def calc_plafonds(df: pd.DataFrame, plafond_gc: int, plafond_ce: int) -> pd.DataFrame:
    resume = []
    for p in df["Propriétaire"].unique():
        d = df[df["Propriétaire"] == p]
        total_gc = d[(d["Statut"] == "Grand Club") & (d["Slot"] != "Blessé")]["Salaire"].sum()
        total_ce = d[(d["Statut"] == "Club École") & (d["Slot"] != "Blessé")]["Salaire"].sum()
        
        resume.append({
            "Propriétaire": str(p),
            "Logo": find_logo_for_owner(p),
            "Total Grand Club": int(total_gc),
            "Montant Disponible GC": int(plafond_gc - total_gc),
            "Total Club École": int(total_ce),
            "Montant Disponible CE": int(plafond_ce - total_ce),
        })
    
    return pd.DataFrame(resume)

plafonds = calc_plafonds(df, st.session_state["PLAFOND_GC"], st.session_state["PLAFOND_CE"])

# =====================================================
# TABS
# =====================================================
tab1, tabA, tabG, tabJ, tabH, tab2, tab3 = st.tabs(
    ["📊 Tableau", "🧾 Alignement", "⚙️ Gestion", "👤 Joueurs", "🕘 Historique", "⚖️ Transactions", "🧠 Recommandations"]
)

# =====================================================
# TAB 1 — TABLEAU
# =====================================================
with tab1:
    headers = st.columns([4, 2, 2, 2, 2])
    headers[0].markdown("**Équipe**")
    headers[1].markdown("**Total Grand Club**")
    headers[2].markdown("**Montant Disponible GC**")
    headers[3].markdown("**Total Club École**")
    headers[4].markdown("**Montant Disponible CE**")
    
    for _, r in plafonds.iterrows():
        cols = st.columns([4, 2, 2, 2, 2])
        owner = str(r["Propriétaire"])
        logo_path = str(r.get("Logo", "")).strip()
        
        with cols[0]:
            c_logo, c_name = st.columns([1, 4])
            with c_logo:
                if logo_path and os.path.exists(logo_path):
                    st.image(logo_path, width=LOGO_SIZE)
                else:
                    st.markdown("—")
            with c_name:
                st.markdown(f"**{owner}**")
        
        cols[1].markdown(money(r["Total Grand Club"]))
        cols[2].markdown(money(r["Montant Disponible GC"]))
        cols[3].markdown(money(r["Total Club École"]))
        cols[4].markdown(money(r["Montant Disponible CE"]))

# =====================================================
# TAB A — ALIGNEMENT
# =====================================================
with tabA:
    st.subheader("🧾 Alignement")
    
    proprietaire = st.selectbox(
        "Propriétaire",
        sorted(st.session_state["data"]["Propriétaire"].unique()),
        key="align_owner",
    )
    
    st.session_state["data"] = clean_data