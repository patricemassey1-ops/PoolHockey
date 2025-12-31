import streamlit as st
import pandas as pd
import io
import os
import re
import html
import textwrap
from datetime import datetime
from urllib.parse import quote, unquote
import base64
import textwrap

# =====================================================
# FILE GUARD (STREAMLIT CLOUD SAFE)
# =====================================================
def must_exist(path: str):
    if not os.path.exists(path):
        st.error(f"❌ Fichier introuvable : {path}")
        st.stop()


# =====================================================
# PLAYERS DB (Hockey_Players.csv) + HOVER TOOLTIP CARD
# =====================================================
PLAYERS_DB_FILE = "Hockey_Players.csv"  # change if your file is elsewhere

def _norm_name(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip()).lower()

@st.cache_data(show_spinner=False)
def load_players_db(path: str):
    return pd.read_csv(path)


    # Normalize player name column guess
    # Expecting something like "Player" or "Joueur" or "Name"
    name_col = None
    for c in dfp.columns:
        cl = c.strip().lower()
        if cl in {"player", "joueur", "name", "full name", "fullname"}:
            name_col = c
            break
    if name_col is None:
        # If we can't detect, just return raw
        return dfp

    dfp["_name_key"] = dfp[name_col].astype(str).map(_norm_name)
    return dfp

def get_player_row(players_df: pd.DataFrame, player_name: str) -> dict | None:
    if players_df is None or players_df.empty:
        return None
    key = _norm_name(player_name)
    if "_name_key" not in players_df.columns:
        return None
    hit = players_df[players_df["_name_key"] == key]
    if hit.empty:
        return None
    return hit.iloc[0].to_dict()

def _pick(d: dict, candidates: list[str], default=""):
    for k in candidates:
        if k in d and pd.notna(d[k]) and str(d[k]).strip() != "":
            return str(d[k]).strip()
    return default

def player_tooltip_css():
    st.markdown(
        textwrap.dedent("""
        <style>
          /* Hover container */
          .ph-wrap{
            position:relative;
            display:inline-block;
          }
          .ph-name{
            color:#4aa3ff;
            font-weight:900;
            text-decoration:underline;
            cursor:default;
          }

          /* Tooltip card (hidden by default) */
          .ph-tip{
            display:none;
            position:absolute;
            left:0;
            top:28px;
            width:520px;
            max-width:70vw;
            background:rgba(10,14,18,.98);
            border:1px solid rgba(255,255,255,.10);
            box-shadow:0 18px 50px rgba(0,0,0,.55);
            border-radius:18px;
            overflow:hidden;
            z-index:9999;
          }
          .ph-wrap:hover .ph-tip{ display:block; }

          /* Header like your screenshot */
          .ph-head{
            display:flex;
            gap:12px;
            align-items:center;
            padding:14px 14px 10px 14px;
            background:linear-gradient(180deg, rgba(12,18,24,1), rgba(7,10,13,1));
          }
          .ph-avatar{
            width:54px;height:54px;border-radius:14px;
            background:rgba(255,255,255,.06);
            object-fit:cover;
            flex:0 0 auto;
            border:1px solid rgba(255,255,255,.10);
          }
          .ph-title{
            font-size:20px;
            font-weight:1000;
            color:#4aa3ff;
            line-height:1.05;
            margin-bottom:4px;
          }
          .ph-sub{
            font-size:13px;
            color:rgba(255,255,255,.72);
            font-weight:700;
          }
          .ph-sub b{ color:rgba(255,255,255,.92); }

          .ph-flag{
            display:inline-flex;
            gap:8px;
            align-items:center;
            margin-top:6px;
            font-size:13px;
            color:rgba(255,255,255,.80);
            font-weight:800;
          }
          .ph-flag img{
            width:18px;height:12px;border-radius:2px;
            border:1px solid rgba(255,255,255,.25);
            object-fit:cover;
          }

          /* Body stats chips */
          .ph-body{ padding:12px 14px 14px 14px; }
          .ph-grid{
            display:grid;
            grid-template-columns: 1fr 1fr;
            gap:8px 14px;
          }
          .ph-kv{
            font-size:13px;
            color:rgba(255,255,255,.75);
            font-weight:800;
            padding:8px 10px;
            border-radius:12px;
            background:rgba(255,255,255,.04);
            border:1px solid rgba(255,255,255,.07);
          }
          .ph-kv span{
            color:rgba(255,255,255,.95);
            font-weight:1000;
            margin-left:6px;
          }

          /* keep tooltip on screen on small viewports */
          @media (max-width: 700px){
            .ph-tip{ width:92vw; }
          }
        </style>
        """),
        unsafe_allow_html=True,
    )

