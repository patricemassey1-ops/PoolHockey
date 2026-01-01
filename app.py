# app.py — Fantrax Pool Hockey (FINAL)
# ✅ Logos propriétaires dans /data
# ✅ Tableau: colonnes renommées
# ✅ Alignement: 3 tableaux (Actifs/Banc/Mineur) avec checkbox + pop-up déplacement
# ✅ Déplacement vers Blessé: salaire exclu des plafonds + IR Date enregistrée (America/Toronto)
# ✅ Pop-up: infos joueur (Pays, Flag, Position, Grandeur, Poids, Cap Hit, Level)
# ✅ Historique + Undo + Delete
# ✅ Import Fantrax robuste
# ✅ Joueurs (data/Hockey.Players.csv) filtres + comparaison

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

PLAYERS_DB_FILE = "data/Hockey.Players.csv"   # ✅ confirmé
LOGO_POOL_FILE = "data/Logo_Pool.png"         # si tu l'as (sinon il s'affiche pas)

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

def clear_selection_key(key: str):
    """Vide la sélection d'un st.dataframe (sans réassigner st.session_state[key])."""
    ss = st.session_state.get(key)
    if isinstance(ss, dict):
        sel = ss.get("selection")
        if isinstance(sel, dict) and "rows" in sel:
            sel["rows"].clear()


def saison_auto():
    now = datetime.now()
    return f"{now.year}-{now.year+1}" if now.month >= 9 else f"{now.year-1}-{now.year}"

def saison_verrouillee(season):
    return int(season[:4]) < int(saison_auto()[:4])

def resolve_image_path_or_url(s: str) -> str:
    s = str(s or "").strip()
    if not s:
        return ""
    # URL
    if s.startswith("http://") or s.startswith("https://"):
        return s
    # déjà dans data/
    if s.startswith("data/") and os.path.exists(s):
        return s
    # fichier local (ex: "flags/canada.png" ou "canada.png")
    if os.path.exists(s):
        return s
    # fallback data/
    cand = os.path.join("data", s)
    if os.path.exists(cand):
        return cand
    return ""

def badge_pos(pos: str) -> str:
    p = normalize_pos(pos)
    colors = {
        "F": "#2563eb",  # bleu
        "D": "#16a34a",  # vert
        "G": "#9333ea",  # violet
    }
    color = colors.get(p, "#6b7280")
    return f"<span style='color:white;background:{color};padding:2px 8px;border-radius:12px;font-size:0.75em'>{p}</span>"


def badge_slot(slot: str) -> str:
    s = str(slot or "").lower()
    if s == "actif":
        return "<span style='color:#166534;font-weight:700'>🟢 Actif</span>"
    if s == "banc":
        return "<span style='color:#92400e;font-weight:700'>🟡 Banc</span>"
    if s == "blessé":
        return "<span style='color:#991b1b;font-weight:700'>🩹 IR</span>"
    return "<span style='color:#1e40af;font-weight:700'>🔵 Mineur</span>"


def close_move_dialog():
    st.session_state["move_ctx"] = None
    st.session_state["last_pick_align"] = None
    do_rerun()

def mini_cap_bar(used: int, cap: int, label: str = "") -> str:
    if cap <= 0:
        pct = 0
    else:
        pct = min(used / cap, 1.25)

    pct_display = used / cap if cap > 0 else 0

    if pct_display <= 0.90:
        color = "#16a34a"   # vert
    elif pct_display <= 1.0:
        color = "#f59e0b"   # orange
    else:
        color = "#dc2626"   # rouge

    bar_width = min(int(pct * 100), 125)

    return f"""
    <div style="margin-bottom:6px">
      <div style="display:flex;justify-content:space-between;font-size:12px;font-weight:700">
        <span>{label}</span>
        <span>{int(pct_display*100)}%</span>
      </div>
      <div style="background:#e5e7eb;border-radius:6px;height:10px;overflow:hidden">
        <div style="
            width:{bar_width}%;
            background:{color};
            height:100%;
            border-radius:6px;
        "></div>
      </div>
      <div style="font-size:11px;opacity:.75">
        {money(used)} / {money(cap)}
      </div>
    </div>
    """


def _count_badge(n, limit):
    if n > limit:
        color = "#ef4444"  # rouge
        icon = " ⚠️"
    else:
        color = "#22c55e"  # vert
        icon = ""

    return f"<span style='color:{color};font-weight:1000'>{n}</span>/{limit}{icon}"

def colored_count(label: str, n: int, limit: int) -> str:
    color = "#16a34a" if n <= limit else "#ef4444"  # vert / rouge
    return f"<span style='font-weight:900;color:{color}'>{label} {n}/{limit}</span>"
      
def view_for_click(x: pd.DataFrame) -> pd.DataFrame:
    """
    Table UI Actif / Banc / Mineur avec badges couleur.
    ⚠️ Ne modifie JAMAIS la colonne 'Joueur'
    """
    if x is None or x.empty:
        return pd.DataFrame(columns=["Joueur", "Pos", "Slot", "Equipe", "Salaire"])

    y = x.copy()

    # Colonnes garanties
    for c, d in {
        "Joueur": "",
        "Pos": "F",
        "Slot": "",
        "Equipe": "",
        "Salaire": 0,
    }.items():
        if c not in y.columns:
            y[c] = d

    # Tri par position
    y["Pos"] = y["Pos"].apply(normalize_pos)
    y["_pos_order"] = y["Pos"].apply(pos_sort_key)
    y = y.sort_values(["_pos_order", "Joueur"]).drop(columns="_pos_order")

    # Badges
    y["Pos"] = y["Pos"].apply(badge_pos)
    y["Slot"] = y["Slot"].apply(badge_slot)
    y["Salaire"] = y["Salaire"].apply(money)

    return y[["Joueur", "Pos", "Slot", "Equipe", "Salaire"]].reset_index(drop=True)


# -------------------------------------------------------------------
# SAFETY PATCH — si un vieux code appelle encore clear_df_selections()
# -------------------------------------------------------------------
def clear_df_selections():
    # Redirige vers la méthode Streamlit-safe
    clear_other_selections(keep_key="__none__")


# =====================================================
# STREAMLIT TABLE SELECTION — TRIO 100% COMPATIBLE
# =====================================================

def clear_other_selections(keep_key: str | None = None):
    for k in ["sel_actifs", "sel_banc", "sel_min"]:
        if keep_key and k == keep_key:
            continue
        ss = st.session_state.get(k)
        if isinstance(ss, dict):
            sel = ss.get("selection")
            if isinstance(sel, dict):
                sel["rows"] = []
            else:
                ss["selection"] = {"rows": []}



def pick_from_df(df_ui: pd.DataFrame, key: str):
    """
    Retourne le nom du joueur sélectionné dans un st.dataframe(selection_mode="single-row").
    """
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
# STREAMLIT — CLEAR OTHER SELECTIONS (4 tableaux)
#   Clés: sel_actifs, sel_banc, sel_min, sel_ir
#   ✅ Ne réassigne jamais st.session_state[key] (évite StreamlitAPIException)
# =====================================================

