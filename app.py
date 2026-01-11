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
import secrets
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
# THEME
#   (retiré: pas de Dark/Light)
# =====================================================


# =====================================================
# CSS — Micro-animations + Alertes visuelles + UI polish
#   ✅ coller UNE seule fois, au top du fichier
# =====================================================
st.markdown(
    """
    <style>
    /* =========================================
       ✨ Micro animations (douces)
       ========================================= */
    .fade-in { animation: fadeIn 180ms ease-out both; }
    @keyframes fadeIn {
        from { opacity: 0; transform: translateY(2px); }
        to   { opacity: 1; transform: translateY(0); }
    }

    .lift { transition: transform 120ms ease, box-shadow 120ms ease; }
    .lift:hover { transform: translateY(-1px); box-shadow: 0 6px 18px rgba(0,0,0,0.35); }

    .pulse-soft { animation: pulseSoft 1.6s ease-in-out infinite; }
    @keyframes pulseSoft {
        0%, 100% { box-shadow: 0 0 0 rgba(0,0,0,0); }
        50% { box-shadow: 0 0 0 6px rgba(34,197,94,0.06); }
    }

    .pulse-warn { animation: pulseWarn 1.8s ease-in-out infinite; }
    @keyframes pulseWarn {
        0%, 100% { box-shadow: 0 0 0 rgba(0,0,0,0); }
        50% { box-shadow: 0 0 0 7px rgba(245,158,11,0.10); }
    }

    .pulse-danger { animation: pulseDanger 1.7s ease-in-out infinite; }
    @keyframes pulseDanger {
        0%, 100% { box-shadow: 0 0 0 rgba(0,0,0,0); }
        50% { box-shadow: 0 0 0 7px rgba(239,68,68,0.10); }
    }

    /* =========================================
       🏷️ Pills / Badges (OK / Warning / Danger)
       ========================================= */
    .pill {
        display: inline-flex;
        align-items: center;
        gap: 0.45rem;
        padding: 0.24rem 0.55rem;
        border-radius: 999px;
        border: 1px solid #374151;
        background: #111827;
        color: #e5e7eb;
        font-size: 0.82rem;
        line-height: 1;
        white-space: nowrap;
        user-select: none;
        transition: transform 120ms ease, background 120ms ease, border-color 120ms ease;
    }
    .pill:hover { transform: translateY(-1px); }

    .pill .dot {
        width: 8px; height: 8px;
        border-radius: 999px;
        background: #6b7280;
    }

    .pill-ok     { border-color: rgba(34,197,94,0.35);  background: rgba(34,197,94,0.08); }
    .pill-ok .dot { background: #22c55e; }

    .pill-warn     { border-color: rgba(245,158,11,0.40); background: rgba(245,158,11,0.10); }
    .pill-warn .dot { background: #f59e0b; }

    .pill-danger     { border-color: rgba(239,68,68,0.45); background: rgba(239,68,68,0.10); }
    .pill-danger .dot { background: #ef4444; }

    /* =========================================
       🧾 Carte d’alerte (bande à gauche)
       ========================================= */
    .alert-card {
        border: 1px solid #1f2937;
        background: #111827;
        border-radius: 12px;
        padding: 0.65rem 0.8rem;
    }
    .alert-card.ok     { border-left: 4px solid #22c55e; }
    .alert-card.warn   { border-left: 4px solid #f59e0b; }
    .alert-card.danger { border-left: 4px solid #ef4444; }

    .muted { color: #9ca3af; font-size: 0.85rem; }

    /* =========================================
       🔝 NAV (radio horizontale) — actif/inactif clair
       ========================================= */
    div[role="radiogroup"] > label {
        background-color: transparent;
        padding: 0.4rem 0.8rem;
        border-radius: 8px;
        font-weight: 500;
        color: #9ca3af;
        transition: all 0.15s ease-in-out;
    }
    div[role="radiogroup"] > label:hover {
        background-color: #1f2937;
        color: #e5e7eb;
    }
    div[role="radiogroup"] > label[data-selected="true"] {
        background-color: #1f2937;
        color: #f9fafb;
        box-shadow: inset 0 -2px 0 #22c55e;
    }

    /* =========================================
       🔘 Boutons uniformes (global)
       ========================================= */
    button {
        background-color: #1f2937 !important;
        color: #f9fafb !important;
        border-radius: 10px !important;
        border: 1px solid #374151 !important;
        font-weight: 500;
        padding: 0.45rem 0.9rem !important;
        transition: all 0.15s ease-in-out;
    }
    button:hover { background-color: #374151 !important; transform: translateY(-1px); }
    button:active { transform: translateY(0); }

    button[kind="primary"] {
        background-color: #16a34a !important;
        border-color: #16a34a !important;
        color: white !important;
    }
    button[kind="primary"]:hover { background-color: #22c55e !important; }

    /* =========================================
       📊 Dataframe (si applicable)
       ========================================= */
    .stDataFrame tbody tr:hover { background-color: rgba(255,255,255,0.04); }
    .stDataFrame thead tr th {
        background-color: #020617 !important;
        color: #9ca3af !important;
        font-weight: 600;
    }
    </style>
    """,
    unsafe_allow_html=True
)

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
LOGO_POOL_FILE = next((os.path.join(DATA_DIR, n) for n in ["Logo_Pool.png","logo_pool.png","LOGO_POOL.png"] if os.path.exists(os.path.join(DATA_DIR, n))), os.path.join(DATA_DIR, "Logo_Pool.png"))
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

# =====================================================
# MAIN HEADER — Logo_Pool + 🏒 (gauche) + 🥅 (droite)
#   ✅ affiché après login (pas seulement sur l'écran mot de passe)
#   ✅ PAS de nouvelle injection CSS (on respecte tes règles d'or)
# =====================================================
# (header global retiré: logo uniquement sur écran mot de passe)

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


def parse_money(v) -> int:
    """Parse montants provenant d'inputs (ex: '3 000 000$', '3000000', 3000000)."""
    try:
        if v is None:
            return 0
        if isinstance(v, (int, float)):
            return int(v)
        s = str(v).strip()
        if not s:
            return 0
        # garder seulement les chiffres
        s2 = re.sub(r"[^0-9]", "", s)
        return int(s2) if s2.isdigit() else 0
    except Exception:
        return 0

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
# HELPERS UI — Pills + Alert cards (1 seule fois)
# =====================================================
def pill(label: str, value: str, level: str = "ok", pulse: bool = False):
    level_class = {"ok": "pill-ok", "warn": "pill-warn", "danger": "pill-danger"}.get(level, "pill-ok")
    pulse_class = {"ok": "pulse-soft", "warn": "pulse-warn", "danger": "pulse-danger"}.get(level, "")
    pulse_class = pulse_class if pulse else ""
    st.markdown(
        f"""
        <span class="pill {level_class} {pulse_class} fade-in">
            <span class="dot"></span>
            <b>{label}</b>
            <span class="muted">{value}</span>
        </span>
        """,
        unsafe_allow_html=True
    )

def alert_card(title: str, subtitle: str, level: str = "ok", pulse: bool = False):
    lvl = level if level in ("ok", "warn", "danger") else "ok"
    pulse_class = {"ok": "pulse-soft", "warn": "pulse-warn", "danger": "pulse-danger"}.get(lvl, "")
    pulse_class = pulse_class if pulse else ""
    st.markdown(
        f"""
        <div class="alert-card {lvl} {pulse_class} fade-in lift">
            <div style="font-weight:600; color:#f9fafb;">{title}</div>
            <div class="muted">{subtitle}</div>
        </div>
        """,
        unsafe_allow_html=True
    )

# =====================================================
# ALERTES — Cap GC/CE + IR + Toasts (1 seule fois)
#   Utilisation: show_status_alerts(...)
# =====================================================
def _level_for_cap(total: int, cap: int) -> str:
    if cap <= 0:
        return "ok"
    if total > cap:
        return "danger"
    reste = cap - total
    pct_reste = reste / cap if cap else 0
    if pct_reste < 0.05:
        return "warn"
    return "ok"

def show_status_alerts(
    *,
    total_gc: int, cap_gc: int,
    total_ce: int, cap_ce: int,
    ir_count: int = 0,
    toast: bool = False,
    context: str = ""
):
    # niveaux
    lvl_gc = _level_for_cap(total_gc, cap_gc)
    lvl_ce = _level_for_cap(total_ce, cap_ce)

    reste_gc = cap_gc - total_gc
    reste_ce = cap_ce - total_ce

    lvl_ir = "ok"
    if ir_count >= 3:
        lvl_ir = "danger"
    elif ir_count > 0:
        lvl_ir = "warn"

    # Pills en haut
    c1, c2, c3 = st.columns([2, 2, 1.4], vertical_alignment="center")
    with c1:
        pill("GC", f"{total_gc:,.0f} / {cap_gc:,.0f} $", level=lvl_gc, pulse=(lvl_gc != "ok"))
        st.write("")
        pill("Reste GC", f"{reste_gc:,.0f} $", level=("danger" if reste_gc < 0 else lvl_gc), pulse=(lvl_gc != "ok"))
    with c2:
        pill("CE", f"{total_ce:,.0f} / {cap_ce:,.0f} $", level=lvl_ce, pulse=(lvl_ce != "ok"))
        st.write("")
        pill("Reste CE", f"{reste_ce:,.0f} $", level=("danger" if reste_ce < 0 else lvl_ce), pulse=(lvl_ce != "ok"))
    with c3:
        pill("IR", f"{ir_count} joueur(s)", level=lvl_ir, pulse=(lvl_ir != "ok"))

    st.write("")

    # Cartes d’alerte (seulement si warn/danger)
    if lvl_gc == "danger":
        alert_card("🚨 Plafond GC dépassé", "Réduis la masse salariale ou déplace un joueur.", level="danger", pulse=True)
    elif lvl_gc == "warn":
        alert_card("⚠️ Reste GC faible", "Tu approches du plafond — attention aux moves.", level="warn", pulse=True)

    if lvl_ce == "danger":
        alert_card("🚨 Plafond CE dépassé", "Ajuste le Club École (CE) pour revenir sous le plafond.", level="danger", pulse=True)
    elif lvl_ce == "warn":
        alert_card("⚠️ Reste CE faible", "Tu approches du plafond CE — attention aux moves.", level="warn", pulse=True)

    if lvl_ir != "ok":
        alert_card("🩹 Joueurs blessés (IR)", "Des joueurs sont sur IR — vérifie tes remplacements.", level=lvl_ir, pulse=(lvl_ir == "danger"))

    # Toasts optionnels (utile après un move)
    if toast:
        prefix = f"{context} — " if context else ""
        if lvl_gc == "danger" or lvl_ce == "danger":
            st.toast(prefix + "🚨 Plafond dépassé", icon="🚨")
        elif lvl_gc == "warn" or lvl_ce == "warn":
            st.toast(prefix + "⚠️ Proche du plafond", icon="⚠️")
        if lvl_ir != "ok":
            st.toast(prefix + f"🩹 IR: {ir_count} joueur(s)", icon="🩹")



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
    """Retourne le chemin logo si trouvé.
    ✅ supporte le case-insensitive (Streamlit Cloud / macOS vs Linux)
    """
    team = str(team or "").strip()
    path = str(LOGOS.get(team, "")).strip()
    if path and os.path.exists(path):
        return path

    # fallback: chercher dans DATA_DIR par nom de fichier (insensible à la casse)
    try:
        if path:
            want = os.path.basename(path).lower()
            for fn in os.listdir(DATA_DIR):
                if fn.lower() == want:
                    p = os.path.join(DATA_DIR, fn)
                    if os.path.exists(p):
                        return p
    except Exception:
        pass

    # fallback 2: si LOGOS a une clé proche (espaces/accents)
    try:
        for k, v in (LOGOS or {}).items():
            if str(k).strip().lower() == team.lower():
                v = str(v).strip()
                if v and os.path.exists(v):
                    return v
    except Exception:
        pass

    return ""

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
# MOVE + HISTORY (définition unique)
#   ✅ corrige NameError: apply_move_with_history
# =====================================================
def apply_move_with_history(owner: str, joueur: str, to_statut: str, to_slot: str, note: str = "") -> bool:
    """
    Applique un move (Statut/Slot) + écrit l'historique.
    - Simple et robuste: on modifie la ligne dans df.
    """
    df = st.session_state.get("data", pd.DataFrame(columns=REQUIRED_COLS))
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        st.session_state["last_move_error"] = "Données manquantes."
        return False

    owner_s = str(owner or "").strip()
    joueur_s = str(joueur or "").strip()

    m = (
        df["Propriétaire"].astype(str).str.strip().eq(owner_s)
        & df["Joueur"].astype(str).str.strip().eq(joueur_s)
    )
    if not m.any():
        st.session_state["last_move_error"] = "Joueur introuvable."
        return False

    idx = df.index[m][0]
    from_statut = str(df.at[idx, "Statut"] if "Statut" in df.columns else "")
    from_slot = str(df.at[idx, "Slot"] if "Slot" in df.columns else "")

    # appliquer
    if "Statut" in df.columns:
        df.at[idx, "Statut"] = str(to_statut or "").strip()
    if "Slot" in df.columns:
        df.at[idx, "Slot"] = str(to_slot or "").strip()

    st.session_state["data"] = df
    persist_data(df, str(st.session_state.get("season") or ""))

    # log history (avec pos/equipe/saison)
    try:
        row = df.loc[idx]
        log_history_row(
            proprietaire=owner_s,
            joueur=joueur_s,
            pos=str(row.get("Pos", "")).strip(),
            equipe=str(row.get("Equipe", "")).strip(),
            from_statut=from_statut,
            from_slot=from_slot,
            to_statut=str(to_statut or "").strip(),
            to_slot=str(to_slot or "").strip(),
            action=str(note or ""),
        )
    except Exception:
        pass

    return True


