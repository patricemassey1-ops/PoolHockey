# =====================================================
# app.py — PMS Pool (version propre + corrections + Admin complet)
#   ✅ 1 seule section Alignement (dans le routing)
#   ✅ sidebar = source de vérité (sync selected_team / align_owner)
#   ✅ Admin Import (preview + confirmer + tri imports)
# =====================================================

# =====================================================
# IMPORTS
# =====================================================
import os
import io
import re
import json
import html
import base64
import hashlib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components


# =====================================================
# STREAMLIT CONFIG (MUST BE FIRST STREAMLIT COMMAND)
# =====================================================
st.set_page_config(page_title="PMS", layout="wide")


# =====================================================
# DATE FORMAT — Français (cloud-proof, no locale)
# =====================================================
MOIS_FR = [
    "", "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre"
]

TZ_TOR = ZoneInfo("America/Montreal")

def to_dt_local(x):
    if x is None:
        return pd.NaT
    dt = pd.to_datetime(x, errors="coerce", utc=False)
    if pd.isna(dt):
        return pd.NaT
    if getattr(dt, "tzinfo", None) is not None:
        dt = dt.tz_convert(TZ_TOR).tz_localize(None)
    return dt

def format_date_fr(x) -> str:
    dt = to_dt_local(x)
    if pd.isna(dt):
        return ""
    return f"{dt.day} {MOIS_FR[int(dt.month)]} {dt.year} {dt:%H:%M:%S}"


# =====================================================
# PATHS / CONSTANTS
# =====================================================
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

PLAYERS_DB_FILE = os.path.join(DATA_DIR, "Hockey.Players.csv")
LOGO_POOL_FILE = os.path.join(DATA_DIR, "Logo_Pool.png")
INIT_MANIFEST_FILE = os.path.join(DATA_DIR, "init_manifest.json")

REQUIRED_COLS = [
    "Propriétaire", "Joueur", "Pos", "Equipe", "Salaire",
    "Statut", "Slot", "IR Date"
]

# Slots
SLOT_ACTIF = "Actif"
SLOT_BANC = "Banc"
SLOT_IR = "Blessé"

STATUT_GC = "Grand Club"
STATUT_CE = "Club École"