SELECTION_KEYS_ALIGN = ["sel_actifs", "sel_banc", "sel_min", "sel_ir"]

def clear_other_selections(keep_key: str):
    """
    Vide la sélection des autres dataframes (Actifs/Banc/Mineur/IR),
    en laissant seulement 'keep_key' intact.
    """
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


def clear_selection_key(k: str):
    """
    Vide la sélection d'UN seul dataframe (utile si tu veux vider aussi keep_key).
    """
    ss = st.session_state.get(k)
    if not isinstance(ss, dict):
        return

    sel = ss.get("selection")
    if isinstance(sel, dict):
        rows = sel.get("rows")
        if isinstance(rows, list):
            rows.clear()
        else:
            sel["rows"] = []
    else:
        ss["selection"] = {"rows": []}



# =====================================================
# PLAYERS DB (data/Hockey.Players.csv)
# =====================================================
def _norm_name(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip()).lower()

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

    dfp["_name_key"] = dfp[name_col].astype(str).map(_norm_name)
    return dfp

def _norm_key(s: str) -> str:
    s = str(s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    # enlève ponctuation et suffixes fréquents
    s = re.sub(r"[^\w\s-]", "", s)
    s = s.replace(" jr", "").replace(" sr", "")
    return s.strip()

def get_player_row(players_df: pd.DataFrame, player_name: str) -> dict | None:
    if players_df is None or players_df.empty:
        return None

    q = _norm_key(player_name)

    # 1) match exact via _name_key si présent
    if "_name_key" in players_df.columns:
        hit = players_df[players_df["_name_key"].astype(str).map(_norm_key) == q]
        if not hit.empty:
            return hit.iloc[0].to_dict()

    # 2) fallback exact sur "Player"
    if "Player" in players_df.columns:
        hit = players_df[players_df["Player"].astype(str).map(_norm_key) == q]
        if not hit.empty:
            return hit.iloc[0].to_dict()

    # 3) fallback "contains" (utile si Fantrax ajoute un suffixe)
    if "Player" in players_df.columns and q:
        mask = players_df["Player"].astype(str).map(_norm_key).str.contains(re.escape(q), na=False)
        hit = players_df[mask]
        if not hit.empty:
            return hit.iloc[0].to_dict()

        # 4) fallback inverse: q est plus long que Player (rare)
        mask2 = players_df["Player"].astype(str).map(_norm_key).apply(lambda x: x in q if x else False)
        hit2 = players_df[mask2]
        if not hit2.empty:
            return hit2.iloc[0].to_dict()

    return None


PLAYERS_DB_FILE = "data/Hockey.Players.csv"
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

    # texte
    for c in ["Propriétaire", "Joueur", "Statut", "Slot", "Pos", "Equipe", "IR Date"]:
        df[c] = df[c].astype(str).fillna("").map(lambda x: re.sub(r"\s+", " ", x).strip())

    # salaire
    def _to_int(x):
        s = str(x).strip().replace(",", "").replace(" ", "")
        s = re.sub(r"[^\d]", "", s)
        return int(s) if s.isdigit() else 0

    df["Salaire"] = df["Salaire"].apply(_to_int).astype(int)

    # statut standard
    df["Statut"] = df["Statut"].replace(
        {
            "GC": "Grand Club",
            "CE": "Club École",
            "Club Ecole": "Club École",
            "GrandClub": "Grand Club",
        }
    )

    # slot standard
    df["Slot"] = df["Slot"].replace(
        {
            "Active": "Actif",
            "Bench": "Banc",
            "IR": "Blessé",
            "Injured": "Blessé",
        }
    )

    # pos standard
    df["Pos"] = df["Pos"].apply(normalize_pos)

    # sécurité slot selon statut
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

def set_move_ctx(owner: str, joueur: str):
    st.session_state["move_nonce"] = st.session_state.get("move_nonce", 0) + 1
    st.session_state["move_ctx"] = {
        "owner": str(owner).strip(),
        "joueur": str(joueur).strip(),  # ✅ minuscule
        "nonce": st.session_state["move_nonce"],
    }


def clear_move_ctx():
    st.session_state["move_ctx"] = None

# =====================================================
# HISTORY
# =====================================================
def load_history(history_file: str) -> pd.DataFrame:
    if os.path.exists(history_file):
        return pd.read_csv(history_file)
    return pd.DataFrame(
        columns=[
            "id", "timestamp", "season",
            "proprietaire", "joueur", "pos", "equipe",
            "from_statut", "from_slot", "to_statut", "to_slot",
            "action"
        ]
    )

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
    # Reset erreur précédente
    st.session_state["last_move_error"] = ""

    # Verrou saison
    if st.session_state.get("LOCKED"):
        st.session_state["last_move_error"] = "🔒 Saison verrouillée : modification impossible."
        return False

    # ✅ df0 DOIT exister
    df0 = st.session_state.get("data")
    if df0 is None or df0.empty:
        st.session_state["last_move_error"] = "Aucune donnée en mémoire (st.session_state['data'] vide)."
        return False

    df0 = df0.copy()

    # Colonnes requises
    if "IR Date" not in df0.columns:
        df0["IR Date"] = ""

    proprietaire = str(proprietaire).strip()
    joueur = str(joueur).strip()
    to_statut = str(to_statut).strip()
    to_slot = str(to_slot).strip()

    allowed_slots_gc = {"Actif", "Banc", "Blessé"}
    allowed_slots_ce = {"", "Blessé"}

    if to_statut == "Grand Club" and to_slot not in allowed_slots_gc:
        st.session_state["last_move_error"] = f"Slot invalide pour Grand Club: {to_slot}"
        return False
    if to_statut == "Club École" and to_slot not in allowed_slots_ce:
        st.session_state["last_move_error"] = f"Slot invalide pour Club École: {to_slot}"
        return False

    mask = (
        df0["Propriétaire"].astype(str).str.strip().eq(proprietaire)
        & df0["Joueur"].astype(str).str.strip().eq(joueur)
    )
    if df0.loc[mask].empty:
        st.session_state["last_move_error"] = "Joueur introuvable pour ce propriétaire."
        return False

    before = df0.loc[mask].iloc[0]
    from_statut = str(before.get("Statut", "")).strip()
    from_slot = str(before.get("Slot", "")).strip()
    pos0 = str(before.get("Pos", "F")).strip()
    equipe0 = str(before.get("Equipe", "")).strip()

    # Applique changement
    df0.loc[mask, "Statut"] = to_statut
    df0.loc[mask, "Slot"] = (to_slot if to_slot else "")

    # IR Date (Toronto)
    entering_ir = (to_slot == "Blessé") and (from_slot != "Blessé")
    leaving_ir = (from_slot == "Blessé") and (to_slot != "Blessé")
    if entering_ir:
        now_tor = datetime.now(ZoneInfo("America/Toronto"))
        df0.loc[mask, "IR Date"] = now_tor.strftime("%Y-%m-%d %H:%M")
    elif leaving_ir:
        df0.loc[mask, "IR Date"] = ""

    # Nettoyage standard
    df0 = clean_data(df0)

    # Sauve en session
    st.session_state["data"] = df0

    # Sauve CSV si possible
    try:
        data_file = st.session_state.get("DATA_FILE")
        if data_file:
            df0.to_csv(data_file, index=False)
    except Exception as e:
        st.session_state["last_move_error"] = f"Erreur sauvegarde CSV: {e}"
        return False

    # Log historique si dispo
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
        # On ne bloque pas le move si l'historique fail
        st.warning(f"⚠️ Déplacement OK, mais historique non écrit: {e}")

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
        raise ValueError("Colonnes Fantrax non détectées (Player/Salary).")

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

    # Fantrax salary souvent en milliers => *1000
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
# SELECTABLE TABLE (checkbox)
# =====================================================
def selectable_roster_table(df_src: pd.DataFrame, key: str, title: str) -> str | None:
    st.markdown(f"### {title}")

    if df_src is None or df_src.empty:
        st.info("Aucun joueur.")
        return None

    t = df_src.copy()
    t["Pos"] = t["Pos"].apply(normalize_pos)
    t["_pos_order"] = t["Pos"].apply(pos_sort_key)
    t = t.sort_values(["_pos_order", "Joueur"]).drop(columns=["_pos_order"]).reset_index(drop=True)

    show = pd.DataFrame({
        "✅": [False] * len(t),
        "Joueur": t["Joueur"].astype(str),
        "Pos": t["Pos"].astype(str),
        "Équipe": t["Equipe"].astype(str),
        "Salaire": t["Salaire"].apply(money),
    })

    edited = st.data_editor(
        show,
        key=key,
        use_container_width=True,
        hide_index=True,
        column_config={
            "✅": st.column_config.CheckboxColumn("✅", help="Coche un joueur pour le déplacer", default=False),
            "Salaire": st.column_config.TextColumn("Salaire"),
        },
        disabled=["Joueur", "Pos", "Équipe", "Salaire"],
    )

    picked_rows = edited.index[edited["✅"] == True].tolist()
    if not picked_rows:
        return None

    idx = int(picked_rows[0])
    if idx < 0 or idx >= len(edited):
        return None

    return str(edited.loc[idx, "Joueur"]).strip()

# =====================================================
# POP-UP DÉPLACEMENT (infos joueur + IR sortant)
# =====================================================

def _pick(d: dict, candidates: list[str], default=""):
    for k in candidates:
        if k in d and pd.notna(d[k]) and str(d[k]).strip() != "":
            return str(d[k]).strip()
    return default


def open_move_dialog():
    ctx = st.session_state.get("move_ctx")
    if not ctx:
        return

    owner = ctx.get("owner")
    joueur = ctx.get("joueur")
    nonce = ctx.get("nonce", 0)

    df = st.session_state["data"]
    row = df[(df["Propriétaire"] == owner) & (df["Joueur"] == joueur)]
    if row.empty:
        return

    row = row.iloc[0]
    cur_statut = row.get("Statut", "")
    cur_slot = row.get("Slot", "")
    cur_pos = row.get("Pos", "")
    cur_team = row.get("Equipe", "")
    cur_salary = row.get("Salaire", 0)

    @st.dialog("🔁 Déplacement joueur", width="small")
    def _dlg():
        # =====================================================
        # HEADER COMPACT
        # =====================================================
        st.markdown(
            f"""
            <div style="line-height:1.2">
                <b>{joueur}</b><br>
                <span style="font-size:0.85em;color:#666">
                    {cur_team} · {cur_pos} · {money(cur_salary)}
                </span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.divider()

        # =====================================================
        # 🩹 CAS IR — POP-UP ULTRA COMPACT
        # =====================================================
        if cur_slot == "Blessé":
            st.markdown(
                "<b>🩹 Joueur sur la liste des blessés</b>",
                unsafe_allow_html=True,
            )

            c1, c2, c3 = st.columns(3)

            if c1.button("🟢 Actifs", use_container_width=True, key=f"ir_actif_{nonce}"):
                apply_move(owner, joueur, "Grand Club", "Actif")
                st.session_state["move_ctx"] = None
                do_rerun()

            if c2.button("🟡 Banc", use_container_width=True, key=f"ir_banc_{nonce}"):
                apply_move(owner, joueur, "Grand Club", "Banc")
                st.session_state["move_ctx"] = None
                do_rerun()

            if c3.button("🔵 Mineur", use_container_width=True, key=f"ir_min_{nonce}"):
                apply_move(owner, joueur, "Club École", "")
                st.session_state["move_ctx"] = None
                do_rerun()

            st.divider()
            if st.button("❌ Annuler", use_container_width=True):
                st.session_state["move_ctx"] = None
                do_rerun()

            return  # ⛔ STOP — IR = UI dédiée uniquement

        # =====================================================
        # CAS NORMAL (Actif / Banc / Mineur / IR)
        # =====================================================
        destinations = [
            ("🟢 Actifs (Grand Club)", ("Grand Club", "Actif")),
            ("🟡 Banc (Grand Club)", ("Grand Club", "Banc")),
            ("🔵 Mineur (Club École)", ("Club École", "")),
            ("🩹 Blessé (IR)", (cur_statut, "Blessé")),
        ]

        current = (cur_statut, cur_slot if cur_slot else "")
        destinations = [d for d in destinations if d[1] != current]

        labels = [d[0] for d in destinations]
        dest_map = {d[0]: d[1] for d in destinations}

        choix = st.radio(
            "Destination",
            labels,
            key=f"dest_{nonce}",
            label_visibility="collapsed",
        )

        to_statut, to_slot = dest_map[choix]

        st.divider()
        c_ok, c_cancel = st.columns(2)

        if c_ok.button("✅ Confirmer", use_container_width=True):
            ok = apply_move_with_history(
                proprietaire=owner,
                joueur=joueur,
                to_statut=to_statut,
                to_slot=to_slot,
                action_label=f"{cur_statut}/{cur_slot or '-'} → {to_statut}/{to_slot or '-'}",
            )
            if ok:
                clear_move_ctx()
                do_rerun()


        if c_cancel.button("❌ Annuler", use_container_width=True):
            st.session_state["move_ctx"] = None
            do_rerun()

    _dlg()




# =====================================================
# SIDEBAR — Saison & plafonds
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
# LOAD DATA / HISTORY quand saison change
# =====================================================
if "season" not in st.session_state or st.session_state["season"] != season:
    if os.path.exists(DATA_FILE):
        st.session_state["data"] = pd.read_csv(DATA_FILE)
    else:
        st.session_state["data"] = pd.DataFrame(columns=REQUIRED_COLS)

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
    help="Le fichier peut contenir Skaters et Goalies séparés par une ligne vide.",
    key=f"fantrax_uploader_{st.session_state['uploader_nonce']}",
)
if uploaded is not None:
    if LOCKED:
        st.sidebar.warning("🔒 Saison verrouillée : import désactivé.")
    else:
        try:
            df_import = parse_fantrax(uploaded)
            if df_import is None or df_import.empty:
                st.sidebar.error("❌ Import invalide : aucune donnée exploitable.")
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

df = st.session_state["data"]
if df.empty:
    st.info("Aucune donnée")
    st.stop()

# =====================================================
# CALCULS PLAFONDS (EXCLUT BLESSÉS)
# =====================================================
resume = []
for p in df["Propriétaire"].unique():
    d = df[df["Propriétaire"] == p]

    total_gc = d[(d["Statut"] == "Grand Club") & (d["Slot"] != "Blessé")]["Salaire"].sum()
    total_ce = d[(d["Statut"] == "Club École") & (d["Slot"] != "Blessé")]["Salaire"].sum()

    logo = find_logo_for_owner(p)

    resume.append({
        "Propriétaire": str(p),
        "Logo": logo,
        "Total Grand Club": int(total_gc),
        "Montant Disponible GC": int(st.session_state["PLAFOND_GC"] - total_gc),
        "Total Club École": int(total_ce),
        "Montant Disponible CE": int(st.session_state["PLAFOND_CE"] - total_ce),
    })

plafonds = pd.DataFrame(resume)




# =====================================================
# TABS
# =====================================================
tab1, tabA, tabJ, tabH, tab2, tab3 = st.tabs(
    ["📊 Tableau", "🧾 Alignement", "👤 Joueurs", "🕘 Historique", "⚖️ Transactions", "🧠 Recommandations"]
)

# =====================================================
# TAB 1 — Tableau (renommé + logos)
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

        # --- COLONNE ÉQUIPE ---
        with cols[0]:
            c_logo, c_name = st.columns([1, 4])

            with c_logo:
                if logo_path and os.path.exists(logo_path):
                    st.image(logo_path, width=LOGO_SIZE)
                else:
                    st.markdown("—")

            with c_name:
                st.markdown(f"**{owner}**")

        # --- AUTRES COLONNES ---
        cols[1].markdown(money(r["Total Grand Club"]))
        cols[2].markdown(money(r["Montant Disponible GC"]))
        cols[3].markdown(money(r["Total Club École"]))
        cols[4].markdown(money(r["Montant Disponible CE"]))


# =====================================================
# TAB A — Alignement (BLOC COMPLET, PROPRE, CORRIGÉ)
#  ✅ Jauge: remplie selon UTILISÉ/CAP (pleine proche du plafond)
#  ✅ AUCUN HTML dans les tableaux (donc plus d'erreurs <span ...>)
#  ✅ IR: sélection cliquable + pop-up permet Actifs/Banc/Mineur
#  ✅ Annuler du pop-up: fonctionne (clear ctx + rerun)
# =====================================================
with tabA:
    st.subheader("🧾 Alignement")

    # ----------------------------
    # Propriétaire
    # ----------------------------
    proprietaire = st.selectbox(
        "Propriétaire",
        sorted(st.session_state["data"]["Propriétaire"].unique()),
        key="align_owner",
    )

    st.session_state["data"] = clean_data(st.session_state["data"])
    df = st.session_state["data"]
    dprop = df[df["Propriétaire"] == proprietaire].copy()

    # ----------------------------
    # Helpers TAB-LOCAL (safe)
    # ----------------------------
    def cap_bar_used(used: int, cap: int, label: str) -> str:
        """
        Bar = USED/CAP (donc pleine quand on approche le plafond)
        Si dépassement: bar rouge pleine + texte dépassement
        """
        used = int(used)
        cap = int(cap) if cap else 0
        remain = cap - used

        if cap <= 0:
            pct = 0
        else:
            pct = min(max(used / cap, 0), 1.0)

        over = used - cap
        is_over = over > 0
        color = "#dc2626" if is_over else "#16a34a"  # rouge si dépasse

        over_txt = f"<div style='font-size:11px;font-weight:800;color:#dc2626'>Dépassement : {money(over)}</div>" if is_over else ""

        return f"""
        <div style="margin-bottom:10px">
          <div style="display:flex;justify-content:space-between;font-size:12px;font-weight:800">
            <span>{label}</span>
            <span style="color:{'#dc2626' if remain < 0 else '#111827'}">{money(remain)}</span>
          </div>
          <div style="background:#e5e7eb;height:10px;border-radius:6px;overflow:hidden">
            <div style="width:{int(pct*100)}%;background:{color};height:100%"></div>
          </div>
          <div style="font-size:11px;opacity:.75">
            Utilisé : {money(used)} / {money(cap)}
          </div>
          {over_txt}
        </div>
        """

    def clear_other_selections(keep_key: str):
        """
        Vider la sélection des autres dataframes SANS réassigner st.session_state[key]
        (évite StreamlitAPIException).
        """
        for k in ["sel_actifs", "sel_banc", "sel_min", "sel_ir"]:
            if k == keep_key:
                continue
            ss = st.session_state.get(k)
            if isinstance(ss, dict):
                sel = ss.get("selection")
                if isinstance(sel, dict) and "rows" in sel:
                    sel["rows"].clear()

    def pick_from_df_local(df_ui: pd.DataFrame, key: str):
        """
        Retourne le Joueur sélectionné dans st.dataframe(selection_mode="single-row")
        """
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

    def view_for_click_plain(x: pd.DataFrame) -> pd.DataFrame:
        """
        UI table SANS HTML (sinon Streamlit affiche les <span ...>)
        """
        if x is None or x.empty:
            return pd.DataFrame(columns=["Joueur", "Pos", "Equipe", "Salaire"])

        y = x.copy()
        if "Joueur" not in y.columns:
            y["Joueur"] = ""
        if "Equipe" not in y.columns:
            y["Equipe"] = ""
        if "Pos" not in y.columns:
            y["Pos"] = "F"
        if "Salaire" not in y.columns:
            y["Salaire"] = 0

        y["Pos"] = y["Pos"].apply(normalize_pos)

        # tri positions
        y["_pos_order"] = y["Pos"].apply(pos_sort_key)
        y = y.sort_values(["_pos_order", "Joueur"]).drop(columns=["_pos_order"])

        # salaire formaté (texte simple)
        y["Salaire"] = y["Salaire"].apply(money)

        return y[["Joueur", "Pos", "Equipe", "Salaire"]].reset_index(drop=True)

    # ----------------------------
    # Groupes (IR séparé)
    # ----------------------------
    injured_all = dprop[dprop.get("Slot", "") == "Blessé"].copy()
    dprop_ok = dprop[dprop.get("Slot", "") != "Blessé"].copy()

    gc_all = dprop_ok[dprop_ok["Statut"] == "Grand Club"].copy()
    ce_all = dprop_ok[dprop_ok["Statut"] == "Club École"].copy()

    gc_actif = gc_all[gc_all.get("Slot", "") == "Actif"].copy()
    gc_banc  = gc_all[gc_all.get("Slot", "") == "Banc"].copy()

    # ----------------------------
    # Compte positions (Actifs)
    # ----------------------------
    tmp = gc_actif.copy()
    tmp["Pos"] = tmp["Pos"].apply(normalize_pos)
    nb_F = int((tmp["Pos"] == "F").sum())
    nb_D = int((tmp["Pos"] == "D").sum())
    nb_G = int((tmp["Pos"] == "G").sum())

    # ----------------------------
    # Plafonds (IR exclu ici)
    # ----------------------------
    cap_gc = int(st.session_state["PLAFOND_GC"])
    cap_ce = int(st.session_state["PLAFOND_CE"])
    used_gc = int(gc_all["Salaire"].sum())
    used_ce = int(ce_all["Salaire"].sum())
    remain_gc = int(cap_gc - used_gc)
    remain_ce = int(cap_ce - used_ce)

    # ----------------------------
    # Jauges (corrigées)
    # ----------------------------
    b1, b2 = st.columns(2)
    with b1:
        st.markdown(cap_bar_used(used_gc, cap_gc, "📉 Plafond Grand Club (GC)"), unsafe_allow_html=True)
    with b2:
        st.markdown(cap_bar_used(used_ce, cap_ce, "📉 Plafond Club École (CE)"), unsafe_allow_html=True)

    # ----------------------------
    # Metrics + compteur actifs
    # ----------------------------
    top = st.columns([1, 1, 1, 1, 1])
    top[0].metric("Total Grand Club", money(used_gc))
    top[1].metric("Montant Disponible GC", money(remain_gc))
    top[2].metric("Total Club École", money(used_ce))
    top[3].metric("Montant Disponible CE", money(remain_ce))
    top[4].metric("Blessés", f"{len(injured_all)}")

    st.markdown(
        f"**Actifs** — F {_count_badge(nb_F,12)} • D {_count_badge(nb_D,6)} • G {_count_badge(nb_G,2)}",
        unsafe_allow_html=True
    )

    st.divider()

    # ----------------------------
    # Tables (SANS HTML)
    # ----------------------------
    df_actifs_ui = view_for_click_plain(gc_actif)
    df_banc_ui   = view_for_click_plain(gc_banc)
    df_min_ui    = view_for_click_plain(ce_all)

    t1, t2, t3 = st.columns(3)
    with t1:
        st.markdown("### 🟢 Actifs")
        st.dataframe(
            df_actifs_ui,
            use_container_width=True,
            hide_index=True,
            selection_mode="single-row",
            on_select="rerun",
            key="sel_actifs",
        )
    with t2:
        st.markdown("### 🟡 Banc")
        st.dataframe(
            df_banc_ui,
            use_container_width=True,
            hide_index=True,
            selection_mode="single-row",
            on_select="rerun",
            key="sel_banc",
        )
    with t3:
        st.markdown("### 🔵 Mineur")
        st.dataframe(
            df_min_ui,
            use_container_width=True,
            hide_index=True,
            selection_mode="single-row",
            on_select="rerun",
            key="sel_min",
        )

    # ----------------------------
    # IR cliquable (SANS HTML)
    # ----------------------------
    st.divider()
    st.markdown("## 🩹 Joueurs Blessés (IR)")

    df_ir_ui = None
    if injured_all.empty:
        st.info("Aucun joueur blessé.")
    else:
        # affiche IR Date si présent, en TEXTE simple
        ir_show = injured_all.copy()
        if "IR Date" in ir_show.columns:
            ir_show["IR Date"] = ir_show["IR Date"].astype(str).str.strip().replace("", "—")

        df_ir_ui = view_for_click_plain(ir_show)
        # (optionnel) on rajoute IR Date dans la table IR seulement
        if "IR Date" in ir_show.columns:
            df_ir_ui = df_ir_ui.merge(
                ir_show[["Joueur", "IR Date"]].drop_duplicates(),
                on="Joueur",
                how="left",
            )
            df_ir_ui["IR Date"] = df_ir_ui["IR Date"].fillna("—")
            df_ir_ui = df_ir_ui[["Joueur", "Pos", "Equipe", "IR Date", "Salaire"]]

        st.dataframe(
            df_ir_ui,
            use_container_width=True,
            hide_index=True,
            selection_mode="single-row",
            on_select="rerun",
            key="sel_ir",
        )

    # ============================
# SÉLECTION UNIQUE (Actifs/Banc/Mineur/IR) -> ouvre dialog
# ✅ Ne traite PAS les clics si un pop-up est déjà ouvert
# ============================

popup_open = st.session_state.get("move_ctx") is not None

if not popup_open:
    picked = None
    picked_key = None

    # 1) Cherche une sélection dans l'ordre (Actifs -> Banc -> Mineur -> IR)
    for k, df_ui in [
        ("sel_actifs", df_actifs_ui),
        ("sel_banc",   df_banc_ui),
        ("sel_min",    df_min_ui),
        ("sel_ir",     df_ir_ui),
    ]:
        if df_ui is None or df_ui.empty:
            continue

        p = pick_from_df(df_ui, k)
        if p:
            picked = str(p).strip()
            picked_key = k
            break

    # 2) Si on a un joueur sélectionné, on ouvre le pop-up
    if picked and picked_key:
        cur_pick = (str(proprietaire).strip(), picked)

        # ctx courant (compatible: owner/proprietaire + joueur/Joueur/player)
        ctx = st.session_state.get("move_ctx") or {}
        ctx_owner = str(ctx.get("owner") or ctx.get("proprietaire") or "").strip()
        ctx_joueur = str(ctx.get("joueur") or ctx.get("Joueur") or ctx.get("player") or "").strip()

        # Si pas déjà ouvert sur ce joueur
        if (ctx_owner, ctx_joueur) != cur_pick:
            set_move_ctx(cur_pick[0], cur_pick[1])

            # ✅ garde seulement la sélection courante
            # (si picked_key == sel_ir, ton helper clear_other_selections ne gère pas sel_ir,
            # donc on clear IR manuellement au besoin)
            if picked_key in ("sel_actifs", "sel_banc", "sel_min"):
                clear_other_selections(picked_key)
                # clear IR si présent
                if "sel_ir" in st.session_state and isinstance(st.session_state["sel_ir"], dict):
                    sel = st.session_state["sel_ir"].get("selection")
                    if isinstance(sel, dict) and "rows" in sel:
                        sel["rows"].clear()
            else:
                # picked_key == sel_ir
                clear_other_selections("sel_actifs")  # vide les 3 principaux
                # on laisse sel_ir sélectionné: c'est lui qui a déclenché le popup

            do_rerun()


    # ----------------------------
    # Pop-up (toujours à la fin)
    # IMPORTANT:
    #  - open_move_dialog() doit inclure IR -> Actifs/Banc/Mineur
    #  - et le bouton Annuler doit faire clear_move_ctx(); do_rerun()
    # ----------------------------
    open_move_dialog()





# =====================================================
# POP-UP DÉPLACEMENT (FINAL)
#   - Si joueur est sur IR (Slot=Blessé) OU vient de sel_ir -> UI ultra compacte (3 boutons 1-clic)
#   - Sinon -> radio + Confirmer/Annuler
#   - Annuler fonctionne toujours
# =====================================================

def open_move_dialog():
    ctx = st.session_state.get("move_ctx")
    if not ctx:
        return

    if st.session_state.get("LOCKED"):
        st.warning("🔒 Saison verrouillée : aucun changement permis.")
        clear_move_ctx()
        return

    owner = str(ctx.get("owner") or ctx.get("proprietaire") or "").strip()
    joueur = str(ctx.get("joueur") or ctx.get("Joueur") or ctx.get("player") or "").strip()
    nonce = int(ctx.get("nonce", 0))

    df_all = st.session_state.get("data")
    if df_all is None or df_all.empty:
        st.error("Aucune donnée.")
        clear_move_ctx()
        return

    mask = (
        df_all["Propriétaire"].astype(str).str.strip().eq(owner)
        & df_all["Joueur"].astype(str).str.strip().eq(joueur)
    )
    if df_all[mask].empty:
        st.error("Joueur introuvable.")
        clear_move_ctx()
        return

    row = df_all[mask].iloc[0]
    cur_statut = str(row.get("Statut", "")).strip()
    cur_slot = str(row.get("Slot", "")).strip()
    cur_pos = normalize_pos(row.get("Pos", "F"))
    cur_equipe = str(row.get("Equipe", "")).strip()
    cur_salaire = int(row.get("Salaire", 0))

    # ✅ IR mode si le joueur est sur IR, ou si le clic vient du tableau IR
    source = str(st.session_state.get("move_source", "")).strip()
    from_ir = (cur_slot == "Blessé") or (source == "sel_ir")

    # Infos DB (si dispo)
    info = get_player_row(players_db, joueur) or {}

    def _pick(d: dict, candidates: list[str], default=""):
        for k in candidates:
            if k in d and pd.notna(d[k]) and str(d[k]).strip() != "":
                return str(d[k]).strip()
        return default

    pays = _pick(info, ["Country", "Pays"], "")
    flag_raw = _pick(info, ["Flag", "Flag URL", "Flag_Image", "FlagURL"], "")
    flag_src = resolve_image_path_or_url(flag_raw)

    position_db = _pick(info, ["Position", "Pos"], "") or cur_pos
    caphit = _pick(info, ["Cap Hit", "CapHit", "AAV"], "")
    level = _pick(info, ["Level"], "")

    # CSS compact
    css = """
    <style>
      .dlg-main{font-weight:900;font-size:16px;line-height:1.1}
      .dlg-sub{opacity:.75;font-weight:700;margin-top:2px;font-size:12px;line-height:1.2}
      .chipwrap{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0 0}
      .chip{display:inline-flex;gap:6px;align-items:center;
            border:1px solid rgba(255,255,255,.12);
            background:rgba(255,255,255,.04);
            border-radius:999px;padding:3px 9px;font-size:11px;font-weight:800}
      .chip b{opacity:.75}
    </style>
    """

    def chip(label, val) -> str:
        v = str(val or "").strip()
        if not v:
            return ""
        return f"<span class='chip'><b>{label}</b> {html.escape(v)}</span>"

    chips_html = "".join([
        chip("Pays", pays),
        chip("Pos", position_db),
        chip("Cap", caphit),
        chip("Level", level),
    ]).strip()

    def _close():
        st.session_state["move_source"] = ""
        clear_move_ctx()

    @st.dialog(f"Déplacement — {joueur}", width="small")
    def _dlg():
        st.markdown(css, unsafe_allow_html=True)

        left, right = st.columns([4, 1])
        with left:
            st.markdown(
                f"<div class='dlg-main'>{html.escape(owner)} • {html.escape(joueur)}</div>"
                f"<div class='dlg-sub'>{html.escape(cur_statut)}{(' / ' + html.escape(cur_slot)) if cur_slot else ''}"
                f" • {html.escape(cur_pos)} • {html.escape(cur_equipe)} • {money(cur_salaire)}</div>",
                unsafe_allow_html=True,
            )
        with right:
            if flag_src:
                st.image(flag_src, width=42)
            elif pays:
                st.caption(pays)

        if chips_html:
            st.markdown(f"<div class='chipwrap'>{chips_html}</div>", unsafe_allow_html=True)

        st.divider()

        # =================================================
# ✅ MODE IR ULTRA COMPACT (1 clic)
# =================================================
if from_ir:
    st.caption("Sortie de IR (1 clic)")
    bA, bB, bC = st.columns(3)

    def _after_ok_toast(msg, icon):
        st.toast(msg, icon=icon)
        # ✅ clear sélections (sans réassigner)
        clear_selection_key("sel_ir")
        clear_selection_key("sel_actifs")
        clear_selection_key("sel_banc")
        clear_selection_key("sel_min")
        _close()
        do_rerun()

    if bA.button("🟢 Actifs", use_container_width=True, key=f"ir_to_actif_{owner}_{joueur}_{nonce}"):
        ok = apply_move_with_history(
            proprietaire=owner,
            joueur=joueur,
            to_statut="Grand Club",
            to_slot="Actif",
            action_label="IR → Actif",
        )
        if ok:
            _after_ok_toast(f"🟢 {joueur} → Actifs", "🟢")
        else:
            st.error(st.session_state.get("last_move_error") or "Déplacement refusé.")

    if bB.button("🟡 Banc", use_container_width=True, key=f"ir_to_banc_{owner}_{joueur}_{nonce}"):
        ok = apply_move_with_history(
            proprietaire=owner,
            joueur=joueur,
            to_statut="Grand Club",
            to_slot="Banc",
            action_label="IR → Banc",
        )
        if ok:
            _after_ok_toast(f"🟡 {joueur} → Banc", "🟡")
        else:
            st.error(st.session_state.get("last_move_error") or "Déplacement refusé.")

    if bC.button("🔵 Mineur", use_container_width=True, key=f"ir_to_min_{owner}_{joueur}_{nonce}"):
        ok = apply_move_with_history(
            proprietaire=owner,
            joueur=joueur,
            to_statut="Club École",
            to_slot="",
            action_label="IR → Mineur",
        )
        if ok:
            _after_ok_toast(f"🔵 {joueur} → Mineur", "🔵")
        else:
            st.error(st.session_state.get("last_move_error") or "Déplacement refusé.")

    st.divider()
    if st.button("✖️ Annuler", use_container_width=True, key=f"cancel_ir_{owner}_{joueur}_{nonce}"):
        # ✅ Annuler qui marche toujours
        clear_selection_key("sel_ir")
        _close()
        do_rerun()

    return



        # =================================================
        # MODE NORMAL (radio + confirmer)
        # =================================================
        destinations = [
            ("🟢 Actifs (GC)", ("Grand Club", "Actif")),
            ("🟡 Banc (GC)", ("Grand Club", "Banc")),
            ("🔵 Mineur (CE)", ("Club École", "")),
            ("🩹 Blessé (IR)", (cur_statut, "Blessé")),  # garde le statut, change seulement slot
        ]

        current = (cur_statut, cur_slot if cur_slot else "")
        destinations = [d for d in destinations if d[1] != current]

        labels = [d[0] for d in destinations]
        mapping = {d[0]: d[1] for d in destinations}

        choice = st.radio(
            "Destination",
            labels,
            index=0,
            key=f"dest_{owner}_{joueur}_{nonce}",
            label_visibility="collapsed",
        )
        to_statut, to_slot = mapping[choice]

        c1, c2 = st.columns(2)
        if c1.button("✅ Confirmer", use_container_width=True, type="primary", key=f"ok_{owner}_{joueur}_{nonce}"):
            ok = apply_move_with_history(
                proprietaire=owner,
                joueur=joueur,
                to_statut=to_statut,
                to_slot=to_slot,
                action_label=f"{cur_statut}/{cur_slot or '-'} → {to_statut}/{to_slot or '-'}",
            )
            if ok:
                if to_slot == "Blessé":
                    st.toast(f"🩹 {joueur} placé sur IR", icon="🩹")
                elif to_statut == "Grand Club" and to_slot == "Actif":
                    st.toast(f"🟢 {joueur} → Actifs", icon="🟢")
                elif to_statut == "Grand Club" and to_slot == "Banc":
                    st.toast(f"🟡 {joueur} → Banc", icon="🟡")
                elif to_statut == "Club École":
                    st.toast(f"🔵 {joueur} → Mineur", icon="🔵")
                else:
                    st.toast("✅ Déplacement enregistré", icon="✅")

                _close()
                do_rerun()

        if c2.button("✖️ Annuler", use_container_width=True, key=f"cancel_{owner}_{joueur}_{nonce}"):
            _close()
            do_rerun()

    _dlg()










# =====================================================
# TAB J — Joueurs (Autonomes)
# =====================================================
with tabJ:
    st.subheader("👤 Joueurs (Autonomes)")
    st.caption("Aucun résultat tant qu’aucun filtre n’est rempli (Nom/Prénom, Équipe, Level/Contrat ou Cap Hit).")

    # ✅ sécurité
    if players_db is None or players_db.empty:
        st.error("Impossible de charger la base joueurs.")
        st.caption(f"Chemin attendu : {PLAYERS_DB_FILE}")
        st.stop()

    df_db = players_db.copy()

   
    if "Player" not in df_db.columns:
        # fallback
        possible = None
        for cand in ["Joueur", "Name", "Full Name", "fullname", "player"]:
            if cand in df_db.columns:
                possible = cand
                break
        if possible:
            df_db = df_db.rename(columns={possible: "Player"})
        else:
            st.error(f"Colonne 'Player' introuvable. Colonnes: {list(df_db.columns)}")
            st.stop()

    def _clean_intlike(x):
        s = str(x).strip()
        if s == "" or s.lower() in {"nan", "none"}:
            return ""
        if re.match(r"^\d+\.0$", s):
            return s.split(".")[0]
        return s

    def _cap_to_int(v) -> int:
        s = str(v if v is not None else "").strip()
        if s == "" or s.lower() in {"nan", "none"}:
            return 0
        s = s.replace("$", "").replace("€", "").replace("£", "")
        s = s.replace(",", "").replace(" ", "")
        s = re.sub(r"\.0+$", "", s)
        s2 = re.sub(r"[^\d]", "", s)
        return int(s2) if s2.isdigit() else 0

    def _money_space(v: int) -> str:
        try:
            return f"{int(v):,}".replace(",", " ") + " $"
        except Exception:
            return "0 $"

    def clear_j_name():
        st.session_state["j_name"] = ""

    c1, c2, c3 = st.columns([2, 1, 1])

    with c1:
        name_col1, name_col2 = st.columns([12, 1])
        with name_col1:
            q_name = st.text_input("Nom / Prénom", placeholder="Ex: Jack Eichel", key="j_name")
        with name_col2:
            st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            st.button("❌", key="j_name_clear", help="Effacer Nom / Prénom", use_container_width=True, on_click=clear_j_name)

    with c2:
        if "Team" in df_db.columns:
            teams = sorted(df_db["Team"].dropna().astype(str).unique())
            q_team = st.selectbox("Équipe", ["Toutes"] + teams, key="j_team")
        else:
            q_team = "Toutes"
            st.selectbox("Équipe", ["Toutes"], disabled=True, key="j_team_disabled")

    with c3:
        level_col = "Level" if "Level" in df_db.columns else None
        if level_col:
            levels = sorted(df_db[level_col].dropna().astype(str).unique())
            q_level = st.selectbox("Level (Contrat)", ["Tous"] + levels, key="j_level")
        else:
            q_level = "Tous"
            st.selectbox("Level (Contrat)", ["Tous"], disabled=True, key="j_level_disabled")

    st.divider()
    st.markdown("### 💰 Recherche par Salaire (Cap Hit)")

    cap_col = None
    for cand in ["Cap Hit", "CapHit", "AAV"]:
        if cand in df_db.columns:
            cap_col = cand
            break

    if not cap_col:
        st.warning("Aucune colonne Cap Hit/CapHit/AAV trouvée → filtre salaire désactivé.")
        cap_enabled = False
        cap_apply = False
        cap_min = 0
        cap_max = 0
    else:
        cap_enabled = True
        df_db["_cap_int"] = df_db[cap_col].apply(_cap_to_int)
        cap_apply = st.checkbox("Activer le filtre Cap Hit", value=False, key="cap_apply")
        cap_min, cap_max = st.slider(
            "Plage Cap Hit",
            min_value=0,
            max_value=30_000_000,
            value=(0, 30_000_000),
            step=250_000,
            format="%d",
            disabled=(not cap_apply),
            key="cap_slider",
        )
        st.caption(f"Plage sélectionnée : **{_money_space(cap_min)} → {_money_space(cap_max)}**")

    has_any_filter = bool(q_name.strip()) or (q_team != "Toutes") or (q_level != "Tous") or bool(cap_apply)

    if not has_any_filter:
        st.info("Entre au moins un filtre pour afficher les résultats.")
    else:
        dff = df_db.copy()
        if q_name.strip():
            dff = dff[dff["Player"].astype(str).str.contains(q_name, case=False, na=False)]
        if q_team != "Toutes" and "Team" in dff.columns:
            dff = dff[dff["Team"].astype(str) == str(q_team)]
        if q_level != "Tous" and level_col and level_col in dff.columns:
            dff = dff[dff[level_col].astype(str) == str(q_level)]
        if cap_enabled and cap_apply:
            if "_cap_int" not in dff.columns:
                dff["_cap_int"] = dff[cap_col].apply(_cap_to_int)
            dff = dff[(dff["_cap_int"] >= int(cap_min)) & (dff["_cap_int"] <= int(cap_max))]

        if dff.empty:
            st.warning("Aucun joueur trouvé avec ces critères.")
        else:
            dff = dff.head(250).reset_index(drop=True)
            st.markdown("### Résultats")

            nhl_gp_col = "NHL GP" if "NHL GP" in dff.columns else None

            show_cols = []
            for c in ["Player", "Team", "Position", cap_col, "Level"]:
                if c and c in dff.columns and c not in show_cols:
                    show_cols.append(c)

            df_show = dff[show_cols].copy()

            if nhl_gp_col:
                insert_at = 3 if ("Position" in df_show.columns) else 1
                df_show.insert(insert_at, "GP", dff[nhl_gp_col])

            if cap_col and cap_col in df_show.columns:
                df_show[cap_col] = dff[cap_col].apply(lambda x: _money_space(_cap_to_int(x)))
                df_show = df_show.rename(columns={cap_col: "Cap Hit"})

            for c in df_show.columns:
                df_show[c] = df_show[c].apply(_clean_intlike)

        st.dataframe(
            df_actifs_ui,
            use_container_width=True,
            hide_index=True,
            selection_mode="single-row",
            on_select="rerun",
            key="sel_actifs",
            unsafe_allow_html=True,
        )




    # Comparaison 2 joueurs
    st.divider()
    st.markdown("### 📊 Comparer 2 joueurs")

    players_list = sorted(df_db["Player"].dropna().astype(str).unique().tolist())

    def _filter_names(q: str, names: list[str], limit: int = 40) -> list[str]:
        q = str(q or "").strip().lower()
        if not q:
            return names[:limit]
        out = [n for n in names if q in n.lower()]
        return out[:limit]

    def clear_cmp_a():
        st.session_state["compare_p1"] = None
        st.session_state["cmp_q1"] = ""
        st.session_state["cmp_sel_1"] = "—"

    def clear_cmp_b():
        st.session_state["compare_p2"] = None
        st.session_state["cmp_q2"] = ""
        st.session_state["cmp_sel_2"] = "—"

    def add_cmp_a():
        sel = st.session_state.get("cmp_sel_1", "—")
        st.session_state["compare_p1"] = None if sel == "—" else sel

    def add_cmp_b():
        sel = st.session_state.get("cmp_sel_2", "—")
        st.session_state["compare_p2"] = None if sel == "—" else sel

    for k, v in {
        "cmp_q1": "",
        "cmp_q2": "",
        "compare_p1": None,
        "compare_p2": None,
        "cmp_sel_1": "—",
        "cmp_sel_2": "—",
    }.items():
        if k not in st.session_state:
            st.session_state[k] = v

    cA, cB = st.columns(2)
    with cA:
        st.markdown("**Joueur A**")
        q1 = st.text_input("Rechercher A", placeholder="Tape un nom…", key="cmp_q1")
        opt1 = ["—"] + _filter_names(q1, players_list, limit=40)
        st.selectbox("Sélection A", opt1, key="cmp_sel_1")
        b1, b2 = st.columns(2)
        b1.button("➕ Ajouter A", use_container_width=True, key="cmp_add_a", on_click=add_cmp_a)
        b2.button("🧹 Effacer A", use_container_width=True, key="cmp_clear_a", on_click=clear_cmp_a)

    with cB:
        st.markdown("**Joueur B**")
        q2 = st.text_input("Rechercher B", placeholder="Tape un nom…", key="cmp_q2")
        opt2 = ["—"] + _filter_names(q2, players_list, limit=40)
        st.selectbox("Sélection B", opt2, key="cmp_sel_2")
        b3, b4 = st.columns(2)
        b3.button("➕ Ajouter B", use_container_width=True, key="cmp_add_b", on_click=add_cmp_b)
        b4.button("🧹 Effacer B", use_container_width=True, key="cmp_clear_b", on_click=clear_cmp_b)

    p1 = st.session_state.get("compare_p1")
    p2 = st.session_state.get("compare_p2")

    if not p1 or not p2:
        st.info("Choisis 2 joueurs (A et B) pour afficher la comparaison.")
    elif p1 == p2:
        st.warning("Choisis 2 joueurs différents.")
    else:
        r1 = df_db[df_db["Player"].astype(str) == str(p1)].head(1)
        r2 = df_db[df_db["Player"].astype(str) == str(p2)].head(1)
        if r1.empty or r2.empty:
            st.error("Impossible de trouver un des joueurs dans la base.")
        else:
            df_cmp = pd.concat([r1, r2], ignore_index=True)
            nhl_gp_col = "NHL GP" if "NHL GP" in df_cmp.columns else None

            cmp_show_cols = []
            for c in ["Player", "Team", "Position", cap_col, "Level"]:
                if c and c in df_cmp.columns and c not in cmp_show_cols:
                    cmp_show_cols.append(c)

            df_cmp_show = df_cmp[cmp_show_cols].copy()
            if nhl_gp_col:
                insert_at = 3 if ("Position" in df_cmp_show.columns) else 1
                df_cmp_show.insert(insert_at, "GP", df_cmp[nhl_gp_col])

            if cap_col and cap_col in df_cmp_show.columns:
                df_cmp_show[cap_col] = df_cmp[cap_col].apply(lambda x: _money_space(_cap_to_int(x)))
                df_cmp_show = df_cmp_show.rename(columns={cap_col: "Cap Hit"})

            for c in df_cmp_show.columns:
                df_cmp_show[c] = df_cmp_show[c].apply(_clean_intlike)

            st.dataframe(
    df_cmp_show,
    use_container_width=True,
    hide_index=True,
)





# =====================================================
# TAB H — Historique
# =====================================================
with tabH:
    st.subheader("🕘 Historique des changements d’alignement")

    h = st.session_state["history"].copy()
    if h.empty:
        st.info("Aucune entrée d’historique pour cette saison.")
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

            st.caption("↩️ = annuler ce changement. ❌ = supprimer l’entrée (sans modifier l’alignement).")

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
                        st.error("🔒 Saison verrouillée : annulation impossible.")
                    else:
                        owner = str(r["proprietaire"])
                        joueur = str(r["joueur"])
                        mask = (st.session_state["data"]["Propriétaire"] == owner) & (st.session_state["data"]["Joueur"] == joueur)

                        if st.session_state["data"][mask].empty:
                            st.error("Impossible d'annuler : joueur introuvable.")
                        else:
                            before = st.session_state["data"][mask].iloc[0]
                            cur_statut = str(before.get("Statut", ""))
                            cur_slot = str(before.get("Slot", "")).strip()
                            pos0 = str(before.get("Pos", "F"))
                            equipe0 = str(before.get("Equipe", ""))

                            st.session_state["data"].loc[mask, "Statut"] = str(r["from_statut"])
                            st.session_state["data"].loc[mask, "Slot"] = str(r["from_slot"]) if str(r["from_slot"]).strip() else ""
                            # si on undo un move IR -> hors IR, on clear IR Date
                            if cur_slot == "Blessé" and str(r["from_slot"]).strip() != "Blessé":
                                st.session_state["data"].loc[mask, "IR Date"] = ""

                            st.session_state["data"] = clean_data(st.session_state["data"])
                            st.session_state["data"].to_csv(DATA_FILE, index=False)

                            log_history_row(
                                owner, joueur, pos0, equipe0,
                                cur_statut, cur_slot,
                                str(r["from_statut"]),
                                (str(r["from_slot"]) if str(r["from_slot"]).strip() else ""),
                                action=f"UNDO #{rid}"
                            )

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
# TAB 2 — Transactions
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
# TAB 3 — Recommandations
# =====================================================
with tab3:
    for _, r in plafonds.iterrows():
        if r["Montant Disponible GC"] < 2_000_000:
            st.warning(f"{r['Propriétaire']} : rétrogradation recommandée")
        if r["Montant Disponible CE"] > 10_000_000:
            st.info(f"{r['Propriétaire']} : rappel possible")