# =====================================================
# PICKS (repêchage) — 8 rondes / 8 choix par équipe
# =====================================================
def _picks_path(season_lbl: str) -> str:
    season_lbl = str(season_lbl or "").strip() or "season"
    return os.path.join(DATA_DIR, f"picks_{season_lbl}.json")

def draft_years_for_season(season_lbl: str) -> list[int]:
    """Fenêtre de 3 années de repêchage basée sur la saison.
    Ex: '2025-2026' -> [2026, 2027, 2028]
    """
    try:
        base = int(str(season_lbl).split("-")[0])
    except Exception:
        base = datetime.now(TZ_TOR).year
    return [base, base + 1, base + 2]


def load_picks(season_lbl: str, teams: list[str] | None = None) -> dict:
    """Structure:
    picks[team][year][round] = owner_du_choix
    - 8 rondes (1..8)
    - années = draft_years_for_season(season_lbl)
    """
    teams = teams or sorted(list(LOGOS.keys()))
    years = [str(y) for y in draft_years_for_season(season_lbl)]
    path = _picks_path(season_lbl)

    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
            # normaliser + auto-ajouter années/rondes manquantes
            for t in teams:
                data.setdefault(t, {})
                for y in years:
                    data[t].setdefault(y, {})
                    for rnd in range(1, 9):
                        data[t][y].setdefault(str(rnd), t)
            return data
        except Exception:
            pass

    # init: chaque équipe possède ses 8 choix, pour les 3 années
    data = {t: {y: {str(r): t for r in range(1, 9)} for y in years} for t in teams}
    save_picks(season_lbl, data)
    return data


def save_picks(season_lbl: str, data: dict) -> None:
    path = _picks_path(season_lbl)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data or {}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def pick_label(year: str, rnd: str) -> str:
    return f"{year} — Ronde {rnd}"

# =====================================================
# BUYOUTS — pénalité 50% salaire (affichée dans la masse)
# =====================================================
def _buyouts_path(season_lbl: str) -> str:
    season_lbl = str(season_lbl or "").strip() or "season"
    return os.path.join(DATA_DIR, f"buyouts_{season_lbl}.csv")

def load_buyouts(season_lbl: str) -> pd.DataFrame:
    path = _buyouts_path(season_lbl)
    cols = ["timestamp", "season", "proprietaire", "joueur", "salaire", "penalite", "bucket"]
    if os.path.exists(path):
        try:
            b = pd.read_csv(path)
            for c in cols:
                if c not in b.columns:
                    b[c] = ""
            return b[cols].copy()
        except Exception:
            return pd.DataFrame(columns=cols)
    return pd.DataFrame(columns=cols)

def save_buyouts(season_lbl: str, b: pd.DataFrame) -> None:
    path = _buyouts_path(season_lbl)
    try:
        b.to_csv(path, index=False)
    except Exception:
        pass

def buyout_penalty_sum(owner: str, bucket: str | None = None) -> int:
    """Somme des pénalités de rachat pour une équipe.
    bucket: 'GC' ou 'CE' (optionnel). Si None -> toutes les pénalités.
    """
    b = st.session_state.get("buyouts")
    if b is None or not isinstance(b, pd.DataFrame) or b.empty:
        return 0
    owner = str(owner or "").strip()

    tmp = b[b["proprietaire"].astype(str).str.strip().eq(owner)].copy()
    if tmp.empty:
        return 0

    if bucket:
        bucket = str(bucket).strip().upper()
        if "bucket" in tmp.columns:
            tmp = tmp[tmp["bucket"].astype(str).str.strip().str.upper().eq(bucket)].copy()
        else:
            # compat vieux fichiers: bucket manquant -> considérer GC par défaut
            if bucket != "GC":
                return 0

    pen = pd.to_numeric(tmp.get("penalite", 0), errors="coerce").fillna(0).astype(int)
    return int(pen.sum())



# =====================================================
# TRADE MARKET (joueurs disponibles aux échanges)
#   - Purement informatif (tag 🔁), persistant par saison
# =====================================================
def _trade_market_path(season_lbl: str) -> str:
    season_lbl = str(season_lbl or "").strip() or "season"
    return os.path.join(DATA_DIR, f"trade_market_{season_lbl}.csv")

def load_trade_market(season_lbl: str) -> pd.DataFrame:
    path = _trade_market_path(season_lbl)
    cols = ["season", "proprietaire", "joueur", "is_available", "updated_at"]
    if os.path.exists(path):
        try:
            t = pd.read_csv(path)
            for c in cols:
                if c not in t.columns:
                    t[c] = ""
            return t[cols].copy()
        except Exception:
            pass
    return pd.DataFrame(columns=cols)

def save_trade_market(season_lbl: str, t: pd.DataFrame) -> None:
    path = _trade_market_path(season_lbl)
    cols = ["season", "proprietaire", "joueur", "is_available", "updated_at"]
    try:
        if t is None or not isinstance(t, pd.DataFrame):
            t = pd.DataFrame(columns=cols)
        for c in cols:
            if c not in t.columns:
                t[c] = ""
        t = t[cols].copy()
        t.to_csv(path, index=False)
    except Exception:
        pass

def is_on_trade_market(t: pd.DataFrame, owner: str, joueur: str) -> bool:
    if t is None or not isinstance(t, pd.DataFrame) or t.empty:
        return False
    owner = str(owner or "").strip()
    joueur = str(joueur or "").strip()
    m = (
        t["proprietaire"].astype(str).str.strip().eq(owner)
        & t["joueur"].astype(str).str.strip().eq(joueur)
    )
    if not m.any():
        return False
    v = str(t.loc[m].iloc[-1].get("is_available", "")).strip().lower()
    return v in {"1", "true", "yes", "oui", "y"}

def set_owner_market(t: pd.DataFrame, season_lbl: str, owner: str, available_players: list[str]) -> pd.DataFrame:
    owner = str(owner or "").strip()
    available_set = {str(x).strip() for x in (available_players or []) if str(x).strip()}
    now = datetime.now(TZ_TOR).isoformat(timespec="seconds")

    base = t.copy() if isinstance(t, pd.DataFrame) else load_trade_market(season_lbl)
    # retire anciennes lignes pour owner puis réécrit l'état final
    if not base.empty:
        base = base[~base["proprietaire"].astype(str).str.strip().eq(owner)].copy()

    rows = []
    for j in sorted(available_set):
        rows.append({
            "season": str(season_lbl),
            "proprietaire": owner,
            "joueur": j,
            "is_available": True,
            "updated_at": now,
        })

    if rows:
        base = pd.concat([base, pd.DataFrame(rows)], ignore_index=True)
    return base


# =====================================================
# TRADE PROPOSALS (approbation des 2 équipes)
#   - Une transaction est valide seulement si owner A + owner B ont approuvé
#   - Persistant par saison (CSV)
# =====================================================
def _trade_proposals_path(season_lbl: str) -> str:
    season_lbl = str(season_lbl or "").strip() or "season"
    return os.path.join(DATA_DIR, f"trade_proposals_{season_lbl}.csv")

def _trade_proposals_cols():
    return [
        "id", "created_at", "season",
        "owner_a", "owner_b",
        "a_players", "b_players",
        "a_picks", "b_picks",
        "a_retained", "b_retained",
        "approved_a", "approved_b",
        "status",
        "note",
    ]

def load_trade_proposals(season_lbl: str) -> pd.DataFrame:
    path = _trade_proposals_path(season_lbl)
    cols = _trade_proposals_cols()
    if os.path.exists(path):
        try:
            t = pd.read_csv(path)
            for c in cols:
                if c not in t.columns:
                    t[c] = ""
            return t[cols].copy()
        except Exception:
            pass
    return pd.DataFrame(columns=cols)

def save_trade_proposals(season_lbl: str, t: pd.DataFrame) -> None:
    path = _trade_proposals_path(season_lbl)
    cols = _trade_proposals_cols()
    try:
        if t is None or not isinstance(t, pd.DataFrame):
            t = pd.DataFrame(columns=cols)
        for c in cols:
            if c not in t.columns:
                t[c] = ""
        t = t[cols].copy()
        t.to_csv(path, index=False)
    except Exception:
        pass

def _json_dump(x) -> str:
    try:
        return json.dumps(x, ensure_ascii=False)
    except Exception:
        return "[]"

def _json_load(s, fallback):
    try:
        if pd.isna(s):
            return fallback
        if isinstance(s, (list, dict)):
            return s
        s = str(s or "").strip()
        return json.loads(s) if s else fallback
    except Exception:
        return fallback

def submit_trade_proposal(season_lbl: str, owner_a: str, owner_b: str,
                          a_players: list[str], b_players: list[str],
                          a_picks: list[str], b_picks: list[str],
                          a_retained: dict, b_retained: dict,
                          note: str = "") -> str:
    t = load_trade_proposals(season_lbl)
    now = datetime.now(TZ_TOR).isoformat(timespec="seconds")
    tid = f"tr_{datetime.now(TZ_TOR).strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(4)}"
    row = {
        "id": tid,
        "created_at": now,
        "season": str(season_lbl),
        "owner_a": str(owner_a).strip(),
        "owner_b": str(owner_b).strip(),
        "a_players": _json_dump(a_players or []),
        "b_players": _json_dump(b_players or []),
        "a_picks": _json_dump(a_picks or []),
        "b_picks": _json_dump(b_picks or []),
        "a_retained": _json_dump(a_retained or {}),
        "b_retained": _json_dump(b_retained or {}),
        "approved_a": False,
        "approved_b": False,
        "status": "pending",
        "note": str(note or ""),
    }
    t = pd.concat([t, pd.DataFrame([row])], ignore_index=True)
    save_trade_proposals(season_lbl, t)
    return tid

def approve_trade_proposal(season_lbl: str, trade_id: str, owner: str, approve: bool) -> bool:
    t = load_trade_proposals(season_lbl)
    if t.empty:
        return False
    m = t["id"].astype(str).eq(str(trade_id))
    if not m.any():
        return False
    i = t.index[m][0]
    oa = str(t.at[i, "owner_a"] or "").strip()
    ob = str(t.at[i, "owner_b"] or "").strip()
    owner = str(owner or "").strip()

    if owner == oa:
        t.at[i, "approved_a"] = bool(approve)
    elif owner == ob:
        t.at[i, "approved_b"] = bool(approve)
    else:
        return False

    # status
    a_ok = str(t.at[i, "approved_a"]).lower() in {"true", "1", "yes"}
    b_ok = str(t.at[i, "approved_b"]).lower() in {"true", "1", "yes"}
    t.at[i, "status"] = "approved" if (a_ok and b_ok) else "pending"

    save_trade_proposals(season_lbl, t)
    return True

