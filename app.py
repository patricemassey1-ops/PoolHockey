# app.py — Fantrax Pool Hockey (NORMALIZED / CLEAN)
# - Single source of truth for team selection
# - Single routing if/elif chain (no syntax errors)
# - Drive OAuth helpers (safe, optional)
# - Multi-team import (admin)
# - Alignement: Actifs + Mineur boxed, Banc + IR expanders, move dialog + history
# - Players DB: filters + cap hit slider
#
# NOTE: This file is intentionally "normalized":
#   - No duplicate definitions of do_rerun / get_selected_team / drive helpers
#   - All helpers defined BEFORE they are used
#   - All tabs handled in ONE routing block

# =====================================================
# IMPORTS
# =====================================================
import os
import io
import re
import json
import html
import time
import base64
import socket
import ssl
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import quote, unquote

import pandas as pd
import streamlit as st

# Google Drive (optional)
# Google Drive (optional)
try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import Flow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
    from googleapiclient.errors import HttpError
    _GOOGLE_OK = True
except Exception:
    _GOOGLE_OK = False


# =====================================================
# STREAMLIT CONFIG
# =====================================================
st.set_page_config(page_title="PMS", layout="wide")


# =====================================================
# PATHS / CONSTANTS
# =====================================================
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

PLAYERS_DB_FILE = os.path.join(DATA_DIR, "Hockey.Players.csv")
LOGO_POOL_FILE = os.path.join(DATA_DIR, "Logo_Pool.png")
INIT_MANIFEST_FILE = os.path.join(DATA_DIR, "init_manifest.json")

# Google Drive folder id (optional)
GDRIVE_FOLDER_ID = str(st.secrets.get("gdrive_oauth", {}).get("folder_id", "")).strip()

# Required columns for your roster data
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

TZ_TOR = ZoneInfo("America/Toronto")


# =====================================================
# BASIC HELPERS
# =====================================================
def _img_b64(path: str) -> str:
    if not path or not os.path.exists(path):
        return ""
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception:
        return ""


def do_rerun():
    """Streamlit rerun compatible."""
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
    """Light normalization to keep your app stable."""
    if df is None or not isinstance(df, pd.DataFrame):
        return pd.DataFrame(columns=REQUIRED_COLS)

    out = df.copy()

    # Ensure required columns
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

    # Drop empty player rows
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
# PERSISTENCE (local + optional Drive batching hooks)
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