def render_player_hover_name(players_df: pd.DataFrame, player_name: str) -> str:
    """
    Returns an HTML snippet: the player's name with a hover tooltip card.
    """
    row = get_player_row(players_df, player_name) or {}

    # Try to find useful fields (works even if some are missing)
    name = player_name.strip()

    # OPTIONAL photo/headshot columns (adapt to your CSV)
    photo_url = _pick(row, ["Photo", "Headshot", "Image", "photo_url", "headshot_url"], default="")

    team = _pick(row, ["Team", "NHL Team", "Equipe", "Équipe"], default="")
    pos = _pick(row, ["Pos", "Position"], default="")
    jersey = _pick(row, ["Jersey #", "Jersey", "No", "#"], default="")
    shoots = _pick(row, ["Shoots", "Shot", "Tire"], default="")
    height = _pick(row, ["Hgt", "Height", "Taille"], default="")
    weight = _pick(row, ["W(lbs)", "Weight", "Poids"], default="")
    dob = _pick(row, ["DOB", "Birthdate", "Date of Birth", "Naissance"], default="")
    draft = _pick(row, ["Draft Year", "Draft", "Année Repêchage"], default="")
    ufa = _pick(row, ["UFA Year", "UFA", "Autonomie"], default="")
    caphit = _pick(row, ["Cap Hit", "CapHit", "AAV"], default="")

    country = _pick(row, ["Country", "Pays"], default="")
    flag_url = _pick(row, ["Flag", "Flag URL", "Flag_Image"], default="")

    # Fallback avatar if no photo
    if not photo_url:
        # tiny inline SVG placeholder
        svg = """<svg xmlns='http://www.w3.org/2000/svg' width='54' height='54'>
        <rect width='54' height='54' rx='14' fill='rgba(255,255,255,0.06)'/>
        <circle cx='27' cy='22' r='9' fill='rgba(255,255,255,0.18)'/>
        <rect x='14' y='34' width='26' height='12' rx='6' fill='rgba(255,255,255,0.14)'/>
        </svg>"""
        photo_url = "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("utf-8")

    # Escape text
    esc = html.escape
    name_e = esc(name)

    sub_bits = []
    if team: sub_bits.append(esc(team))
    if pos: sub_bits.append(f"• <b>{esc(pos)}</b>")
    if jersey: sub_bits.append(f"• #{esc(jersey)}")
    sub_line = " ".join(sub_bits) if sub_bits else "<span style='opacity:.6'>Info indisponible</span>"

    # Key/values (only show those that exist)
    kv = []
    def add_kv(label, value):
        if value and str(value).strip():
            kv.append((label, str(value).strip()))

    add_kv("Shoots", shoots)
    add_kv("Height", height)
    add_kv("Weight", weight)
    add_kv("DOB", dob)
    add_kv("Draft", draft)
    add_kv("UFA", ufa)
    add_kv("Cap Hit", caphit)

    kv_html = ""
    if kv:
        kv_html = "".join([f"<div class='ph-kv'>{esc(k)}:<span>{esc(v)}</span></div>" for k, v in kv])
    else:
        kv_html = "<div class='ph-kv'>No details<span>—</span></div>"

    flag_html = ""
    if country or flag_url:
        img = f"<img src='{esc(flag_url)}' />" if flag_url else ""
        flag_html = f"<div class='ph-flag'>{img}<span>{esc(country) if country else ''}</span></div>"

    return f"""
      <span class="ph-wrap">
        <span class="ph-name">{name_e}</span>
        <div class="ph-tip">
          <div class="ph-head">
            <img class="ph-avatar" src="{esc(photo_url)}" />
            <div style="min-width:0;">
              <div class="ph-title">{name_e}</div>
              <div class="ph-sub">{sub_line}</div>
              {flag_html}
            </div>
          </div>
          <div class="ph-body">
            <div class="ph-grid">
              {kv_html}
            </div>
          </div>
        </div>
      </span>
    """