def latest_trade_proposal(season_lbl: str) -> dict | None:
    t = load_trade_proposals(season_lbl)
    if t is None or t.empty:
        return None
    tmp = t.copy()
    tmp["_dt"] = tmp["created_at"].apply(to_dt_local)
    tmp = tmp.sort_values("_dt", ascending=False, na_position="last")
    r = tmp.iloc[0].to_dict()
    # parse json columns for UI use
    r["a_players"] = _json_load(r.get("a_players"), [])
    r["b_players"] = _json_load(r.get("b_players"), [])
    r["a_picks"] = _json_load(r.get("a_picks"), [])
    r["b_picks"] = _json_load(r.get("b_picks"), [])
    r["a_retained"] = _json_load(r.get("a_retained"), {})
    r["b_retained"] = _json_load(r.get("b_retained"), {})
    return r
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
    """Parse un export Fantrax (format variable).
    ✅ supporte colonnes: Player/Name/Joueur + Salary/Cap Hit/AAV/Salaire
    ✅ supporte séparateurs: , ; \t |
    """
    raw = upload.read()
    if isinstance(raw, bytes):
        raw_text = raw.decode("utf-8", errors="ignore")
    else:
        raw_text = str(raw)

    raw_lines = raw_text.splitlines()
    # Nettoyage chars invisibles (évite U+007F)
    raw_lines = [re.sub(r"[\x00-\x1f\x7f]", "", l) for l in raw_lines]

    # Détection header: on cherche une ligne qui contient un marqueur "joueur" ET un marqueur "salaire"
    name_marks = ("player", "name", "joueur")
    sal_marks = ("salary", "cap hit", "caphit", "aav", "salaire")

    def _looks_like_header(line: str) -> bool:
        low = line.lower()
        return any(k in low for k in name_marks) and any(k in low for k in sal_marks)

    # Séparateur: celui qui découpe le plus "proprement" la ligne header
    def detect_sep(lines):
        cand_seps = [",", ";", "\t", "|"]
        header_line = next((l for l in lines if _looks_like_header(l)), "")
        if not header_line:
            # fallback: première ligne non vide
            header_line = next((l for l in lines if l.strip()), "")
        best = ","
        best_score = -1
        for sep in cand_seps:
            parts = [p.strip().strip('"') for p in header_line.split(sep)]
            # score = nb de colonnes non vides
            score = sum(1 for p in parts if p)
            if score > best_score:
                best_score = score
                best = sep
        return best

    sep = detect_sep(raw_lines)

    header_idxs = [i for i, l in enumerate(raw_lines) if _looks_like_header(l) and sep in l]
    if not header_idxs:
        # Tentative 2: on prend la première ligne qui contient le séparateur + au moins 3 colonnes
        for i, l in enumerate(raw_lines):
            if sep in l and len([p for p in l.split(sep) if p.strip()]) >= 3:
                header_idxs = [i]
                break

    if not header_idxs:
        raise ValueError("Colonnes Fantrax non détectées (Player/Salary ou équivalent).")

    def read_section(start, end):
        lines = [l for l in raw_lines[start:end] if l.strip() != ""]
        if len(lines) < 2:
            return None
        dfp = pd.read_csv(io.StringIO("\n".join(lines)), sep=sep, engine="python", on_bad_lines="skip")
        dfp.columns = [str(c).strip().replace('"', "") for c in dfp.columns]
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
            p = p.lower()
            for c in df.columns:
                if p in str(c).lower():
                    return c
        return None

    # Player / Name
    player_col = find_col(["player", "name", "joueur"])
    # Salary / Cap Hit / AAV
    salary_col = find_col(["salary", "cap hit", "caphit", "aav", "salaire", "cap-hit"])
    team_col = find_col(["team", "équipe", "equipe"])
    pos_col = find_col(["pos", "position"])
    status_col = find_col(["status", "statut"])

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
        .str.replace("$", "", regex=False)
        .replace(["None", "nan", "NaN", ""], "0")
    )
    # Fantrax: souvent en milliers -> si petit nombre, multiplier par 1000
    sal_num = pd.to_numeric(sal, errors="coerce").fillna(0)
    if sal_num.max() <= 50000:
        sal_num = (sal_num * 1000)
    out["Salaire"] = sal_num.astype(int)

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
# DIALOG GUARD — un seul dialog à la fois
# =====================================================
def _set_active_dialog(name: str):
    st.session_state["active_dialog"] = str(name or "").strip()

def _clear_active_dialog(name: str | None = None):
    if name is None or st.session_state.get("active_dialog") == name:
        st.session_state["active_dialog"] = ""

def _can_open_dialog(name: str) -> bool:
    cur = str(st.session_state.get("active_dialog") or "")
    return (cur == "") or (cur == str(name or ""))

# =====================================================
# MOVE DIALOG — auto-remplacement IR + étiquette exacte
# =====================================================

# =====================================================
# PENDING MOVES (déplacements programmés)
# =====================================================
def _init_pending_moves():
    if "pending_moves" not in st.session_state or st.session_state["pending_moves"] is None:
        st.session_state["pending_moves"] = []

def process_pending_moves():
    """
    Applique les moves programmés dont la date d'effet est atteinte.
    Stockage: st.session_state["pending_moves"] = list[dict]
    """
    _init_pending_moves()
    moves = st.session_state.get("pending_moves") or []
    if not isinstance(moves, list) or not moves:
        return

    now = datetime.now(TZ_TOR)
    keep = []
    applied = 0

    for mv in moves:
        try:
            eff = pd.to_datetime(mv.get("effective_at"), errors="coerce")
            eff = eff.to_pydatetime() if not pd.isna(eff) else None
        except Exception:
            eff = None

        if eff is None or eff > now:
            keep.append(mv)
            continue

        owner = str(mv.get("owner","")).strip()
        joueur = str(mv.get("joueur","")).strip()
        to_statut = str(mv.get("to_statut","")).strip()
        to_slot = str(mv.get("to_slot","")).strip()
        note = str(mv.get("note","")).strip() or "Move programmé"

        ok = False
        if "apply_move_with_history" in globals() and callable(globals()["apply_move_with_history"]):
            ok = bool(globals()["apply_move_with_history"](owner, joueur, to_statut, to_slot, note))
        else:
            # fallback minimal
            df = st.session_state.get("data", pd.DataFrame(columns=REQUIRED_COLS))
            m = (
                df["Propriétaire"].astype(str).str.strip().eq(owner)
                & df["Joueur"].astype(str).str.strip().eq(joueur)
            )
            if m.any():
                idx = df.index[m][0]
                df.at[idx, "Statut"] = to_statut
                df.at[idx, "Slot"] = to_slot
                st.session_state["data"] = df
                ok = True

        if ok:
            applied += 1
        else:
            keep.append(mv)

    st.session_state["pending_moves"] = keep
    if applied:
        try:
            persist_data(st.session_state.get("data"), st.session_state.get("season"))
        except Exception:
            pass