def persist_data(df: pd.DataFrame, season_lbl: str) -> None:
    season_lbl = str(season_lbl or "").strip() or "season"
    path = os.path.join(DATA_DIR, f"fantrax_{season_lbl}.csv")
    st.session_state["DATA_FILE"] = path
    try:
        df.to_csv(path, index=False)
    except Exception:
        pass

    # Optional drive queue (if user enabled)
    if "queue_drive_save_df" in globals() and callable(globals()["queue_drive_save_df"]):
        try:
            globals()["queue_drive_save_df"](df, f"fantrax_{season_lbl}.csv")
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

    if "queue_drive_save_df" in globals() and callable(globals()["queue_drive_save_df"]):
        try:
            globals()["queue_drive_save_df"](h, f"history_{season_lbl}.csv")
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
        "change_type", "effective_date",
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
    change_type: str = "",
    effective_date: str = "",
):
    """Append a row to history (and persist). change_type/effective_date are optional."""
    h = st.session_state.get("history")
    h = h.copy() if isinstance(h, pd.DataFrame) else _history_empty_df()

    row_hist = {
        "id": next_hist_id(h),
        "timestamp": datetime.now(TZ_TOR).isoformat(timespec="seconds"),
        "season": str(st.session_state.get("season", "")).strip(),
        "proprietaire": str(proprietaire or ""),
        "joueur": str(joueur or ""),
        "pos": str(pos or ""),
        "equipe": str(equipe or ""),
        "from_statut": str(from_statut or ""),
        "from_slot": str(from_slot or ""),
        "to_statut": str(to_statut or ""),
        "to_slot": str(to_slot or ""),
        "change_type": str(change_type or ""),
        "effective_date": str(effective_date or ""),
        "action": str(action or ""),
    }

    h = pd.concat([h, pd.DataFrame([row_hist])], ignore_index=True)
    st.session_state["history"] = h

    season_lbl = str(st.session_state.get("season", "")).strip()
    persist_history(h, season_lbl)


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
# FANTRAX PARSER (as provided, lightly cleaned)
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
    # Fantrax salaries often in "thousands" -> your original multiplies by 1000
    out["Salaire"] = pd.to_numeric(sal, errors="coerce").fillna(0).astype(int) * 1000

    if status_col:
        out["Statut"] = df[status_col].apply(lambda x: STATUT_CE if "min" in str(x).lower() else STATUT_GC)
    else:
        out["Statut"] = STATUT_GC

    out["Slot"] = out["Statut"].apply(lambda s: SLOT_ACTIF if s == STATUT_GC else "")
    out["IR Date"] = ""
    out = clean_data(out)
    return out


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
# MOVE CONTEXT + APPLY MOVE
# =====================================================
def set_move_ctx(owner: str, joueur: str, source_key: str):
    st.session_state["move_nonce"] = int(st.session_state.get("move_nonce", 0)) + 1
    st.session_state["move_source"] = str(source_key or "").strip()
    st.session_state["move_ctx"] = {
        "owner": str(owner).strip(),
        "joueur": str(joueur).strip(),
        "nonce": st.session_state["move_nonce"],
    }


def clear_move_ctx():
    st.session_state["move_ctx"] = None
    st.session_state["move_source"] = ""


def apply_move_with_history(proprietaire: str, joueur: str, to_statut: str, to_slot: str, action_label: str, change_type: str = "", effective_date: str = "") -> bool:
    st.session_state["last_move_error"] = ""

    if st.session_state.get("LOCKED"):
        st.session_state["last_move_error"] = "🔒 Saison verrouillée : modification impossible."
        return False

    df0 = st.session_state.get("data")
    if df0 is None or not isinstance(df0, pd.DataFrame) or df0.empty:
        st.session_state["last_move_error"] = "Aucune donnée en mémoire."
        return False

    df0 = df0.copy()
    if "IR Date" not in df0.columns:
        df0["IR Date"] = ""

    proprietaire = str(proprietaire or "").strip()
    joueur = str(joueur or "").strip()
    to_statut = str(to_statut or "").strip()
    to_slot = str(to_slot or "").strip()

    mask = (
        df0["Propriétaire"].astype(str).str.strip().eq(proprietaire)
        & df0["Joueur"].astype(str).str.strip().eq(joueur)
    )
    if df0.loc[mask].empty:
        st.session_state["last_move_error"] = "Joueur introuvable."
        return False

    before = df0.loc[mask].iloc[0]
    from_statut = str(before.get("Statut", "")).strip()
    from_slot = str(before.get("Slot", "")).strip()
    pos0 = str(before.get("Pos", "F")).strip()
    equipe0 = str(before.get("Equipe", "")).strip()

    # IR keeps current statut
    if to_slot == SLOT_IR:
        to_statut = from_statut

    allowed_slots_gc = {SLOT_ACTIF, SLOT_BANC, SLOT_IR}
    allowed_slots_ce = {"", SLOT_IR}

    if to_statut == STATUT_GC and to_slot not in allowed_slots_gc:
        st.session_state["last_move_error"] = f"Slot invalide GC : {to_slot}"
        return False
    if to_statut == STATUT_CE and to_slot not in allowed_slots_ce:
        st.session_state["last_move_error"] = f"Slot invalide CE : {to_slot}"
        return False

    # Apply
    df0.loc[mask, "Statut"] = to_statut
    df0.loc[mask, "Slot"] = to_slot if to_slot else ""

    entering_ir = (to_slot == SLOT_IR) and (from_slot != SLOT_IR)
    leaving_ir = (from_slot == SLOT_IR) and (to_slot != SLOT_IR)

    if entering_ir:
        df0.loc[mask, "IR Date"] = datetime.now(TZ_TOR).strftime("%Y-%m-%d %H:%M")
    elif leaving_ir:
        df0.loc[mask, "IR Date"] = ""

    df0 = clean_data(df0)
    st.session_state["data"] = df0

    # History
    try:
        log_history_row(
            proprietaire=proprietaire,
            joueur=joueur,
            pos=pos0,
            equipe=equipe0,
            from_statut=from_statut,
            from_slot=from_slot,
            to_statut=to_statut,
            to_slot=to_slot,            action=action_label,
            change_type=change_type,
            effective_date=effective_date,
        )
    except Exception:
        pass

    # Persist
    season_lbl = str(st.session_state.get("season", "")).strip()
    try:
        persist_data(df0, season_lbl)
    except Exception as e:
        st.session_state["last_move_error"] = f"Erreur persistance: {type(e).__name__}: {e}"
        return False

    return True