# =====================================================
# CONFIG
# =====================================================
st.set_page_config("Fantrax Pool Hockey", layout="wide")
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

# =====================================================
# SESSION DEFAULTS + RERUN COMPAT + UPLOADER RESET
# =====================================================
if "uploader_nonce" not in st.session_state:
    st.session_state["uploader_nonce"] = 0

def do_rerun():
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()

if "PLAFOND_GC" not in st.session_state:
    st.session_state["PLAFOND_GC"] = 95_500_000
if "PLAFOND_CE" not in st.session_state:
    st.session_state["PLAFOND_CE"] = 47_750_000
if "move_ctx" not in st.session_state:
    st.session_state["move_ctx"] = None
if "move_nonce" not in st.session_state:
    st.session_state["move_nonce"] = 0

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
# SAISON
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
    try:
        return f"{int(v):,}".replace(",", " ") + " $"
    except Exception:
        return "0 $"

# =====================================================
# POSITIONS
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

# =====================================================
# DATA CLEAN
# =====================================================
def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df

    for col in ["Propriétaire", "Joueur", "Salaire", "Statut", "Slot", "Pos", "Equipe"]:
        if col not in df.columns:
            df[col] = "" if col != "Salaire" else 0

    df["Propriétaire"] = df["Propriétaire"].astype(str).str.strip()
    df["Joueur"] = df["Joueur"].astype(str).str.strip()
    df["Equipe"] = df["Equipe"].astype(str).str.strip()
    df["Statut"] = df["Statut"].astype(str).str.strip()
    df["Slot"] = df["Slot"].astype(str).str.strip()
    df["Pos"] = df["Pos"].astype(str).str.strip()

    # Normalise blessé
    df["Slot"] = df["Slot"].replace(
        {"IR": "Blessé", "Blesse": "Blessé", "Blesses": "Blessé", "Injured": "Blessé", "INJ": "Blessé"}
    )

    # Salaire int (accepte "12 500 000 $" etc.)
    df["Salaire"] = (
        df["Salaire"]
        .astype(str)
        .str.replace("$", "", regex=False)
        .str.replace(" ", "", regex=False)
        .str.replace(",", "", regex=False)
        .replace(["None", "nan", "NaN", ""], "0")
    )
    df["Salaire"] = pd.to_numeric(df["Salaire"], errors="coerce").fillna(0).astype(int)

    # Pos
    df["Pos"] = df["Pos"].apply(normalize_pos)

    # Retire lignes parasites
    forbidden = {"none", "skaters", "goalies", "player", "null"}
    df = df[~df["Joueur"].str.lower().isin(forbidden)]
    df = df[df["Joueur"].str.len() > 2]

    # Retire ligne vide typique entre sections
    df = df[
        ~(
            (df["Salaire"] <= 0)
            & (df["Equipe"].str.lower().isin(["none", "nan", "", "n/a"]))
        )
    ]

    # Slot par défaut
    mask_gc_default = (df["Statut"] == "Grand Club") & (df["Slot"].fillna("").eq(""))
    df.loc[mask_gc_default, "Slot"] = "Actif"
    mask_ce_default = (df["Statut"] == "Club École") & (df["Slot"] != "Blessé")
    df.loc[mask_ce_default, "Slot"] = ""

    # Aucun doublon par propriétaire
    df = df.drop_duplicates(subset=["Propriétaire", "Joueur"], keep="last").reset_index(drop=True)
    return df

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
        raise ValueError("Colonnes Fantrax non détectées (Player/Salary).")

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
# UI HELPERS
# =====================================================
def view_for_click(x: pd.DataFrame) -> pd.DataFrame:
    """
    IMPORTANT: on ne modifie PAS le champ Joueur (pas de '🩹 ' dedans),
    sinon les sélections/liens deviennent incohérents.
    """
    if x is None or x.empty:
        return pd.DataFrame(columns=["Joueur", "Pos", "Equipe", "Salaire", "État"])

    y = x.copy()
    y["Pos"] = y["Pos"].apply(normalize_pos)

    # État visible
    y["État"] = ""
    if "Slot" in y.columns:
        y.loc[y["Slot"].astype(str).str.strip().eq("Blessé"), "État"] = "🩹 BLESSÉ"

    y["_pos_order"] = y["Pos"].apply(pos_sort_key)
    y = y.sort_values(["_pos_order", "Joueur"]).drop(columns=["_pos_order"])

    y["Salaire"] = y["Salaire"].apply(money)

    cols = ["Joueur", "Pos", "Equipe", "Salaire", "État"]
    for c in cols:
        if c not in y.columns:
            y[c] = ""
    return y[cols].reset_index(drop=True)