# =====================================================
# 🔐 PASSWORD GATE + HEADER
# =====================================================
def _sha256(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()

def _login_header():
    logo_file = os.path.join("data", "Logo_Pool.png")

    st.markdown(
        """
        <style>
          .block-container { padding-top: 1.2rem !important; }
          .pms-header-wrap{ max-width: 1120px; margin: 0 auto 10px auto; }
          .pms-emoji{ font-size: 64px; line-height: 1; display:flex; align-items:center; justify-content:center;
                     opacity: .95; filter: drop-shadow(0 6px 14px rgba(0,0,0,.35)); }
          .pms-text{ font-weight: 1000; letter-spacing: .06em; color: #ff3b30; font-size: 54px; line-height: 1;
                     margin-left: 10px; text-shadow: 0 10px 20px rgba(0,0,0,.35); display:inline-block;
                     transform: translateY(-2px); }
          .pms-logo{ width: 100%; display:flex; justify-content:center; align-items:center; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    with st.container():
        st.markdown('<div class="pms-header-wrap">', unsafe_allow_html=True)
        c1, c2, c3 = st.columns([2, 8, 2], vertical_alignment="center")

        with c1:
            st.markdown(
                '<div class="pms-emoji">🏒<span class="pms-text">PMS</span></div>',
                unsafe_allow_html=True,
            )

        with c2:
            if os.path.exists(logo_file):
                st.image(logo_file, use_container_width=True)
            else:
                st.markdown('<div class="pms-logo"><span class="pms-text">PMS</span></div>', unsafe_allow_html=True)

        with c3:
            st.markdown('<div class="pms-emoji">🥅</div>', unsafe_allow_html=True)

        st.markdown("</div>", unsafe_allow_html=True)

    st.divider()

def require_password():
    cfg = st.secrets.get("security", {}) or {}

    if bool(cfg.get("enable_hash_tool", False)):
        return

    expected = str(cfg.get("password_sha256", "")).strip()
    if not expected:
        return

    if st.session_state.get("authed", False):
        return

    _login_header()
    st.title("🔐 Accès sécurisé")
    st.caption("Entre le mot de passe partagé pour accéder à l’application.")

    pwd = st.text_input("Mot de passe", type="password")
    col1, col2 = st.columns([1, 2], vertical_alignment="center")

    with col1:
        if st.button("Se connecter", type="primary", use_container_width=True):
            if _sha256(pwd) == expected:
                st.session_state["authed"] = True
                st.success("✅ Accès autorisé")
                st.rerun()
            else:
                st.error("❌ Mot de passe invalide")

    with col2:
        st.info("Astuce: si tu changes le mot de passe, regénère un nouveau hash et remplace-le dans Secrets.")

    st.stop()

require_password()

if bool(st.secrets.get("security", {}).get("enable_hash_tool", False)):
    st.markdown("### 🔐 Générateur de hash (temporaire)")
    pwd = st.text_input("Mot de passe à hasher", type="password")
    if pwd:
        h = hashlib.sha256(pwd.encode("utf-8")).hexdigest()
        st.code(h)
        st.info("⬆️ Copie ce hash dans Streamlit Secrets puis remet enable_hash_tool=false.")
    st.divider()


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
    if "G" in p:
        return "G"
    if "D" in p:
        return "D"
    return "F"

def pos_sort_key(pos: str) -> int:
    return {"F": 0, "D": 1, "G": 2}.get(str(pos).upper(), 99)

def saison_auto() -> str:
    now = datetime.now(TZ_TOR)
    return f"{now.year}-{now.year+1}" if now.month >= 9 else f"{now.year-1}-{now.year}"

def saison_verrouillee(season: str) -> bool:
    try:
        return int(str(season)[:4]) < int(saison_auto()[:4])
    except Exception:
        return False

def render_badge(text: str, bg: str, fg: str = "white") -> str:
    t = html.escape(str(text or ""))
    return (
        "<span style='display:inline-block;padding:2px 8px;border-radius:999px;"
        f"background:{bg};color:{fg};font-weight:900;font-size:12px'>"
        f"{t}</span>"
    )

def pos_badge_html(pos: str) -> str:
    p = normalize_pos(pos)
    if p == "F":
        return render_badge("F", "#16a34a")
    if p == "D":
        return render_badge("D", "#2563eb")
    return render_badge("G", "#7c3aed")

def _count_badge(n: int, limit: int) -> str:
    if n > limit:
        return f"<span style='color:#ef4444;font-weight:1000'>{n}</span>/{limit} ⚠️"
    return f"<span style='color:#22c55e;font-weight:1000'>{n}</span>/{limit}"

def cap_bar_html(used: int, cap: int, label: str) -> str:
    cap = int(cap or 0)
    used = int(used or 0)
    remain = cap - used
    pct = max(0, min((used / cap) if cap else 0, 1))
    color = "#16a34a" if remain >= 0 else "#dc2626"
    return f"""
    <div style="margin-bottom:10px">
      <div style="display:flex;justify-content:space-between;font-size:12px;font-weight:900">
        <span>{html.escape(label)}</span>
        <span style="color:{color}">{money(remain)}</span>
      </div>
      <div style="background:#e5e7eb;height:10px;border-radius:6px;overflow:hidden">
        <div style="width:{int(pct*100)}%;background:{color};height:100%"></div>
      </div>
      <div style="font-size:11px;opacity:.75">
        Utilisé : {money(used)} / {money(cap)}
      </div>
    </div>
    """

def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame):
        return pd.DataFrame(columns=REQUIRED_COLS)

    out = df.copy()

    for c in REQUIRED_COLS:
        if c not in out.columns:
            out[c] = "" if c in {"Propriétaire", "Joueur", "Pos", "Equipe", "Statut", "Slot", "IR Date"} else 0

    out["Propriétaire"] = out["Propriétaire"].astype(str).str.strip()
    out["Joueur"] = out["Joueur"].astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
    out["Pos"] = out["Pos"].astype(str).apply(normalize_pos)
    out["Equipe"] = out["Equipe"].astype(str).str.strip()

    out["Salaire"] = pd.to_numeric(out["Salaire"], errors="coerce").fillna(0).astype(int)

    out["Statut"] = out["Statut"].astype(str).str.strip().replace({"": STATUT_GC})
    out["Slot"] = out["Slot"].astype(str).str.strip()
    out["IR Date"] = out["IR Date"].astype(str).str.strip()

    bad = {"", "none", "nan", "null"}
    out = out[~out["Joueur"].str.lower().isin(bad)].copy()
    return out.reset_index(drop=True)


# =====================================================
# LOGOS
# =====================================================
LOGOS = {
    "Nordiques": os.path.join(DATA_DIR, "Nordiques_Logo.png"),
    "Cracheurs": os.path.join(DATA_DIR, "Cracheurs_Logo.png"),
    "Prédateurs": os.path.join(DATA_DIR, "Predateurs_logo.png"),
    "Red Wings": os.path.join(DATA_DIR, "Red_Wings_Logo.png"),
    "Whalers": os.path.join(DATA_DIR, "Whalers_Logo.png"),
    "Canadiens": os.path.join(DATA_DIR, "montreal-canadiens-logo.png"),
}

def team_logo_path(team: str) -> str:
    path = str(LOGOS.get(str(team or "").strip(), "")).strip()
    return path if path and os.path.exists(path) else ""


# =====================================================
# TEAM SELECTION (single source of truth)
# =====================================================
def pick_team(team: str):
    team = str(team or "").strip()
    st.session_state["selected_team"] = team
    st.session_state["align_owner"] = team
    do_rerun()

def get_selected_team() -> str:
    v = str(st.session_state.get("selected_team") or "").strip()
    if v:
        return v
    v = str(st.session_state.get("align_owner") or "").strip()
    return v

def _is_admin_whalers() -> bool:
    if bool(st.session_state.get("IS_ADMIN", False)):
        return True
    return get_selected_team().strip().lower() == "whalers"


# =====================================================
# INIT MANIFEST
# =====================================================
def load_init_manifest() -> dict:
    try:
        if os.path.exists(INIT_MANIFEST_FILE):
            with open(INIT_MANIFEST_FILE, "r", encoding="utf-8") as f:
                return json.load(f) or {}
    except Exception:
        pass
    return {}

def save_init_manifest(manifest: dict) -> None:
    try:
        with open(INIT_MANIFEST_FILE, "w", encoding="utf-8") as f:
            json.dump(manifest or {}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# =====================================================
# PERSISTENCE
# =====================================================
def persist_data(df: pd.DataFrame, season_lbl: str) -> None:
    season_lbl = str(season_lbl or "").strip() or "season"
    path = os.path.join(DATA_DIR, f"fantrax_{season_lbl}.csv")
    st.session_state["DATA_FILE"] = path
    try:
        df.to_csv(path, index=False)
    except Exception:
        pass

def persist_history(h: pd.DataFrame, season_lbl: str) -> None:
    season_lbl = str(season_lbl or "").strip() or "season"
    path = os.path.join(DATA_DIR, f"history_{season_lbl}.csv")
    st.session_state["HISTORY_FILE"] = path
    try:
        h.to_csv(path, index=False)
    except Exception:
        pass


# =====================================================
# HISTORY (normalized)
# =====================================================
def _history_expected_cols():
    return [
        "id", "timestamp", "season",
        "proprietaire", "joueur", "pos", "equipe",
        "from_statut", "from_slot", "to_statut", "to_slot",
        "action",
    ]

def _history_empty_df():
    return pd.DataFrame(columns=_history_expected_cols())

def load_history_file(path: str) -> pd.DataFrame:
    try:
        if path and os.path.exists(path):
            h = pd.read_csv(path)
            if isinstance(h, pd.DataFrame):
                for c in _history_expected_cols():
                    if c not in h.columns:
                        h[c] = ""
                return h[_history_expected_cols()].copy()
    except Exception:
        pass
    return _history_empty_df()

def next_hist_id(h: pd.DataFrame) -> int:
    try:
        if h is None or not isinstance(h, pd.DataFrame) or h.empty or "id" not in h.columns:
            return 1
        v = pd.to_numeric(h["id"], errors="coerce").fillna(0)
        return int(v.max()) + 1
    except Exception:
        return 1

def log_history_row(
    proprietaire: str,
    joueur: str,
    pos: str,
    equipe: str,
    from_statut: str,
    from_slot: str,
    to_statut: str,
    to_slot: str,
    action: str,
):
    h = st.session_state.get("history")
    h = h.copy() if isinstance(h, pd.DataFrame) else _history_empty_df()

    row_hist = {
        "id": next_hist_id(h),
        "timestamp": datetime.now(TZ_TOR).strftime("%Y-%m-%d %H:%M:%S"),
        "season": str(st.session_state.get("season", "") or ""),
        "proprietaire": str(proprietaire or ""),
        "joueur": str(joueur or ""),
        "pos": str(pos or ""),
        "equipe": str(equipe or ""),
        "from_statut": str(from_statut or ""),
        "from_slot": str(from_slot or ""),
        "to_statut": str(to_statut or ""),
        "to_slot": str(to_slot or ""),
        "action": str(action or ""),
    }

    h = pd.concat([h, pd.DataFrame([row_hist])], ignore_index=True)
    st.session_state["history"] = h
    persist_history(h, str(st.session_state.get("season", "")).strip())


# =====================================================
# PLAYERS DB
# =====================================================
def _norm_name(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip()).lower()

@st.cache_data(show_spinner=False)
def load_players_db(path: str) -> pd.DataFrame:
    if not path or not os.path.exists(path):
        return pd.DataFrame()
    try:
        dfp = pd.read_csv(path)
    except Exception:
        return pd.DataFrame()

    name_col = None
    for c in dfp.columns:
        cl = c.strip().lower()
        if cl in {"player", "joueur", "name", "full name", "fullname"}:
            name_col = c
            break
    if name_col is not None:
        dfp["_name_key"] = dfp[name_col].astype(str).map(_norm_name)
    return dfp


# =====================================================
# FANTRAX PARSER
# =====================================================
def parse_fantrax(upload) -> pd.DataFrame:
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

    sal = (
        df[salary_col].astype(str)
        .str.replace(",", "", regex=False)
        .str.replace(" ", "", regex=False)
        .replace(["None", "nan", "NaN", ""], "0")
    )
    out["Salaire"] = pd.to_numeric(sal, errors="coerce").fillna(0).astype(int) * 1000

    if status_col:
        out["Statut"] = df[status_col].apply(lambda x: STATUT_CE if "min" in str(x).lower() else STATUT_GC)
    else:
        out["Statut"] = STATUT_GC

    out["Slot"] = out["Statut"].apply(lambda s: SLOT_ACTIF if s == STATUT_GC else "")
    out["IR Date"] = ""
    return clean_data(out)

def ensure_owner_column(df: pd.DataFrame, fallback_owner: str) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame):
        return df
    out = df.copy()
    candidates = [
        "Propriétaire", "Proprietaire",
        "Owner", "owner", "Owners", "owners",
        "Team", "team",
        "Équipe", "Equipe", "équipe", "equipe",
        "Franchise", "franchise",
        "Club", "club",
    ]
    existing = next((c for c in candidates if c in out.columns), None)
    if existing and existing != "Propriétaire":
        out["Propriétaire"] = out[existing]
    if "Propriétaire" not in out.columns:
        out["Propriétaire"] = str(fallback_owner or "").strip()

    s = out["Propriétaire"].astype(str).str.strip()
    s = s.replace({"nan": "", "None": ""})
    s = s.mask(s.eq(""), str(fallback_owner or "").strip())
    out["Propriétaire"] = s
    return out


# =====================================================
# MOVE DIALOG — auto-remplacement IR + étiquette exacte
# =====================================================
def open_move_dialog():
    ctx = st.session_state.get("move_ctx")
    if not ctx:
        return

    if st.session_state.get("LOCKED"):
        st.warning("🔒 Saison verrouillée : aucun changement permis.")
        clear_move_ctx()
        return

    owner = str(ctx.get("owner", "")).strip()
    joueur = str(ctx.get("joueur", "")).strip()
    nonce = int(ctx.get("nonce", 0))

    df_all = st.session_state.get("data")
    if df_all is None or not isinstance(df_all, pd.DataFrame) or df_all.empty:
        st.error("Aucune donnée chargée.")
        clear_move_ctx()
        return

    df_all = clean_data(df_all)

    mask = (
        df_all["Propriétaire"].astype(str).str.strip().eq(owner)
        & df_all["Joueur"].astype(str).str.strip().eq(joueur)
    )
    if df_all.loc[mask].empty:
        st.error("Joueur introuvable.")
        clear_move_ctx()
        return

    row = df_all.loc[mask].iloc[0]
    cur_statut = str(row.get("Statut", "")).strip()
    cur_slot = str(row.get("Slot", "")).strip()
    cur_pos = normalize_pos(row.get("Pos", "F"))
    cur_team = str(row.get("Equipe", "")).strip()
    cur_sal = int(row.get("Salaire", 0) or 0)

    def _close():
        clear_move_ctx()

    # -------------------------------------------------
    # RÈGLES D’EFFET (TES RÈGLES)
    # -------------------------------------------------
    def _effective_date(reason: str, from_statut: str, from_slot: str,
                        to_statut: str, to_slot: str) -> datetime:
        """
        Règles finales:
        - Changement demi-mois → IMMÉDIAT (toujours)
        - Blessure :
            - GC → CE (mineur) → IMMÉDIAT
            - CE → Actif (GC Actif) → +3 jours
            - autres → IMMÉDIAT
        """
        now = datetime.now(TZ_TOR)

        reason_low = str(reason or "").lower().strip()
        from_statut = str(from_statut or "").strip()
        from_slot = str(from_slot or "").strip()
        to_statut = str(to_statut or "").strip()
        to_slot = str(to_slot or "").strip()

        # Demi-mois = immédiat
        if reason_low.startswith("changement"):
            return now

        # Blessure
        if reason_low.startswith("bless"):
            # GC -> CE immédiat
            if from_statut == STATUT_GC and to_statut == STATUT_CE:
                return now
            # CE -> Actif (+3 jours)
            if from_statut == STATUT_CE and to_statut == STATUT_GC and to_slot == SLOT_ACTIF:
                return now + timedelta(days=3)
            return now

        return now

    # -------------------------------------------------
    # AUTO-REMPLACEMENT (GC Actif -> IR)
    # -------------------------------------------------
    def _auto_replace_injured(owner_: str, injured_pos_: str) -> bool:
        dfx = st.session_state.get("data")
        if dfx is None or not isinstance(dfx, pd.DataFrame) or dfx.empty:
            return False

        dfx = clean_data(dfx)
        owner_ = str(owner_ or "").strip()
        injured_pos_ = normalize_pos(injured_pos_)

        dprop = dfx[dfx["Propriétaire"].astype(str).str.strip().eq(owner_)].copy()
        if dprop.empty:
            return False

        # Exclure IR
        dprop_ok = dprop[dprop.get("Slot", "") != SLOT_IR].copy()

        # Banc GC
        banc = dprop_ok[
            (dprop_ok["Statut"] == STATUT_GC)
            & (dprop_ok.get("Slot", "").astype(str).str.strip() == SLOT_BANC)
        ].copy()

        # CE
        ce = dprop_ok[
            (dprop_ok["Statut"] == STATUT_CE)
        ].copy()

        def _pick(df_cand: pd.DataFrame) -> str | None:
            if df_cand is None or df_cand.empty:
                return None

            tmp = df_cand.copy()
            tmp["Pos"] = tmp.get("Pos", "F").apply(normalize_pos)
            tmp["Salaire"] = pd.to_numeric(tmp.get("Salaire", 0), errors="coerce").fillna(0).astype(int)

            same = tmp[tmp["Pos"] == injured_pos_].copy()
            pool = same if not same.empty else tmp

            pool["_posk"] = pool["Pos"].apply(pos_sort_key)
            pool = pool.sort_values(
                by=["_posk", "Salaire", "Joueur"],
                ascending=[True, False, True],
                kind="mergesort",
            )

            j = str(pool.iloc[0].get("Joueur", "")).strip()
            return j if j else None

        # 1) Banc -> Actif (immédiat)
        pick = _pick(banc)
        if pick:
            ok = apply_move_with_history(
                owner_,
                pick,
                STATUT_GC,
                SLOT_ACTIF,
                "AUTO REMPLACEMENT — Banc → Actif (blessure)",
            )
            return bool(ok)

        # 2) CE -> Actif (immédiat dans le remplacement auto)
        pick = _pick(ce)
        if pick:
            ok = apply_move_with_history(
                owner_,
                pick,
                STATUT_GC,
                SLOT_ACTIF,
                "AUTO REMPLACEMENT — CE → Actif (blessure)",
            )
            return bool(ok)

        return False

    css = """
    <style>
      .dlg-title{font-weight:1000;font-size:16px;line-height:1.1}
      .dlg-sub{opacity:.75;font-weight:800;font-size:12px;margin-top:2px}
      .pill{display:inline-block;padding:2px 10px;border-radius:999px;
            background:rgba(255,255,255,.08);
            border:1px solid rgba(255,255,255,.12);
            font-weight:900;font-size:12px}
    </style>
    """

    @st.dialog(f"Déplacement — {joueur}", width="small")
    def _dlg():
        st.markdown(css, unsafe_allow_html=True)
        st.markdown(
            f"<div class='dlg-title'>{html.escape(owner)} • {html.escape(joueur)}</div>"
            f"<div class='dlg-sub'>{html.escape(cur_statut)}"
            f"{(' / ' + html.escape(cur_slot)) if cur_slot else ''}"
            f" • {html.escape(cur_pos)} • {html.escape(cur_team)} • {money(cur_sal)}</div>",
            unsafe_allow_html=True,
        )
        st.divider()

        # 1) Type
        reason = st.radio(
            "Type de changement",
            ["Changement demi-mois", "Blessure"],
            horizontal=True,
            key=f"mv_reason_{owner}_{joueur}_{nonce}",
        )

        st.divider()

        # 2) Destination (mapping AVEC TES constantes)
        destinations = [
            ("🟢 Actif", (STATUT_GC, SLOT_ACTIF)),
            ("🟡 Banc", (STATUT_GC, SLOT_BANC)),
            ("🔵 Mineur", (STATUT_CE, "")),
            ("🩹 Blessé (IR)", (cur_statut, SLOT_IR)),
        ]

        current = (cur_statut, cur_slot or "")
        destinations = [d for d in destinations if d[1] != current]

        labels = [d[0] for d in destinations]
        mapping = {d[0]: d[1] for d in destinations}

        choice = st.radio(
            "Destination",
            labels,
            label_visibility="collapsed",
            key=f"dest_{owner}_{joueur}_{nonce}",
        )
        to_statut, to_slot = mapping[choice]

        # 3) Effet exact (DATE + HEURE locale)
        now = datetime.now(TZ_TOR)
        eff_dt = _effective_date(reason, cur_statut, cur_slot, to_statut, to_slot)

        # Sécurité : si à quelques ms près ça doit être immédiat, on le traite immédiat
        immediate = (eff_dt <= (now + timedelta(seconds=1)))

        if immediate:
            hint = "immédiat"
        else:
            hint = eff_dt.strftime("effectif le %Y-%m-%d %H:%M")

        st.markdown(f"<span class='pill'>⏱️ {hint}</span>", unsafe_allow_html=True)
        st.divider()

        def _schedule_move(note: str):
            _init_pending_moves()
            st.session_state["pending_moves"].append({
                "owner": owner,
                "joueur": joueur,
                "to_statut": to_statut,
                "to_slot": to_slot,
                "reason": reason,
                "note": note,
                "effective_at": eff_dt.isoformat(timespec="seconds"),
                "created_at": now.isoformat(timespec="seconds"),
            })

        c1, c2 = st.columns(2)

        if c1.button("✅ Confirmer", type="primary", use_container_width=True, key=f"ok_{owner}_{joueur}_{nonce}"):

            note = f"{reason} — {cur_statut}/{cur_slot or '-'} → {to_statut}/{to_slot or '-'}"

            # IMMÉDIAT
            if immediate:
                ok = apply_move_with_history(owner, joueur, to_statut, to_slot, note)
                if ok:
                    # ✅ Auto-remplacement si GC ACTIF -> IR
                    if cur_statut == STATUT_GC and cur_slot == SLOT_ACTIF and to_slot == SLOT_IR:
                        rep_ok = _auto_replace_injured(owner, cur_pos)
                        if rep_ok:
                            st.toast("🩹 Remplacement automatique effectué", icon="🩹")
                        else:
                            st.toast("⚠️ Aucun remplaçant disponible (Banc/CE)", icon="⚠️")

                    st.toast("✅ Déplacement effectué", icon="✅")
                    _close()
                    do_rerun()
                else:
                    st.error(st.session_state.get("last_move_error") or "Déplacement refusé.")

            # PROGRAMMÉ
            else:
                _schedule_move(note)
                st.toast(f"🕒 Déplacement programmé ({hint})", icon="🕒")
                _close()
                do_rerun()

        if c2.button("✖️ Annuler", use_container_width=True, key=f"cancel_{owner}_{joueur}_{nonce}"):
            _close()
            do_rerun()

    _dlg()






# =====================================================
# DIALOG — Preview Alignement Grand Club (GC)
# =====================================================
def open_gc_preview_dialog():
    if not st.session_state.get("gc_preview_open"):
        return

    owner = str(get_selected_team() or "").strip()

    df0 = st.session_state.get("data", pd.DataFrame(columns=REQUIRED_COLS))
    df0 = clean_data(df0) if isinstance(df0, pd.DataFrame) else pd.DataFrame(columns=REQUIRED_COLS)

    dprop = df0[df0.get("Propriétaire", "").astype(str).str.strip().eq(owner)].copy() if (not df0.empty and owner) else pd.DataFrame()

    # Enlève IR pour le preview GC (tu peux enlever ce filtre si tu veux inclure IR)
    if not dprop.empty and "Slot" in dprop.columns:
        dprop = dprop[dprop.get("Slot", "") != SLOT_IR].copy()

    gc_all = dprop[dprop.get("Statut", "") == STATUT_GC].copy() if not dprop.empty else pd.DataFrame()

    cap_gc = int(st.session_state.get("PLAFOND_GC", 0) or 0)
    used_gc = int(gc_all["Salaire"].sum()) if (not gc_all.empty and "Salaire" in gc_all.columns) else 0
    remain_gc = cap_gc - used_gc

    @st.dialog(f"👀 Alignement GC — {owner or 'Équipe'}", width="large")
    def _dlg():
        st.caption("Prévisualisation rapide du Grand Club (GC).")

        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("Total GC", money(used_gc))
        with c2:
            st.metric("Plafond GC", money(cap_gc))
        with c3:
            if used_gc > cap_gc:
                st.error(f"Non conforme — dépassement: {money(used_gc - cap_gc)}")
            else:
                st.success(f"Conforme — reste: {money(remain_gc)}")

        if gc_all.empty:
            st.info("Aucun joueur GC pour cette équipe.")
        else:
            # ✅ Pos complètement à gauche
            show_cols = [c for c in ["Pos", "Joueur", "Equipe", "Slot", "Salaire"] if c in gc_all.columns]
            df_show = gc_all[show_cols].copy()

            if "Salaire" in df_show.columns:
                df_show["Salaire"] = df_show["Salaire"].apply(lambda x: money(int(x) if str(x).strip() else 0))

            st.dataframe(df_show, use_container_width=True, hide_index=True)

        if st.button("OK", use_container_width=True, key="gc_preview_ok"):
            st.session_state["gc_preview_open"] = False
            do_rerun()

    _dlg()



# =====================================================
# PLAFONDS builder + Tableau UI
# =====================================================
def rebuild_plafonds(df: pd.DataFrame) -> pd.DataFrame:
    cap_gc = int(st.session_state.get("PLAFOND_GC", 95_500_000) or 0)
    cap_ce = int(st.session_state.get("PLAFOND_CE", 47_750_000) or 0)

    teams_all = sorted(list(LOGOS.keys()))
    resume = []
    for team in teams_all:
        d = df[df["Propriétaire"].astype(str).str.strip().eq(team)].copy()
        if d.empty:
            total_gc = 0
            total_ce = 0
        else:
            total_gc = d[(d["Statut"] == STATUT_GC) & (d["Slot"] != SLOT_IR)]["Salaire"].sum()
            total_ce = d[(d["Statut"] == STATUT_CE) & (d["Slot"] != SLOT_IR)]["Salaire"].sum()

        resume.append(
            {
                "Propriétaire": team,
                "Logo": team_logo_path(team),
                "Total Grand Club": int(total_gc),
                "Montant Disponible GC": int(cap_gc - int(total_gc)),
                "Total Club École": int(total_ce),
                "Montant Disponible CE": int(cap_ce - int(total_ce)),
            }
        )
    return pd.DataFrame(resume)

def build_tableau_ui(plafonds: pd.DataFrame):
    selected = str(get_selected_team() or "").strip()

    if plafonds is None or not isinstance(plafonds, pd.DataFrame) or plafonds.empty:
        st.info("Aucune équipe configurée.")
        return

    view = plafonds.copy()
    cols = ["Propriétaire", "Total Grand Club", "Montant Disponible GC", "Total Club École", "Montant Disponible CE"]
    for c in cols:
        if c not in view.columns:
            view[c] = 0 if ("Total" in c or "Montant" in c) else "—"

    def _fmt_money(x):
        try:
            return money(int(float(x)))
        except Exception:
            return money(0)

    for c in ["Total Grand Club", "Montant Disponible GC", "Total Club École", "Montant Disponible CE"]:
        view[c] = view[c].apply(_fmt_money)

    css = """
    <style>
      .pms-wrap{ margin-top: 10px; border: 1px solid rgba(255,255,255,0.10); border-radius: 16px;
                overflow: hidden; background: rgba(255,255,255,0.02); }
      table.pms{ width: 100%; border-collapse: collapse; font-size: 14px; color: rgba(255,255,255,0.92);
                 font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif; }
      table.pms thead th{ text-align: left; padding: 11px 12px; background: rgba(255,255,255,0.06);
                         border-bottom: 1px solid rgba(255,255,255,0.10); font-weight: 900; letter-spacing: .2px;
                         color: rgba(255,255,255,0.88); }
      table.pms tbody td{ padding: 11px 12px; border-bottom: 1px solid rgba(255,255,255,0.06);
                         vertical-align: middle; font-weight: 650; }
      table.pms tbody tr{ transition: background 220ms ease, transform 220ms ease; }
      table.pms tbody tr:hover{ background: rgba(255,255,255,0.035); }
      tr.pms-selected{ background: rgba(34,197,94,0.16) !important; }
      tr.pms-selected td:first-child{ border-left: 5px solid rgba(34,197,94,0.85); }
      .cell-right{ text-align:right; white-space:nowrap; }
      .pms-check{ display:inline-block; margin-left: 10px; font-weight: 1000; color: rgba(34,197,94,0.95);
                 opacity: 0; transform: translateY(1px); animation: pmsFadeIn 280ms ease forwards; }
      @keyframes pmsFadeIn{ from { opacity: 0; transform: translateY(3px); } to { opacity: 1; transform: translateY(0px); } }
    </style>
    """

    rows = []
    for _, r in view[cols].iterrows():
        owner = str(r.get("Propriétaire", "")).strip()
        is_sel = bool(selected) and (owner == selected)
        tr_class = "pms-selected" if is_sel else ""
        check = "<span class='pms-check'>✓</span>" if is_sel else ""
        rows.append(
            f"""
            <tr class="{tr_class}">
              <td><b>{html.escape(owner)}</b>{check}</td>
              <td class="cell-right">{html.escape(str(r.get("Total Grand Club","")))}</td>
              <td class="cell-right">{html.escape(str(r.get("Montant Disponible GC","")))}</td>
              <td class="cell-right">{html.escape(str(r.get("Total Club École","")))}</td>
              <td class="cell-right">{html.escape(str(r.get("Montant Disponible CE","")))}</td>
            </tr>
            """
        )

    html_doc = f"""
    {css}
    <div class="pms-wrap">
      <table class="pms">
        <thead>
          <tr>
            <th>Propriétaire</th>
            <th style="text-align:right">Total GC</th>
            <th style="text-align:right">Reste GC</th>
            <th style="text-align:right">Total CE</th>
            <th style="text-align:right">Reste CE</th>
          </tr>
        </thead>
        <tbody>
          {''.join(rows)}
        </tbody>
      </table>
    </div>
    """

    if not selected:
        st.info("Choisis une équipe dans la barre latérale pour la surligner ici.")

    components.html(html_doc, height=360, scrolling=False)


# =====================================================
# LOAD DATA + HISTORY + PENDING MOVES (ORDER IS CRITICAL)
# =====================================================

# --- Saison (fallback sécurisé)
season = str(st.session_state.get("season") or "").strip()
if not season:
    season = saison_auto()
    st.session_state["season"] = season

# --- Paths
DATA_FILE = os.path.join(DATA_DIR, f"fantrax_{season}.csv")
HISTORY_FILE = os.path.join(DATA_DIR, f"history_{season}.csv")

st.session_state["DATA_FILE"] = DATA_FILE
st.session_state["HISTORY_FILE"] = HISTORY_FILE

# -----------------------------------------------------
# 1) LOAD ALIGNEMENT DATA (CSV → session_state)
# -----------------------------------------------------
if "data_season" not in st.session_state or st.session_state["data_season"] != season:

    if os.path.exists(DATA_FILE):
        try:
            df_loaded = pd.read_csv(DATA_FILE)
        except Exception:
            df_loaded = pd.DataFrame(columns=REQUIRED_COLS)
    else:
        df_loaded = pd.DataFrame(columns=REQUIRED_COLS)
        try:
            df_loaded.to_csv(DATA_FILE, index=False)
        except Exception:
            pass

    df_loaded = clean_data(df_loaded)
    st.session_state["data"] = df_loaded
    st.session_state["data_season"] = season

# -----------------------------------------------------
# 2) LOAD HISTORY (CSV → session_state)
# -----------------------------------------------------
if "history_season" not in st.session_state or st.session_state["history_season"] != season:
    st.session_state["history"] = load_history_file(HISTORY_FILE)
    st.session_state["history_season"] = season

# -----------------------------------------------------
# 3) PROCESS PENDING MOVES  ⬅️ IMPORTANT
#    (CE → Actif +3 jours, Actif → Banc +1 jour, etc.)
# -----------------------------------------------------
# ⚠️ DOIT être appelé APRÈS data + history chargés
process_pending_moves()

# -----------------------------------------------------
# 4) PLAYERS DATABASE (read-only)
# -----------------------------------------------------
players_db = load_players_db(PLAYERS_DB_FILE)
st.session_state["players_db"] = players_db

# -----------------------------------------------------
# 5) REBUILD PLAFONDS (toujours à partir des data finales)
# -----------------------------------------------------
df_final = st.session_state.get("data", pd.DataFrame(columns=REQUIRED_COLS))
df_final = clean_data(df_final)
st.session_state["data"] = df_final

plafonds = rebuild_plafonds(df_final)
st.session_state["plafonds"] = plafonds



# =====================================================
# SIDEBAR — Saison + Équipe + Plafonds + Mobile
# =====================================================
st.sidebar.header("📅 Saison")
saisons = ["2024-2025", "2025-2026", "2026-2027"]
auto = saison_auto()
if auto not in saisons:
    saisons.append(auto)
    saisons.sort()

season_pick = st.sidebar.selectbox("Saison", saisons, index=saisons.index(auto), key="sb_season_select")
st.session_state["season"] = season_pick
st.session_state["LOCKED"] = saison_verrouillee(season_pick)

# Mobile view
st.sidebar.checkbox("📱 Mode mobile", key="mobile_view")
if st.session_state.get("mobile_view", False):
    st.markdown(
        "<style>.block-container{padding-top:0.8rem !important; padding-left:0.8rem !important; padding-right:0.8rem !important;}</style>",
        unsafe_allow_html=True
    )

# Default caps
if "PLAFOND_GC" not in st.session_state:
    st.session_state["PLAFOND_GC"] = 95_500_000
if "PLAFOND_CE" not in st.session_state:
    st.session_state["PLAFOND_CE"] = 47_750_000

st.sidebar.divider()
st.sidebar.header("💰 Plafonds")
if st.sidebar.button("✏️ Modifier les plafonds"):
    st.session_state["edit_plafond"] = True

if st.session_state.get("edit_plafond"):
    st.session_state["PLAFOND_GC"] = st.sidebar.number_input(
        "Plafond Grand Club",
        value=int(st.session_state["PLAFOND_GC"]),
        step=500_000,
    )
    st.session_state["PLAFOND_CE"] = st.sidebar.number_input(
        "Plafond Club École",
        value=int(st.session_state["PLAFOND_CE"]),
        step=250_000,
    )

st.sidebar.metric("🏒 Plafond Grand Club", money(st.session_state["PLAFOND_GC"]))
st.sidebar.metric("🏫 Plafond Club École", money(st.session_state["PLAFOND_CE"]))

# Team picker
st.sidebar.divider()
st.sidebar.markdown("### 🏒 Équipes")
teams = list(LOGOS.keys())
cur = str(st.session_state.get("selected_team", "")).strip()
if cur not in teams and teams:
    cur = teams[0]

chosen = st.sidebar.selectbox(
    "Choisir une équipe",
    teams if teams else [""],
    index=(teams.index(cur) if cur in teams else 0),
    key="sb_team_select",
)

# ✅ SYNC — SOURCE DE VÉRITÉ
if chosen and str(chosen).strip():
    st.session_state["selected_team"] = str(chosen).strip()
    st.session_state["align_owner"] = str(chosen).strip()

logo_path = team_logo_path(get_selected_team())
if logo_path:
    st.sidebar.image(logo_path, use_container_width=True)

if st.sidebar.button("👀 Prévisualiser l’alignement GC", use_container_width=True, key="sb_preview_gc"):
    st.session_state["gc_preview_open"] = True
    st.session_state["active_tab"] = "🧾 Alignement"
    do_rerun()


# =====================================================
# NAV
# =====================================================
is_admin = _is_admin_whalers()

NAV_TABS = [
    "📊 Tableau",
    "🧾 Alignement",
    "👤 Joueurs",
    "🕘 Historique",
    "⚖️ Transactions",
]
if is_admin:
    NAV_TABS.append("🛠️ Gestion Admin")
NAV_TABS.append("🧠 Recommandations")

if "active_tab" not in st.session_state:
    st.session_state["active_tab"] = "📊 Tableau"
if st.session_state["active_tab"] not in NAV_TABS:
    st.session_state["active_tab"] = NAV_TABS[0]

active_tab = st.radio("", NAV_TABS, horizontal=True, key="active_tab")
st.divider()


# =====================================================
# Global scheduled moves + dialogs
# =====================================================
process_pending_moves()
open_gc_preview_dialog()


# =====================================================
# ROUTING PRINCIPAL — ONE SINGLE CHAIN
# =====================================================
if active_tab == "📊 Tableau":
    st.subheader("📊 Tableau — Masses salariales (toutes les équipes)")
    build_tableau_ui(st.session_state.get("plafonds"))

elif active_tab == "🧾 Alignement":
    st.subheader("🧾 Alignement")

    df = clean_data(st.session_state.get("data", pd.DataFrame(columns=REQUIRED_COLS)))
    st.session_state["data"] = df

    proprietaire = str(get_selected_team() or "").strip()
    if not proprietaire:
        st.info("Sélectionne une équipe dans le menu à gauche.")
        st.stop()

    dprop = df[df["Propriétaire"].astype(str).str.strip().eq(proprietaire)].copy()

    cap_gc = int(st.session_state.get("PLAFOND_GC", 0) or 0)
    cap_ce = int(st.session_state.get("PLAFOND_CE", 0) or 0)

    if dprop.empty:
        st.warning(f"Aucun alignement importé pour **{proprietaire}** (Admin → Import).")
        j1, j2 = st.columns(2)
        with j1: st.markdown(cap_bar_html(0, cap_gc, f"📊 Plafond GC — {proprietaire}"), unsafe_allow_html=True)
        with j2: st.markdown(cap_bar_html(0, cap_ce, f"📊 Plafond CE — {proprietaire}"), unsafe_allow_html=True)
        clear_move_ctx()
        st.stop()

    injured_all = dprop[dprop.get("Slot", "") == SLOT_IR].copy()
    dprop_ok = dprop[dprop.get("Slot", "") != SLOT_IR].copy()

    gc_all = dprop_ok[dprop_ok["Statut"] == STATUT_GC].copy()
    ce_all = dprop_ok[dprop_ok["Statut"] == STATUT_CE].copy()

    gc_actif = gc_all[gc_all.get("Slot", "") == SLOT_ACTIF].copy()
    gc_banc = gc_all[gc_all.get("Slot", "") == SLOT_BANC].copy()

    tmp = gc_actif.copy()
    tmp["Pos"] = tmp.get("Pos", "F").apply(normalize_pos)
    nb_F = int((tmp["Pos"] == "F").sum())
    nb_D = int((tmp["Pos"] == "D").sum())
    nb_G = int((tmp["Pos"] == "G").sum())

    used_gc = int(gc_all["Salaire"].sum()) if "Salaire" in gc_all.columns else 0
    used_ce = int(ce_all["Salaire"].sum()) if "Salaire" in ce_all.columns else 0
    remain_gc = cap_gc - used_gc
    remain_ce = cap_ce - used_ce

    j1, j2 = st.columns(2)
    with j1: st.markdown(cap_bar_html(used_gc, cap_gc, f"📊 Plafond GC — {proprietaire}"), unsafe_allow_html=True)
    with j2: st.markdown(cap_bar_html(used_ce, cap_ce, f"📊 Plafond CE — {proprietaire}"), unsafe_allow_html=True)

    def gm_metric(label: str, value: str):
        st.markdown(
            f"""
            <div style="text-align:left">
                <div style="font-size:12px;opacity:.75;font-weight:700">{html.escape(label)}</div>
                <div style="font-size:20px;font-weight:1000">{html.escape(str(value))}</div>
            </div>
            """,
            unsafe_allow_html=True
        )

    cols = st.columns(6)
    with cols[0]: gm_metric("Total GC", money(used_gc))
    with cols[1]: gm_metric("Reste GC", money(remain_gc))
    with cols[2]: gm_metric("Total CE", money(used_ce))
    with cols[3]: gm_metric("Reste CE", money(remain_ce))
    with cols[4]: gm_metric("Banc", str(len(gc_banc)))
    with cols[5]: gm_metric("IR", str(len(injured_all)))

    st.markdown(
        f"**Actifs** — F {_count_badge(nb_F, 12)} • D {_count_badge(nb_D, 6)} • G {_count_badge(nb_G, 2)}",
        unsafe_allow_html=True,
    )

    st.divider()

    popup_open = st.session_state.get("move_ctx") is not None
    if popup_open:
        st.caption("🔒 Sélection désactivée: un déplacement est en cours.")

    mobile_view = bool(st.session_state.get("mobile_view", False))

    def _render_gc_block():
        with st.container(border=True):
            st.markdown("### 🟢 Actifs (Grand Club)")
            if gc_actif.empty:
                st.info("Aucun joueur.")
            else:
                if not popup_open:
                    p = roster_click_list(gc_actif, proprietaire, "actifs")
                    if p:
                        set_move_ctx(proprietaire, p, "actifs"); do_rerun()
                else:
                    roster_click_list(gc_actif, proprietaire, "actifs_disabled")

    def _render_ce_block():
        with st.container(border=True):
            st.markdown("### 🔵 Mineur (Club École)")
            if ce_all.empty:
                st.info("Aucun joueur.")
            else:
                if not popup_open:
                    p = roster_click_list(ce_all, proprietaire, "min")
                    if p:
                        set_move_ctx(proprietaire, p, "min"); do_rerun()
                else:
                    roster_click_list(ce_all, proprietaire, "min_disabled")

    if mobile_view:
        _render_gc_block()
        st.divider()
        _render_ce_block()
    else:
        colA, colB = st.columns(2, gap="small")
        with colA: _render_gc_block()
        with colB: _render_ce_block()

    st.divider()

    with st.expander("🟡 Banc", expanded=True):
        if gc_banc.empty:
            st.info("Aucun joueur.")
        else:
            if not popup_open:
                p = roster_click_list(gc_banc, proprietaire, "banc")
                if p:
                    set_move_ctx(proprietaire, p, "banc"); do_rerun()
            else:
                roster_click_list(gc_banc, proprietaire, "banc_disabled")

    with st.expander("🩹 Joueurs Blessés (IR)", expanded=True):
        if injured_all.empty:
            st.info("Aucun joueur blessé.")
        else:
            if not popup_open:
                p_ir = roster_click_list(injured_all, proprietaire, "ir")
                if p_ir:
                    set_move_ctx(proprietaire, p_ir, "ir"); do_rerun()
            else:
                roster_click_list(injured_all, proprietaire, "ir_disabled")

    open_move_dialog()

elif active_tab == "👤 Joueurs":
    st.subheader("👤 Joueurs")
    st.caption("Aucun résultat tant qu’aucun filtre n’est rempli.")

    players_db = st.session_state.get("players_db")
    if players_db is None or not isinstance(players_db, pd.DataFrame) or players_db.empty:
        st.error("Impossible de charger la base joueurs.")
        st.caption(f"Chemin attendu : {PLAYERS_DB_FILE}")
        st.stop()

    df_db = players_db.copy()

    if "Player" not in df_db.columns:
        found = None
        for cand in ["Joueur", "Name", "Full Name", "fullname", "player"]:
            if cand in df_db.columns:
                found = cand
                break
        if found:
            df_db = df_db.rename(columns={found: "Player"})
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
        s = re.sub(r"[^\d]", "", s)
        return int(s) if s.isdigit() else 0

    def _money_space(v: int) -> str:
        try:
            return f"{int(v):,}".replace(",", " ") + " $"
        except Exception:
            return "0 $"

    def clear_j_name():
        st.session_state["j_name"] = ""

    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        a, b = st.columns([12, 1])
        with a:
            q_name = st.text_input("Nom / Prénom", placeholder="Ex: Jack Eichel", key="j_name")
        with b:
            st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            st.button("❌", key="j_name_clear", help="Effacer Nom / Prénom",
                      use_container_width=True, on_click=clear_j_name)

    with c2:
        if "Team" in df_db.columns:
            teams_db = sorted(df_db["Team"].dropna().astype(str).unique().tolist())
            options_team = ["Toutes"] + teams_db
            cur_team = st.session_state.get("j_team", "Toutes")
            if cur_team not in options_team:
                st.session_state["j_team"] = "Toutes"
            q_team = st.selectbox("Équipe", options_team, key="j_team")
        else:
            q_team = "Toutes"
            st.selectbox("Équipe", ["Toutes"], disabled=True, key="j_team_disabled")

    with c3:
        level_col = "Level" if "Level" in df_db.columns else None
        if level_col:
            levels = sorted(df_db[level_col].dropna().astype(str).unique().tolist())
            options_level = ["Tous"] + levels
            cur_level = st.session_state.get("j_level", "Tous")
            if cur_level not in options_level:
                st.session_state["j_level"] = "Tous"
            q_level = st.selectbox("Level (Contrat)", options_level, key="j_level")
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
        cap_apply = False
        cap_min = cap_max = 0
    else:
        df_db["_cap_int"] = df_db[cap_col].apply(_cap_to_int)
        cap_apply = st.checkbox("Activer le filtre Cap Hit", value=False, key="cap_apply")
        cap_min, cap_max = st.slider(
            "Plage Cap Hit",
            min_value=0,
            max_value=30_000_000,
            value=(0, 30_000_000),
            step=250_000,
            disabled=(not cap_apply),
            key="cap_slider",
        )
        st.caption(f"Plage sélectionnée : **{_money_space(cap_min)} → {_money_space(cap_max)}**")

    has_filter = bool(str(q_name).strip()) or q_team != "Toutes" or q_level != "Tous" or cap_apply
    if not has_filter:
        st.info("Entre au moins un filtre pour afficher les résultats.")
    else:
        dff = df_db.copy()
        if str(q_name).strip():
            dff = dff[dff["Player"].astype(str).str.contains(q_name, case=False, na=False)]
        if q_team != "Toutes" and "Team" in dff.columns:
            dff = dff[dff["Team"].astype(str) == q_team]
        if q_level != "Tous" and level_col:
            dff = dff[dff[level_col].astype(str) == q_level]
        if cap_col and cap_apply:
            dff = dff[(dff["_cap_int"] >= cap_min) & (dff["_cap_int"] <= cap_max)]

        if dff.empty:
            st.warning("Aucun joueur trouvé avec ces critères.")
        else:
            dff = dff.head(250).reset_index(drop=True)
            st.markdown("### Résultats")
            show_cols = [c for c in ["Player", "Team", "Position", cap_col, "Level"] if c and c in dff.columns]
            df_show = dff[show_cols].copy()

            if cap_col in df_show.columns:
                df_show[cap_col] = df_show[cap_col].apply(lambda x: _money_space(_cap_to_int(x)))
                df_show = df_show.rename(columns={cap_col: "Cap Hit"})

            for c in df_show.columns:
                df_show[c] = df_show[c].apply(_clean_intlike)

            st.dataframe(df_show, use_container_width=True, hide_index=True)

elif active_tab == "🕘 Historique":
    st.subheader("🕘 Historique des changements d’alignement")

    h = st.session_state.get("history")
    h = h.copy() if isinstance(h, pd.DataFrame) else _history_empty_df()

    if h.empty:
        st.info("Aucune entrée d’historique pour cette saison.")
        st.stop()

    h["timestamp_dt"] = h["timestamp"].apply(to_dt_local)
    h = h.sort_values("timestamp_dt", ascending=False, na_position="last")

    owners = ["Tous"] + sorted(h["proprietaire"].dropna().astype(str).str.strip().unique().tolist())
    owner_filter = st.selectbox("Filtrer par propriétaire", owners, key="hist_owner_filter")
    if owner_filter != "Tous":
        h = h[h["proprietaire"].astype(str).str.strip().eq(str(owner_filter).strip())]

    if h.empty:
        st.info("Aucune entrée pour ce propriétaire.")
        st.stop()

    h_show = h.copy()
    h_show["timestamp"] = h_show["timestamp_dt"].apply(format_date_fr)
    h_show = h_show.drop(columns=["timestamp_dt"])

    st.dataframe(h_show.head(500), use_container_width=True, hide_index=True)

elif active_tab == "⚖️ Transactions":
    st.subheader("⚖️ Transactions")
    st.caption("Vérifie si une transaction respecte le plafond GC / CE.")

    plafonds = st.session_state.get("plafonds")
    df = st.session_state.get("data")
    if df is None or df.empty or plafonds is None or plafonds.empty:
        st.info("Aucune donnée pour cette saison. Va dans 🛠️ Gestion Admin → Import.")
        st.stop()

    owners = sorted(plafonds["Propriétaire"].dropna().astype(str).unique().tolist())
    if not owners:
        st.info("Aucun propriétaire trouvé. Va dans 🛠️ Gestion Admin → Import.")
        st.stop()

    p = st.selectbox("Propriétaire", owners, key="tx_owner")
    salaire = st.number_input("Salaire du joueur", min_value=0, step=100_000, value=0, key="tx_salary")
    statut = st.radio("Statut", [STATUT_GC, STATUT_CE], key="tx_statut", horizontal=True)

    ligne_df = plafonds[plafonds["Propriétaire"].astype(str) == str(p)]
    if ligne_df.empty:
        st.error("Propriétaire introuvable dans les plafonds.")
        st.stop()

    ligne = ligne_df.iloc[0]
    reste = int(ligne["Montant Disponible GC"]) if statut == STATUT_GC else int(ligne["Montant Disponible CE"])
    st.metric("Montant disponible", money(reste))

    if int(salaire) > int(reste):
        st.error("🚨 Dépassement du plafond")
    else:
        st.success("✅ Transaction valide")

elif active_tab == "🛠️ Gestion Admin":
    if not is_admin:
        st.warning("Accès admin requis.")
        st.stop()

    st.subheader("🛠️ Gestion Admin")
    st.markdown("### 📥 Import (multi-équipes)")

    manifest = load_init_manifest() or {}
    if "fantrax_by_team" not in manifest:
        manifest["fantrax_by_team"] = {}

    teams = sorted(list(LOGOS.keys())) or ["Whalers"]
    default_owner = get_selected_team().strip() or teams[0]
    if default_owner not in teams:
        default_owner = teams[0]

    chosen_owner = st.selectbox(
        "Importer l'alignement dans quelle équipe ?",
        teams,
        index=teams.index(default_owner),
        key="admin_import_team_pick",
    )

    clear_team_before = st.checkbox(
        f"Vider l’alignement de {chosen_owner} avant import",
        value=True,
        help="Recommandé si tu réimportes la même équipe.",
        key="admin_clear_team_before",
    )

    u_nonce = int(st.session_state.get("uploader_nonce", 0))
    c_init1, c_init2 = st.columns(2)
    with c_init1:
        init_align = st.file_uploader(
            "CSV — Alignement (Fantrax)",
            type=["csv", "txt"],
            key=f"admin_import_align__{season_pick}__{chosen_owner}__{u_nonce}",
        )
    with c_init2:
        init_hist = st.file_uploader(
            "CSV — Historique (optionnel)",
            type=["csv", "txt"],
            key=f"admin_import_hist__{season_pick}__{chosen_owner}__{u_nonce}",
        )

    c_btn1, c_btn2 = st.columns([1, 1])

    with c_btn1:
        if st.button("👀 Prévisualiser", use_container_width=True, key="admin_preview_import"):
            if init_align is None:
                st.warning("Choisis un fichier CSV alignement avant de prévisualiser.")
            else:
                try:
                    buf = io.BytesIO(init_align.getbuffer())
                    buf.name = init_align.name
                    df_import = parse_fantrax(buf)
                    df_import = ensure_owner_column(df_import, fallback_owner=chosen_owner)
                    df_import["Propriétaire"] = str(chosen_owner).strip()
                    df_import = clean_data(df_import)

                    st.session_state["init_preview_df"] = df_import
                    st.session_state["init_preview_owner"] = str(chosen_owner).strip()
                    st.session_state["init_preview_filename"] = init_align.name
                    st.success(f"✅ Preview prête — {len(df_import)} joueur(s) pour **{chosen_owner}**.")
                except Exception as e:
                    st.error(f"❌ Preview échouée : {type(e).__name__}: {e}")

    preview_df = st.session_state.get("init_preview_df")
    if isinstance(preview_df, pd.DataFrame) and not preview_df.empty:
        with st.expander("🔎 Aperçu (20 premières lignes)", expanded=True):
            st.dataframe(preview_df.head(20), use_container_width=True)

    with c_btn2:
        disabled_confirm = not (isinstance(preview_df, pd.DataFrame) and not preview_df.empty)
        if st.button("✅ Confirmer l'import", use_container_width=True, disabled=disabled_confirm, key="admin_confirm_import"):
            df_team = st.session_state.get("init_preview_df")
            owner_final = str(st.session_state.get("init_preview_owner", chosen_owner) or "").strip()
            filename_final = st.session_state.get("init_preview_filename", "") or (init_align.name if init_align else "")

            df_cur = clean_data(st.session_state.get("data", pd.DataFrame(columns=REQUIRED_COLS)))

            df_team = clean_data(df_team.copy())
            df_team["Propriétaire"] = owner_final
            df_team = clean_data(df_team)

            if clear_team_before:
                keep = df_cur[df_cur["Propriétaire"].astype(str).str.strip() != owner_final].copy()
                df_new = pd.concat([keep, df_team], ignore_index=True)
            else:
                df_new = pd.concat([df_cur, df_team], ignore_index=True)

            if {"Propriétaire", "Joueur"}.issubset(df_new.columns):
                df_new["Propriétaire"] = df_new["Propriétaire"].astype(str).str.strip()
                df_new["Joueur"] = df_new["Joueur"].astype(str).str.strip()
                df_new = df_new.drop_duplicates(subset=["Propriétaire", "Joueur"], keep="last")

            df_new = clean_data(df_new)
            st.session_state["data"] = df_new
            persist_data(df_new, season_pick)

            st.session_state["plafonds"] = rebuild_plafonds(df_new)

            st.session_state["selected_team"] = owner_final
            st.session_state["align_owner"] = owner_final
            clear_move_ctx()

            manifest["fantrax_by_team"][owner_final] = {
                "uploaded_name": filename_final,
                "season": season_pick,
                "saved_at": datetime.now(TZ_TOR).isoformat(timespec="seconds"),
                "team": owner_final,
            }
            save_init_manifest(manifest)

            if init_hist is not None:
                try:
                    h0 = pd.read_csv(io.BytesIO(init_hist.getbuffer()))
                    if "Propriétaire" in h0.columns and "proprietaire" not in h0.columns:
                        h0["proprietaire"] = h0["Propriétaire"]
                    if "Joueur" in h0.columns and "joueur" not in h0.columns:
                        h0["joueur"] = h0["Joueur"]
                    for c in _history_expected_cols():
                        if c not in h0.columns:
                            h0[c] = ""
                    h0 = h0[_history_expected_cols()].copy()
                    st.session_state["history"] = h0
                    persist_history(h0, season_pick)
                except Exception as e:
                    st.warning(f"⚠️ Historique initial non chargé : {type(e).__name__}: {e}")

            st.session_state["uploader_nonce"] = int(st.session_state.get("uploader_nonce", 0)) + 1
            st.session_state.pop("init_preview_df", None)
            st.session_state.pop("init_preview_owner", None)
            st.session_state.pop("init_preview_filename", None)

            st.success(f"✅ Import OK — seule l’équipe **{owner_final}** a été mise à jour.")
            do_rerun()

    st.divider()
    st.markdown("### 📌 Derniers imports par équipe")

    by_team = manifest.get("fantrax_by_team", {}) or {}
    if not by_team:
        st.caption("— Aucun import enregistré —")
    else:
        if "admin_imports_desc" not in st.session_state:
            st.session_state["admin_imports_desc"] = True

        c1, c2, _ = st.columns([0.12, 1, 3], vertical_alignment="center")
        with c1:
            icon = "⬇️" if st.session_state["admin_imports_desc"] else "⬆️"
            if st.button(icon, key="admin_imports_sort_btn", help="Changer l'ordre de tri"):
                st.session_state["admin_imports_desc"] = not st.session_state["admin_imports_desc"]
                do_rerun()
        with c2:
            st.caption("Tri par date")

        rows = []
        for team, info in by_team.items():
            rows.append(
                {
                    "Équipe": str(team).strip(),
                    "Fichier": str(info.get("uploaded_name", "") or "").strip(),
                    "Date": str(info.get("saved_at", "") or "").strip(),
                }
            )

        df_imports = pd.DataFrame(rows)
        df_imports["_dt"] = df_imports["Date"].apply(to_dt_local)

        df_imports = df_imports.sort_values(
            by="_dt",
            ascending=(not st.session_state["admin_imports_desc"]),
            na_position="last",
        )

        df_imports["Date"] = df_imports["_dt"].apply(format_date_fr)
        df_imports = df_imports.drop(columns=["_dt"]).reset_index(drop=True)

        st.dataframe(df_imports, use_container_width=True, hide_index=True)

elif active_tab == "🧠 Recommandations":
    st.subheader("🧠 Recommandations")
    st.caption("Recommandations automatiques basées sur les montants disponibles.")

    plafonds0 = st.session_state.get("plafonds")
    df = st.session_state.get("data")
    if df is None or df.empty or plafonds0 is None or plafonds0.empty:
        st.info("Aucune donnée pour cette saison. Va dans 🛠️ Gestion Admin → Import.")
        st.stop()

    for _, r in plafonds0.iterrows():
        dispo_gc = int(r.get("Montant Disponible GC", 0) or 0)
        dispo_ce = int(r.get("Montant Disponible CE", 0) or 0)
        owner = str(r.get("Propriétaire", "")).strip()

        if dispo_gc < 2_000_000:
            st.warning(f"{owner} : rétrogradation recommandée")
        if dispo_ce > 10_000_000:
            st.info(f"{owner} : rappel possible")

else:
    st.warning("Onglet inconnu")