def open_move_dialog():
    if not _can_open_dialog('move'):
        return
    # si un autre dialog est demandé, ne pas en ouvrir 2
    if st.session_state.get('gc_preview_open'):
        return
    _set_active_dialog('move')
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
        _clear_active_dialog("move")

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
        if reason_low.startswith("bless") or reason_low.startswith("remp"):
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
            ok = _apply_f(
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
            ok = _apply_f(
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

        # 1) Type (adapté selon le joueur)
        is_ir = (cur_slot == SLOT_IR)
        is_banc = (cur_statut == STATUT_GC and cur_slot == SLOT_BANC)
        is_ce = (cur_statut == STATUT_CE)

        # Règles:
        # - Joueur IR: retour GC uniquement (Actif)
        # - Joueur Banc: pas d'option Blessure (donc pas de type Blessure)
        # - Joueur CE: le type "Blessure" devient "Remplacement"
        if is_ir:
            reason = "Blessure"
            st.markdown("<span class='pill'>🩹 Joueur sur IR — retour au GC seulement</span>", unsafe_allow_html=True)
        else:
            if is_ce:
                reason_opts = ["Changement demi-mois", "Remplacement"]
            else:
                reason_opts = ["Changement demi-mois", "Blessure"]

            # Banc GC: jamais Blessure
            if is_banc:
                reason_opts = ["Changement demi-mois"]

            reason = st.radio(
                "Type de changement",
                reason_opts,
                horizontal=True,
                key=f"mv_reason_{owner}_{joueur}_{nonce}",
            )

        st.divider()

        # 2) Destination (selon règles)
        destinations = []

        if is_ir:
            # (1) joueur blessé: retour GC uniquement
            destinations = [("🟢 Retour Actif", (STATUT_GC, SLOT_ACTIF))]
        else:
            if reason == "Changement demi-mois":
                # (2) Demi-mois: pas de choix "Blessé" jamais
                if cur_statut == STATUT_GC and cur_slot == SLOT_ACTIF:
                    destinations = [
                        ("🟡 Banc", (STATUT_GC, SLOT_BANC)),
                        ("🔵 Mineur", (STATUT_CE, "")),
                    ]
                elif cur_statut == STATUT_GC and cur_slot == SLOT_BANC:
                    destinations = [
                        ("🟢 Actif", (STATUT_GC, SLOT_ACTIF)),
                        ("🔵 Mineur", (STATUT_CE, "")),
                    ]
                else:
                    # joueur CE: demi-mois -> Banc GC ou Mineur (reste CE)
                    destinations = [
                        ("🟡 Banc", (STATUT_GC, SLOT_BANC)),
                        ("🔵 Mineur", (STATUT_CE, "")),
                    ]

            else:
                # (3) Blessure / Remplacement
                if is_ce:
                    # CE -> seulement Actif (remplacement)
                    destinations = [("🟢 Actif", (STATUT_GC, SLOT_ACTIF))]
                else:
                    # GC: Blessure -> seulement Blessé (IR)
                    # Banc n'arrive pas ici car reason_opts l'exclut
                    destinations = [("🩹 Blessé (IR)", (STATUT_GC, SLOT_IR))]

        # Enlever l'option identique à l'état actuel
        current = (cur_statut, cur_slot or "")
        destinations = [d for d in destinations if d[1] != current]

        labels = [d[0] for d in destinations]
        mapping = {d[0]: d[1] for d in destinations}

        # sécurité si aucune destination
        if not labels:
            st.info("Aucune destination valide pour ce joueur.")
            st.stop()

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

        # ✅ Sécurité: apply_move_with_history doit exister
        _apply_f = globals().get("apply_move_with_history")
        if not callable(_apply_f):
            def _apply_f(owner_x: str, joueur_x: str, to_statut_x: str, to_slot_x: str, note_x: str = "") -> bool:
                df_x = st.session_state.get("data", pd.DataFrame(columns=REQUIRED_COLS))
                if df_x is None or df_x.empty:
                    st.session_state["last_move_error"] = "Données manquantes."
                    return False
                m2 = (
                    df_x["Propriétaire"].astype(str).str.strip().eq(str(owner_x).strip())
                    & df_x["Joueur"].astype(str).str.strip().eq(str(joueur_x).strip())
                )
                if not m2.any():
                    st.session_state["last_move_error"] = "Joueur introuvable."
                    return False
                idx2 = df_x.index[m2][0]
                from_statut2 = str(df_x.at[idx2, "Statut"]) if "Statut" in df_x.columns else ""
                from_slot2 = str(df_x.at[idx2, "Slot"]) if "Slot" in df_x.columns else ""
                df_x.at[idx2, "Statut"] = to_statut_x
                df_x.at[idx2, "Slot"] = to_slot_x
                st.session_state["data"] = clean_data(df_x)
                persist_data(st.session_state["data"], str(st.session_state.get("season") or season))
                # log minimal
                try:
                    log_history_row(str(owner_x), str(joueur_x), "", "", from_statut2, from_slot2, str(to_statut_x), str(to_slot_x), str(note_x))
                except Exception:
                    pass
                return True

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
                ok = _apply_f(owner, joueur, to_statut, to_slot, note)
                if ok:
                    # ✅ Auto-remplacement retiré (comme demandé)

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
    if not _can_open_dialog('gc_preview'):
        return
    _set_active_dialog('gc_preview')
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
            _clear_active_dialog("gc_preview")
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

            # + pénalités de rachat (50%) (peuvent être appliquées GC ou CE)
            total_gc = int(total_gc) + int(buyout_penalty_sum(team, "GC"))
            total_ce = int(total_ce) + int(buyout_penalty_sum(team, "CE"))

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
    """
    Tableau des masses salariales (cliquable):
      - clic sur le nom d'équipe => sélectionne l'équipe (comme l'ancien selectbox sidebar)
      - aucun dédoublement: on affiche une seule fois les valeurs
    """
    selected = str(get_selected_team() or "").strip()

    if plafonds is None or not isinstance(plafonds, pd.DataFrame) or plafonds.empty:
        st.info("Aucune équipe configurée.")
        return

    view = plafonds.copy()

    # Colonnes attendues (fallback)
    for c in ["Propriétaire", "Total Grand Club", "Montant Disponible GC", "Total Club École", "Montant Disponible CE"]:
        if c not in view.columns:
            view[c] = 0 if ("Total" in c or "Montant" in c) else ""

    # Format money
    def _fmt_money(x):
        try:
            return money(int(float(x)))
        except Exception:
            return money(0)

    view["_TotalGC"] = view["Total Grand Club"].apply(_fmt_money)
    view["_ResteGC"] = view["Montant Disponible GC"].apply(_fmt_money)
    view["_TotalCE"] = view["Total Club École"].apply(_fmt_money)
    view["_ResteCE"] = view["Montant Disponible CE"].apply(_fmt_money)

    st.markdown("#### Cliquez sur une équipe pour la sélectionner")
    h = st.columns([2.6, 1.5, 1.5, 1.5, 1.5], vertical_alignment="center")
    h[0].markdown("**Équipe**")
    h[1].markdown("**Total GC**")
    h[2].markdown("**Reste GC**")
    h[3].markdown("**Total CE**")
    h[4].markdown("**Reste CE**")

    for _, r in view.iterrows():
        owner = str(r.get("Propriétaire", "")).strip()
        is_sel = bool(owner) and owner == selected

        c = st.columns([2.6, 1.5, 1.5, 1.5, 1.5], vertical_alignment="center")

        label = f"✅ {owner}" if is_sel else owner
        if c[0].button(label, key=f"tbl_pick_{owner}", use_container_width=True):
            pick_team(owner)

        c[1].markdown(r["_TotalGC"])
        c[2].markdown(r["_ResteGC"])
        c[3].markdown(r["_TotalCE"])
        c[4].markdown(r["_ResteCE"])


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
# 1) LOAD DATA (CSV → session_state)
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

    st.session_state["data"] = clean_data(df_loaded)
    st.session_state["data_season"] = season
else:
    # sécurité: s'assurer que data est propre
    st.session_state["data"] = clean_data(st.session_state.get("data", pd.DataFrame(columns=REQUIRED_COLS)))

# -----------------------------------------------------
# 2) LOAD HISTORY (CSV → session_state)
# -----------------------------------------------------
if "history_season" not in st.session_state or st.session_state["history_season"] != season:
    st.session_state["history"] = load_history_file(HISTORY_FILE)
    st.session_state["history_season"] = season
else:
    # sécurité: s'assurer que history est un DF
    h0 = st.session_state.get("history")
    st.session_state["history"] = h0 if isinstance(h0, pd.DataFrame) else _history_empty_df()

# -----------------------------------------------------
# 3) PROCESS PENDING MOVES  ⬅️ IMPORTANT
#    (doit être appelé APRÈS data + history chargés)
# -----------------------------------------------------
if "process_pending_moves" in globals() and callable(globals()["process_pending_moves"]):
    try:
        process_pending_moves()
    except Exception as e:
        st.warning(f"⚠️ process_pending_moves() a échoué: {type(e).__name__}: {e}")

# -----------------------------------------------------
# 4) PLAYERS DATABASE (read-only)
# -----------------------------------------------------
players_db = load_players_db(PLAYERS_DB_FILE)
st.session_state["players_db"] = players_db

# -----------------------------------------------------
# 5) BUILD PLAFONDS (si tu l'utilises globalement)
# -----------------------------------------------------
df0 = clean_data(st.session_state.get("data", pd.DataFrame(columns=REQUIRED_COLS)))
st.session_state["data"] = df0
st.session_state["plafonds"] = rebuild_plafonds(df0)




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
st.sidebar.markdown("### 🏒 Équipe choisie")
team_sel = str(st.session_state.get("selected_team", "") or "").strip()
if not team_sel:
    team_sel = "—"
st.sidebar.write(f"**{team_sel}**")

logo_path = team_logo_path(team_sel)
if logo_path:
    st.sidebar.image(logo_path, use_container_width=True)

# (Sélection de l'équipe = via clic dans le tableau de la page 📊 Tableau)

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
    "🧑‍💼 GM",
    "👤 Joueurs autonomes",
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
# MOVE CONTEXT (safe)
#   - set_move_ctx() : ouvre le dialog
#   - clear_move_ctx(): ferme le dialog
# =====================================================
def set_move_ctx(owner: str, joueur: str, source_key: str):
    owner = str(owner or "").strip()
    joueur = str(joueur or "").strip()
    source_key = str(source_key or "").strip()

    # 🔒 reset toast flag à l'ouverture d'un nouveau move
    st.session_state["just_moved"] = False

    st.session_state["move_nonce"] = int(st.session_state.get("move_nonce", 0)) + 1
    st.session_state["move_source"] = source_key
    st.session_state["move_ctx"] = {
        "owner": owner,
        "joueur": joueur,
        "nonce": st.session_state["move_nonce"],
    }

def clear_move_ctx():
    st.session_state["move_ctx"] = None
    st.session_state["move_source"] = ""



# =====================================================
# Global scheduled moves + dialogs (APPELS SAFE)
#   ✅ 1 seule fois
#   ✅ seulement si data/history existent
#   ✅ jamais de NameError
# =====================================================
_has_data = isinstance(st.session_state.get("data"), pd.DataFrame)
_has_hist = isinstance(st.session_state.get("history"), pd.DataFrame)

if _has_data and _has_hist:

    # 1) Appliquer les déplacements programmés
    if "process_pending_moves" in globals() and callable(globals()["process_pending_moves"]):
        try:
            process_pending_moves()
        except Exception as e:
            st.warning(f"⚠️ process_pending_moves() a échoué: {type(e).__name__}: {e}")

    # 2) Dialog preview GC (si présent)
    if "open_gc_preview_dialog" in globals() and callable(globals()["open_gc_preview_dialog"]):
        try:
            open_gc_preview_dialog()
        except Exception as e:
            st.warning(f"⚠️ open_gc_preview_dialog() a échoué: {type(e).__name__}: {e}")

    # 3) Dialog MOVE (si présent)  ✅ IMPORTANT
    if "open_move_dialog" in globals() and callable(globals()["open_move_dialog"]):
        try:
            open_move_dialog()
        except Exception as e:
            st.warning(f"⚠️ open_move_dialog() a échoué: {type(e).__name__}: {e}")




# =====================================================
# UI — roster click list (compact list)
#   ⚠️ DOIT être défini AVANT Alignement (car appelé dans _render_gc_block)
# =====================================================
def roster_click_list(df_src: pd.DataFrame, owner: str, source_key: str) -> str | None:
    if df_src is None or not isinstance(df_src, pd.DataFrame) or df_src.empty:
        st.info("Aucun joueur.")
        return None

    # CSS injecté 1x
    if not st.session_state.get("_roster_css_injected", False):
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
              .levelCell{
                white-space: nowrap;
                opacity: .85;
                font-weight: 800;
              }
            </style>
            """,
            unsafe_allow_html=True,
        )
        st.session_state["_roster_css_injected"] = True

    t = df_src.copy()

    # colonnes minimales
    for c, d in {"Joueur": "", "Pos": "F", "Equipe": "", "Salaire": 0, "Level": ""}.items():
        if c not in t.columns:
            t[c] = d

    t["Joueur"] = t["Joueur"].astype(str).fillna("").map(lambda x: re.sub(r"\s+", " ", x).strip())
    t["Equipe"] = t["Equipe"].astype(str).fillna("").map(lambda x: re.sub(r"\s+", " ", x).strip())
    t["Level"]  = t["Level"].astype(str).fillna("").map(lambda x: re.sub(r"\s+", " ", x).strip())
    t["Salaire"] = pd.to_numeric(t["Salaire"], errors="coerce").fillna(0).astype(int)

    bad = {"", "none", "nan", "null"}
    t = t[~t["Joueur"].str.lower().isin(bad)].copy()
    if t.empty:
        st.info("Aucun joueur.")
        return None

    # tri
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

    disabled = str(source_key or "").endswith("_disabled")

    # header
    h = st.columns([1.0, 1.4, 3.6, 1.2, 2.0])
    h[0].markdown("**Pos**")
    h[1].markdown("**Équipe**")
    h[2].markdown("**Joueur**")
    h[3].markdown("**Level**")
    h[4].markdown("**Salaire**")

    clicked = None
    for _, r in t.iterrows():
        joueur = str(r.get("Joueur", "")).strip()
        if not joueur:
            continue

        pos = r.get("Pos", "F")
        team = str(r.get("Equipe", "")).strip()
        lvl = str(r.get("Level", "")).strip()
        salaire = int(r.get("Salaire", 0) or 0)

        row_sig = f"{joueur}|{pos}|{team}|{lvl}|{salaire}"
        row_key = re.sub(r"[^a-zA-Z0-9_|\-]", "_", row_sig)[:120]

        c = st.columns([1.0, 1.4, 3.6, 1.2, 2.0])
        c[0].markdown(pos_badge_html(pos), unsafe_allow_html=True)
        c[1].markdown(team if team and team.lower() not in bad else "—")

        if c[2].button(
            joueur,
            key=f"{source_key}_{owner}_{row_key}",
            use_container_width=True,
            disabled=disabled,
        ):
            clicked = joueur

        c[3].markdown(
            f"<span class='levelCell'>{html.escape(lvl) if lvl and lvl.lower() not in bad else '—'}</span>",
            unsafe_allow_html=True,
        )
        c[4].markdown(f"<span class='salaryCell'>{money(salaire)}</span>", unsafe_allow_html=True)

    return clicked


# =====================================================
# ROUTING PRINCIPAL — ONE SINGLE CHAIN
# =====================================================
if active_tab == "📊 Tableau":
    st.subheader("📊 Tableau — Masses salariales (toutes les équipes)")
    # Alertes échanges (approbations)
    tprops = load_trade_proposals(season)
    if tprops is not None and not tprops.empty:
        tp = tprops.copy()
        tp["_dt"] = tp["created_at"].apply(to_dt_local)
        tp = tp.sort_values("_dt", ascending=False, na_position="last")
        pending = tp[tp["status"].astype(str).eq("pending")].head(5)
        approved = tp[tp["status"].astype(str).eq("approved")].head(5)

        if not pending.empty:
            with st.expander("🚨 Échanges en attente d'approbation", expanded=True):
                for _, r in pending.iterrows():
                    oa = str(r["owner_a"]); ob = str(r["owner_b"])
                    created = format_date_fr(r["created_at"])
                    st.warning(f"Échange **{oa}** ⇄ **{ob}** — en attente (créé le {created})")

        if not approved.empty:
            with st.expander("✅ Échanges approuvés", expanded=False):
                for _, r in approved.iterrows():
                    oa = str(r["owner_a"]); ob = str(r["owner_b"])
                    created = format_date_fr(r["created_at"])
                    st.success(f"Échange **{oa}** ⇄ **{ob}** — approuvé (créé le {created})")


    # Sous-titre discret (UI)
    st.markdown(
        '<div class="muted">Vue d’ensemble des équipes pour la saison active</div>',
        unsafe_allow_html=True
    )

    st.write("")  # spacing léger

    # ⚠️ Le tableau principal reste inchangé
    build_tableau_ui(st.session_state.get("plafonds"))



    # =====================================================
    # 📌 Réclamations Joueurs autonomes + Points (ordre d'embauche)
    # =====================================================
    st.subheader("📝 Réclamations — Joueurs autonomes (priorité par points)")

    # charger équipes depuis plafonds si possible
    teams_list = []
    try:
        pl = st.session_state.get("plafonds")
        if isinstance(pl, pd.DataFrame) and not pl.empty and "Propriétaire" in pl.columns:
            teams_list = [str(x).strip() for x in pl["Propriétaire"].dropna().tolist()]
    except Exception:
        teams_list = []

    points_df = load_points(season, teams_list)
    with st.expander("⚙️ Points / Classement (modifiable manuellement)", expanded=False):
        ed_points = st.data_editor(
            points_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Propriétaire": st.column_config.TextColumn("Propriétaire", disabled=True),
                "Points": st.column_config.NumberColumn("Points", min_value=0, step=1),
            },
            key="points_editor",
        )
        if st.button("💾 Enregistrer les points", key="save_points", use_container_width=True):
            persist_points(ed_points, season)
            st.toast("✅ Points enregistrés", icon="✅")
            do_rerun()

    # Réclamations
    _init_fa_claims()
    claims = st.session_state.get("fa_claims") or {}
    if not claims:
        st.info("Aucune réclamation pour le moment.")
    else:
        order = _fa_priority_order(points_df)
        rows = []
        for owner in order if order else sorted(claims.keys()):
            for i, c in enumerate(claims.get(owner, []) or [], start=1):
                rows.append({
                    "Priorité": order.index(owner) + 1 if owner in order else 999,
                    "Propriétaire": owner,
                    "#": i,
                    "Joueur": c.get("player", ""),
                    "Destination": c.get("dest", "GC"),
                })
        dfc = pd.DataFrame(rows)
        if not dfc.empty:
            dfc = dfc.sort_values(["Priorité", "Propriétaire", "#"], kind="mergesort")
            st.dataframe(dfc, use_container_width=True, hide_index=True)
        else:
            st.info("Aucune réclamation pour le moment.")

        # confirmer embauche: seul propriétaire en priorité (ou admin) peut confirmer
        owner_me = str(get_selected_team() or "").strip()
        is_admin = bool(_is_admin_whalers()) if "_is_admin_whalers" in globals() else False

        next_owner = None
        for ow in order:
            if claims.get(ow):
                next_owner = ow
                break

        if next_owner:
            st.caption(f"Prochaine priorité d'embauche: **{next_owner}** (points les plus bas).")

        if next_owner and (is_admin or owner_me == next_owner):
            st.markdown("##### ✅ Confirmer une embauche (équipe en priorité)")
            ow = next_owner
            for idx2, c in enumerate(list(claims.get(ow, [])), start=1):
                pname = str(c.get("player", "")).strip()
                dest = str(c.get("dest", "GC")).strip()
                if not pname:
                    continue
                cols = st.columns([6, 2, 2], vertical_alignment="center")
                cols[0].markdown(f"**{pname}** → {dest}")
                note = cols[1].text_input("Note", value="Embauche FA", key=f"hire_note_{ow}_{idx2}")
                if cols[2].button("Valider", key=f"hire_btn_{ow}_{idx2}", use_container_width=True):
                    ok = hire_free_agent(ow, pname, dest, note.strip() or f"EMBAUCHE FA ({dest})")
                    if ok:
                        # retirer de la liste
                        st.session_state["fa_claims"][ow] = [
                            x for x in st.session_state["fa_claims"].get(ow, [])
                            if _norm_name(x.get("player", "")) != _norm_name(pname)
                        ]
                        persist_fa_claims(st.session_state["fa_claims"], season)
                        st.toast("✅ Joueur embauché", icon="✅")
                        do_rerun()
                    else:
                        st.error(st.session_state.get("last_move_error", "Impossible d'embaucher ce joueur."))

    def _recent_changes_df(limit: int = 15) -> pd.DataFrame:
        rows = []

        # Moves / actions via history
        h = st.session_state.get("history")
        if isinstance(h, pd.DataFrame) and not h.empty:
            hh = h.copy()
            # normaliser colonnes
            if "timestamp" in hh.columns:
                hh["_dt"] = hh["timestamp"].apply(to_dt_local)
            else:
                hh["_dt"] = pd.NaT
            for _, r in hh.iterrows():
                rows.append({
                    "Date": format_date_fr(r.get("timestamp")),
                    "_dt": r.get("_dt", pd.NaT),
                    "Type": str(r.get("action", "") or "MOVE"),
                    "Équipe": str(r.get("proprietaire", "") or ""),
                    "Détail": f"{str(r.get('joueur','') or '')} — {str(r.get('from_statut','') or '')}/{str(r.get('from_slot','') or '')} → {str(r.get('to_statut','') or '')}/{str(r.get('to_slot','') or '')}".strip(),
                })

        # Rachats
        b = st.session_state.get("buyouts")
        if isinstance(b, pd.DataFrame) and not b.empty:
            bb = b.copy()
            bb["_dt"] = bb["timestamp"].apply(to_dt_local) if "timestamp" in bb.columns else pd.NaT
            for _, r in bb.iterrows():
                bucket = str(r.get("bucket", "GC") or "GC").strip().upper()
                rows.append({
                    "Date": format_date_fr(r.get("timestamp")),
                    "_dt": r.get("_dt", pd.NaT),
                    "Type": f"RACHAT {bucket}",
                    "Équipe": str(r.get("proprietaire", "") or ""),
                    "Détail": f"{str(r.get('joueur','') or '')} — pénalité {money(int(float(r.get('penalite',0) or 0)))}",
                })

        # (placeholder) Échanges: si tu ajoutes un log plus tard, on l’intègre ici
        out = pd.DataFrame(rows)
        if out.empty:
            return out

        out = out.sort_values(by="_dt", ascending=False, na_position="last").drop(columns=["_dt"])
        return out.head(int(limit))

    recent = _recent_changes_df(20)
    if recent.empty:
        st.caption("Aucun changement enregistré pour l’instant.")
    else:
        st.dataframe(recent, use_container_width=True, hide_index=True)


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
        with j1:
            st.markdown(cap_bar_html(0, cap_gc, f"📊 Plafond GC — {proprietaire}"), unsafe_allow_html=True)
        with j2:
            st.markdown(cap_bar_html(0, cap_ce, f"📊 Plafond CE — {proprietaire}"), unsafe_allow_html=True)
        clear_move_ctx()
        st.stop()

    # --- Split IR vs non-IR (DOIT être avant les totaux)
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

    # --- Barres plafond (tes barres restent)
    j1, j2 = st.columns(2)
    with j1:
        st.markdown(cap_bar_html(used_gc, cap_gc, f"📊 Plafond GC — {proprietaire}"), unsafe_allow_html=True)
    with j2:
        st.markdown(cap_bar_html(used_ce, cap_ce, f"📊 Plafond CE — {proprietaire}"), unsafe_allow_html=True)

    st.write("")

    # --- ✅ Pills + Alert cards (après calculs)
    show_status_alerts(
        total_gc=int(used_gc),
        cap_gc=int(cap_gc),
        total_ce=int(used_ce),
        cap_ce=int(cap_ce),
        ir_count=int(len(injured_all)),
        toast=False,
        context=proprietaire,
    )

    st.write("")

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

    if st.session_state.pop("just_moved", False):
        show_status_alerts(
            total_gc=int(used_gc),
            cap_gc=int(cap_gc),
            total_ce=int(used_ce),
            cap_ce=int(cap_ce),
            ir_count=int(len(injured_all)),
            toast=True,
            context="Move appliqué",
        )



elif active_tab == "🧑‍💼 GM":
    st.subheader("🧑‍💼 GM")
    owner = str(get_selected_team() or "").strip()
    if not owner:
        st.info("Sélectionne une équipe en cliquant son nom dans 📊 Tableau.")
        st.stop()

    df = clean_data(st.session_state.get("data", pd.DataFrame(columns=REQUIRED_COLS)))
    st.session_state["data"] = df

    dprop = df[df["Propriétaire"].astype(str).str.strip().eq(owner)].copy()
    if dprop.empty:
        st.warning("Aucune donnée d'alignement pour cette équipe.")
        st.stop()

    # masse salariale (incl. pénalités)
    cap_gc = int(st.session_state.get("PLAFOND_GC", 0) or 0)
    cap_ce = int(st.session_state.get("PLAFOND_CE", 0) or 0)

    d_ok = dprop[dprop.get("Slot", "") != SLOT_IR].copy()
    total_gc = int(d_ok[(d_ok["Statut"] == STATUT_GC)]["Salaire"].sum())
    total_ce = int(d_ok[(d_ok["Statut"] == STATUT_CE)]["Salaire"].sum())
    pen_gc = int(buyout_penalty_sum(owner, "GC"))
    pen_ce = int(buyout_penalty_sum(owner, "CE"))
    total_gc_incl = total_gc + pen_gc
    total_ce_incl = total_ce + pen_ce

    c1, c2, c3 = st.columns(3)
    c1.metric("Masse GC", money(total_gc))
    if pen_gc:
        c2.metric("Pénalités rachat GC (50%)", money(pen_gc))
    if pen_gc:
        c3.metric("GC (incl. pénalités)", money(total_gc_incl))
    c4, c5, _c6 = st.columns(3)
    c4.metric("Masse CE", money(total_ce))
    if pen_ce:
        c5.metric("Pénalités rachat CE (50%)", money(pen_ce))
        _c6.metric("CE (incl. pénalités)", money(total_ce_incl))
    st.markdown(cap_bar_html((total_gc_incl if pen_gc else total_gc), cap_gc, f"📊 Plafond GC — {owner}"), unsafe_allow_html=True)
    st.markdown(cap_bar_html((total_ce_incl if pen_ce else total_ce), cap_ce, f"📊 Plafond CE — {owner}"), unsafe_allow_html=True)

    st.divider()

    # Picks
    teams = sorted(list(LOGOS.keys()))
    picks = st.session_state.get("picks")
    if not isinstance(picks, dict) or st.session_state.get("_picks_season") != str(st.session_state.get("season")):
        picks = load_picks(str(st.session_state.get("season")), teams)
        st.session_state["picks"] = picks
        st.session_state["_picks_season"] = str(st.session_state.get("season"))

    my_picks = picks.get(owner, {}) if isinstance(picks, dict) else {}
    st.markdown("### 🎯 Choix de repêchage")
    years = sorted([str(y) for y in (my_picks.keys() if isinstance(my_picks, dict) else [])])
    total_slots = len(years) * 8 if years else 0

    rows = []
    owned_count = 0
    if isinstance(my_picks, dict):
        for y in years:
            rounds = my_picks.get(y, {}) if isinstance(my_picks.get(y, {}), dict) else {}
            for r in range(1, 9):
                holder = str(rounds.get(str(r), owner)).strip()
                rows.append({"Année": int(y), "Ronde": r, "Appartient à": holder})
                if holder == owner:
                    owned_count += 1

    st.write(f"Choix appartenant à **{owner}** : **{owned_count} / {total_slots}** (3 années × 8 rondes).")
    st.caption("Les échanges peuvent inclure des choix 2025/2026/2027 (selon la saison). La ronde 8 peut être verrouillée ailleurs si tu veux une règle stricte.")

    df_picks = pd.DataFrame(rows).sort_values(["Année", "Ronde"])
    st.dataframe(df_picks, use_container_width=True, hide_index=True)
    st.divider()

    # Buyout
    st.markdown("### 💥 Rachat de contrat (pénalité 50%)")

    # UI compact (sélection moins large)
    left, right = st.columns([2.2, 1], vertical_alignment="top")
    with left:
        opts = sorted(dprop["Joueur"].astype(str).dropna().unique().tolist())
        joueur = st.selectbox("Joueur", opts, key="gm_buyout_player") if opts else ""
    with right:
        bucket = st.radio("Appliquer sur", ["Rachat GC", "Rachat CE"], horizontal=False, key="gm_buyout_bucket")

    if joueur:
        row = dprop[dprop["Joueur"].astype(str).eq(joueur)].iloc[0]
        salaire = int(row.get("Salaire", 0) or 0)
        penalite = int(round(salaire * 0.5))
        bucket_code = "GC" if bucket == "Rachat GC" else "CE"

        st.info(
            f"Salaire: **{money(salaire)}** → Pénalité: **{money(penalite)}** "
            f"(ajoutée à la masse **{bucket_code}**)"
        )

        # bouton dédié sous le choix (comme demandé)
        if st.button("✅ Confirmer le rachat", type="primary", use_container_width=True, key="gm_buyout_ok"):
            # Charger buyouts
            b = st.session_state.get("buyouts")
            if b is None or not isinstance(b, pd.DataFrame) or st.session_state.get("_buyouts_season") != str(st.session_state.get("season")):
                b = load_buyouts(str(st.session_state.get("season")))

            rec = {
                "timestamp": datetime.now(TZ_TOR).strftime("%Y-%m-%d %H:%M:%S"),
                "season": str(st.session_state.get("season")),
                "proprietaire": owner,
                "joueur": joueur,
                "salaire": salaire,
                "penalite": penalite,
                "bucket": bucket_code,
            }
            b = pd.concat([b, pd.DataFrame([rec])], ignore_index=True)
            st.session_state["buyouts"] = b
            st.session_state["_buyouts_season"] = str(st.session_state.get("season"))
            save_buyouts(str(st.session_state.get("season")), b)

            # Historique: une entrée claire
            try:
                log_history_row(
                    proprietaire=owner,
                    joueur=joueur,
                    pos=str(row.get("Pos", "") or ""),
                    equipe=str(row.get("Equipe", "") or ""),
                    from_statut=str(row.get("Statut", "") or ""),
                    from_slot=str(row.get("Slot", "") or ""),
                    to_statut="",
                    to_slot="",
                    action=f"RACHAT {bucket_code} (50%)",
                )
            except Exception:
                pass

            # Retirer le joueur du roster
            df2 = st.session_state.get("data", df).copy()
            m = df2["Propriétaire"].astype(str).str.strip().eq(owner) & df2["Joueur"].astype(str).str.strip().eq(joueur)
            df2 = df2.loc[~m].copy()
            st.session_state["data"] = clean_data(df2)
            persist_data(st.session_state["data"], str(st.session_state.get("season")))

            # Rebuild plafonds (avec pénalité dans GC/CE)
            st.session_state["plafonds"] = rebuild_plafonds(st.session_state["data"])
            st.toast(f"✅ Rachat appliqué. Pénalité ajoutée à la masse {bucket_code}.", icon="✅")
            do_rerun()


    st.divider()
    st.markdown("### 🔁 Marché des échanges")
    st.caption("Marque les joueurs de ton équipe comme disponibles sur le marché des échanges.")

    tm = load_trade_market(season)
    owner = str(get_selected_team() or "").strip()
    df_all = st.session_state.get("data", pd.DataFrame(columns=REQUIRED_COLS))
    df_all = clean_data(df_all) if isinstance(df_all, pd.DataFrame) else pd.DataFrame(columns=REQUIRED_COLS)

    dprop = df_all[df_all.get("Propriétaire","").astype(str).str.strip().eq(owner)].copy() if owner else pd.DataFrame()
    options = []
    if not dprop.empty:
        for j in sorted(dprop["Joueur"].dropna().astype(str).unique().tolist()):
            if j.strip():
                options.append(j.strip())

    selected_now = []
    if options:
        for j in options:
            if is_on_trade_market(tm, owner, j):
                selected_now.append(j)

    picked = st.multiselect(
        "Joueurs sur le marché",
        options,
        default=selected_now,
        key="gm_trade_market_ms",
    )

    cA, cB = st.columns([1, 1])
    with cA:
        if st.button("💾 Enregistrer", type="primary", use_container_width=True, key="gm_trade_market_save"):
            # reset owner entries then set selected
            if owner:
                tm[str(owner)] = {str(j): True for j in (picked or [])}
                save_trade_market(season, tm)
                st.toast("✅ Marché mis à jour", icon="✅")
                do_rerun()
    with cB:
        if st.button("🧹 Tout retirer", use_container_width=True, key="gm_trade_market_clear"):
            if owner:
                tm[str(owner)] = {}
                save_trade_market(season, tm)
                st.toast("✅ Marché vidé", icon="✅")
                do_rerun()

elif active_tab == "👤 Joueurs autonomes":
    st.subheader("👤 Joueurs autonomes")
    st.caption("Recherche dans la base — aucun résultat tant qu’aucun filtre n’est rempli.")

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
            q_raw = st.text_input("Nom / Prénom", placeholder="Tape 3 lettres…", key="j_name")

            # 🔎 Autocomplete (3+ lettres) → suggestions
            q_name = q_raw
            if isinstance(df_db, pd.DataFrame) and "Player" in df_db.columns and str(q_raw or "").strip() and len(str(q_raw).strip()) >= 3:
                _q = str(q_raw).strip()
                _cand = (
                    df_db["Player"].astype(str)
                    .dropna()
                    .loc[lambda s: s.str.contains(_q, case=False, na=False)]
                    .drop_duplicates()
                    .head(40)
                    .tolist()
                )
                if _cand:
                    picked = st.selectbox(
                        "Suggestions",
                        ["—"] + _cand,
                        index=0,
                        key="fa_suggest_pick",
                        help="Choisis un joueur pour compléter automatiquement",
                    )
                    if picked and picked != "—":
                        q_name = picked
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

            # --- GP / Games Played (NHL) + admissibilité (≠ELC et <85 GP)
            gp_col = None
            for cand in ["GP", "Games", "Games Played", "NHL GP", "GP NHL", "GP_NHL", "games_played"]:
                if cand in dff.columns:
                    gp_col = cand
                    break
            if gp_col:
                dff["_gp_int"] = pd.to_numeric(dff[gp_col], errors="coerce").fillna(0).astype(int)
            else:
                dff["_gp_int"] = 0

            lvl_col = "Level" if "Level" in dff.columns else None
            dff["_lvl_norm"] = dff[lvl_col].astype(str).str.strip().str.upper() if lvl_col else ""

            dff["_admissible"] = (dff["_lvl_norm"] != "ELC") & (dff["_gp_int"] < 85)

            only_eligible = st.checkbox(
                "Afficher seulement les joueurs admissibles (≠ ELC et < 85 matchs NHL)",
                value=True,
                key="fa_only_eligible",
            )
            if only_eligible:
                dff = dff[dff["_admissible"]].copy()

            # Tableau affiché
            show_cols = [c for c in ["Player", "Team", "Position", (gp_col or ""), cap_col, "Level"] if c and c in dff.columns]
            df_show = dff[show_cols].copy()

            if gp_col and gp_col in df_show.columns:
                df_show = df_show.rename(columns={gp_col: "GP"})

            if cap_col and cap_col in df_show.columns:
                df_show[cap_col] = df_show[cap_col].apply(lambda x: _money_space(_cap_to_int(x)))
                df_show = df_show.rename(columns={cap_col: "Cap Hit"})

            for c in df_show.columns:
                df_show[c] = df_show[c].apply(_clean_intlike)

            st.dataframe(df_show, use_container_width=True, hide_index=True)

    # =====================================================
    # 🎯 Sélection / Réclamations (Joueurs autonomes)
    #   - Affiche Propriétaire si déjà détenu
    #   - Sélection via cases (max 5 par équipe)
    #   - Destination GC/CE par joueur
    #   - Les réclamations apparaissent ensuite dans 📊 Tableau selon le classement (points)
    # =====================================================

    # Map joueurs déjà détenus (pour afficher Propriétaire)
    df_roster = st.session_state.get("data", pd.DataFrame(columns=REQUIRED_COLS))
    df_roster = clean_data(df_roster) if isinstance(df_roster, pd.DataFrame) else pd.DataFrame(columns=REQUIRED_COLS)

    owned_map = {}
    try:
        tmp_owned = df_roster[["Propriétaire", "Joueur"]].copy()
        tmp_owned["_k"] = tmp_owned["Joueur"].astype(str).map(_norm_name)
        for _, rr in tmp_owned.iterrows():
            owned_map[str(rr["_k"])] = str(rr["Propriétaire"]).strip()
    except Exception:
        owned_map = {}

    # Ajouter colonne Propriétaire (si déjà détenu)
    if "Player" in dff.columns:
        dff["_owner"] = dff["Player"].astype(str).map(lambda x: owned_map.get(_norm_name(x), ""))

    only_unowned = st.checkbox(
        "Afficher seulement les joueurs vraiment autonomes (non signés)",
        value=True,
        key="fa_only_unowned",
    )
    if only_unowned and "_owner" in dff.columns:
        dff = dff[dff["_owner"].astype(str).str.strip().eq("")].copy()

    # Table sélectionnable
    df_pick = dff.copy()
    df_pick["_sel"] = False
    df_pick["_dest"] = "GC"

    show_cols = []
    if "_sel" in df_pick.columns: show_cols.append("_sel")
    for c in ["Player", "Team", "Position", "Level"]:
        if c in df_pick.columns: show_cols.append(c)
    if gp_col and "_gp_int" in df_pick.columns:
        show_cols.append("_gp_int")
    if "_owner" in df_pick.columns:
        show_cols.append("_owner")
    if "_dest" in df_pick.columns:
        show_cols.append("_dest")

    df_view = df_pick[show_cols].copy()
    rename = {"_sel": "✅", "_gp_int": "GP", "_owner": "Propriétaire", "_dest": "Destination"}
    df_view = df_view.rename(columns=rename)

    st.caption("Coche des joueurs (max 5) puis choisis Destination (GC/CE).")

    edited = st.data_editor(
        df_view,
        use_container_width=True,
        hide_index=True,
        column_config={
            "✅": st.column_config.CheckboxColumn("✅", help="Sélectionner", default=False),
            "Destination": st.column_config.SelectboxColumn("Destination", options=["GC", "CE"]),
        },
        disabled=[c for c in df_view.columns if c not in {"✅", "Destination"}],
        key="fa_editor",
    )

    # Extract selected rows
    picked = edited[edited["✅"] == True].copy() if isinstance(edited, pd.DataFrame) and "✅" in edited.columns else pd.DataFrame()
    if not picked.empty and len(picked) > 5:
        st.warning("Maximum 5 joueurs sélectionnés. Garde les 5 que tu veux.")
        picked = picked.head(5)

    # Enregistrer comme réclamations pour l'équipe courante
    owner_me = str(get_selected_team() or "").strip()
    if not owner_me:
        st.info("Choisis une équipe (dans 📊 Tableau) avant de créer des réclamations.")
    else:
        if st.button("📌 Ajouter à ma liste de réclamations (max 5)", type="primary", use_container_width=True, key="fa_add_claims"):
            _init_fa_claims()
            cur_claims = st.session_state["fa_claims"].get(owner_me, [])
            # rebuild list (on remplace l'ancienne sélection)
            new_claims = []
            for _, rr in picked.iterrows():
                pname = str(rr.get("Player", "")).strip()
                dest = str(rr.get("Destination", "GC")).strip() or "GC"
                if pname:
                    new_claims.append({"player": pname, "dest": dest})
            if len(new_claims) > 5:
                new_claims = new_claims[:5]
            st.session_state["fa_claims"][owner_me] = new_claims
            persist_fa_claims(st.session_state["fa_claims"], season)
            st.toast("✅ Réclamations enregistrées", icon="✅")

        # Afficher la liste actuelle
        _init_fa_claims()
        cur_claims = st.session_state["fa_claims"].get(owner_me, [])
        if cur_claims:
            st.markdown("#### 📌 Mes réclamations")
            st.dataframe(pd.DataFrame(cur_claims).rename(columns={"player": "Joueur", "dest": "Destination"}), use_container_width=True, hide_index=True)
            if st.button("🗑️ Vider mes réclamations", use_container_width=True, key="fa_clear_claims"):
                st.session_state["fa_claims"][owner_me] = []
                persist_fa_claims(st.session_state["fa_claims"], season)
                do_rerun()


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

    # -------------------------------------------------
    # ✅ Approbation requise (2 propriétaires)
    # -------------------------------------------------
    latest = latest_trade_proposal(season)
    if latest:
        oa = str(latest.get("owner_a","")).strip()
        ob = str(latest.get("owner_b","")).strip()
        status = str(latest.get("status","")).strip()
        created = format_date_fr(latest.get("created_at"))
        st.markdown("### ✅ Dernière proposition d'échange")
        left, right = st.columns([3, 2], vertical_alignment="center")
        with left:
            st.markdown(f"**{oa}** ⇄ **{ob}**")
            st.caption(f"Créée le {created} — statut: **{status}**")
        with right:
            # Les checkboxes sont activées seulement pour les équipes concernées
            current_team = str(get_selected_team() or "").strip()
            can_a = (current_team == oa)
            can_b = (current_team == ob)

            a_prev = str(latest.get("approved_a","")).lower() in {"true","1","yes"}
            b_prev = str(latest.get("approved_b","")).lower() in {"true","1","yes"}

            a_ok = st.checkbox(f"Approuvé par {oa}", value=a_prev, disabled=(not can_a), key=f"appr_a_{latest['id']}")
            b_ok = st.checkbox(f"Approuvé par {ob}", value=b_prev, disabled=(not can_b), key=f"appr_b_{latest['id']}")

            if can_a and (a_ok != a_prev):
                approve_trade_proposal(season, latest["id"], oa, a_ok)
                st.toast("✅ Approbation mise à jour", icon="✅")
                do_rerun()
            if can_b and (b_ok != b_prev):
                approve_trade_proposal(season, latest["id"], ob, b_ok)
                st.toast("✅ Approbation mise à jour", icon="✅")
                do_rerun()

        # Détails compact
        with st.expander("📦 Détails de la proposition", expanded=False):
            st.markdown(f"**{oa} donne**: {', '.join(latest.get('a_players',[]) or []) or '—'}")
            st.markdown(f"**{oa} picks**: {', '.join(latest.get('a_picks',[]) or []) or '—'}")
            st.markdown(f"**{ob} donne**: {', '.join(latest.get('b_players',[]) or []) or '—'}")
            st.markdown(f"**{ob} picks**: {', '.join(latest.get('b_picks',[]) or []) or '—'}")
            if str(latest.get("note","")).strip():
                st.caption(f"Note: {latest['note']}")

        st.divider()
    st.caption("Construis une transaction (joueurs + choix + salaire retenu) et vois l’impact sur les masses salariales.")

    plafonds = st.session_state.get("plafonds")
    df = st.session_state.get("data")
    if df is None or df.empty or plafonds is None or plafonds.empty:
        st.info("Aucune donnée pour cette saison. Va dans 🛠️ Gestion Admin → Import.")
        st.stop()

    owners = sorted(plafonds["Propriétaire"].dropna().astype(str).str.strip().unique().tolist())
    if len(owners) < 2:
        st.info("Il faut au moins 2 équipes pour bâtir une transaction.")
        st.stop()

    picks = load_picks(season, sorted(list(LOGOS.keys())))
    market = load_trade_market(season) if "load_trade_market" in globals() else pd.DataFrame(columns=["season","proprietaire","joueur","is_available","updated_at"])

    def _roster(owner: str) -> pd.DataFrame:
        d = df[df["Propriétaire"].astype(str).str.strip().eq(str(owner).strip())].copy()
        d = clean_data(d)
        # on exclut IR du marché par défaut
        if "Slot" in d.columns:
            d = d[d["Slot"].astype(str).str.strip() != SLOT_IR].copy()
        return d

    def _player_label(r) -> str:
        j = str(r.get("Joueur","")).strip()
        pos = str(r.get("Pos","")).strip()
        team = str(r.get("Equipe","")).strip()
        lvl = str(r.get("Level","")).strip()
        sal = int(pd.to_numeric(r.get("Salaire",0), errors="coerce") or 0)
        flag = "🔁 " if is_on_trade_market(market, str(r.get("Propriétaire","")), j) else ""
        return f"{flag}{j} · {pos} · {team} · {lvl or '—'} · {money(sal)}"

    def _owner_picks(owner: str):
        """Retourne les choix détenus par owner sous forme 'YYYY — R{round} — {orig}' (rondes 1-7)."""
        out = []
        if isinstance(picks, dict) and picks:
            for orig_team, years_map in (picks or {}).items():
                if not isinstance(years_map, dict):
                    continue
                for year, rounds in years_map.items():
                    if not isinstance(rounds, dict):
                        continue
                    for rd, holder in rounds.items():
                        try:
                            rdi = int(rd)
                        except Exception:
                            continue
                        if rdi >= 8:  # 8e ronde non échangeable
                            continue
                        if str(holder).strip() == str(owner).strip():
                            out.append(f"{year} — R{rdi} — {orig_team}")
        def _k(x: str):
            m1 = re.search(r"^(\d{4})", x)
            m2 = re.search(r"R(\d+)", x)
            y = int(m1.group(1)) if m1 else 0
            r = int(m2.group(1)) if m2 else 0
            return (y, r, x)
        return sorted(out, key=_k)

# --- Choix des 2 propriétaires côte à côte
    cA, cB = st.columns(2, vertical_alignment="top")
    with cA:
        owner_a = st.selectbox("Propriétaire A", owners, index=0, key="tx_owner_a")
    with cB:
        owner_b = st.selectbox("Propriétaire B", owners, index=1 if len(owners)>1 else 0, key="tx_owner_b")

    if owner_a == owner_b:
        st.warning("Choisis deux propriétaires différents.")
        st.stop()

    st.divider()

    # --- Options marché
    mc1, mc2 = st.columns([1, 2], vertical_alignment="center")
    with mc1:
        market_only = st.checkbox("Afficher seulement joueurs sur le marché", value=False, key="tx_market_only")
    with mc2:
        st.caption("🔁 = joueur annoncé disponible sur le marché des échanges.")

    dfa = _roster(owner_a)
    dfb = _roster(owner_b)

    # --- Sélection multi joueurs + picks
    left, right = st.columns(2, vertical_alignment="top")

    def _multiselect_players(owner: str, dfo: pd.DataFrame, side_key: str):
        if dfo.empty:
            st.info("Aucun joueur.")
            return [], {}

        # options
        rows = dfo.to_dict("records")
        opts = []
        map_lbl_to_name = {}
        for r in rows:
            j = str(r.get("Joueur","")).strip()
            if not j:
                continue
            if market_only and (not is_on_trade_market(market, owner, j)):
                continue
            lbl = _player_label(r)
            opts.append(lbl)
            map_lbl_to_name[lbl] = j

        picked_lbl = st.multiselect("Joueurs inclus", opts, key=f"tx_players_{side_key}")
        picked_names = [map_lbl_to_name[x] for x in picked_lbl if x in map_lbl_to_name]

        # retenue salaire (par joueur)
        retained = {}
        if picked_names:
            st.markdown("**Salaire retenu (optionnel)**")
            for j in picked_names:
                sal = int(pd.to_numeric(dfo.loc[dfo["Joueur"].astype(str).str.strip().eq(j), "Salaire"].iloc[0], errors="coerce") or 0)
                retained[j] = st.number_input(
                    f"Retenu sur {j}",
                    min_value=0,
                    max_value=int(sal),
                    step=50_000,
                    value=0,
                    key=f"tx_ret_{side_key}_{re.sub(r'[^a-zA-Z0-9_]', '_', j)[:40]}",
                )

        # picks
        owner_picks = _owner_picks(owner)
        picked_picks = st.multiselect("Choix de repêchage (R1–R7)", owner_picks, key=f"tx_picks_{side_key}")

        # montants retenus global (cash) — optionnel
        cash = st.number_input("Montant retenu (cash) — optionnel", min_value=0, step=50_000, value=0, key=f"tx_cash_{side_key}")

        return picked_names, {"retained": retained, "picks": picked_picks, "cash": int(cash)}

    with left:
        st.markdown(f"### {owner_a} ➜ envoie")
        a_players, a_meta = _multiselect_players(owner_a, dfa, "A")

    with right:
        st.markdown(f"### {owner_b} ➜ envoie")
        b_players, b_meta = _multiselect_players(owner_b, dfb, "B")

    st.divider()

    # --- Affichage détails (salaire, pos, level, années restantes si dispo)
    def _detail_df(owner: str, dfo: pd.DataFrame, picked: list[str]) -> pd.DataFrame:
        if not picked:
            return pd.DataFrame(columns=["Joueur","Pos","Equipe","Salaire","Level","Années (si dispo)","Marché"])
        tmp = dfo[dfo["Joueur"].astype(str).str.strip().isin([str(x).strip() for x in picked])].copy()
        tmp["Salaire"] = tmp["Salaire"].apply(lambda x: money(int(pd.to_numeric(x, errors="coerce") or 0)))
        tmp["Marché"] = tmp["Joueur"].apply(lambda j: "Oui" if is_on_trade_market(market, owner, str(j)) else "Non")

        # années restantes (si dispo)
        yrs = ""
        for cand in ["Years Left","Years","Yrs","Term","Contract Years Remaining","YearsRemaining"]:
            if cand in tmp.columns:
                yrs = cand
                break
        if yrs:
            tmp["Années (si dispo)"] = tmp[yrs].astype(str)
        else:
            tmp["Années (si dispo)"] = ""

        keep = [c for c in ["Joueur","Pos","Equipe","Salaire","Level","Années (si dispo)","Marché"] if c in tmp.columns]
        return tmp[keep].reset_index(drop=True)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"#### Détails — {owner_a} envoie")
        st.dataframe(_detail_df(owner_a, dfa, a_players), use_container_width=True, hide_index=True)
    with c2:
        st.markdown(f"#### Détails — {owner_b} envoie")
        st.dataframe(_detail_df(owner_b, dfb, b_players), use_container_width=True, hide_index=True)

    # --- Résumé + Impact (approximation simple)
    def _sum_salary(dfo: pd.DataFrame, picked: list[str]) -> int:
        if not picked or dfo.empty:
            return 0
        m = dfo["Joueur"].astype(str).str.strip().isin([str(x).strip() for x in picked])
        return int(pd.to_numeric(dfo.loc[m, "Salaire"], errors="coerce").fillna(0).sum())

    sal_a = _sum_salary(dfa, a_players)
    sal_b = _sum_salary(dfb, b_players)

    ret_a = int(sum((a_meta.get("retained") or {}).values()))
    ret_b = int(sum((b_meta.get("retained") or {}).values()))

    # Impact net (simplifié): l'équipe qui envoie garde la retenue (elle paie), l'équipe qui reçoit ajoute salaire - retenue
    # A reçoit: sal_b - ret_b ; A enlève: sal_a ; A paie: ret_a ; +cash optionnel
    # Net cap A = (sal_b - ret_b) - sal_a + ret_a + cash_A (si tu utilises cash comme pénalité)
    net_a = (sal_b - ret_b) - sal_a + ret_a + int(a_meta.get("cash",0))
    net_b = (sal_a - ret_a) - sal_b + ret_b + int(b_meta.get("cash",0))

    st.markdown("### Résumé")
    s1, s2 = st.columns(2)
    with s1:
        st.markdown(f"**{owner_a}** reçoit: {len(b_players)} joueur(s), {len(b_meta.get('picks',[]))} pick(s)")
        st.caption(f"Variation cap (approx): {money(net_a)} (positif = augmente)")
    with s2:
        st.markdown(f"**{owner_b}** reçoit: {len(a_players)} joueur(s), {len(a_meta.get('picks',[]))} pick(s)")
        st.caption(f"Variation cap (approx): {money(net_b)} (positif = augmente)")
    st.divider()

    # -------------------------------------------------
    # Soumettre une proposition (sera valide seulement après 2 approbations)
    # -------------------------------------------------
    note = st.text_input("Note (optionnel)", value="", key="tx_note")
    if st.button("📨 Soumettre la proposition d'échange", type="primary", use_container_width=True, key="tx_submit"):
        tid = submit_trade_proposal(
            season_lbl=season,
            owner_a=owner_a,
            owner_b=owner_b,
            a_players=a_players,
            b_players=b_players,
            a_picks=a_meta.get("picks", []),
            b_picks=b_meta.get("picks", []),
            a_retained={"retained_total": parse_money(a_meta.get("retained", 0)), "cash": parse_money(a_meta.get("cash", 0))},
            b_retained={"retained_total": parse_money(b_meta.get("retained", 0)), "cash": parse_money(b_meta.get("cash", 0))},
            note=note,
        )
        st.toast("✅ Proposition soumise. Les 2 équipes doivent approuver.", icon="✅")
        # Log historique (info)
        log_history_row(owner_a, f"ÉCHANGE PROPOSÉ → {owner_b}", "", "", "", "", "", "", f"trade_proposal:{tid}")
        log_history_row(owner_b, f"ÉCHANGE PROPOSÉ → {owner_a}", "", "", "", "", "", "", f"trade_proposal:{tid}")
        do_rerun()

    # Marché des échanges: déplacé dans l’onglet 🧑‍💼 GM.


elif active_tab == "🛠️ Gestion Admin":
    if not is_admin:
        st.warning("Accès admin requis.")
        st.stop()

    st.subheader("🛠️ Gestion Admin")


    # =====================================================
    # 📥 Import Fantrax par équipe (RESTORÉ)
    #   - Preview + Confirmer
    #   - Enregistre un manifest des imports (fantrax_by_team)
    # =====================================================
    manifest = load_init_manifest() or {}
    if "fantrax_by_team" not in manifest:
        manifest["fantrax_by_team"] = {}

    with st.expander("📥 Importer un alignement Fantrax (par équipe)", expanded=True):
        teams = sorted(list(LOGOS.keys())) or []
        default_owner = str(st.session_state.get("selected_team") or (teams[0] if teams else "")).strip()
        if teams and default_owner not in teams:
            default_owner = teams[0]

        chosen_owner = st.selectbox(
            "Importer l'alignement dans quelle équipe ?",
            teams if teams else [""],
            index=(teams.index(default_owner) if teams and default_owner in teams else 0),
            key="admin_import_team_pick",
        )

        clear_team_before = st.checkbox(
            f"Vider l’alignement de {chosen_owner} avant import",
            value=True,
            help="Recommandé si tu réimportes la même équipe.",
            key="admin_clear_team_before",
        )

        u_nonce = int(st.session_state.get("uploader_nonce", 0))
        init_align = st.file_uploader(
            "CSV — Alignement (Fantrax)",
            type=["csv", "txt"],
            key=f"admin_import_align__{season}__{chosen_owner}__{u_nonce}",
        )

        cbtn1, cbtn2 = st.columns([1, 1])
        with cbtn1:
            if st.button("👀 Prévisualiser", use_container_width=True, key="admin_preview_import"):
                if init_align is None:
                    st.warning("Choisis un fichier CSV alignement avant de prévisualiser.")
                else:
                    try:
                        buf = io.BytesIO(init_align.getbuffer())
                        buf.name = getattr(init_align, "name", "fantrax.csv")
                        df_import = parse_fantrax(buf)

                        # force owner + clean + inject levels
                        df_import = ensure_owner_column(df_import, fallback_owner=chosen_owner)
                        df_import["Propriétaire"] = str(chosen_owner).strip()
                        df_import = clean_data(df_import)

                        # Level inject (si base dispo)
                        players_db = st.session_state.get("players_db") or load_players_db(PLAYERS_DB_FILE)
                        if isinstance(players_db, pd.DataFrame) and not players_db.empty:
                            df_import = inject_levels(df_import, players_db)

                        st.session_state["init_preview_df"] = df_import
                        st.session_state["init_preview_owner"] = str(chosen_owner).strip()
                        st.session_state["init_preview_filename"] = getattr(init_align, "name", "fantrax.csv")
                        st.success(f"✅ Preview prête — {len(df_import)} joueur(s) pour **{chosen_owner}**.")
                    except Exception as e:
                        st.error(f"❌ Preview échouée : {type(e).__name__}: {e}")

        preview_df = st.session_state.get("init_preview_df")
        if isinstance(preview_df, pd.DataFrame) and not preview_df.empty:
            st.dataframe(preview_df.head(30), use_container_width=True, hide_index=True)

        with cbtn2:
            disabled_confirm = not (isinstance(preview_df, pd.DataFrame) and not preview_df.empty)
            if st.button("✅ Confirmer l'import", use_container_width=True, disabled=disabled_confirm, key="admin_confirm_import"):
                df_team = st.session_state.get("init_preview_df").copy()
                owner_final = str(st.session_state.get("init_preview_owner", chosen_owner) or "").strip()
                filename_final = str(st.session_state.get("init_preview_filename", "") or "").strip()

                df_cur = clean_data(st.session_state.get("data", pd.DataFrame(columns=REQUIRED_COLS)))

                if clear_team_before:
                    keep = df_cur[df_cur["Propriétaire"].astype(str).str.strip() != owner_final].copy()
                    df_new = pd.concat([keep, df_team], ignore_index=True)
                else:
                    df_new = pd.concat([df_cur, df_team], ignore_index=True)

                # dédoublonnage (même joueur même owner)
                if {"Propriétaire", "Joueur"}.issubset(df_new.columns):
                    df_new["Propriétaire"] = df_new["Propriétaire"].astype(str).str.strip()
                    df_new["Joueur"] = df_new["Joueur"].astype(str).str.strip()
                    df_new = df_new.drop_duplicates(subset=["Propriétaire", "Joueur"], keep="last")

                df_new = clean_data(df_new)

                # reinject levels si possible
                players_db = st.session_state.get("players_db")
                if isinstance(players_db, pd.DataFrame) and not players_db.empty:
                    df_new = inject_levels(df_new, players_db)

                st.session_state["data"] = df_new
                persist_data(df_new, season)

                st.session_state["plafonds"] = rebuild_plafonds(df_new)
                st.session_state["selected_team"] = owner_final

                manifest["fantrax_by_team"][owner_final] = {
                    "uploaded_name": filename_final,
                    "season": season,
                    "saved_at": datetime.now(TZ_TOR).isoformat(timespec="seconds"),
                    "team": owner_final,
                }
                save_init_manifest(manifest)

                st.session_state["uploader_nonce"] = int(st.session_state.get("uploader_nonce", 0)) + 1
                st.session_state.pop("init_preview_df", None)
                st.session_state.pop("init_preview_owner", None)
                st.session_state.pop("init_preview_filename", None)

                st.success(f"✅ Import OK — équipe **{owner_final}** mise à jour.")
                do_rerun()

    st.divider()


    # =====================================================
    # ✅ Console Admin — Ajout / Retrait joueur (note obligatoire)
    # =====================================================
        
    # =====================================================
    # ✅ Console Admin — Ajout / Retrait joueur (note obligatoire)
    # =====================================================
    with st.expander("➕➖ Ajouter / Retirer un joueur (ADMIN)", expanded=False):
        st.caption("Seule la gestion Admin peut ajouter/retirer un joueur d'une équipe. Une note est obligatoire et chaque action est inscrite à l'historique.")
        df = st.session_state.get("data", pd.DataFrame(columns=REQUIRED_COLS))
        df = clean_data(df) if isinstance(df, pd.DataFrame) else pd.DataFrame(columns=REQUIRED_COLS)

        owners = []
        try:
            pl = st.session_state.get("plafonds")
            if isinstance(pl, pd.DataFrame) and not pl.empty and "Propriétaire" in pl.columns:
                owners = sorted([str(x).strip() for x in pl["Propriétaire"].dropna().tolist()])
        except Exception:
            owners = sorted(df["Propriétaire"].dropna().astype(str).unique().tolist()) if "Propriétaire" in df.columns else []

        a_owner = st.selectbox("Propriétaire", owners if owners else [""], key="adm_owner_pick")
        action = st.radio("Action", ["Ajouter", "Retirer"], horizontal=True, key="adm_add_remove")
        note = st.text_input("Note (obligatoire)", key="adm_note")

        if action == "Ajouter":
            pname = st.text_input("Joueur (nom exact)", key="adm_add_player")
            dest = st.radio("Destination", ["GC", "CE"], horizontal=True, key="adm_add_dest")
            if st.button("✅ Ajouter le joueur", type="primary", use_container_width=True, key="adm_add_btn"):
                if not note.strip():
                    st.error("La note est obligatoire.")
                elif not a_owner.strip() or not pname.strip():
                    st.error("Propriétaire et joueur requis.")
                else:
                    ok = hire_free_agent(a_owner.strip(), pname.strip(), dest, note.strip())
                    if ok:
                        st.toast("✅ Joueur ajouté", icon="✅")
                        do_rerun()
                    else:
                        st.error(st.session_state.get("last_move_error", "Impossible d'ajouter le joueur."))
        else:
            team_players = []
            try:
                team_players = sorted(
                    df[df["Propriétaire"].astype(str).str.strip().eq(str(a_owner).strip())]["Joueur"]
                    .dropna()
                    .astype(str)
                    .tolist()
                )
            except Exception:
                team_players = []
            pname = st.selectbox("Joueur à retirer", team_players if team_players else [""], key="adm_remove_player")
            if st.button("🗑️ Retirer le joueur", type="primary", use_container_width=True, key="adm_remove_btn"):
                if not note.strip():
                    st.error("La note est obligatoire.")
                elif not a_owner.strip() or not pname.strip():
                    st.error("Propriétaire et joueur requis.")
                else:
                    try:
                        mask_owner = df["Propriétaire"].astype(str).str.strip().eq(str(a_owner).strip())
                        mask_player = df["Joueur"].astype(str).map(_norm_name).eq(_norm_name(pname))
                        df2 = df.loc[~(mask_owner & mask_player)].copy()
                        st.session_state["data"] = clean_data(df2)
                        persist_data(st.session_state["data"], season)
                        log_history_row(
                            proprietaire=str(a_owner).strip(),
                            joueur=str(pname).strip(),
                            pos="",
                            equipe="",
                            from_statut="",
                            from_slot="",
                            to_statut="",
                            to_slot="",
                            action=f"RETRAIT ADMIN — {note.strip()}",
                        )
                        st.toast("✅ Joueur retiré", icon="✅")
                        do_rerun()
                    except Exception as ex:
                        st.error(f"Erreur: {ex}")

    # =====================================================
    # 🔌 Test de persistance (local)
    # =====================================================
    with st.expander("🔌 Tester la sauvegarde", expanded=False):
        if st.button("🧪 Tester écriture/lecture locale", use_container_width=True, key="adm_test_storage"):
            try:
                test_path = os.path.join(DATA_DIR, f"_test_write_{season}.txt")
                with open(test_path, "w", encoding="utf-8") as f:
                    f.write("ok")
                ok = os.path.exists(test_path) and open(test_path, "r", encoding="utf-8").read().strip() == "ok"
                st.success("✅ Sauvegarde locale OK" if ok else "❌ Test local échoué")
            except Exception as ex:
                st.error(f"❌ Test local échoué: {ex}")

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
    st.caption("Une recommandation unique par équipe (résumé).")

    plafonds0 = st.session_state.get("plafonds")
    df = st.session_state.get("data")
    if df is None or df.empty or plafonds0 is None or plafonds0.empty:
        st.info("Aucune donnée pour cette saison. Va dans 🛠️ Gestion Admin → Import.")
        st.stop()

    rows = []
    for _, r in plafonds0.iterrows():
        owner = str(r.get("Propriétaire", "")).strip()
        dispo_gc = int(r.get("Montant Disponible GC", 0) or 0)
        dispo_ce = int(r.get("Montant Disponible CE", 0) or 0)

        # Une seule ligne par équipe
        if dispo_gc < 2_000_000:
            reco = "Rétrogradation recommandée (manque de marge GC)"
            lvl = "warn"
        elif dispo_ce > 10_000_000:
            reco = "Rappel possible (marge CE élevée)"
            lvl = "ok"
        else:
            reco = "Aucune action urgente"
            lvl = "ok"

        rows.append({"Équipe": owner, "Marge GC": money(dispo_gc), "Marge CE": money(dispo_ce), "Recommandation": reco, "_lvl": lvl})

    out = pd.DataFrame(rows).sort_values(by=["Équipe"], kind="mergesort").reset_index(drop=True)
    st.dataframe(out.drop(columns=["_lvl"]), use_container_width=True, hide_index=True)


else:
    st.warning("Onglet inconnu")