def clear_df_selections():
    for k in ["sel_actifs", "sel_banc", "sel_min"]:
        if k in st.session_state and isinstance(st.session_state[k], dict):
            st.session_state[k]["selection"] = {"rows": []}

def pick_from_df(df_ui: pd.DataFrame, key: str):
    ss = st.session_state.get(key)
    if not ss or not isinstance(ss, dict):
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

def set_move_ctx(owner: str, joueur: str):
    st.session_state["move_nonce"] = st.session_state.get("move_nonce", 0) + 1
    st.session_state["move_ctx"] = {"owner": owner, "joueur": joueur, "nonce": st.session_state["move_nonce"]}

def clear_move_ctx():
    st.session_state["move_ctx"] = None

# =====================================================
# QUERY PARAMS (IR click)
# =====================================================
def _get_qp(key: str):
    if hasattr(st, "query_params"):
        v = st.query_params.get(key)
        if isinstance(v, list):
            return v[0] if v else None
        return v
    qp = st.experimental_get_query_params()
    v = qp.get(key)
    return v[0] if v else None

def _clear_qp(key: str):
    if hasattr(st, "query_params"):
        try:
            st.query_params.pop(key, None)
        except Exception:
            st.query_params[key] = ""
    else:
        st.experimental_set_query_params()

# =====================================================
# HISTORY
# =====================================================
def load_history(history_file: str) -> pd.DataFrame:
    if os.path.exists(history_file):
        return pd.read_csv(history_file)
    return pd.DataFrame(columns=[
        "id", "timestamp", "season",
        "proprietaire", "joueur", "pos", "equipe",
        "from_statut", "from_slot",
        "to_statut", "to_slot",
        "action"
    ])

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
    save_history(HISTORY_FILE, h)