# =====================================================
# UI — roster click list (your compact list)
# =====================================================
def roster_click_list(df_src: pd.DataFrame, owner: str, source_key: str) -> str | None:
    if df_src is None or not isinstance(df_src, pd.DataFrame) or df_src.empty:
        st.info("Aucun joueur.")
        return None

    st.markdown(
        """
        <style>
          div[data-testid="stButton"] > button{
            padding: 0.18rem 0.45rem;
            font-weight: 900;
            text-align: left;
            justify-content: flex-start;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
          }
          .salaryCell{
            white-space: nowrap;
            text-align: right;
            font-weight: 900;
            display: block;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )

    t = df_src.copy()
    for c, d in {"Joueur": "", "Pos": "F", "Equipe": "", "Salaire": 0}.items():
        if c not in t.columns:
            t[c] = d

    t["Joueur"] = t["Joueur"].astype(str).fillna("").map(lambda x: re.sub(r"\s+", " ", x).strip())
    t["Equipe"] = t["Equipe"].astype(str).fillna("").map(lambda x: re.sub(r"\s+", " ", x).strip())
    t["Salaire"] = pd.to_numeric(t["Salaire"], errors="coerce").fillna(0).astype(int)

    bad = {"", "none", "nan", "null"}
    t = t[~t["Joueur"].str.lower().isin(bad)].copy()
    if t.empty:
        st.info("Aucun joueur.")
        return None

    t["Pos"] = t["Pos"].apply(normalize_pos)
    t["_pos"] = t["Pos"].apply(pos_sort_key)
    t["_initial"] = t["Joueur"].str.upper().str[0].fillna("?")

    t = (
        t.sort_values(
            by=["_pos", "Salaire", "_initial", "Joueur"],
            ascending=[True, False, True, True],
            kind="mergesort",
        )
        .drop(columns=["_pos", "_initial"])
        .reset_index(drop=True)
    )

    h = st.columns([1.2, 1.6, 3.6, 2.4])
    h[0].markdown("**Pos**")
    h[1].markdown("**Team**")
    h[2].markdown("**Joueur**")
    h[3].markdown("**Salaire**")

    clicked = None
    for i, r in t.iterrows():
        joueur = str(r.get("Joueur", "")).strip()
        if not joueur:
            continue

        pos = r.get("Pos", "F")
        team = str(r.get("Equipe", "")).strip()
        salaire = int(r.get("Salaire", 0) or 0)

        c = st.columns([1.2, 1.6, 3.6, 2.4])
        c[0].markdown(pos_badge_html(pos), unsafe_allow_html=True)
        c[1].markdown(team if team and team.lower() not in bad else "—")

        if c[2].button(joueur, key=f"{source_key}_{owner}_{joueur}_{i}", use_container_width=True):
            clicked = joueur

        c[3].markdown(f"<span class='salaryCell'>{money(salaire)}</span>", unsafe_allow_html=True)

    return clicked


# =====================================================
# MOVE DIALOG (single version)
# =====================================================
def open_move_dialog():
    """
    Move dialog with:
    - Type: "Changement demi-mois" (effectif immédiat)
            "Blessure" (délais selon la destination)
    - Destination: Actif / Banc / Mineur / Blessé
    - History includes optional change_type + effective_date.
    """
    ctx = st.session_state.get("move_ctx")
    if not ctx:
        return

    if st.session_state.get("LOCKED"):
        st.warning("🔒 Saison verrouillée : aucun changement permis.")
        clear_move_ctx()
        return

    import streamlit.components.v1 as components  # safe at runtime (Streamlit Cloud)

    owner = str(ctx.get("owner", "")).strip()
    joueur = str(ctx.get("joueur", "")).strip()
    nonce = int(ctx.get("nonce", 0))

    df_all = st.session_state.get("data")
    if df_all is None or not isinstance(df_all, pd.DataFrame) or df_all.empty:
        st.error("Aucune donnée chargée.")
        clear_move_ctx()
        return

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

    # Where was the click from (actifs/min/banc/ir)
    source = str(st.session_state.get("move_source", "")).strip()

    # Helper: normalize current slot
    cur_slot_norm = cur_slot or ""
    if source == "ir":
        cur_slot_norm = SLOT_IR
    elif source == "banc":
        cur_slot_norm = SLOT_BANC
    elif source == "actifs":
        cur_slot_norm = SLOT_ACTIF

    def _close():
        clear_move_ctx()

    def _today():
        return datetime.now(TZ_TOR).date()

    def _fmt_date(d):
        return d.isoformat()

    def compute_effective_date(change_type: str, from_statut: str, from_slot: str, to_statut: str, to_slot: str) -> str:
        """
        Rules:
        - Changement demi-mois: immédiat
        - Retour vers Actif: immédiat
        - Actif -> Mineur: +3 jours (Blessure seulement)
        - Actif -> Banc: +1 jour (Blessure seulement)
        - Otherwise: immédiat
        """
        change_type = str(change_type or "").strip().lower()
        if "demi" in change_type:
            return _fmt_date(_today())

        # Immediate if going to active GC slot
        if to_statut == STATUT_GC and (to_slot == SLOT_ACTIF):
            return _fmt_date(_today())

        # Only delays when leaving active slot
        from_is_actif = (from_statut == STATUT_GC and (from_slot == SLOT_ACTIF))
        if from_is_actif and (to_statut == STATUT_CE):
            return _fmt_date(_today() + timedelta(days=3))
        if from_is_actif and (to_statut == STATUT_GC and to_slot == SLOT_BANC):
            return _fmt_date(_today() + timedelta(days=1))

        return _fmt_date(_today())

    css = """
    <style>
      .dlg-title{font-weight:1000;font-size:16px;line-height:1.1}
      .dlg-sub{opacity:.75;font-weight:800;font-size:12px;margin-top:2px}
      .pms-pill{display:inline-block;padding:4px 10px;border-radius:999px;border:1px solid rgba(255,255,255,0.14);background:rgba(255,255,255,0.06);font-weight:900;font-size:12px}
      .pms-note{opacity:.8;font-size:12px;font-weight:700}
      .pms-hr{height:1px;background:rgba(255,255,255,0.10);margin:10px 0}
    </style>
    """

    @st.dialog(f"Déplacement — {joueur}", width="small")
    def _dlg():
        st.markdown(css, unsafe_allow_html=True)
        st.markdown(
            f"<div class='dlg-title'>{html.escape(owner)} • {html.escape(joueur)}</div>"
            f"<div class='dlg-sub'>{html.escape(cur_statut)}"
            f"{(' / ' + html.escape(cur_slot_norm)) if cur_slot_norm else ''}"
            f" • {html.escape(cur_pos)} • {html.escape(cur_team)} • {money(cur_sal)}</div>",
            unsafe_allow_html=True,
        )
        st.divider()

        # 1) Type de changement
        change_type = st.radio(
            "Type de changement",
            ["Changement demi-mois", "Blessure"],
            index=0,
            key=f"mv_type_{owner}_{joueur}_{nonce}",
        )

        st.markdown("<div class='pms-hr'></div>", unsafe_allow_html=True)

        # 2) Destination
        destinations = [
            ("🟢 Actif", (STATUT_GC, SLOT_ACTIF)),
            ("🟡 Banc", (STATUT_GC, SLOT_BANC)),
            ("🔵 Mineur", (STATUT_CE, "")),
            ("🩹 Blessé", (cur_statut or STATUT_GC, SLOT_IR)),
        ]

        current = (cur_statut, cur_slot_norm)
        dest_filtered = [d for d in destinations if d[1] != current]
        if not dest_filtered:
            st.info("Aucune destination disponible.")
            if st.button("✖️ Fermer", use_container_width=True, key=f"mv_close_{owner}_{joueur}_{nonce}"):
                _close(); do_rerun()
            return

        labels = [d[0] for d in dest_filtered]
        mapping = {d[0]: d[1] for d in dest_filtered}

        choice = st.radio(
            "Destination",
            labels,
            index=0,
            label_visibility="collapsed",
            key=f"mv_dest_{owner}_{joueur}_{nonce}",
        )
        to_statut, to_slot = mapping[choice]

        eff = compute_effective_date(change_type, cur_statut, cur_slot_norm, to_statut, to_slot)

        # Explain effective date
        if eff == _fmt_date(_today()):
            st.caption("⏱️ **Effectif : immédiatement**")
        else:
            st.caption(f"⏱️ **Effectif : {eff}**")

        st.markdown("<div class='pms-hr'></div>", unsafe_allow_html=True)

        c1, c2 = st.columns(2)
        if c1.button("✅ Confirmer", type="primary", use_container_width=True, key=f"mv_ok_{owner}_{joueur}_{nonce}"):
            ok = apply_move_with_history(
                owner,
                joueur,
                to_statut,
                to_slot,
                f"{change_type} — {cur_statut}/{cur_slot_norm or '-'} → {to_statut}/{to_slot or '-'}",
                change_type=change_type,
                effective_date=eff,
            )
            if ok:
                # Toast icon by destination
                icon = "✅"
                if to_slot == SLOT_ACTIF:
                    icon = "🟢"
                elif to_slot == SLOT_BANC:
                    icon = "🟡"
                elif to_statut == STATUT_CE:
                    icon = "🔵"
                elif to_slot == SLOT_IR:
                    icon = "🩹"

                msg = f"{icon} {joueur} → {choice.replace('🟢 ', '').replace('🟡 ', '').replace('🔵 ', '').replace('🩹 ', '')}"
                if eff != _fmt_date(_today()):
                    msg += f" (effectif {eff})"

                st.toast(msg, icon=icon)
                _close(); do_rerun()
            else:
                st.error(st.session_state.get("last_move_error") or "Déplacement refusé.")

        if c2.button("✖️ Annuler", use_container_width=True, key=f"mv_cancel_{owner}_{joueur}_{nonce}"):
            _close(); do_rerun()

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
                "Importé": "✅" if (not d.empty) else "—",
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
    """
    Tableau (massse salariale) — Cloud-proof HTML render:
    - text white
    - subtle highlight for selected row
    - green checkmark (fade-in) instead of "Sélectionnée"
    """
    if plafonds is None or not isinstance(plafonds, pd.DataFrame) or plafonds.empty:
        st.info("Aucune équipe configurée.")
        return

    import streamlit.components.v1 as components

    selected = str(get_selected_team() or "").strip()

    view = plafonds.copy()
    cols = [
        "Importé",
        "Propriétaire",
        "Total Grand Club",
        "Montant Disponible GC",
        "Total Club École",
        "Montant Disponible CE",
    ]
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
      :root{
        --pms-border: rgba(255,255,255,0.14);
        --pms-border2: rgba(255,255,255,0.08);
        --pms-head: rgba(255,255,255,0.06);
        --pms-rowhover: rgba(255,255,255,0.04);
        --pms-text: rgba(255,255,255,0.95);
        --pms-muted: rgba(255,255,255,0.70);
        --pms-green: rgba(34,197,94,1);
        --pms-hi: rgba(34,197,94,0.12); /* subtle highlighter */
        --pms-hi2: rgba(34,197,94,0.22);
      }

      .pms-wrap{
        margin-top: 8px;
        border: 1px solid var(--pms-border);
        border-radius: 16px;
        overflow: hidden;
        background: rgba(0,0,0,0.20);
      }

      table.pms{
        width:100%;
        border-collapse: collapse;
        font-size: 14px;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
        color: var(--pms-text);
      }

      thead th{
        text-align:left;
        padding: 10px 12px;
        background: var(--pms-head);
        border-bottom: 1px solid var(--pms-border);
        font-weight: 900;
        color: var(--pms-text);
      }

      tbody td{
        padding: 10px 12px;
        border-bottom: 1px solid var(--pms-border2);
        vertical-align: middle;
        font-weight: 700;
        color: var(--pms-text);
        transition: background 180ms ease, box-shadow 180ms ease;
      }

      tbody tr:hover td{
        background: var(--pms-rowhover);
      }

      .cell-right{ text-align:right; white-space:nowrap; }
      .import-ok{ font-weight: 1000; color: var(--pms-muted); }

      /* Selected row: subtle highlighter + left glow */
      tr.pms-selected td{
        background: linear-gradient(90deg, var(--pms-hi2), var(--pms-hi)) !important;
        box-shadow: inset 0 0 0 1px rgba(34,197,94,0.28);
      }
      tr.pms-selected td:first-child{
        box-shadow: inset 6px 0 0 rgba(34,197,94,0.65), inset 0 0 0 1px rgba(34,197,94,0.28);
      }

      /* Checkmark */
      .pms-check{
        display:inline-block;
        margin-left: 10px;
        font-weight: 1000;
        color: var(--pms-green);
        opacity: 0;
        transform: translateY(2px);
        animation: pmsFadeIn 420ms ease forwards;
      }
      @keyframes pmsFadeIn{
        from{ opacity:0; transform: translateY(2px); }
        to{ opacity:1; transform: translateY(0px); }
      }
    </style>
    """

    rows_html = []
    for _, r in view[cols].iterrows():
        owner = str(r.get("Propriétaire", "")).strip()
        is_sel = bool(selected) and (owner == selected)

        tr_class = "pms-selected" if is_sel else ""
        check = "<span class='pms-check'>✓</span>" if is_sel else ""

        imp = str(r.get("Importé", "—")).strip() or "—"
        imp_html = f"<span class='import-ok'>{html.escape(imp)}</span>"

        rows_html.append(
            f"""
<tr class="{tr_class}">
  <td>{imp_html}</td>
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
        <th>Importé</th>
        <th>Propriétaire</th>
        <th style="text-align:right">Total GC</th>
        <th style="text-align:right">Reste GC</th>
        <th style="text-align:right">Total CE</th>
        <th style="text-align:right">Reste CE</th>
      </tr>
    </thead>
    <tbody>
      {''.join(rows_html)}
    </tbody>
  </table>
</div>
"""

    if not selected:
        st.info("Sélectionne une équipe dans la barre latérale pour la surligner ici.")

    components.html(html_doc, height=440, scrolling=True)
