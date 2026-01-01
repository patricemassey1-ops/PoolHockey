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
    Table UI pour Actif/Banc/Mineur.
    IMPORTANT: ne modifie pas le champ 'Joueur' (pas d'emoji),
    sinon la sélection devient incohérente.
    """
    if x is None or x.empty:
        return pd.DataFrame(columns=["Joueur", "Pos", "Equipe", "Salaire"])

    y = x.copy()

    # Pos
    if "Pos" not in y.columns:
        y["Pos"] = "F"
    y["Pos"] = y["Pos"].apply(normalize_pos)

    # Tri
    if "Joueur" not in y.columns:
        y["Joueur"] = ""
    y["_pos_order"] = y["Pos"].apply(pos_sort_key)
    y = y.sort_values(["_pos_order", "Joueur"]).drop(columns=["_pos_order"])

    # Equipe
    if "Equipe" not in y.columns:
        y["Equipe"] = ""

    # Salaire formaté
    if "Salaire" not in y.columns:
        y["Salaire"] = 0
    y["Salaire"] = y["Salaire"].apply(money)

    return y[["Joueur", "Pos", "Equipe", "Salaire"]].reset_index(drop=True)

def clear_other_selections(keep_key: str):
    for k in ["sel_actifs", "sel_banc", "sel_min"]:
        if k != keep_key:
            ss = st.session_state.get(k)
            if isinstance(ss, dict):
                ss["selection"] = {"rows": []}
                st.session_state[k] = ss


def pick_from_df(df_ui: pd.DataFrame, key: str):
    ss = st.session_state.get(key)
    if not isinstance(ss, dict):
        return None
    sel = ss.get("selection", {})
    rows = sel.get("rows", [])
    if not rows:
        return None
    idx = rows[0]
    if df_ui is None or df_ui.empty:
        return None
    if idx < 0 or idx >= len(df_ui):
        return None
    return str(df_ui.iloc[idx]["Joueur"]).strip()

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
    st.session_state["move_ctx"] = {"owner": owner, "joueur": joueur, "nonce": st.session_state["move_nonce"]}

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
    if st.session_state.get("LOCKED"):
        st.error("🔒 Saison verrouillée : modification impossible.")
        return False

    df0 = st.session_state.get("data")
    if df0 is None or df0.empty:
        st.error("Aucune donnée en mémoire.")
        return False

    if "IR Date" not in df0.columns:
        df0["IR Date"] = ""

    to_statut = str(to_statut).strip()
    to_slot = str(to_slot).strip()

    allowed_slots_gc = {"Actif", "Banc", "Blessé"}
    allowed_slots_ce = {"", "Blessé"}

    if to_statut == "Grand Club" and to_slot not in allowed_slots_gc:
        st.error(f"Slot invalide pour Grand Club: {to_slot}")
        return False
    if to_statut == "Club École" and to_slot not in allowed_slots_ce:
        st.error(f"Slot invalide pour Club École: {to_slot}")
        return False

    mask = (df0["Propriétaire"] == proprietaire) & (df0["Joueur"] == joueur)
    if df0[mask].empty:
        st.error("Joueur introuvable pour ce propriétaire.")
        return False

    before = df0[mask].iloc[0]
    from_statut = str(before.get("Statut", "")).strip()
    from_slot = str(before.get("Slot", "")).strip()
    pos0 = str(before.get("Pos", "F")).strip()
    equipe0 = str(before.get("Equipe", "")).strip()

    df0.loc[mask, "Statut"] = to_statut
    df0.loc[mask, "Slot"] = to_slot if to_slot else ""

    # IR Date (Toronto)
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
        df0.to_csv(st.session_state["DATA_FILE"], index=False)
    except Exception as e:
        st.error(f"Erreur sauvegarde CSV: {e}")
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
# POP-UP DÉPLACEMENT (infos joueur)
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

    if st.session_state.get("LOCKED"):
        st.warning("🔒 Saison verrouillée : aucun changement permis.")
        clear_move_ctx()
        return

    owner = ctx["owner"]
    joueur = ctx["joueur"]
    nonce = ctx.get("nonce", 0)

    df_all = st.session_state["data"]
    mask = (df_all["Propriétaire"] == owner) & (df_all["Joueur"] == joueur)
    if df_all[mask].empty:
        st.error("Joueur introuvable.")
        clear_move_ctx()
        return

    row = df_all[mask].iloc[0]
    cur_statut = str(row["Statut"])
    cur_slot = str(row.get("Slot", "")).strip()
    cur_pos = normalize_pos(row.get("Pos", "F"))
    cur_equipe = str(row.get("Equipe", ""))
    cur_salaire = int(row.get("Salaire", 0))

    # Infos DB
    info = get_player_row(players_db, joueur) or {}
    pays = _pick(info, ["Country", "Pays"], "")
    flag_raw = _pick(info, ["Flag", "Flag URL", "Flag_Image", "FlagURL"], "")
    flag_src = resolve_image_path_or_url(flag_raw)
    position_db = _pick(info, ["Position", "Pos"], "")
    taille = _pick(info, ["Height", "Hgt", "Taille"], "")
    poids = _pick(info, ["Weight", "W(lbs)", "Poids"], "")
    caphit = _pick(info, ["Cap Hit", "CapHit", "AAV"], "")
    level = _pick(info, ["Level"], "")

    # Chips compactes
    chips = []
    def chip(label, val):
        val = str(val or "").strip()
        if val:
            chips.append(f"<span class='chip'><b>{label}</b> {val}</span>")

    chip("Pays", pays)
    chip("Pos", position_db or cur_pos)
    chip("Taille", taille)
    chip("Poids", poids)
    chip("Cap", caphit)
    chip("Level", level)

    css = """
    <style>
      .dlg-main{font-weight:900;font-size:16px}
      .dlg-sub{opacity:.75;font-weight:700;margin-top:-2px}
      .chipwrap{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0 2px}
      .chip{display:inline-flex;gap:6px;align-items:center;
            border:1px solid rgba(255,255,255,.12);
            background:rgba(255,255,255,.04);
            border-radius:999px;padding:4px 10px;font-size:12px;font-weight:800}
      .chip b{opacity:.75}
    </style>
    """

    @st.dialog(f"Déplacement — {joueur}", width="small")
    def _dlg():
        st.markdown(css, unsafe_allow_html=True)

        left, right = st.columns([4, 1])
        with left:
            st.markdown(
                f"<div class='dlg-main'>{owner} • {joueur}</div>"
                f"<div class='dlg-sub'>{cur_statut}{(' / ' + cur_slot) if cur_slot else ''} • {cur_pos} • {cur_equipe} • {money(cur_salaire)}</div>",
                unsafe_allow_html=True
            )
        with right:
            if flag_src:
                st.image(flag_src, width=44)
            elif pays:
                st.caption(pays)

        if chips:
            st.markdown("<div class='chipwrap'>" + "".join(chips) + "</div>", unsafe_allow_html=True)
        else:
            st.caption("ℹ️ Infos joueur non trouvées dans data/Hockey.Players.csv (match nom).")

        st.divider()

        destinations = [
            ("🟡 Banc (Grand Club)", ("Grand Club", "Banc")),
            ("🔵 Mineur (Club École)", ("Club École", "")),
            ("🩹 Blessé (IR)", (cur_statut, "Blessé")),
        ]

        current = (cur_statut, cur_slot if cur_slot else "")
        destinations = [d for d in destinations if d[1] != current]
        if cur_slot == "Blessé":
            destinations = [d for d in destinations if d[1][1] != "Blessé"]

        choice = st.radio(
            "Destination",
            [d[0] for d in destinations],
            index=0,
            key=f"dest_{owner}_{joueur}_{nonce}",
            label_visibility="collapsed",
        )
        to_statut, to_slot = dict(destinations)[choice]

        c1, c2 = st.columns(2)
        if c1.button("✅ Confirmer", key=f"confirm_{owner}_{joueur}_{nonce}", use_container_width=True, type="primary"):
            ok2 = apply_move_with_history(
                proprietaire=owner,
                joueur=joueur,
                to_statut=to_statut,
                to_slot=to_slot,
                action_label=f"{cur_statut}/{cur_slot or '-'} → {to_statut}/{to_slot or '-'}",
            )
            if ok2:
                clear_move_ctx()
                if to_slot == "Blessé":
                    st.toast(f"🩹 {joueur} placé sur IR (date enregistrée)", icon="🩹")
                elif to_statut == "Grand Club" and to_slot == "Banc":
                    st.toast(f"🟡 {joueur} → Banc", icon="🟡")
                elif to_statut == "Club École":
                    st.toast(f"🔵 {joueur} → Mineur", icon="🔵")
                else:
                    st.toast("✅ Déplacement enregistré", icon="✅")
                do_rerun()

        if c2.button("✖️ Annuler", key=f"cancel_{owner}_{joueur}_{nonce}", use_container_width=True):
            clear_move_ctx()
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
# TAB A — Alignement (FINAL) : 3 tableaux + sélection unique + anti-boucle + pop-up
# =====================================================
with tabA:
    st.subheader("🧾 Alignement")

    proprietaire = st.selectbox(
        "Propriétaire",
        sorted(st.session_state["data"]["Propriétaire"].unique()),
        key="align_owner",
    )

    st.session_state["data"] = clean_data(st.session_state["data"])
    data_all = st.session_state["data"]
    dprop = data_all[data_all["Propriétaire"] == proprietaire].copy()

    # Sépare IR vs non-IR
    injured_all = dprop[dprop.get("Slot", "") == "Blessé"].copy()
    dprop_not_inj = dprop[dprop.get("Slot", "") != "Blessé"].copy()

    # Groupes
    gc_all = dprop_not_inj[dprop_not_inj["Statut"] == "Grand Club"].copy()
    ce_all = dprop_not_inj[dprop_not_inj["Statut"] == "Club École"].copy()

    gc_actif = gc_all[gc_all.get("Slot", "") == "Actif"].copy()
    gc_banc  = gc_all[gc_all.get("Slot", "") == "Banc"].copy()

    # Counts (Actifs)
    tmp = gc_actif.copy()
    tmp["Pos"] = tmp["Pos"].apply(normalize_pos)
    nb_F = int((tmp["Pos"] == "F").sum())
    nb_D = int((tmp["Pos"] == "D").sum())
    nb_G = int((tmp["Pos"] == "G").sum())

    total_gc = int(gc_all["Salaire"].sum())
    total_ce = int(ce_all["Salaire"].sum())
    restant_gc = int(st.session_state["PLAFOND_GC"] - total_gc)
    restant_ce = int(st.session_state["PLAFOND_CE"] - total_ce)

    st.session_state["align_counts"] = {"F": nb_F, "D": nb_D, "G": nb_G}

    top = st.columns([1, 1, 1, 1, 1])
    top[0].metric("Total Grand Club", money(total_gc))
    top[1].metric("Montant Disponible GC", money(restant_gc))
    top[2].metric("Total Club École", money(total_ce))
    top[3].metric("Montant Disponible CE", money(restant_ce))
    top[4].metric("Blessés", f"{len(injured_all)}")

    st.markdown(
        f"Actifs: F {_count_badge(nb_F,12)} • D {_count_badge(nb_D,6)} • G {_count_badge(nb_G,2)}",
        unsafe_allow_html=True
    )

    st.divider()

    # -------------------------------------------------
    # Anti-boucle: si aucun pop-up n’est actif, on reset le dernier pick
    # -------------------------------------------------
    if st.session_state.get("move_ctx") is None:
        st.session_state["last_pick_align"] = None

    # -------------------------------------------------
    # 3 TABLEAUX (Actif / Banc / Mineur) — sélection unique
    # IMPORTANT: pas de on_select="rerun" pour éviter la boucle STOP
    # -------------------------------------------------
    df_actifs_ui = view_for_click(gc_actif)
    df_banc_ui   = view_for_click(gc_banc)
    df_min_ui    = view_for_click(ce_all)

    c1, c2, c3 = st.columns(3)

    with c1:
        st.markdown("### 🟢 Actifs")
        st.dataframe(
            df_actifs_ui,
            use_container_width=True,
            hide_index=True,
            selection_mode="single-row",
            key="sel_actifs",
        )

    with c2:
        st.markdown("### 🟡 Banc")
        st.dataframe(
            df_banc_ui,
            use_container_width=True,
            hide_index=True,
            selection_mode="single-row",
            key="sel_banc",
        )

    with c3:
        st.markdown("### 🔵 Mineur")
        st.dataframe(
            df_min_ui,
            use_container_width=True,
            hide_index=True,
            selection_mode="single-row",
            key="sel_min",
        )

    # -------------------------------------------------
    # ✅ Sélection UNIQUE (impossible d'en avoir 2)
    # - si un tableau est sélectionné, on clear les 2 autres
    # -------------------------------------------------
    def clear_other_selections(keep_key: str):
        for k in ["sel_actifs", "sel_banc", "sel_min"]:
            if k != keep_key:
                ss = st.session_state.get(k)
                if isinstance(ss, dict):
                    ss["selection"] = {"rows": []}
                    st.session_state[k] = ss

    picked = None

    pA = pick_from_df(df_actifs_ui, "sel_actifs")
    if pA:
        clear_other_selections("sel_actifs")
        picked = pA

    pB = pick_from_df(df_banc_ui, "sel_banc")
    if (picked is None) and pB:
        clear_other_selections("sel_banc")
        picked = pB

    pM = pick_from_df(df_min_ui, "sel_min")
    if (picked is None) and pM:
        clear_other_selections("sel_min")
        picked = pM

    if picked:
        picked = str(picked).strip()
        last_pick = st.session_state.get("last_pick_align")
        cur_pick = (proprietaire, picked)

        # ✅ Clear sélection (évite que Streamlit "ré-voit" la ligne au rerun)
        clear_df_selections()

        # ✅ Anti-double ouverture + ouvre pop-up
        if last_pick != cur_pick:
            st.session_state["last_pick_align"] = cur_pick
            set_move_ctx(proprietaire, picked)
            do_rerun()

    # -------------------------------------------------
    # 🩹 IR — table simple (sans sélection dataframe)
    # -------------------------------------------------
    st.divider()
    st.markdown("## 🩹 Joueurs Blessés (IR)")

    # assure IR Date
    if "IR Date" not in st.session_state["data"].columns:
        st.session_state["data"]["IR Date"] = ""
        st.session_state["data"] = clean_data(st.session_state["data"])
        st.session_state["data"].to_csv(DATA_FILE, index=False)

        # refresh local copies
        data_all = st.session_state["data"]
        dprop = data_all[data_all["Propriétaire"] == proprietaire].copy()
        injured_all = dprop[dprop.get("Slot", "") == "Blessé"].copy()

    if injured_all.empty:
        st.info("Aucun joueur blessé.")
    else:
        ir_show = injured_all.copy()
        ir_show["Pos"] = ir_show["Pos"].apply(normalize_pos)
        ir_show["Salaire"] = ir_show["Salaire"].apply(money)
        ir_show["IR Date"] = ir_show.get("IR Date", "").astype(str).str.strip()
        ir_show.loc[ir_show["IR Date"].eq(""), "IR Date"] = "—"

        ir_show = ir_show[["Joueur", "Pos", "Equipe", "IR Date", "Salaire"]].reset_index(drop=True)
        st.dataframe(ir_show, use_container_width=True, hide_index=True)

    # ✅ Pop-up à la fin du tab
    open_move_dialog()


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
    df_show,
    use_container_width=True,
    hide_index=True,
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