# =====================================================
# APPLY MOVE (SAFE)
# =====================================================
def apply_move_with_history(proprietaire: str, joueur: str, to_statut: str, to_slot: str, action_label: str) -> bool:
    if LOCKED:
        st.error("🔒 Saison verrouillée : modification impossible.")
        return False

    df0 = st.session_state.get("data")
    if df0 is None or df0.empty:
        st.error("Aucune donnée en mémoire.")
        return False

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

    df0 = clean_data(df0)
    df0 = df0.drop_duplicates(subset=["Propriétaire", "Joueur"], keep="last").reset_index(drop=True)

    st.session_state["data"] = df0
    try:
        df0.to_csv(DATA_FILE, index=False)
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
# POP-UP (SIMPLE + KEYS UNIQUES + TOAST INTELLIGENT)
# =====================================================
def open_move_dialog():
    ctx = st.session_state.get("move_ctx")
    if not ctx:
        return

    if LOCKED:
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

    counts = st.session_state.get("align_counts", {"F": 0, "D": 0, "G": 0})
    f_count = int(counts.get("F", 0))
    d_count = int(counts.get("D", 0))
    g_count = int(counts.get("G", 0))

    def can_go_actif(pos: str):
        if pos == "F" and f_count >= 12:
            return False, "🚫 Déjà 12 F actifs."
        if pos == "D" and d_count >= 6:
            return False, "🚫 Déjà 6 D actifs."
        if pos == "G" and g_count >= 2:
            return False, "🚫 Déjà 2 G actifs."
        return True, ""

    @st.dialog(f"Déplacement — {joueur}")
    def _dlg():
        st.caption(f"**{owner}** • **{joueur}** • Pos **{cur_pos}** • **{cur_equipe}** • Salaire **{money(cur_salaire)}**")
        st.caption(f"Actuel : **{cur_statut}**" + (f" (**{cur_slot}**)" if cur_slot else ""))

        destinations = [
            ("🟢 Grand Club / Actif", ("Grand Club", "Actif")),
            ("🟡 Grand Club / Banc", ("Grand Club", "Banc")),
            ("🔵 Mineur", ("Club École", "")),
            ("🩹 Joueurs Blessés (IR)", (cur_statut, "Blessé")),
        ]

        current = (cur_statut, cur_slot if cur_slot else "")
        destinations = [d for d in destinations if d[1] != current]

        if cur_slot == "Blessé":
            destinations = [d for d in destinations if d[1][1] != "Blessé"]

        if not destinations:
            st.info("Aucune destination disponible.")
            if st.button("Fermer", key=f"close_{owner}_{joueur}_{nonce}", use_container_width=True):
                clear_move_ctx()
                st.rerun()
            return

        choice = st.radio(
            "Destination",
            [d[0] for d in destinations],
            index=0,
            key=f"dest_{owner}_{joueur}_{nonce}",
        )
        to_statut, to_slot = dict(destinations)[choice]

        c1, c2 = st.columns(2)

        if c1.button("✅ Confirmer", key=f"confirm_{owner}_{joueur}_{nonce}", use_container_width=True):
            if to_statut == "Grand Club" and to_slot == "Actif":
                ok, msg = can_go_actif(cur_pos)
                if not ok:
                    st.error(msg)
                    return

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
                    st.toast(f"🩹 {joueur} placé sur la liste des blessés (IR)", icon="🩹")
                elif to_statut == "Grand Club" and to_slot == "Actif":
                    st.toast(f"🟢 {joueur} ajouté au Grand Club (Actif)", icon="🟢")
                elif to_statut == "Grand Club" and to_slot == "Banc":
                    st.toast(f"🟡 {joueur} déplacé sur le banc du Grand Club", icon="🟡")
                elif to_statut == "Club École":
                    st.toast(f"🔵 {joueur} envoyé au Club École (Mineur)", icon="🔵")
                else:
                    st.toast(f"✅ Déplacement enregistré pour {joueur}", icon="✅")

                st.rerun()

        if c2.button("Annuler", key=f"cancel_{owner}_{joueur}_{nonce}", use_container_width=True):
            clear_move_ctx()
            st.rerun()

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

st.sidebar.divider()
st.sidebar.header("💰 Plafonds")
if st.sidebar.button("✏️ Modifier les plafonds"):
    st.session_state["edit_plafond"] = True
if st.session_state.get("edit_plafond"):
    st.session_state["PLAFOND_GC"] = st.sidebar.number_input(
        "Plafond Grand Club", value=int(st.session_state["PLAFOND_GC"]), step=500_000
    )
    st.session_state["PLAFOND_CE"] = st.sidebar.number_input(
        "Plafond Club École", value=int(st.session_state["PLAFOND_CE"]), step=250_000
    )
st.sidebar.metric("🏒 Grand Club", money(st.session_state["PLAFOND_GC"]))
st.sidebar.metric("🏫 Club École", money(st.session_state["PLAFOND_CE"]))

# =====================================================
# LOAD DATA / HISTORY WHEN SEASON CHANGES
# =====================================================
if "season" not in st.session_state or st.session_state["season"] != season:
    if os.path.exists(DATA_FILE):
        st.session_state["data"] = pd.read_csv(DATA_FILE)
    else:
        st.session_state["data"] = pd.DataFrame(columns=["Propriétaire", "Joueur", "Salaire", "Statut", "Slot", "Pos", "Equipe"])

    if "Slot" not in st.session_state["data"].columns:
        st.session_state["data"]["Slot"] = ""

    st.session_state["data"] = clean_data(st.session_state["data"])
    st.session_state["data"].to_csv(DATA_FILE, index=False)
    st.session_state["season"] = season

if "history_season" not in st.session_state or st.session_state["history_season"] != season:
    st.session_state["history"] = load_history(HISTORY_FILE)
    st.session_state["history_season"] = season

# =====================================================
# IMPORT FANTRAX (FIX: pas besoin de refresh)
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
if os.path.exists("Logo_Pool.png"):
    st.image("Logo_Pool.png", use_container_width=True)
st.title("🏒 Fantrax – Gestion Salariale")

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
    gc = d[(d["Statut"] == "Grand Club") & (d["Slot"] != "Blessé")]["Salaire"].sum()
    ce = d[(d["Statut"] == "Club École") & (d["Slot"] != "Blessé")]["Salaire"].sum()

    logo = ""
    for k, v in LOGOS.items():
        if k.lower() in str(p).lower():
            logo = v

    resume.append({
        "Propriétaire": p,
        "Logo": logo,
        "GC": int(gc),
        "Restant GC": int(st.session_state["PLAFOND_GC"] - gc),
        "CE": int(ce),
        "Restant CE": int(st.session_state["PLAFOND_CE"] - ce),
    })

plafonds = pd.DataFrame(resume)

# =====================================================
# TABS
# =====================================================
tab1, tabA, tabJ, tabH, tab2, tab3 = st.tabs(
    ["📊 Tableau", "🧾 Alignement", "👤 Joueurs", "🕘 Historique", "⚖️ Transactions", "🧠 Recommandations"]
)




# =====================================================
# TAB 1 - TABLEAU
# =====================================================
with tab1:
    headers = st.columns([4, 2, 2, 2, 2])
    headers[0].markdown("**Équipe**")
    headers[1].markdown("**Total GC**")
    headers[2].markdown("**Restant GC**")
    headers[3].markdown("**Total CE**")
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
# TAB A - ALIGNEMENT
# =====================================================
with tabA:
    st.subheader("🧾 Alignement")
    st.caption("Sélectionne un joueur (Actifs/Banc/Mineur) ou clique une ligne Blessé (IR) pour ouvrir le pop-up.")

    proprietaire = st.selectbox(
        "Propriétaire",
        sorted(st.session_state["data"]["Propriétaire"].unique()),
        key="align_owner",
    )

    st.session_state["data"] = clean_data(st.session_state["data"])
    data_all = st.session_state["data"]
    dprop = data_all[data_all["Propriétaire"] == proprietaire].copy()

    injured_all = dprop[dprop.get("Slot", "") == "Blessé"].copy()
    dprop_not_inj = dprop[dprop.get("Slot", "") != "Blessé"].copy()

    gc_all = dprop_not_inj[dprop_not_inj["Statut"] == "Grand Club"].copy()
    ce_all = dprop_not_inj[dprop_not_inj["Statut"] == "Club École"].copy()

    gc_actif = gc_all[gc_all.get("Slot", "") == "Actif"].copy()
    gc_banc  = gc_all[gc_all.get("Slot", "") == "Banc"].copy()

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
    top[0].metric("GC", money(total_gc))
    top[1].metric("R GC", money(restant_gc))
    top[2].metric("CE", money(total_ce))
    top[3].metric("R CE", money(restant_ce))
    top[4].metric("Blessés", f"{len(injured_all)}")

    st.caption(f"Actifs: F {nb_F}/12 • D {nb_D}/6 • G {nb_G}/2")
    st.divider()

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
            on_select="rerun",
            key="sel_actifs",
        )
    with c2:
        st.markdown("### 🟡 Banc")
        st.dataframe(
            df_banc_ui,
            use_container_width=True,
            hide_index=True,
            selection_mode="single-row",
            on_select="rerun",
            key="sel_banc",
        )
    with c3:
        st.markdown("### 🔵 Mineur")
        st.dataframe(
            df_min_ui,
            use_container_width=True,
            hide_index=True,
            selection_mode="single-row",
            on_select="rerun",
            key="sel_min",
        )

    picked = (
        pick_from_df(df_actifs_ui, "sel_actifs")
        or pick_from_df(df_banc_ui, "sel_banc")
        or pick_from_df(df_min_ui, "sel_min")
    )
    if picked:
        clear_df_selections()
        set_move_ctx(proprietaire, picked)
        st.rerun()

    st.divider()
    st.markdown("## 🩹 Joueurs Blessés (IR)")
    df_inj_ui = view_for_click(injured_all)

    picked_ir = _get_qp("ir_pick")
    if picked_ir:
        picked_ir = unquote(picked_ir)
        set_move_ctx(proprietaire, picked_ir)
        _clear_qp("ir_pick")
        st.rerun()

    if df_inj_ui.empty:
        st.info("Aucun joueur blessé.")
    else:
        # [Votre code CSS et HTML pour la table IR]
        pass

    open_move_dialog()


# =====================================================
# TAB J - JOUEURS (RECHERCHE + TOOLTIP HOVER)
# =====================================================
with tabJ:
    st.subheader("👤 Joueurs (Autonome)")
    st.caption("Recherche un joueur — survole son nom pour voir son profil complet.")

    # -------------------------------------------------
    # LOAD DATA (CACHE)
    # -------------------------------------------------
    @st.cache_data(show_spinner=False)
    def load_players():
        return pd.read_csv("data/Hockey.Players.csv")

    df_players = load_players()

    # -------------------------------------------------
    # SEARCH CONTROLS
    # -------------------------------------------------
    c1, c2, c3 = st.columns([2, 1, 1])

    with c1:
        search_name = st.text_input("Nom / Prénom", placeholder="Ex: Zibanejad")

    with c2:
        teams = sorted(df_players["Team"].dropna().unique())
        team = st.selectbox("Équipe", ["Toutes"] + teams)

    with c3:
        levels = sorted(df_players["Level"].dropna().unique())
        level = st.selectbox("Level", ["Tous"] + levels)

    # -------------------------------------------------
    # FILTER DATA
    # -------------------------------------------------
    df = df_players.copy()

    if search_name:
        df = df[df["Player"].str.contains(search_name, case=False, na=False)]

    if team != "Toutes":
        df = df[df["Team"] == team]

    if level != "Tous":
        df = df[df["Level"] == level]

    if df.empty:
        st.info("Aucun joueur trouvé.")
        st.stop()

    df = df.head(200)  # sécurité perf

    # -------------------------------------------------
    # STYLES
    # -------------------------------------------------
    st.markdown(
        """
        <style>
        .player-row:hover{background:#120000;}
        .tt-wrap{position:relative;display:inline-block}
        .tt-bubble{
            display:none;position:absolute;left:0;top:110%;
            width:420px;background:#0b0b0b;border:1px solid #ff2d2d;
            border-radius:14px;padding:12px;z-index:9999;
            box-shadow:0 14px 30px rgba(0,0,0,.55)
        }
        .tt-wrap:hover .tt-bubble{display:block}
        .tt-head{display:flex;align-items:center;gap:10px;margin-bottom:10px}
        .tt-flag{width:26px;border-radius:4px;border:1px solid #222}
        .tt-name{font-weight:1000;color:white}
        .tt-country{color:#ff2d2d;font-weight:900}
        .tt-grid{display:grid;grid-template-columns:130px 1fr;gap:6px 10px}
        .tt-k{color:#ff2d2d;font-weight:900}
        .tt-v{color:#eee;font-weight:800}
        </style>
        """,
        unsafe_allow_html=True
    )

    # -------------------------------------------------
    # TABLE
    # -------------------------------------------------
    rows = ""

    for _, r in df.iterrows():
        flag = r.get("Flag", "")
        country = r.get("Country", "")
        name = r.get("Player", "")
        team = r.get("Team", "")
        pos = r.get("Position", "")
        cap = r.get("Cap Hit", "")

        tooltip = f"""
        <div class="tt-head">
            <img src="{flag}" class="tt-flag">
            <div>
                <div class="tt-name">{name}</div>
                <div class="tt-country">{country}</div>
            </div>
        </div>
        <div class="tt-grid">
            <div class="tt-k">Équipe</div><div class="tt-v">{team}</div>
            <div class="tt-k">Position</div><div class="tt-v">{pos}</div>
            <div class="tt-k">Taille</div><div class="tt-v">{r.get("H(f)", "")}</div>
            <div class="tt-k">Poids</div><div class="tt-v">{r.get("W(lbs)", "")} lbs</div>
            <div class="tt-k">Âge</div><div class="tt-v">{r.get("Age", "")}</div>
            <div class="tt-k">Cap Hit</div><div class="tt-v">{cap}</div>
            <div class="tt-k">Contrat</div><div class="tt-v">{r.get("Expiry Year", "")} ({r.get("Expiry Status", "")})</div>
        </div>
        """

        rows += f"""
        <tr class="player-row">
            <td>
                <span class="tt-wrap">
                    {name}
                    <div class="tt-bubble">{tooltip}</div>
                </span>
            </td>
            <td>{team}</td>
            <td>{pos}</td>
            <td style="text-align:right">{cap}</td>
        </tr>
        """

    st.markdown(
        f"""
        <table style="width:100%;border-collapse:collapse">
            <thead>
                <tr style="color:#ff2d2d">
                    <th>Joueur</th>
                    <th>Équipe</th>
                    <th>Pos</th>
                    <th style="text-align:right">Cap Hit</th>
                </tr>
            </thead>
            <tbody>{rows}</tbody>
        </table>
        """,
        unsafe_allow_html=True
    )







# =====================================================
# TAB H - HISTORIQUE
# =====================================================
with tabH:
    st.subheader("🕘 Historique des changements d’alignement")

    h = st.session_state["history"].copy()
    if h.empty:
        st.info("Aucune entrée d’historique pour cette saison.")
        st.stop()

    owners = ["Tous"] + sorted(h["proprietaire"].dropna().astype(str).unique().tolist())
    owner_filter = st.selectbox("Filtrer par propriétaire", owners, key="hist_owner_filter")

    if owner_filter != "Tous":
        h = h[h["proprietaire"].astype(str) == owner_filter]

    if h.empty:
        st.info("Aucune entrée pour ce propriétaire.")
        st.stop()

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
                st.stop()

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
                st.rerun()

        if cols[8].button("❌", key=f"del_{rid}"):
            h2 = st.session_state["history"].copy()
            h2 = h2[h2["id"] != rid]
            st.session_state["history"] = h2
            save_history(HISTORY_FILE, h2)
            st.toast("🗑️ Entrée supprimée", icon="🗑️")
            st.rerun()

# =====================================================
# TAB 2 - TRANSACTIONS
# =====================================================
with tab2:
    p = st.selectbox("Propriétaire", plafonds["Propriétaire"], key="tx_owner")
    salaire = st.number_input("Salaire du joueur", min_value=0, step=100000, key="tx_salary")
    statut = st.radio("Statut", ["Grand Club", "Club École"], key="tx_statut")

    ligne = plafonds[plafonds["Propriétaire"] == p].iloc[0]
    reste = ligne["Restant GC"] if statut == "Grand Club" else ligne["Restant CE"]

    if salaire > reste:
        st.error("🚨 Dépassement du plafond")
    else:
        st.success("✅ Transaction valide")

# =====================================================
# TAB 3 - RECOMMANDATIONS
# =====================================================
with tab3:
    for _, r in plafonds.iterrows():
        if r["Restant GC"] < 2_000_000:
            st.warning(f"{r['Propriétaire']} : rétrogradation recommandée")
        if r["Restant CE"] > 10_000_000:
            st.info(f"{r['Propriétaire']} : rappel possible")
