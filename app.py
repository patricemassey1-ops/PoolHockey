from __future__ import annotations

import os
import io
import uuid
import re
import unicodedata
import json
import html
import base64
import hashlib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import inspect


# =====================================================
# TIMEZONE (safe)
# =====================================================
try:
    TZ_TOR = ZoneInfo("America/Montreal")
except Exception:
    TZ_TOR = None




# =====================================================
# Helpers — clés joueurs (global, utilisé partout)
#   ⚠️ Doit être défini AVANT l'UI (Transactions, Autonomes, etc.)
# =====================================================
def _strip_accents(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))

def _norm_player_key(s: str) -> str:
    """Normalise un nom pour matching robuste (accents, ponctuation, espaces)."""
    s = _strip_accents(str(s or "")).lower().strip()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

# =====================================================
# SAFE IMAGE (evite MediaFileHandler: Missing file)
# =====================================================
def safe_image(image, *args, **kwargs):
    """Wrapper st.image safe: accepte path str ou objet image."""
    try:
        if isinstance(image, str):
            p = image.strip()
            if p and os.path.exists(p):
                return st.image(p, *args, **kwargs)
            cap = kwargs.get("caption") or ""
            if cap:
                st.caption(cap)
            return None
        return st.image(image, *args, **kwargs)
    except Exception:
        cap = kwargs.get("caption") or ""
        if cap:
            st.caption(cap)
        return None


# =====================================================
# app.py — PMS Pool (version propre + corrections + Admin complet)
#   ✅ 1 seule section Alignement (dans le routing)
#   ✅ sidebar = source de vérité (sync selected_team / align_owner)
#   ✅ Admin Import (preview + confirmer + tri imports)
# =====================================================

# =====================================================
# IMPORTS


# =====================================================

# =====================================================
# Level override helper (alias) — must exist before Admin import preview
# =====================================================
def force_level_from_players(df: pd.DataFrame) -> pd.DataFrame:
    """Compat wrapper: Admin import calls this; delegates to apply_players_level when available."""
    try:
        fn = globals().get("apply_players_level")
        if callable(fn):
            return fn(df)
    except Exception:
        pass
    return df





# =====================================================
# PATHS — repo local (Streamlit Cloud safe)
#   ✅ Place tes logos à côté de app.py:
#      - logo_pool.png
#      - gm_logo.png
# =====================================================
APP_DIR = os.path.dirname(os.path.abspath(__file__))

def _resolve_local_logo(candidates: list[str]) -> str:
    """Retourne le 1er fichier existant (recherche robuste).

    Ordre de recherche:
      1) APP_DIR (dossier de app.py)
      2) CWD (working dir Streamlit)
      3) data/ (si présent)
    """
    search_dirs = [APP_DIR, os.getcwd(), os.path.join(os.getcwd(), "data"), os.path.join(APP_DIR, "data")]
    for name in candidates:
        for d in search_dirs:
            p = os.path.join(d, name)
            if os.path.exists(p):
                return p
    # chemin attendu (même si absent) pour diagnostic
    return os.path.join(APP_DIR, candidates[0])  # chemin attendu (même si absent)

# Logos critiques (local, stable) — mets-les à côté de app.py
LOGO_POOL_FILE = _resolve_local_logo(["logo_pool.png","Logo_Pool.png","LOGO_POOL.png","logo_pool.jpg","Logo_Pool.jpg"])
GM_LOGO_FILE = _resolve_local_logo(["gm_logo.png","GM_LOGO.png","gm_logo.jpg"])
# =====================================================
# STREAMLIT CONFIG (MUST BE FIRST STREAMLIT COMMAND)
# =====================================================
st.set_page_config(page_title="PMS", layout="wide")

# --- BOOT LOOP GUARD (soft)
# Streamlit peut exécuter le script plusieurs fois au chargement initial.
# On ne bloque jamais l'UI ici: au pire on désactive les rerun automatiques.
_boot_now = datetime.now(TZ_TOR) if ("TZ_TOR" in globals() and TZ_TOR) else datetime.now()
_boot_ts = st.session_state.get("_boot_ts")
_boot_count = int(st.session_state.get("_boot_count", 0) or 0)
_boot_armed = bool(st.session_state.get("_boot_armed", False))

if _boot_ts:
    try:
        _boot_prev = datetime.fromisoformat(str(_boot_ts))
        if (_boot_now - _boot_prev).total_seconds() < 3:
            _boot_count += 1
        else:
            _boot_count = 0
    except Exception:
        _boot_count = 0
else:
    _boot_count = 0

st.session_state["_boot_ts"] = _boot_now.isoformat()
st.session_state["_boot_count"] = _boot_count

# Si armé et boucle forte, on désactive les rerun automatiques au lieu de stopper.
if _boot_armed and _boot_count >= 25:
    st.session_state['_disable_auto_rerun'] = True
    srcinfo = st.session_state.get('_last_rerun_source') or {}
    where = str(srcinfo.get('where',''))
    reason = str(srcinfo.get('reason',''))
    st.warning('⚠️ Boucle de rerun détectée: rerun automatiques désactivés (mode safe).')
    if where or reason:
        st.caption(f"Dernier rerun demandé par: {where} {('— '+reason) if reason else ''}")
    st.info("Va dans la sidebar → change d'onglet/équipe une fois. Si ça persiste: refresh (Ctrl/Cmd+R).")

# --- reset rerun guard each run (prevents "Running/STOP" loop & stuck reruns)
st.session_state["_rerun_requested"] = False
# --- plafonds par défaut (évite cap=0)
if "PLAFOND_GC" not in st.session_state or int(st.session_state.get("PLAFOND_GC") or 0) <= 0:
    st.session_state["PLAFOND_GC"] = 95_500_000
if "PLAFOND_CE" not in st.session_state or int(st.session_state.get("PLAFOND_CE") or 0) <= 0:
    st.session_state["PLAFOND_CE"] = 47_750_000



# =====================================================
# TEAM SELECTION — LOOP-FREE
#   ✅ Aucun do_rerun() déclenché par la sidebar
#   ✅ selected_team est synchronisé depuis selected_team_ui après le widget
# =====================================================

# =====================================================
# GM LOGO (cute) — place gm_logo.png in the project root (same folder as app.py)
# =====================================================
LEGACY_GM_LOGO_FILE = None  # v20: removed duplicate


def _gm_logo_data_uri() -> str | None:
    """Return gm_logo.png as a data URI (base64) so we can style it via HTML/CSS."""
    path = str(GM_LOGO_FILE or "").strip()
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        # PNG expected; if you switch formats, update mime.
        return f"data:image/png;base64,{b64}"
    except Exception:
        return None


def render_gm_logo(active: bool, width: int = 40, tooltip: str = "Gestion d’équipe"):
    """
    GM logo with:
      - grayscale when inactive
      - small hover tooltip
    (Same approach can be reused for Admin later.)
    """
    uri = _gm_logo_data_uri()
    if not uri:
        return

    cls = "gm-logo active" if active else "gm-logo inactive"
    # title = native browser tooltip (simple + reliable)
    st.session_state['_theme_css_injected'] = True
    st.markdown(
        f"""
        <div class="gm-logo-wrap" title="{html.escape(tooltip)}">
            <img class="{cls}" src="{uri}" width="{int(width)}" />
        </div>
        """,
        unsafe_allow_html=True,
    )


# Backward compatibility (if some older blocks still call it)
def _render_gm_logo(width: int = 36):
    render_gm_logo(active=True, width=width)


# Anti double rerun (zéro surprise)
st.session_state["_rerun_requested"] = False

# =====================================================
# THEME
#   (retiré: pas de Dark/Light)
# =====================================================


# =====================================================
# CSS — Micro-animations + Alertes visuelles + UI polish
#   ✅ coller UNE seule fois, au top du fichier
# =====================================================
# =====================================================
# THEME — une seule injection CSS (Règles d’or)
#   ✅ 1 thème, 1 injection
#   ✅ aucun CSS ailleurs
# =====================================================
THEME_CSS = """

/* v35 Level badges */
.levelBadge{
  display:inline-block;
  padding:2px 10px;
  border-radius:999px;
  font-weight:800;
  font-size:0.82rem;
  letter-spacing:0.4px;
  border:1px solid rgba(255,255,255,0.14);
  background: rgba(255,255,255,0.06);
}
.levelBadge.std{ }
.levelBadge.elc{ }
.levelBadge.unk{
  opacity:0.85;
}
.levelWarn{
  display:inline-block;
  padding:2px 10px;
  border-radius:999px;
  font-weight:800;
  font-size:0.82rem;
  border:1px solid rgba(255,166,0,0.35);
  background: rgba(255,166,0,0.10);
}



/* v28 centered broadcast */
.pms-center-stack { padding: 18px 16px; }
.pms-center-stack img { max-height: 260px; width: auto; }
.pms-under{
  text-align:center;
  font-weight: 800;
  font-size: 3.2rem;
  letter-spacing: 2px;
  margin-top: 6px;
  text-shadow: 0 10px 28px rgba(0,0,0,0.35);
}
.pms-side-emoji{
  font-size: 3.6rem;
  line-height: 1;
  opacity: 0.95;
  filter: drop-shadow(0 12px 24px rgba(0,0,0,0.35));
  display:flex;
  justify-content:center;
  align-items:center;
  height: 100%;
}
/* réduire l’espace au-dessus (blend avec toolbar streamlit) */
section.main > div { padding-top: 0.25rem; }



/* v27: blend the Streamlit top bar line */
section.main > div { padding-top: 0.5rem; }



/* v26 broadcast header */
.pms-broadcast-bar{
  border-radius: 18px;
  padding: 18px 16px;
  margin-top: -6px;
  background: linear-gradient(90deg, rgba(255,255,255,0.05), rgba(255,255,255,0.02), rgba(255,255,255,0.05));
  border: 1px solid rgba(255,255,255,0.10);
  box-shadow: 0 14px 40px rgba(0,0,0,0.30);

}
.pms-title{
  text-shadow: 0 10px 28px rgba(0,0,0,0.35);
  letter-spacing: 1px;
}


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



.dlg-title{font-weight:1000;font-size:16px;line-height:1.1}
      .dlg-sub{opacity:.75;font-weight:800;font-size:12px;margin-top:2px}
      .pill{display:inline-block;padding:2px 10px;border-radius:999px;
            background:rgba(255,255,255,.08);
            border:1px solid rgba(255,255,255,.12);
            font-weight:900;font-size:12px}

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
              .lvlSTD{ color:#60a5fa; font-weight:900; }
              .lvlELC{ color:#a78bfa; font-weight:900; }

.pms-mobile .block-container{padding-top:0.8rem !important; padding-left:0.8rem !important; padding-right:0.8rem !important;}
/* =========================================
   🔐 Login header (password page)
   ========================================= */
.pms-header-wrap{
  display:flex;
  align-items:center;
  gap:12px;
}
.pms-left{
  display:flex;
  align-items:center;
  gap:10px;
}
.pms-right{
  display:flex;
  justify-content:flex-end;
  align-items:center;
}
.pms-title{
  font-weight:800;
  letter-spacing:0.5px;
  font-size:3.6rem;
  line-height:1;
}
.pms-emoji-big{
  font-size:3.9rem; /* bigger sticks + net */
  line-height:1;
}



/* v13: pool logo sizing (pro) */
/* =========================================
   🧑‍💼 GM logo (sidebar): grayscale when inactive
   ========================================= */
.gm-logo-wrap{
  display:flex;
  justify-content:center;
  margin: 2px 0 8px 0;
}
.gm-logo{
  border-radius:10px;
  transition: filter 160ms ease, transform 160ms ease, opacity 160ms ease;
  cursor: default;
}
.gm-logo.inactive{
  filter: grayscale(100%);
  opacity: 0.72;
}
.gm-logo.active{
  filter: none;
  opacity: 1;
}
.gm-logo-wrap:hover .gm-logo{
  transform: translateY(-1px);
}

/* =========================
   GM TAB UI TWEAKS
   ========================= */
.gm-header { display:flex; align-items:center; gap:14px; margin: 0 0 8px 0; }
.gm-header .gm-title { font-size: 18px; font-weight: 800; opacity: .9; }
.gm-mass { font-size: 34px; font-weight: 900; line-height: 1.05; }
.gm-sub { font-size: 12px; opacity: .75; margin-top: 2px; }

.pick-mini {
  display:inline-block;
  width:100%;
  padding:8px 10px;
  border-radius: 14px;
  border: 1px solid rgba(255,255,255,.10);
  background: rgba(255,255,255,.04);
  font-size: 12px;
  line-height: 1.2;
  text-align:center;
  white-space: nowrap;
  overflow:hidden;
  text-overflow: ellipsis;
}
.pick-mini b { font-size: 13px; }



/* =====================================================
   GM TAB (migré depuis st.markdown <style>/*STYLE_REMOVED*/ inline)
   ===================================================== */
.gm-top { display:flex; align-items:center; gap:16px; margin-top:4px; }
.gm-top img { width:132px; } /* 3x */

.gm-team { font-weight:800; font-size:22px; opacity:0.92; }

.gm-grid {
  display:grid;
  grid-template-columns: 1fr 1fr;
  gap:22px;
  margin-top:10px;
}

.gm-card {
  border:1px solid rgba(255,255,255,0.10);
  background: rgba(255,255,255,0.04);
  border-radius:14px;
  padding:14px 14px;
}

.gm-label { font-size:12px; opacity:0.75; margin-bottom:6px; }
.gm-value { font-size:34px; font-weight:900; letter-spacing:0.2px; }

.gm-sub {
  font-size:12px;
  opacity:0.75;
  margin-top:4px;
  display:flex;
  justify-content:space-between;
}

.pick-row { display:flex; gap:8px; flex-wrap:wrap; margin-top:8px; }

.pick-pill {
  padding:6px 10px;
  border-radius:999px;
  font-weight:700;
  border:1px solid rgba(255,255,255,0.14);
  background: rgba(255,255,255,0.04);
}

.pick-pill.mine {
  border-color: rgba(34,197,94,0.55);
  background: rgba(34,197,94,0.10);
}

.pick-pill.other { opacity:0.75; }

.section-title { font-size:22px; font-weight:900; margin: 6px 0 2px; }
.muted { opacity:0.75; font-size:13px; }


/* =====================================================
   GM PICKS — lignes par année
   ===================================================== */
.pick-line { display:flex; align-items:flex-start; gap:12px; margin-top:10px; }
.pick-year { width:88px; min-width:88px; display:flex; flex-direction:column; gap:6px; }
.pick-year .pick-sub { font-size:12px; opacity:0.75; padding-left:4px; }


/* Destination hint */
.dest-hint{
  margin-top: .35rem;
  padding: .45rem .6rem;
  border-radius: .6rem;
  border: 1px solid rgba(46, 204, 113, .45);
  background: rgba(46, 204, 113, .10);
  color: rgba(230, 255, 240, .95);
  font-weight: 600;
}

</style>


/* ===============================
   PICKS — layout fixe & responsive
   =============================== */
.pick-line{
  display: grid;
  grid-template-columns: 84px 1fr;
  gap: 12px;
  align-items: start;
  margin: 10px 0;
}

.pick-year{
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.pick-year-badge{
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 8px 10px;
  border-radius: 999px;
  font-weight: 800;
  letter-spacing: .3px;
  border: 1px solid rgba(34,197,94,.55);
  background: rgba(34,197,94,.10);
}

.pick-sub{
  font-size: 12px;
  opacity: .8;
  padding-left: 6px;
}

.pick-row{
  display: flex;
  gap: 10px;
  flex-wrap: nowrap;
  max-width: 100%;
  overflow-x: auto;
  overflow-y: hidden;
  white-space: nowrap;
  -webkit-overflow-scrolling: touch;
  padding-bottom: 6px;
}

.pick-row::-webkit-scrollbar{ height: 8px; }
.pick-row::-webkit-scrollbar-thumb{ background: rgba(255,255,255,.15); border-radius: 999px; }
.pick-row::-webkit-scrollbar-track{ background: transparent; }

.pick-pill{
  font-size: 13px;
  padding: 7px 10px;
}

/* Mobile */
.mobile .pick-line{
  grid-template-columns: 72px 1fr;
  gap: 10px;
}
.mobile .pick-pill{
  font-size: 12px;
  padding: 6px 8px;
}
.mobile .pick-year-badge{
  padding: 7px 9px;
}


/* ===============================
   GM — petits styles pro
   =============================== */
.gm-card-head{
  margin: 2px 0 12px 0;
}
.gm-card-title{
  font-size: 18px;
  font-weight: 800;
  letter-spacing: 0.2px;
}
.gm-card-sub{
  margin-top: 4px;
  font-size: 13px;
  opacity: 0.75;
}
.gm-metric{
  font-size: 18px;
  font-weight: 800;
  margin-top: 2px;
}"""

def apply_theme():
    if st.session_state.get('_theme_css_injected', False):
        return
    st.markdown(THEME_CSS, unsafe_allow_html=True)

def _set_mobile_class(enabled: bool):
    """No-op (v20): évite les erreurs frontend liées aux <script> inline."""
    return

# Appel UNIQUE
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

PLAYERS_DB_FILE = os.path.join(DATA_DIR, "Hockey.players.csv")  # source: /data/Hockey.players.csv
PLAYERS_DB_FALLBACKS = [
    "data/hockey.players.csv",
    "/data/hockey.players.csv",
    "data/Hockey.players.csv",
    "/data/Hockey.players.csv",
    "data/Hockey.Players.csv",
    "/data/Hockey.Players.csv",
    "Hockey.players.csv",
    "Hockey.Players.csv",
]

# (v18) Logos critiques chargés localement (à côté de app.py)
INIT_MANIFEST_FILE = os.path.join(DATA_DIR, "init_manifest.json")


def _first_existing(paths: list[str]) -> str:
    for p in paths:
        try:
            if p and os.path.exists(p):
                return p
        except Exception:
            pass
    return paths[0] if paths else ""

REQUIRED_COLS = [
    "Propriétaire", "Joueur", "Pos", "Equipe", "Salaire",
    "Level",
    "Statut", "Slot", "IR Date"
]

# Slots
SLOT_ACTIF = "Actif"
SLOT_BANC = "Banc"
SLOT_IR = "Blessé"

SLOT_RACHAT = "RACHAT"
STATUT_GC = "Grand Club"
STATUT_CE = "Club École"


# =====================================================
# 🔐 PASSWORD GATE + HEADER
# =====================================================
def _sha256(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()





def _login_header():
    # =========================
    # LOGIN HEADER — v28 (Broadcast centered)
    #   ✅ Logo pool énorme centré
    #   ✅ PMS en dessous (centré)
    #   ✅ Icônes en support gauche/droite
    # =========================
    logo_file = LOGO_POOL_FILE

    with st.container():
        st.markdown('<div class="pms-broadcast-bar pms-center-stack">', unsafe_allow_html=True)

        left, center, right = st.columns([2, 10, 2], vertical_alignment="center")

        with left:
            st.markdown('<div class="pms-side-emoji">🏒</div>', unsafe_allow_html=True)

        with center:
            # Logo pool (plein espace disponible) — plus "broadcast"
            if isinstance(logo_file, str) and os.path.exists(logo_file):
                st.image(logo_file, use_container_width=True)
            else:
                st.caption("⚠️ logo_pool introuvable. Mets logo_pool.png à côté de app.py.")

            # PMS sous le logo (centré)
            st.markdown('<div class="pms-under">PMS</div>', unsafe_allow_html=True)

        with right:
            st.markdown('<div class="pms-side-emoji">🥅</div>', unsafe_allow_html=True)

        st.markdown('</div>', unsafe_allow_html=True)

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
                do_rerun()
            else:
                st.error("❌ Mot de passe invalide")

    with col2:
        st.info("Astuce: si tu changes le mot de passe, regénère un nouveau hash et remplace-le dans Secrets.")

    st.stop()

require_password()

# Arm the boot-loop guard only AFTER successful auth / first full render.
# This avoids false positives during Streamlit's normal initial multi-runs.
st.session_state["_boot_armed"] = True

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
def do_rerun(reason: str = ''):
    """Rerun sécurisé (diagnostic-friendly).

    - Jamais plus d'un rerun par run
    - Respecte le mode safe (_disable_auto_rerun)
    - Trace la source du rerun pour diagnostiquer les boucles
    """
    if st.session_state.get('_disable_auto_rerun', False):
        return
    if st.session_state.get('_rerun_requested', False):
        return

    # capture caller (ligne/fonction)
    try:
        frm = inspect.stack()[1]
        loc = f"{frm.filename}:{frm.lineno} ({frm.function})"
    except Exception:
        loc = 'unknown'
    st.session_state['_last_rerun_source'] = {'where': loc, 'reason': str(reason or '')}

    st.session_state['_rerun_requested'] = True
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

    # Level (STD / ELC) — peut être ajouté depuis hockey.players.csv
    out["Level"] = out["Level"].astype(str).str.strip()

    out["Statut"] = out["Statut"].astype(str).str.strip().replace({"": STATUT_GC})
    out["Slot"] = out["Slot"].astype(str).str.strip()
    out["IR Date"] = out["IR Date"].astype(str).str.strip()

    bad = {"", "none", "nan", "null"}
    out = out[~out["Joueur"].str.lower().isin(bad)].copy()
    return out.reset_index(drop=True)


# =====================================================
# ENRICH — Level depuis hockey.players.csv (players_db)
# =====================================================
def enrich_level_from_players_db(df: pd.DataFrame) -> pd.DataFrame:
    """Complète df['Level'] (STD/ELC) et df['Expiry Year'] à partir de la base Hockey.Players.csv (players_db)."""
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return df

    players_db = st.session_state.get("players_db")
    if players_db is None or not isinstance(players_db, pd.DataFrame) or players_db.empty:
        return df

    db = players_db.copy()

    # Trouver la colonne nom joueur
    name_col = None
    for cand in ["Player", "Joueur", "Name", "Full Name", "fullname", "player"]:
        if cand in db.columns:
            name_col = cand
            break
    if name_col is None:
        return df
    if "Level" not in db.columns and "Expiry Year" not in db.columns:
        return df

    def _n(x: str) -> str:
        """Normalise un nom joueur pour matching robuste (accents, ponctuation, ordre)."""
        s = str(x or "").strip().lower()
        s = s.replace("’", "'")
        s = re.sub(r"[\.]", "", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    def _swap_last_first(s: str) -> str:
        # 'Last, First' -> 'First Last'
        if "," in s:
            parts = [p.strip() for p in s.split(",", 1)]
            if len(parts) == 2 and parts[0] and parts[1]:
                return f"{parts[1]} {parts[0]}".strip()
        return s

    base_names = db[name_col].astype(str).fillna("")

    # --- map Level
    mp_level = {}
    if "Level" in db.columns:
        db["Level"] = db["Level"].astype(str).str.strip()
        lvl_keys, lvl_vals = [], []
        for nm, lvl in zip(base_names.tolist(), db["Level"].tolist()):
            lvl = str(lvl).strip()
            if not lvl or lvl.lower() in {"none", "nan", "null"}:
                continue
            n0 = _n(nm)
            n1 = _n(_swap_last_first(nm))
            if n0:
                lvl_keys.append(n0); lvl_vals.append(lvl)
            if n1 and n1 != n0:
                lvl_keys.append(n1); lvl_vals.append(lvl)
        mp_level = dict(zip(lvl_keys, lvl_vals))

    # --- map Expiry Year
    mp_exp = {}
    if "Expiry Year" in db.columns:
        exp_keys, exp_vals = [], []
        exp_series = pd.to_numeric(db["Expiry Year"], errors="coerce")
        exp_series = exp_series.where(exp_series.notna(), None)
        for nm, exp in zip(base_names.tolist(), exp_series.tolist()):
            # exp peut être NaN (float) même après to_numeric -> guard robuste
            if exp is None or (isinstance(exp, float) and pd.isna(exp)):
                continue
            try:
                exp_int = int(float(exp))
            except Exception:
                continue
            exp = str(exp_int)
            n0 = _n(nm)
            n1 = _n(_swap_last_first(nm))
            if n0:
                exp_keys.append(n0); exp_vals.append(exp)
            if n1 and n1 != n0:
                exp_keys.append(n1); exp_vals.append(exp)
        mp_exp = dict(zip(exp_keys, exp_vals))

    out = df.copy()

    # Ensure cols exist
    if "Level" not in out.columns:
        out["Level"] = ""
    if "Expiry Year" not in out.columns:
        out["Expiry Year"] = ""

    bad = {"", "none", "nan", "null"}

    # Fill Level
    cur_lvl = out["Level"].astype(str).str.strip()
    need_lvl = cur_lvl.eq("") | cur_lvl.str.lower().isin(bad)
    if need_lvl.any() and mp_level:
        def _lvl_lookup(name: str) -> str:
            n0 = _n(name)
            if n0 in mp_level:
                return mp_level.get(n0, "")
            n1 = _n(_swap_last_first(name))
            return mp_level.get(n1, "")
        out.loc[need_lvl, "Level"] = out.loc[need_lvl, "Joueur"].astype(str).map(_lvl_lookup)

    # Fill Expiry Year
    cur_exp = out["Expiry Year"].astype(str).str.strip()
    need_exp = cur_exp.eq("") | cur_exp.str.lower().isin(bad)
    if need_exp.any() and mp_exp:
        def _exp_lookup(name: str) -> str:
            n0 = _n(name)
            if n0 in mp_exp:
                return mp_exp.get(n0, "")
            n1 = _n(_swap_last_first(name))
            return mp_exp.get(n1, "")
        out.loc[need_exp, "Expiry Year"] = out.loc[need_exp, "Joueur"].astype(str).map(_exp_lookup)

    out["Level"] = out["Level"].astype(str).str.strip()
    out["Expiry Year"] = out["Expiry Year"].astype(str).str.strip()
    return out


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
    banc_count: int = 0,
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
        lvl_banc = "ok" if int(banc_count or 0) == 0 else "warn"
        pill("Banc", f"{int(banc_count or 0)} joueur(s)", level=lvl_banc, pulse=(lvl_banc != "ok"))

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
    """Demande de changement d'équipe (safe).
    Ne modifie PAS directement selected_team (key widget possible) — on pose un intent,
    appliqué en début de run par _apply_pending_team_selection().
    """
    team = str(team or "").strip()
    if not team:
        return
    # intent
    st.session_state["_pending_team_select"] = team
    # rerun immédiat (boutons Home / tableau)
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

def load_picks(season_lbl: str, teams: list[str]) -> dict:
    path = _picks_path(season_lbl)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
            # normaliser
            for t in teams:
                data.setdefault(t, {})
                for rnd in range(1, 9):
                    data[t].setdefault(str(rnd), t)
            return data
        except Exception:
            pass
    # init: chaque équipe possède ses 8 choix
    data = {t: {str(r): t for r in range(1, 9)} for t in teams}
    save_picks(season_lbl, data)
    return data

def save_picks(season_lbl: str, data: dict) -> None:
    path = _picks_path(season_lbl)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data or {}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# =====================================================
# PENDING TRADES (2-step approval) — persisted per season
#   - Draft: lives in session_state (safe across tab changes)
#   - Pending: saved to DATA_DIR so it survives refresh/redeploy
# =====================================================
def _pending_trades_path(season_lbl: str) -> str:
    season_lbl = str(season_lbl or "").strip() or "season"
    return os.path.join(DATA_DIR, f"pending_trades_{season_lbl}.json")

def load_pending_trades(season_lbl: str) -> list[dict]:
    path = _pending_trades_path(season_lbl)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f) or []
            if isinstance(data, list):
                return data
        except Exception:
            return []
    return []

def save_pending_trades(season_lbl: str, trades: list[dict]) -> None:
    path = _pending_trades_path(season_lbl)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(trades or [], f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def _new_trade_id() -> str:
    return uuid.uuid4().hex[:12]

def _parse_pick_label(lbl: str) -> dict | None:
    """Parse 'R2 — Whalers' -> {'round': '2', 'origin': 'Whalers'}"""
    s = str(lbl or "").strip()
    if not s:
        return None
    # accept "R2 — Team" or "R2 - Team"
    s = s.replace(" - ", " — ")
    if "—" not in s:
        return None
    left, right = [x.strip() for x in s.split("—", 1)]
    if not left.upper().startswith("R"):
        return None
    rnd = left.upper().replace("R", "").strip()
    origin = right.strip()
    if not rnd.isdigit() or not origin:
        return None
    return {"round": str(int(rnd)), "origin": origin}

def _pick_label(p: dict) -> str:
    try:
        return f"R{int(p.get('round',0))} — {str(p.get('origin','')).strip()}"
    except Exception:
        return ""


def pending_locks(season_lbl: str) -> dict:
    """Return locked assets (players + picks) from PENDING trades.
    Used to prevent the same player/pick being committed in multiple pending transactions.
    """
    locks = {"players": {}, "picks": {}}  # key -> info
    try:
        pend = load_pending_trades(season_lbl)
    except Exception:
        pend = []
    for tr in pend or []:
        if str(tr.get("status","")).upper() != "PENDING":
            continue
        tid = str(tr.get("id","")).strip()
        a = str(tr.get("owner_a","")).strip()
        b = str(tr.get("owner_b","")).strip()

        # players
        for side, names in (("A", tr.get("players_a") or []), ("B", tr.get("players_b") or [])):
            for nm in names or []:
                k = _norm_player_key(nm)
                if not k:
                    continue
                locks["players"].setdefault(k, {"name": str(nm), "trade_id": tid, "owners": f"{a}↔{b}", "side": side})

        # picks
        for side, picks in (("A", tr.get("picks_a") or []), ("B", tr.get("picks_b") or [])):
            for p in picks or []:
                try:
                    rnd = str(int(p.get("round", 0)))
                    org = str(p.get("origin","")).strip()
                except Exception:
                    continue
                if not org or rnd == "0":
                    continue
                k = f"{org}__{rnd}"
                locks["picks"].setdefault(k, {"label": _pick_label({"round": rnd, "origin": org}), "trade_id": tid, "owners": f"{a}↔{b}", "side": side})
    return locks

def _trade_preview_pills(items: list[str], kind: str) -> str:
    """kind: 'player' or 'pick'"""
    pills = []
    for it in items:
        it = str(it or "").strip()
        if not it:
            continue
        icon = "👤" if kind == "player" else "🎯"
        pills.append(f'<span class="trade-pill">{icon} {html_escape(it)}</span>')
    return " ".join(pills) if pills else '<span class="muted">Aucun</span>'

def _approvals_badge(tr: dict) -> str:
    a = tr.get("owner_a","")
    b = tr.get("owner_b","")
    ap = tr.get("approvals", {}) or {}
    ok_a = "✅" if ap.get(a) else "⏳"
    ok_b = "✅" if ap.get(b) else "⏳"
    return f"{ok_a} {html_escape(a)} &nbsp;&nbsp; {ok_b} {html_escape(b)}"

def _execute_trade_record(tr: dict, df: pd.DataFrame, season_lbl: str, teams: list[str]) -> pd.DataFrame:
    """Apply a pending trade to df + picks storage, append history. Returns updated df."""
    owner_a = str(tr.get("owner_a","")).strip()
    owner_b = str(tr.get("owner_b","")).strip()
    players_a = [str(x).strip() for x in (tr.get("players_a") or []) if str(x).strip()]
    players_b = [str(x).strip() for x in (tr.get("players_b") or []) if str(x).strip()]
    picks_a = tr.get("picks_a") or []  # list of dicts
    picks_b = tr.get("picks_b") or []
    retained_a = int(tr.get("retained_a", 0) or 0)
    retained_b = int(tr.get("retained_b", 0) or 0)

    df2 = df.copy()

    # --- transfer players (by normalized name)
    if not df2.empty and "Joueur" in df2.columns and "Propriétaire" in df2.columns:
        def _move_players(names: list[str], src: str, dst: str):
            if not names:
                return
            keys = set(_norm_player_key(n) for n in names if n)
            mask = df2["Propriétaire"].astype(str).str.strip().eq(src) & df2["Joueur"].astype(str).apply(_norm_player_key).isin(keys)
            df2.loc[mask, "Propriétaire"] = dst

        _move_players(players_a, owner_a, owner_b)
        _move_players(players_b, owner_b, owner_a)

    # --- transfer picks (persisted JSON)
    try:
        picks = load_picks(season_lbl, teams)
        # For each pick: origin -> holder becomes other team
        for p in picks_a:
            origin = str(p.get("origin","")).strip()
            rnd = str(p.get("round","")).strip()
            if origin and rnd:
                picks.setdefault(origin, {})
                picks[origin][str(rnd)] = owner_b
        for p in picks_b:
            origin = str(p.get("origin","")).strip()
            rnd = str(p.get("round","")).strip()
            if origin and rnd:
                picks.setdefault(origin, {})
                picks[origin][str(rnd)] = owner_a
        save_picks(season_lbl, picks)
    except Exception:
        pass

    # --- log history (players + picks)
    try:
        ts = now_ts()
        hid = str(tr.get("id","")).strip() or _new_trade_id()
        if "history" not in st.session_state or st.session_state.get("history") is None:
            st.session_state["history"] = pd.DataFrame()
        h = st.session_state.get("history", pd.DataFrame()).copy()

        rows = []
        if players_a:
            rows.append({"timestamp": ts, "action": "TRADE", "proprietaire": owner_a, "details": f"{owner_a} ➜ {owner_b}: " + ", ".join(players_a), "trade_id": hid})
        if players_b:
            rows.append({"timestamp": ts, "action": "TRADE", "proprietaire": owner_b, "details": f"{owner_b} ➜ {owner_a}: " + ", ".join(players_b), "trade_id": hid})
        for p in picks_a:
            rows.append({"timestamp": ts, "action": "PICK_TRADE", "proprietaire": owner_a, "details": f"{owner_a} ➜ {owner_b}: {_pick_label(p)}", "trade_id": hid})
        for p in picks_b:
            rows.append({"timestamp": ts, "action": "PICK_TRADE", "proprietaire": owner_b, "details": f"{owner_b} ➜ {owner_a}: {_pick_label(p)}", "trade_id": hid})

        if rows:
            add = pd.DataFrame(rows)
            if h is None or h.empty:
                h = add
            else:
                h = pd.concat([add, h], ignore_index=True)
            st.session_state["history"] = h
    except Exception:
        pass

    # --- persist df + plafonds
    try:
        persist_data(df2, season_lbl)
    except Exception:
        pass
    try:
        st.session_state["data"] = df2
        st.session_state["plafonds"] = build_plafonds(df2)
    except Exception:
        pass

    return df2


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

def _transactions_path(season_lbl: str) -> str:
    season_lbl = str(season_lbl or "").strip() or "season"
    return os.path.join(DATA_DIR, f"transactions_{season_lbl}.csv")

def load_transactions(season_lbl: str) -> pd.DataFrame:
    """Charge les transactions sauvegardées (proposées) pour une saison."""
    path = _transactions_path(season_lbl)
    cols = ["timestamp","season","owner_a","owner_b","a_players","b_players","a_picks","b_picks","a_retained","b_retained","a_cash","b_cash","status"]
    if not os.path.exists(path):
        return pd.DataFrame(columns=cols)
    try:
        t = pd.read_csv(path)
        for c in cols:
            if c not in t.columns:
                t[c] = ""
        return t[cols].copy()
    except Exception:
        return pd.DataFrame(columns=cols)

def save_transactions(season_lbl: str, t: pd.DataFrame) -> None:
    """Persist transactions to local CSV (Cloud-safe)."""
    path = _transactions_path(season_lbl)
    cols = ["timestamp","season","owner_a","owner_b","a_players","b_players","a_picks","b_picks","a_retained","b_retained","a_cash","b_cash","status"]
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

def append_transaction(season_lbl: str, row: dict) -> None:
    t = load_transactions(season_lbl)
    t = pd.concat([t, pd.DataFrame([row])], ignore_index=True)
    save_transactions(season_lbl, t)

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
# PLAYERS DB
# =====================================================
def _norm_name(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip()).lower()

@st.cache_data(show_spinner=False)
def load_players_db(path: str, mtime: float = 0.0) -> pd.DataFrame:
    """
    Charge Hockey.Players.csv (ou équivalent) avec cache Streamlit.
    Le param `mtime` sert uniquement à invalider le cache quand le fichier change.
    """
    if not path or not os.path.exists(path):
        return pd.DataFrame()

    try:
        dfp = pd.read_csv(path)
    except Exception:
        return pd.DataFrame()

    # colonne nom joueur (flex)
    name_col = None
    for c in dfp.columns:
        cl = str(c).strip().lower()
        if cl in {"player", "joueur", "name", "full name", "fullname"}:
            name_col = c
            break

    if name_col is not None:
        dfp["_name_key"] = dfp[name_col].astype(str).map(_norm_name)

    return dfp

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

        # Exclure les lignes de cap mort des listes (Actifs/Banc/Mineur), mais garder pour le calcul du cap ailleurs
        dprop_ok = dprop_ok[dprop_ok.get("Slot","").astype(str).str.strip().ne(SLOT_RACHAT)].copy()

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
    @st.dialog(f"Déplacement — {joueur}", width="small")
    def _dlg():
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
        # RÈGLE: si le joueur provient du CE et que "Blessure" est sélectionné,
        #        le seul choix permis est "🟢 Actif" (rappel pour remplacer).
        if reason == "Blessure" and cur_statut == STATUT_CE:
            destinations = [("🟢 Actif", (STATUT_GC, SLOT_ACTIF))]
        else:
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
                st.session_state["data"] = enrich_level_from_players_db(st.session_state["data"])
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

    cap_gc = int(st.session_state.get("PLAFOND_GC", 95_500_000) or 0)
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
# BOOTSTRAP GLOBAL (ordre propre)
#   0) players_db
#   1) data (load → clean → enrich Level)
#   2) history
#   3) pending moves
#   4) plafonds
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
# 0) PLAYERS DATABASE (AVANT enrich)
# -----------------------------------------------------
pdb_path = _first_existing(PLAYERS_DB_FALLBACKS) if "PLAYERS_DB_FALLBACKS" in globals() else ""
pdb_mtime = 0.0
if pdb_path and os.path.exists(pdb_path):
    try:
        pdb_mtime = float(os.path.getmtime(pdb_path))
    except Exception:
        pdb_mtime = 0.0

players_db = load_players_db(pdb_path, pdb_mtime) if pdb_path else pd.DataFrame()
st.session_state["players_db"] = players_db

# -----------------------------------------------------
# 1) LOAD DATA (CSV → session_state) puis enrich Level
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
    df_loaded = enrich_level_from_players_db(df_loaded)  # ✅ players_db est déjà prêt
    st.session_state["data"] = df_loaded
    st.session_state["data_season"] = season
else:
    # sécurité: s'assurer que data est un DF + clean/enrich léger
    d0 = st.session_state.get("data")
    d0 = d0 if isinstance(d0, pd.DataFrame) else pd.DataFrame(columns=REQUIRED_COLS)
    d0 = clean_data(d0)
    d0 = enrich_level_from_players_db(d0)
    st.session_state["data"] = d0

# -----------------------------------------------------
# 2) LOAD HISTORY (CSV → session_state)
# -----------------------------------------------------
if "history_season" not in st.session_state or st.session_state["history_season"] != season:
    st.session_state["history"] = load_history_file(HISTORY_FILE)
    st.session_state["history_season"] = season
else:
    h0 = st.session_state.get("history")
    st.session_state["history"] = h0 if isinstance(h0, pd.DataFrame) else _history_empty_df()

# -----------------------------------------------------
# 3) PROCESS PENDING MOVES (APRÈS data + history)
# -----------------------------------------------------
if "process_pending_moves" in globals() and callable(globals()["process_pending_moves"]):
    try:
        process_pending_moves()
    except Exception as e:
        st.warning(f"⚠️ process_pending_moves() a échoué: {type(e).__name__}: {e}")

# -----------------------------------------------------
# 4) BUILD PLAFONDS (sur data enrichie)
# -----------------------------------------------------
df0 = st.session_state.get("data", pd.DataFrame(columns=REQUIRED_COLS))
df0 = df0 if isinstance(df0, pd.DataFrame) else pd.DataFrame(columns=REQUIRED_COLS)
df0 = clean_data(df0)
df0 = enrich_level_from_players_db(df0)
st.session_state["data"] = df0
st.session_state["plafonds"] = rebuild_plafonds(df0)


# Init onglet actif (safe)
if "active_tab" not in st.session_state:
    st.session_state["active_tab"] = "🏠 Home"

# =====================================================
# SIDEBAR — Saison + Équipe + Plafonds + Mobile
# =====================================================
st.sidebar.checkbox("📱 Mode mobile", key="mobile_view")
_set_mobile_class(bool(st.session_state.get("mobile_view", False)))
st.sidebar.divider()

st.sidebar.header("📅 Saison")
saisons = ["2024-2025", "2025-2026", "2026-2027"]
auto = saison_auto()
if auto not in saisons:
    saisons.append(auto)
    saisons.sort()

season_pick = st.sidebar.selectbox("Saison", saisons, index=saisons.index(auto), key="sb_season_select")
st.session_state["season"] = season_pick
st.session_state["LOCKED"] = saison_verrouillee(season_pick)


def _tx_pending_from_state() -> bool:
    """Detecte une transaction en cours (sélections joueurs/picks/cash) via session_state."""
    ss = st.session_state
    for k, v in ss.items():
        if k.startswith(("tx_players_", "tx_picks_")):
            if isinstance(v, (list, tuple, set)) and len(v) > 0:
                return True
        if k.startswith(("tx_cash_", "tx_ret_")):
            try:
                if int(v or 0) > 0:
                    return True
            except Exception:
                pass
    return False

def _nav_label(tab_id: str) -> str:
    # Badge transaction en attente (affichage seulement; tab_id reste stable)
    if tab_id == "⚖️ Transactions" and _tx_pending_from_state():
        return "🔴 " + tab_id
    # Emoji ICE à côté de GM (affichage seulement; tab_id reste stable)
    if tab_id == "🧊 GM":
        return "🧊 GM"
    return tab_id


st.sidebar.markdown("### Navigation")

# -----------------------------------------------------
# SIDEBAR NAV (radio) — sans logo, GM = 🧊
#   ✅ Définit NAV_TABS + `active_tab` (source de vérité)
# -----------------------------------------------------

is_admin = _is_admin_whalers()

NAV_TABS = [
    "🏠 Home",
    "🧾 Alignement",
    "🧊 GM",
    "👤 Joueurs autonomes",
    "🕘 Historique",
    "⚖️ Transactions",
]
if is_admin:
    NAV_TABS.append("🛠️ Gestion Admin")
NAV_TABS.append("🧠 Recommandations")

# init + fallback (safe)
if "active_tab" not in st.session_state:
    st.session_state["active_tab"] = NAV_TABS[0]
if st.session_state["active_tab"] not in NAV_TABS:
    st.session_state["active_tab"] = NAV_TABS[0]

# Widget (labels = tabs, pas de mapping fragile)
_cur = st.session_state.get("active_tab", NAV_TABS[0])
_cur_idx = NAV_TABS.index(_cur) if _cur in NAV_TABS else 0

# ✅ Source de vérité unique pour la navigation
active_tab = st.sidebar.radio(
    "Navigation",
    NAV_TABS,
    index=_cur_idx,
    key="active_tab",
)

active_tab = st.session_state.get("active_tab", NAV_TABS[0])

st.sidebar.divider()
st.sidebar.markdown("### 🏒 Équipe")

teams = sorted(list(LOGOS.keys())) if 'LOGOS' in globals() else []
teams = [str(t).strip() for t in teams if str(t).strip()]
if not teams:
    teams = ['Whalers']

# Init state
cur_team = str(st.session_state.get('selected_team') or '').strip()
if not cur_team or cur_team not in teams:
    cur_team = teams[0]
    st.session_state['selected_team'] = cur_team
    st.session_state['align_owner'] = cur_team

if 'selected_team_ui' not in st.session_state or str(st.session_state.get('selected_team_ui') or '').strip() not in teams:
    st.session_state['selected_team_ui'] = cur_team

chosen_team = st.sidebar.selectbox(
    'Choisir une équipe',
    teams,
    index=(teams.index(st.session_state['selected_team_ui']) if st.session_state['selected_team_ui'] in teams else 0),
    key='selected_team_ui',
)

# Sync UI → state (SANS rerun)
if chosen_team and chosen_team != st.session_state.get('selected_team'):
    st.session_state['selected_team'] = chosen_team
    st.session_state['align_owner'] = chosen_team

logo_path = team_logo_path(str(st.session_state.get('selected_team') or '').strip())
if logo_path:
    st.sidebar.image(logo_path, use_container_width=True)


if st.sidebar.button("👀 Prévisualiser l’alignement GC", use_container_width=True, key="sb_preview_gc"):
    st.session_state["gc_preview_open"] = True
    st.session_state["active_tab"] = "🧾 Alignement"
    # pas de do_rerun() : le clic déclenche déjà un rerun

st.sidebar.divider()
st.sidebar.header("💰 Plafonds")
st.sidebar.metric("🏒 Plafond Grand Club", money(st.session_state.get("PLAFOND_GC", 95_500_000)))
st.sidebar.metric("🏫 Plafond Club École", money(st.session_state.get("PLAFOND_CE", 47_750_000)))

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
    # v38: force Level (STD/ELC) via Hockey.Players.csv before rendering
    try:
        df_src = apply_players_level(df_src)
    except Exception:
        pass
    if df_src is None or not isinstance(df_src, pd.DataFrame) or df_src.empty:
        st.info("Aucun joueur.")
        return None

    # CSS injecté 1x
    t = df_src.copy()

    # colonnes minimales
    for c, d in {"Joueur": "", "Pos": "F", "Equipe": "", "Salaire": 0, "Level": "", "Expiry Year": ""}.items():
        if c not in t.columns:
            t[c] = d

    t["Joueur"] = t["Joueur"].astype(str).fillna("").map(lambda x: re.sub(r"\s+", " ", x).strip())
    t["Equipe"] = t["Equipe"].astype(str).fillna("").map(lambda x: re.sub(r"\s+", " ", x).strip())
    t["Level"]  = t["Level"].astype(str).fillna("").map(lambda x: re.sub(r"\s+", " ", x).strip())
    t["Expiry Year"] = t["Expiry Year"].astype(str).fillna("").map(lambda x: re.sub(r"\s+", " ", x).strip())
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
    )

    disabled = str(source_key or "").endswith("_disabled")

    # header
    h = st.columns([0.9, 1.2, 3.6, 1.0, 1.6])
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

        c = st.columns([0.9, 1.2, 3.6, 1.0, 1.6])
        c[0].markdown(pos_badge_html(pos), unsafe_allow_html=True)
        c[1].markdown(team if team and team.lower() not in bad else "—")

        if c[2].button(
            joueur,
            key=f"{source_key}_{owner}_{row_key}",
            use_container_width=True,
            disabled=disabled,
        ):
            clicked = joueur

        lvl_u = str(lvl or "").strip().upper()
        lvl_cls = "lvlELC" if lvl_u == "ELC" else ("lvlSTD" if lvl_u == "STD" else "")
        c[3].markdown(
            f"<span class='levelCell {lvl_cls}'>{html.escape(lvl) if lvl and lvl.lower() not in bad else '—'}</span>",
            unsafe_allow_html=True,
        )
        c[4].markdown(f"<span class='salaryCell'>{money(salaire)}</span>", unsafe_allow_html=True)

    return clicked




def render_tab_gm():
    owner = str(get_selected_team() or "").strip()
    if not owner:
        st.info("Sélectionne une équipe.")
        return

    df = clean_data(st.session_state.get("data", pd.DataFrame(columns=REQUIRED_COLS)))
    dprop = df[df["Propriétaire"].astype(str).str.strip().eq(owner)].copy()

    # =========================
    # HEADER GM — logo + masses
    # =========================
    colL, colR = st.columns([1.2, 3], vertical_alignment="center")

    with colL:
        # GM logo (priorité) puis logo d'équipe
        gm_logo = "gm_logo.png"
        if os.path.exists(gm_logo):
            st.image(gm_logo, width=110)
        else:
            logo = team_logo_path(owner)
            if logo:
                st.image(logo, width=110)

        st.markdown(
            f"<div style='font-size:22px;font-weight:900;margin-top:6px;'>🧊 GM — {html.escape(owner)}</div>",
            unsafe_allow_html=True,
        )

    with colR:
        cap_gc = int(st.session_state.get("PLAFOND_GC", 95_500_000))
        cap_ce = int(st.session_state.get("PLAFOND_CE", 47_750_000))

        used_gc = int(dprop[dprop["Statut"] == STATUT_GC]["Salaire"].sum()) if not dprop.empty else 0
        used_ce = int(dprop[dprop["Statut"] == STATUT_CE]["Salaire"].sum()) if not dprop.empty else 0

        r_gc = cap_gc - used_gc
        r_ce = cap_ce - used_ce

        c1, c2 = st.columns(2)
        with c1:
            st.markdown(
                f"""
                <div style="padding:14px;border-radius:14px;background:rgba(255,255,255,.05)">
                  <div style="font-size:13px;opacity:.8">Masse Grand Club</div>
                  <div style="font-size:26px;font-weight:900;margin:4px 0">{money(used_gc)}</div>
                  <div style="font-size:13px;opacity:.75">Plafond {money(cap_gc)}</div>
                  <div style="font-size:14px;font-weight:700;color:{'#ef4444' if r_gc < 0 else '#22c55e'}">
                    Reste {money(r_gc)}
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with c2:
            st.markdown(
                f"""
                <div style="padding:14px;border-radius:14px;background:rgba(255,255,255,.05)">
                  <div style="font-size:13px;opacity:.8">Masse Club École</div>
                  <div style="font-size:26px;font-weight:900;margin:4px 0">{money(used_ce)}</div>
                  <div style="font-size:13px;opacity:.75">Plafond {money(cap_ce)}</div>
                  <div style="font-size:14px;font-weight:700;color:{'#ef4444' if r_ce < 0 else '#22c55e'}">
                    Reste {money(r_ce)}
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.divider()

    # =========================
    # GM — picks & buyouts
    # =========================
    render_tab_gm_picks_buyout(owner, dprop)


def render_tab_gm_picks_buyout(owner: str, dprop: "pd.DataFrame") -> None:
    """
    GM: Choix de repêchage + Rachat de contrat
    - Collapses complets (pas de nested expander)
    - HTML avec styles INLINE (donc rendu pro même si le CSS est cassé / non injecté)
    """
    owner = str(owner or "").strip()
    teams = sorted(list(LOGOS.keys())) if "LOGOS" in globals() else []
    season = str(st.session_state.get("season", "") or "").strip()

    # -------------------------
    # 🎯 PICKS
    # -------------------------
    with st.expander("🎯 Choix de repêchage", expanded=True):
        st.caption("Possession des rondes 1 à 8, par année")

        # base year = fin de saison (ex "2025-2026" => 2026)
        nums = re.findall(r"\d{4}", season)
        base_year = None
        if len(nums) >= 2:
            try:
                base_year = int(nums[-1])
            except Exception:
                base_year = None
        elif len(nums) == 1:
            try:
                base_year = int(nums[0])
            except Exception:
                base_year = None

        years = [str(base_year + i) for i in range(0, 3)] if base_year else ([season] if season else [])

        # cache picks
        cache = st.session_state.get("_picks_cache")
        if not isinstance(cache, dict):
            cache = {}
            st.session_state["_picks_cache"] = cache

        # styles inline (fallback robuste)
        row_style = (
            "display:flex;gap:10px;flex-wrap:nowrap;overflow-x:auto;overflow-y:hidden;"
            "white-space:nowrap;padding:6px 0 10px 0;-webkit-overflow-scrolling:touch;"
        )
        pill_mine = (
            "display:inline-flex;align-items:center;justify-content:center;"
            "padding:7px 10px;border-radius:999px;font-weight:700;font-size:13px;"
            "border:1px solid rgba(34,197,94,.55);background:rgba(34,197,94,.10);"
        )
        pill_other = (
            "display:inline-flex;align-items:center;justify-content:center;"
            "padding:7px 10px;border-radius:999px;font-weight:700;font-size:13px;"
            "border:1px solid rgba(255,255,255,.14);background:rgba(255,255,255,.06);"
            "opacity:.92;"
        )
        year_badge = (
            "display:inline-flex;align-items:center;justify-content:center;"
            "padding:8px 10px;border-radius:999px;font-weight:900;font-size:13px;"
            "border:1px solid rgba(34,197,94,.55);background:rgba(34,197,94,.10);"
            "width:70px;"
        )

        for ylbl in years:
            if ylbl not in cache:
                try:
                    cache[ylbl] = load_picks(ylbl, teams)
                except Exception:
                    cache[ylbl] = {}
                st.session_state["_picks_cache"] = cache

            p_all = cache.get(ylbl, {}) or {}
            my_p = p_all.get(owner, {}) if isinstance(p_all, dict) else {}

            nb = 0
            for rr in range(1, 9):
                who = str(my_p.get(str(rr), owner) or "").strip() or owner
                if who == owner:
                    nb += 1

            # line container (grid-like using columns)
            cY, cR = st.columns([1, 8], vertical_alignment="top")
            with cY:
                st.markdown(
                    f"<div style='{year_badge}'>{html.escape(str(ylbl))}</div>"
                    f"<div style='font-size:12px;opacity:.75;padding-left:6px;margin-top:6px;'>{nb} choix</div>",
                    unsafe_allow_html=True,
                )
            with cR:
                pills = [f"<div style='{row_style}'>"]
                for rr in range(1, 9):
                    who = str(my_p.get(str(rr), owner) or "").strip() or owner
                    style = pill_mine if who == owner else pill_other
                    label = f"R{rr} • {html.escape(who)}"
                    pills.append(f"<span style='{style}' title='{html.escape(who)}'>{label}</span>")
                pills.append("</div>")
                st.markdown("".join(pills), unsafe_allow_html=True)

        show_detail = st.checkbox("Voir le détail en tableau", value=False, key=f"gm_picks_detail_{owner}")
        if show_detail:
            rows = []
            for ylbl in years:
                p_all = st.session_state.get("_picks_cache", {}).get(ylbl, {}) or {}
                my_p = p_all.get(owner, {}) if isinstance(p_all, dict) else {}
                for rr in range(1, 9):
                    who = str(my_p.get(str(rr), owner) or "").strip() or owner
                    rows.append({
                        "Année": str(ylbl),
                        "Ronde": int(rr),
                        "Appartenant à": who,
                        "Reçu le": "—",
                    })
            if rows:
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            else:
                st.info("Aucun choix trouvé pour cette équipe.")

    st.divider()

    # -------------------------
    # 🧾 RACHAT
    # -------------------------
    with st.expander("🧾 Rachat de contrat", expanded=False):
        st.caption("Pénalité automatique : 50% du salaire • Le joueur devient Autonome")

        candidates = dprop.copy()
        if "Joueur" in candidates.columns:
            candidates = candidates[~candidates["Joueur"].astype(str).str.startswith("RACHAT —", na=False)].copy()
        if "Salaire" in candidates.columns:
            candidates = candidates[candidates["Salaire"].fillna(0).astype(float) > 0].copy()

        name_col = "Joueur" if "Joueur" in candidates.columns else ("Player" if "Player" in candidates.columns else None)
        if not name_col or candidates.empty:
            st.info("Aucun joueur éligible au rachat.")
            return

        display = []
        disp_salary = {}
        disp_name = {}
        for _, r in candidates.iterrows():
            nm = str(r.get(name_col, "")).strip()
            if not nm:
                continue
            sal_raw = float(r.get("Salaire", 0) or 0)
            sal = money(int(sal_raw))
            pos = str(r.get("Position", r.get("Pos", "")) or "").strip()
            team = str(r.get("Team", r.get("Équipe", "")) or "").strip()
            disp = f"{nm}  —  {pos}  {team}  —  {sal}"
            display.append(disp)
            disp_salary[disp] = sal_raw
            disp_name[disp] = nm

        picked_rows = st.selectbox("Joueur à racheter", [""] + display, index=0, key="gm_buyout_pick")
        sel_salary = float(disp_salary.get(picked_rows, 0) or 0)
        penalite = int(round(sel_salary * 0.50)) if sel_salary > 0 else 0
        can_apply = bool(str(picked_rows).strip())

        c1, c2, c3 = st.columns([1, 1, 2], vertical_alignment="center")
        with c1:
            bucket = st.radio("Appliqué à", ["GC", "CE"], horizontal=True, key="gm_buyout_bucket")
        with c2:
            st.metric("Pénalité (50%)", money(int(penalite)) if can_apply else "—")
        with c3:
            note = st.text_input("Note (optionnel)", key="gm_buyout_note")

        if st.button("✅ Confirmer le rachat", type="primary", disabled=not can_apply, use_container_width=True, key="gm_buyout_confirm"):
            df_all = st.session_state.get("data", pd.DataFrame(columns=REQUIRED_COLS))
            df_new, player_name, penalite_calc, removed = apply_buyout(df_all, owner, picked_rows, bucket)

            st.session_state["data"] = df_new

            # Sauvegarde data
            try:
                data_file = str(st.session_state.get("DATA_FILE", "") or "").strip()
                if data_file:
                    df_new.to_csv(data_file, index=False)
            except Exception:
                pass

            # Rebuild plafonds
            try:
                st.session_state["plafonds"] = rebuild_plafonds(df_new)
            except Exception:
                pass

            # Marché: joueur devient autonome
            try:
                season_lbl = str(st.session_state.get("season","") or "").strip()
                push_buyout_to_market(season_lbl, player_name)
            except Exception:
                pass

            # Historique
            try:
                h = st.session_state.get("history", pd.DataFrame())
                if not isinstance(h, pd.DataFrame):
                    h = pd.DataFrame()
                row = {
                    "timestamp": datetime.now(ZoneInfo("America/Toronto")).isoformat(timespec="seconds"),
                    "action": "RACHAT",
                    "proprietaire": owner,
                    "joueur": player_name,
                    "detail": f"{bucket} — pénalité {money(int(penalite_calc or 0))}",
                    "note": str(note or ""),
                }
                h = pd.concat([h, pd.DataFrame([row])], ignore_index=True)
                st.session_state["history"] = h
                hf = str(st.session_state.get("HISTORY_FILE","") or "").strip()
                if hf:
                    h.to_csv(hf, index=False)
            except Exception:
                pass

            st.success(f"Rachat appliqué ✅ — {player_name} devient **Autonome** (pénalité {money(int(penalite_calc or 0))} sur {bucket})")
            do_rerun()






def push_buyout_to_market(season_lbl: str, player_name: str) -> None:
    if not ("load_trade_market" in globals() and callable(globals()["load_trade_market"]) and
            "save_trade_market" in globals() and callable(globals()["save_trade_market"])):
        return

    season_lbl = str(season_lbl or "").strip()
    joueur_key = str(player_name or "").strip()
    if not season_lbl or not joueur_key:
        return

    try:
        tm = load_trade_market(season_lbl)
    except Exception:
        tm = pd.DataFrame()

    if not isinstance(tm, pd.DataFrame):
        tm = pd.DataFrame()

    for c in ["season", "proprietaire", "joueur", "is_available", "updated_at"]:
        if c not in tm.columns:
            tm[c] = ""

    now_s = datetime.now(ZoneInfo("America/Toronto")).strftime("%Y-%m-%d %H:%M:%S")
    mask = tm["joueur"].astype(str).str.strip().eq(joueur_key)

    if mask.any():
        tm.loc[mask, "season"] = season_lbl
        tm.loc[mask, "proprietaire"] = "Autonome"
        tm.loc[mask, "is_available"] = True
        tm.loc[mask, "updated_at"] = now_s
    else:
        tm = pd.concat([tm, pd.DataFrame([{
            "season": season_lbl,
            "proprietaire": "Autonome",
            "joueur": joueur_key,
            "is_available": True,
            "updated_at": now_s,
        }])], ignore_index=True)

    try:
        save_trade_market(season_lbl, tm)
    except Exception:
        pass



def render_tab_autonomes(show_header: bool = True, lock_dest_to_owner: bool = False):
    """Onglet Joueurs autonomes / Ajout joueurs (Admin).

    Règles:
    - Un joueur est jouable IFF (NHL GP >= 84) ET (Level != ELC)
    - La sélection (max 5) est persistée par propriétaire + saison et ne disparaît pas quand on change la recherche.
    """

    # --- Contexte
    try:
        owner = str(get_selected_team() or "").strip() if "get_selected_team" in globals() else ""
    except Exception:
        owner = ""

    season_lbl = str(st.session_state.get("season", "") or "").strip()
    scope = "auto" if lock_dest_to_owner else "admin"
    pick_state_key = f"fa_pick__{season_lbl}__{owner or 'x'}__{scope}"
    sel_players = [str(x).strip() for x in (st.session_state.get(pick_state_key) or []) if str(x).strip()]

    if show_header:
        st.subheader("👤 Joueurs autonomes")
        st.caption("Recherche → sélection (max 5) → confirmer. La sélection reste même si tu changes la recherche.")

    players_db = st.session_state.get("players_db")
    if players_db is None or (not isinstance(players_db, pd.DataFrame)) or players_db.empty:
        st.error("Impossible de charger la base joueurs (players_db).")
        st.stop()

    df_db = players_db.copy()

    # --- Helpers
    def _cap_to_int(v) -> int:
        try:
            s = str(v).strip()
            if not s or s.lower() in ("nan", "none"):
                return 0
            s = s.replace("$", "").replace("€", "").replace("£", "")
            s = s.replace(",", " ").replace(" ", " ")
            s = re.sub(r"[^0-9.]", "", s)
            return int(round(float(s))) if s else 0
        except Exception:
            return 0

    def _as_int(v) -> int:
        try:
            return int(float(v))
        except Exception:
            return 0

    def _reason(nhl_gp: int, lvl_u: str) -> str:
        reasons = []
        if nhl_gp < 84:
            reasons.append("NHL GP < 84")
        if (lvl_u or "").strip().upper() == "ELC":
            reasons.append("Level = ELC")
        return " + ".join(reasons) if reasons else "—"

    # --- Normalisation colonnes (best effort)
    if "Player" not in df_db.columns:
        for cand in ["Joueur", "Name", "Full Name", "fullname", "player"]:
            if cand in df_db.columns:
                df_db = df_db.rename(columns={cand: "Player"})
                break
    if "Team" not in df_db.columns:
        for cand in ["Équipe", "Equipe", "NHL Team", "team", "Club"]:
            if cand in df_db.columns:
                df_db = df_db.rename(columns={cand: "Team"})
                break
    if "Position" not in df_db.columns:
        for cand in ["Pos", "POS", "position"]:
            if cand in df_db.columns:
                df_db = df_db.rename(columns={cand: "Position"})
                break

    level_col = "Level" if "Level" in df_db.columns else None
    if not level_col:
        for cand in ["Contrat", "Contract", "Type", "level"]:
            if cand in df_db.columns:
                df_db = df_db.rename(columns={cand: "Level"})
                level_col = "Level"
                break

    cap_col = None
    for cand in ["Cap Hit", "CapHit", "Cap", "Salary", "Salaire", "AAV"]:
        if cand in df_db.columns:
            cap_col = cand
            break

    nhl_gp_col = None
    for cand in ["NHL GP", "NHL_GP", "NHLGP", "NHL Games", "NHLGames", "GP", "NHL_Games"]:
        if cand in df_db.columns:
            nhl_gp_col = cand
            break

    # --- Mapping "appartient déjà à" (à partir de la ligue)
    df_league = st.session_state.get("data")
    owner_map = {}
    def _norm_player_key(name: str) -> str:
        """Normalise un nom joueur pour matcher 'Leo Carlsson' et 'Carlsson, Leo'."""
        s = str(name or "").strip().lower()
        if "," in s:
            # 'nom, prenom' -> 'prenom nom'
            parts = [p.strip() for p in s.split(",", 1)]
            if len(parts) == 2 and parts[1] and parts[0]:
                s = f"{parts[1]} {parts[0]}".strip()
        # compacter espaces
        s = " ".join(s.split())
        return s

    if isinstance(df_league, pd.DataFrame) and not df_league.empty and "Joueur" in df_league.columns and "Propriétaire" in df_league.columns:
        tmp = df_league[["Joueur", "Propriétaire"]].copy()
        tmp["_k"] = tmp["Joueur"].astype(str).map(_norm_player_key)
        for _, rr in tmp.iterrows():
            owner_map[str(rr.get("_k", ""))] = str(rr.get("Propriétaire", "") or "").strip()

    def owned_to(player: str) -> str:
        return owner_map.get(_norm_player_key(player), "")

    # --- UI filtres
    f1, f2, f3 = st.columns([5, 3, 3], vertical_alignment="center")
    with f1:
        q_name = st.text_input("Nom / Prénom", value="", key=f"fa_q_name__{season_lbl}__{owner or 'x'}").strip()
    with f2:
        teams = ["Toutes"]
        if "Team" in df_db.columns:
            teams += sorted(df_db["Team"].dropna().astype(str).str.strip().unique().tolist())
        team_pick = st.selectbox("Équipe", teams, index=0, key=f"fa_team_pick__{season_lbl}__{owner or 'x'}")
    with f3:
        levels = ["Tous"]
        if level_col:
            levels += sorted(df_db["Level"].dropna().astype(str).str.strip().unique().tolist())
        lvl_pick = st.selectbox("Level (Contrat)", levels, index=0, key=f"fa_lvl_pick__{season_lbl}__{owner or 'x'}")

    # Rien ne doit apparaître tant que rien n'est saisi (sauf si sélection déjà en cours)
    if not q_name and not sel_players:
        st.info("Commence à taper un nom (ou début de nom) dans **Nom / Prénom** pour afficher des résultats.")
        st.stop()

    st.divider()

    st.markdown("### 💰 Recherche par Salaire (Cap Hit)")
    cap_on = st.checkbox("Activer le filtre Cap Hit", value=False, key=f"fa_cap_on__{season_lbl}__{owner or 'x'}")

    cap_min, cap_max = (0, 30_000_000)
    if cap_col and cap_col in df_db.columns:
        try:
            vals = df_db[cap_col].apply(_cap_to_int)
            if vals.notna().any():
                cap_min = int(vals.min())
                cap_max = int(vals.max())
        except Exception:
            pass
    cap_min = max(0, int(cap_min or 0))
    cap_max = max(int(cap_max or 1), 1)

    cap_rng = (0, cap_max)
    if cap_on:
        cap_rng = st.slider(
            "Plage Cap Hit",
            min_value=0,
            max_value=int(cap_max),
            value=(0, int(cap_max)),
            step=50_000,
            key=f"fa_cap_rng__{season_lbl}__{owner or 'x'}",
        )

    st.divider()

    only_jouable = st.checkbox(
        "🚫 Exclure les joueurs selon les critères (NHL GP < 84 ou Level = ELC)",
        value=True,
        key=f"fa_only_jouable__{season_lbl}__{owner or 'x'}",
    )

    # --- Filtrage
    dff = df_db.copy()
    if q_name:
        dff = dff[dff["Player"].astype(str).str.lower().str.contains(q_name.lower(), na=False)].copy()
    if team_pick != "Toutes" and "Team" in dff.columns:
        dff = dff[dff["Team"].astype(str).str.strip().eq(str(team_pick).strip())].copy()
    if lvl_pick != "Tous" and level_col:
        dff = dff[dff["Level"].astype(str).str.strip().eq(str(lvl_pick).strip())].copy()
    if cap_on and cap_col and cap_col in dff.columns:
        cap_vals = dff[cap_col].apply(_cap_to_int)
        dff = dff[(cap_vals >= int(cap_rng[0])) & (cap_vals <= int(cap_rng[1]))].copy()

    if dff.empty:
        st.warning("Aucun joueur trouvé.")
        return

    # --- Calcul jouable + raison
    dff["_nhl_gp"] = dff[nhl_gp_col].apply(_as_int) if nhl_gp_col and nhl_gp_col in dff.columns else 0
    dff["_lvl_u"] = dff["Level"].astype(str).str.strip().str.upper() if level_col else ""
    dff["✅ Jouable"] = (dff["_nhl_gp"] >= 84) & (dff["_lvl_u"] != "ELC")
    dff["Raison"] = [
        _reason(int(gp or 0), str(lv or ""))
        for gp, lv in zip(dff["_nhl_gp"].tolist(), dff["_lvl_u"].tolist())
    ]
    if only_jouable:
        dff = dff[dff["✅ Jouable"]].copy()
        if dff.empty:
            st.warning("Aucun joueur jouable avec ces filtres.")
            return

    dff = dff.head(300).reset_index(drop=True)

    # --- Présentation Fantrax
    show_cols = ["Player", "Position", "Team"]
    show_cols = [c for c in show_cols if c in dff.columns]
    df_show = dff[show_cols].copy()
    if cap_col and cap_col in dff.columns:
        df_show["Cap Hit"] = dff[cap_col].apply(lambda x: money(_cap_to_int(x)))
    df_show["NHL GP"] = dff["_nhl_gp"].astype(int)
    if level_col:
        df_show["Level"] = dff["Level"].astype(str).str.strip()
    df_show["✅"] = dff["✅ Jouable"].apply(lambda v: "✅" if bool(v) else "—")
    df_show["🔴"] = df_show["Player"].apply(lambda p: "🔴" if owned_to(p) else "")
    df_show["Appartenant à"] = df_show["Player"].apply(owned_to)
    df_show["Raison"] = dff["Raison"].astype(str)

    # Tri: sélectionnés en haut
    df_show["_sel"] = df_show["Player"].astype(str).str.strip().isin(sel_players)
    df_show = df_show.sort_values(by=["_sel", "Player"], ascending=[False, True], na_position="last").drop(columns=["_sel"]).reset_index(drop=True)

    # Légende colonnes
    st.markdown(
        "**Colonnes :** ✅ = jouable (NHL GP ≥ 84 et Level ≠ ELC) • 🔴 = déjà dans une équipe • Appartenant à = propriétaire actuel (si 🔴) • Raison = pourquoi NON jouable."
    )

    st.dataframe(df_show, use_container_width=True, hide_index=True)

    # --- Sélection persistante (max 5)
    n_sel = len(sel_players)
    st.markdown(f"### ✅ Sélection ({n_sel} / 5)")

    if n_sel == 0:
        st.caption("Aucun joueur sélectionné. Utilise les résultats ci-dessous puis ajoute.")
    else:
        sel_df = df_show[df_show["Player"].astype(str).str.strip().isin(sel_players)].copy()
        # highlight non-jouables (si affichés sans filtre)
        try:
            def _style_row(row):
                nonj = str(row.get("Raison", "—")) != "—"
                owned = str(row.get("Appartenant à", "") or "").strip() != ""
                if nonj:
                    return ["background: rgba(239,68,68,0.12); font-weight:700;"] * len(row)
                if owned:
                    return ["border: 2px solid rgba(239,68,68,0.95);"] * len(row)
                return [""] * len(row)
            st.dataframe(sel_df.style.apply(_style_row, axis=1), use_container_width=True, hide_index=True)
        except Exception:
            st.dataframe(sel_df, use_container_width=True, hide_index=True)

        # Retirer un joueur
        remove_opts = sel_players
        to_remove = st.multiselect(
            "Retirer de la sélection",
            options=remove_opts,
            default=[],
            key=f"fa_remove__{season_lbl}__{owner or 'x'}__{scope}",
            disabled=(n_sel == 0),
        )
        if to_remove and st.button(
            "🗑️ Retirer",
            use_container_width=True,
            key=f"fa_remove_btn__{season_lbl}__{owner or 'x'}__{scope}",
        ):
            st.session_state[pick_state_key] = [p for p in sel_players if p not in set(to_remove)]
            do_rerun()

    # Ajouter depuis résultats
    st.write("")
    can_add_more = len(sel_players) < 5
    add_choices = [p for p in df_show["Player"].astype(str).str.strip().tolist() if p]
        # --- Ajouter depuis les résultats (multi-ajout stable) ---
    add_widget_key = f"fa_pending_add__{season_lbl}__{owner or 'x'}__{scope}"
    add_btn_key = f"fa_add_btn__{season_lbl}__{owner or 'x'}__{scope}"

    def _fa_add_to_selection(_wkey=add_widget_key, _pick_key=pick_state_key):
        pending = st.session_state.get(_wkey, []) or []
        cur = st.session_state.get(_pick_key, []) or []
        new_list = [str(x).strip() for x in cur if str(x).strip()]

        for p in pending:
            p = str(p).strip()
            if p and p not in new_list:
                new_list.append(p)

        st.session_state[_pick_key] = new_list[:5]
        # ✅ on peut vider un widget key seulement via callback
        st.session_state[_wkey] = []

    pending_add = st.multiselect(
        "Ajouter depuis les résultats (max 5 total)",
        options=add_choices,
        default=[],
        key=add_widget_key,
        disabled=(not can_add_more),
    )

    if pending_add:
        st.caption("À ajouter à la sélection : " + ", ".join([str(x) for x in pending_add[:5]]))

    st.button(
        "➕ Ajouter à la sélection",
        type="primary",
        use_container_width=True,
        key=add_btn_key,
        disabled=(not pending_add or not can_add_more),
        on_click=_fa_add_to_selection,
    )

    if len(sel_players) >= 5:
        st.info("Sélection complète (5/5) — retire un joueur pour en ajouter un autre.")

    st.divider()

    # --- Validation pour confirmation
    picked_now = [str(x).strip() for x in (st.session_state.get(pick_state_key) or []) if str(x).strip()]
    if not picked_now:
        st.caption("Sélectionne jusqu'à 5 joueurs avant de confirmer.")
        return

    # On reconstruit un df pour les joueurs sélectionnés (afin d'avoir NHL GP/Level même si filtres)
    sel_full = df_db[df_db["Player"].astype(str).str.strip().isin(picked_now)].copy()
    if sel_full.empty:
        st.warning("Sélection introuvable dans la base (réessaie la recherche).")
        return

    sel_full["_nhl_gp"] = sel_full[nhl_gp_col].apply(_as_int) if nhl_gp_col and nhl_gp_col in sel_full.columns else 0
    sel_full["_lvl_u"] = sel_full["Level"].astype(str).str.strip().str.upper() if level_col else ""
    sel_full["_jouable"] = (sel_full["_nhl_gp"] >= 84) & (sel_full["_lvl_u"] != "ELC")
    non_jouables = sel_full[~sel_full["_jouable"]]
    owned = [p for p in picked_now if owned_to(p)]

    has_non_jouable = not non_jouables.empty
    has_owned = len(owned) > 0

    if has_non_jouable:
        st.error("❌ Embauche impossible: au moins un joueur sélectionné est NON JOUABLE (NHL GP < 84 ou Level = ELC). Retire-le de la sélection.")
    if has_owned:
        st.error("❌ Embauche impossible: au moins un joueur sélectionné appartient déjà à une équipe. Retire-le de la sélection.")

    # --- Destination + affectation
    owners = []
    if isinstance(df_league, pd.DataFrame) and not df_league.empty and "Propriétaire" in df_league.columns:
        owners = sorted(df_league["Propriétaire"].dropna().astype(str).str.strip().unique().tolist())
    if not owners and "LOGOS" in globals():
        owners = sorted(list(LOGOS.keys()))
    if not owners:
        owners = [owner] if owner else []

    cA, cB = st.columns([2, 2], vertical_alignment="center")
    with cA:
        dest_default = owner if owner in owners else (owners[0] if owners else "")
        dest_options = [dest_default] if (lock_dest_to_owner and dest_default) else owners
        dest_owner = st.selectbox(
            "Équipe destination",
            options=dest_options,
            index=0,
            key=f"fa_dest_owner__{season_lbl}__{owner or 'x'}__{scope}",
            disabled=bool(lock_dest_to_owner),
        )
    
        # 🟢 Micro-fix UX: rendre la destination très visible
        st.markdown('<div class="dest-hint">⬇️ Destination : choisis l’équipe ici</div>', unsafe_allow_html=True)
    with cB:
        assign_state_key = f"fa_assign__{season_lbl}__{owner or 'x'}__{scope}"
        assign = st.radio("Affectation", ["GC", "Banc", "CE"], horizontal=True, key=assign_state_key)

    # --- Confirmer
    if st.button(
        "✅ Confirmer l’embauche",
        type="primary",
        use_container_width=True,
        key=f"fa_confirm__{season_lbl}__{owner or 'x'}__{scope}",
        disabled=(has_non_jouable or has_owned or (not bool(dest_owner))),
    ):
        df_all = st.session_state.get("data", pd.DataFrame(columns=REQUIRED_COLS))
        if not isinstance(df_all, pd.DataFrame):
            df_all = pd.DataFrame(columns=REQUIRED_COLS)

        added = 0
        skipped = []
        for pname in picked_now:
            if not pname:
                continue
            if owned_to(pname):
                skipped.append(f"{pname} (déjà à {owned_to(pname)})")
                continue

            sub = df_db[df_db["Player"].astype(str).str.strip().eq(pname)].head(1)
            if sub.empty:
                skipped.append(f"{pname} (introuvable)")
                continue
            r0 = sub.iloc[0].to_dict()

            gp = _as_int(r0.get(nhl_gp_col, 0)) if nhl_gp_col else 0
            lv = str(r0.get("Level", "") or "").strip().upper() if level_col else ""
            if (gp < 84) or (lv == "ELC"):
                skipped.append(f"{pname} (NON JOUABLE)")
                continue

            pos = str(r0.get("Position", r0.get("Pos", "")) or "").strip()
            team = str(r0.get("Team", "") or "").strip()
            sal = _cap_to_int(r0.get(cap_col, 0)) if cap_col else 0
            lvl = str(r0.get("Level", "") or "").strip() if level_col else ""

            if assign == "GC":
                statut_val, slot_val = STATUT_GC, SLOT_ACTIF
            elif assign == "Banc":
                statut_val, slot_val = STATUT_GC, SLOT_BANC
            else:
                statut_val, slot_val = STATUT_CE, SLOT_MINEUR

            new_row = {
                "Propriétaire": str(dest_owner),
                "Joueur": pname,
                "Équipe": team,
                "Pos": pos,
                "Salaire": int(sal or 0),
                "Statut": statut_val,
                "Slot": slot_val,
                "Level": lvl,
            }
            for c in REQUIRED_COLS:
                if c not in new_row:
                    new_row[c] = ""

            df_all = pd.concat([df_all, pd.DataFrame([new_row])], ignore_index=True)
            added += 1

        st.session_state["data"] = df_all
        try:
            st.session_state["plafonds"] = rebuild_plafonds(df_all)
        except Exception:
            pass

        # Reset sélection seulement après confirmation
        st.session_state[pick_state_key] = []

        if skipped:
            st.warning("Ignorés: " + "; ".join(skipped[:10]))
        st.success(f"Embauche complétée ✅ — {added} joueur(s) ajoutés à {dest_owner}.")
        do_rerun()


def tx_current_actor() -> str:
    """Best-effort: the currently selected team in sidebar is the acting owner."""
    return str(st.session_state.get("selected_team", "") or "").strip()

def tx_pick_key_from_label(lbl: str) -> str | None:
    p = _parse_pick_label(lbl)
    if not p:
        return None
    try:
        rnd = str(int(p.get("round", 0)))
        org = str(p.get("origin", "")).strip()
    except Exception:
        return None
    if not org or rnd == "0":
        return None
    return f"{org}__{rnd}"

def tx_locked_label_suffix(lock_info: dict | None) -> str:
    if not lock_info:
        return ""
    tid = str(lock_info.get("trade_id", "") or "").strip()
    oa = str(lock_info.get("owner_a", "") or "").strip()
    ob = str(lock_info.get("owner_b", "") or "").strip()
    who = f"{oa}↔{ob}".strip("↔")
    if tid:
        return f"  🔒 engagé ({who} #{tid})"
    return f"  🔒 engagé ({who})" if who else "  🔒 engagé"

def tx_roster(df: pd.DataFrame, owner: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    d = df[df["Propriétaire"].astype(str).str.strip().eq(str(owner).strip())].copy()
    d = clean_data(d)
    # Exclure IR de la transaction (optionnel: tu peux retirer ce filtre si tu veux permettre)
    if "Slot" in d.columns:
        try:
            d = d[d["Slot"].astype(str).str.strip() != SLOT_IR].copy()
        except Exception:
            pass
    return d

def tx_player_key(row: pd.Series) -> str:
    return _norm_player_key(row.get("Joueur", ""))

def tx_player_label(row: pd.Series) -> str:
    name = str(row.get("Joueur", "")).strip()
    pos = str(row.get("Pos", row.get("Position", "")) or "").strip()
    team = str(row.get("Équipe", row.get("Equipe", "")) or "").strip()
    sal = row.get("Salaire", "")
    try:
        sal_str = money(float(sal)) if str(sal).strip() != "" else ""
    except Exception:
        sal_str = str(sal)
    bits = [b for b in [name, pos, team] if b]
    base = " • ".join(bits) if bits else name
    if sal_str:
        base = f"{base} — {sal_str}"
    return base

def tx_build_player_options(roster: pd.DataFrame, locks: dict, keep_keys: set[str]) -> tuple[list[str], dict]:
    """Returns (labels, meta_by_label). meta has player_key + locked bool."""
    labels = []
    meta = {}
    if roster is None or roster.empty:
        return labels, meta
    for _, r in roster.iterrows():
        k = tx_player_key(r)
        lock_info = (locks.get("players") or {}).get(k)
        locked = bool(lock_info) and (k not in keep_keys)
        base = tx_player_label(r)
        lbl = base + (tx_locked_label_suffix(lock_info) if locked else "")
        labels.append(lbl)
        meta[lbl] = {"player_key": k, "locked": locked, "lock": lock_info, "base": base}
    return labels, meta

def tx_build_pick_options(owner: str, season_lbl: str, year: int, locks: dict, keep_keys: set[str]) -> tuple[list[str], dict]:
    """List picks currently held by owner for a given year. Shows locked label when in other pending trade."""
    labels = []
    meta = {}
    try:
        picks = load_picks(season_lbl)
    except Exception:
        picks = {}
    # picks schema: picks[origin][round] = holder
    for origin, rounds in (picks or {}).items():
        if not isinstance(rounds, dict):
            continue
        for rd, holder in rounds.items():
            try:
                rd_int = int(str(rd))
            except Exception:
                continue
            if str(holder).strip() != str(owner).strip():
                continue
            # optional: if you store year, filter here; in your app picks are per season/year file already
            base = f"R{rd_int} — {origin}"
            k = f"{origin}__{rd_int}"
            lock_info = (locks.get("picks") or {}).get(k)
            locked = bool(lock_info) and (k not in keep_keys)
            lbl = base + (tx_locked_label_suffix(lock_info) if locked else "")
            labels.append(lbl)
            meta[lbl] = {"pick_key": k, "locked": locked, "lock": lock_info, "base": base, "origin": origin, "round": str(rd_int)}
    # stable sort by round then origin
    def _sort_key(lbl):
        b = meta.get(lbl, {}).get("base", lbl)
        p = _parse_pick_label(b)
        try:
            return (int(p.get("round", 99)), str(p.get("origin","")))
        except Exception:
            return (99, str(b))
    labels = sorted(labels, key=_sort_key)
    return labels, meta

def tx_draft_key(season_lbl: str) -> str:
    return f"tx_draft__{season_lbl}"

def tx_get_draft(season_lbl: str) -> dict:
    k = tx_draft_key(season_lbl)
    if k not in st.session_state or not isinstance(st.session_state.get(k), dict):
        st.session_state[k] = {}
    return st.session_state[k]

def tx_clear_draft(season_lbl: str):
    st.session_state[tx_draft_key(season_lbl)] = {}

def tx_validate_draft(owner_a: str, owner_b: str, a_sel: list[str], b_sel: list[str], a_pick_sel: list[str], b_pick_sel: list[str],
                      locks: dict, a_meta: dict, b_meta: dict, ap_meta: dict, bp_meta: dict) -> list[str]:
    errs = []
    if not owner_a or not owner_b:
        errs.append("Choisis les 2 propriétaires.")
        return errs
    if owner_a.strip() == owner_b.strip():
        errs.append("Une transaction doit impliquer deux équipes différentes.")
        return errs

    any_assets = bool(a_sel or b_sel or a_pick_sel or b_pick_sel)
    if not any_assets:
        errs.append("Ajoute au moins un joueur ou un choix pour soumettre une transaction.")
        return errs

    # locked selections
    for lbl in a_sel:
        if a_meta.get(lbl, {}).get("locked"):
            errs.append(f"🔒 Joueur déjà engagé: {a_meta[lbl]['base']}")
    for lbl in b_sel:
        if b_meta.get(lbl, {}).get("locked"):
            errs.append(f"🔒 Joueur déjà engagé: {b_meta[lbl]['base']}")
    for lbl in a_pick_sel:
        if ap_meta.get(lbl, {}).get("locked"):
            errs.append(f"🔒 Choix déjà engagé: {ap_meta[lbl]['base']}")
    for lbl in b_pick_sel:
        if bp_meta.get(lbl, {}).get("locked"):
            errs.append(f"🔒 Choix déjà engagé: {bp_meta[lbl]['base']}")
    return errs

def tx_make_trade_payload(season_lbl: str, owner_a: str, owner_b: str,
                          a_sel: list[str], b_sel: list[str], a_pick_sel: list[str], b_pick_sel: list[str],
                          a_meta: dict, b_meta: dict, ap_meta: dict, bp_meta: dict,
                          ret_a: int, ret_b: int, cash_a: int, cash_b: int) -> dict:
    def _players(labels, meta):
        out=[]
        for lbl in labels:
            info=meta.get(lbl, {})
            k=info.get("player_key")
            base=info.get("base", lbl)
            if k:
                out.append({"key": k, "label": base})
        return out
    def _picks(labels, meta):
        out=[]
        for lbl in labels:
            info=meta.get(lbl, {})
            k=info.get("pick_key")
            base=info.get("base", lbl)
            if k:
                out.append({"key": k, "label": base})
        return out

    trade_id = str(uuid.uuid4())[:8].upper()
    actor = tx_current_actor()
    approvals = {owner_a: bool(actor and actor.strip()==owner_a.strip()),
                 owner_b: bool(actor and actor.strip()==owner_b.strip())}
    return {
        "id": trade_id,
        "season": season_lbl,
        "status": "PENDING",
        "created_ts": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "created_by": actor,
        "owner_a": owner_a,
        "owner_b": owner_b,
        "a_to_b": {"players": _players(a_sel, a_meta), "picks": _picks(a_pick_sel, ap_meta), "retention_salary": int(ret_a or 0), "cash": int(cash_a or 0)},
        "b_to_a": {"players": _players(b_sel, b_meta), "picks": _picks(b_pick_sel, bp_meta), "retention_salary": int(ret_b or 0), "cash": int(cash_b or 0)},
        "approvals": approvals,
    }

def tx_save_pending(season_lbl: str, trade: dict):
    pend = load_pending_trades(season_lbl) if "load_pending_trades" in globals() else []
    if not isinstance(pend, list):
        pend = []
    pend.append(trade)
    if "save_pending_trades" in globals():
        save_pending_trades(season_lbl, pend)

def tx_update_pending(season_lbl: str, pend: list[dict]):
    if "save_pending_trades" in globals():
        save_pending_trades(season_lbl, pend)

def tx_find_pending(season_lbl: str, trade_id: str) -> tuple[int, dict | None, list]:
    pend = load_pending_trades(season_lbl) if "load_pending_trades" in globals() else []
    if not isinstance(pend, list):
        pend = []
    for i, t in enumerate(pend):
        if str(t.get("id","")) == str(trade_id):
            return i, t, pend
    return -1, None, pend

def tx_apply_trade_execution(season_lbl: str, trade: dict):
    """Executes trade: players + picks, writes history, persists."""
    # DataFrame
    df = st.session_state.get("data", pd.DataFrame())
    if df is None or df.empty:
        return

    owner_a = str(trade.get("owner_a","")).strip()
    owner_b = str(trade.get("owner_b","")).strip()

    def _move_player_by_key(player_key: str, new_owner: str):
        nonlocal df
        if not player_key:
            return
        # match by normalized key on Joueur
        if "Joueur" not in df.columns:
            return
        mask = df["Joueur"].astype(str).apply(_norm_player_key).eq(player_key)
        if mask.any():
            df.loc[mask, "Propriétaire"] = new_owner

    for it in (trade.get("a_to_b", {}).get("players") or []):
        _move_player_by_key(str(it.get("key","")), owner_b)
    for it in (trade.get("b_to_a", {}).get("players") or []):
        _move_player_by_key(str(it.get("key","")), owner_a)

    st.session_state["data"] = df

    # Picks
    try:
        picks = load_picks(season_lbl)
    except Exception:
        picks = {}
    def _move_pick_key(pick_key: str, to_owner: str):
        # pick_key = origin__round
        if not pick_key or "__" not in pick_key:
            return
        origin, rnd = pick_key.split("__", 1)
        origin = origin.strip()
        rnd = rnd.strip()
        if not origin or not rnd:
            return
        if origin not in picks or not isinstance(picks.get(origin), dict):
            picks[origin] = {}
        picks[origin][str(int(rnd))] = to_owner

    for it in (trade.get("a_to_b", {}).get("picks") or []):
        _move_pick_key(str(it.get("key","")), owner_b)
    for it in (trade.get("b_to_a", {}).get("picks") or []):
        _move_pick_key(str(it.get("key","")), owner_a)

    if "save_picks" in globals():
        save_picks(season_lbl, picks)

    # History logging (minimal)
    if "append_history_event" in globals() and callable(globals().get("append_history_event")):
        try:
            append_history_event({
                "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
                "action": "TRADE_EXEC",
                "owner_a": owner_a,
                "owner_b": owner_b,
                "trade_id": str(trade.get("id","")),
            })
        except Exception:
            pass

    # Rebuild plafonds if function exists
    if "rebuild_plafonds" in globals() and callable(globals().get("rebuild_plafonds")):
        try:
            st.session_state["plafonds"] = rebuild_plafonds(st.session_state.get("data"))
        except Exception:
            pass
    # Persist data if available
    if "persist_data" in globals() and callable(globals().get("persist_data")):
        try:
            persist_data(st.session_state.get("data"), season_lbl)
        except Exception:
            pass

def tx_render_pending_section(season_lbl: str):
    st.subheader("⏳ Transactions en attente")
    pend = load_pending_trades(season_lbl) if "load_pending_trades" in globals() else []
    if not isinstance(pend, list) or not pend:
        st.caption("Aucune transaction en attente.")
        return

    actor = tx_current_actor()
    for t in pend:
        if str(t.get("status","")).upper() != "PENDING":
            continue
        tid = str(t.get("id",""))
        oa = str(t.get("owner_a",""))
        ob = str(t.get("owner_b",""))
        appr = t.get("approvals", {}) or {}
        a_ok = bool(appr.get(oa))
        b_ok = bool(appr.get(ob))

        with st.container(border=True):
            st.markdown(f"**#{tid}** — {oa} ↔ {ob}")
            st.caption(f"Approuvé: {oa}={'✅' if a_ok else '⏳'} • {ob}={'✅' if b_ok else '⏳'}")

            can_approve = actor and actor.strip() in [oa.strip(), ob.strip()]
            if can_approve:
                already = bool(appr.get(actor))
                c1, c2, c3 = st.columns([1,1,2], vertical_alignment="center")
                with c1:
                    if st.button("✅ Approuver", key=f"appr_{tid}", disabled=already):
                        idx, tr, allp = tx_find_pending(season_lbl, tid)
                        if tr:
                            tr.setdefault("approvals", {})[actor] = True
                            # execute if both
                            oa2=str(tr.get("owner_a",""))
                            ob2=str(tr.get("owner_b",""))
                            ap=tr.get("approvals",{}) or {}
                            if ap.get(oa2) and ap.get(ob2):
                                tr["status"]="COMPLETED"
                                tx_apply_trade_execution(season_lbl, tr)
                            allp[idx]=tr
                            tx_update_pending(season_lbl, allp)
                            do_rerun()
                with c2:
                    if st.button("🗑️ Annuler", key=f"cancel_{tid}", disabled=not can_approve):
                        idx, tr, allp = tx_find_pending(season_lbl, tid)
                        if idx >= 0:
                            allp.pop(idx)
                            tx_update_pending(season_lbl, allp)
                            do_rerun()
            else:
                st.caption("Seuls les propriétaires impliqués peuvent approuver.")

def render_tab_transactions():
    """UI + flow for trades (draft -> validate -> save pending -> approvals -> execute)."""
    season_lbl = str(st.session_state.get("season", "") or "").strip() or "2025-2026"
    df = st.session_state.get("data", pd.DataFrame())
    if df is None:
        df = pd.DataFrame()

    st.subheader("⚖️ Transactions")
    st.caption("Construis une transaction (joueurs + choix + salaire retenu) et vois l’impact sur les masses salariales.")

    owners = sorted(df["Propriétaire"].dropna().astype(str).unique().tolist()) if ("Propriétaire" in df.columns and not df.empty) else []
    if not owners:
        st.info("Aucune donnée chargée. Va dans Gestion Admin → Import Fantrax.")
        return

    # Draft persistence
    draft = tx_get_draft(season_lbl)

    # Owners A/B
    cA, cB = st.columns(2)
    with cA:
        owner_a = st.selectbox("Propriétaire A", owners, index=owners.index(draft.get("owner_a", owners[0])) if draft.get("owner_a") in owners else 0, key=f"tx_owner_a__{season_lbl}")
    with cB:
        default_b = draft.get("owner_b")
        if default_b not in owners or default_b == owner_a:
            # pick another default
            default_b = next((o for o in owners if o != owner_a), owners[0])
        owner_b = st.selectbox("Propriétaire B", owners, index=owners.index(default_b), key=f"tx_owner_b__{season_lbl}")

    # Save to draft (non-widget keys)
    draft["owner_a"]=owner_a
    draft["owner_b"]=owner_b

    # Locks
    locks = pending_locks(season_lbl) if "pending_locks" in globals() else {"players":{}, "picks":{}}

    # Keep keys already selected in this draft, so they don't show as locked for you
    keep_player_keys=set()
    keep_pick_keys=set()
    for side in ["a_players","b_players"]:
        for k in (draft.get(side, []) or []):
            keep_player_keys.add(str(k))
    for side in ["a_picks","b_picks"]:
        for k in (draft.get(side, []) or []):
            keep_pick_keys.add(str(k))

    dfa = tx_roster(df, owner_a)
    dfb = tx_roster(df, owner_b)

    st.divider()
    show_market_only = st.checkbox("Afficher seulement joueurs sur le marché", value=bool(draft.get("market_only", False)), key=f"tx_market_only__{season_lbl}")
    draft["market_only"]=show_market_only

    if show_market_only and "Marché" in df.columns:
        try:
            dfa = dfa[dfa["Marché"].astype(str).str.lower().isin(["oui","true","1","yes"])].copy()
            dfb = dfb[dfb["Marché"].astype(str).str.lower().isin(["oui","true","1","yes"])].copy()
        except Exception:
            pass

    # Build options
    a_labels, a_meta = tx_build_player_options(dfa, locks, keep_player_keys)
    b_labels, b_meta = tx_build_player_options(dfb, locks, keep_player_keys)

    # default selections from draft keys -> labels (match base by key)
    def _labels_from_keys(keys, meta):
        out=[]
        ks=set(keys or [])
        for lbl, info in meta.items():
            if info.get("player_key") in ks:
                out.append(lbl)
        return out

    a_default = _labels_from_keys(draft.get("a_players", []), a_meta)
    b_default = _labels_from_keys(draft.get("b_players", []), b_meta)

    left, right = st.columns(2)
    with left:
        st.markdown(f"## {owner_a} ➜ envoie")
        a_sel = st.multiselect("Joueurs inclus", options=a_labels, default=a_default, key=f"tx_a_players__{season_lbl}")
        ret_a = st.number_input("Salaire retenu (optionnel)", min_value=0, step=1, value=int(draft.get("ret_a", 0) or 0), key=f"tx_ret_a__{season_lbl}")
        cash_a = st.number_input("Montant retenu (cash) — optionnel", min_value=0, step=1, value=int(draft.get("cash_a", 0) or 0), key=f"tx_cash_a__{season_lbl}")
    with right:
        st.markdown(f"## {owner_b} ➜ envoie")
        b_sel = st.multiselect("Joueurs inclus", options=b_labels, default=b_default, key=f"tx_b_players__{season_lbl}")
        ret_b = st.number_input("Salaire retenu (optionnel)", min_value=0, step=1, value=int(draft.get("ret_b", 0) or 0), key=f"tx_ret_b__{season_lbl}")
        cash_b = st.number_input("Montant retenu (cash) — optionnel", min_value=0, step=1, value=int(draft.get("cash_b", 0) or 0), key=f"tx_cash_b__{season_lbl}")

    # Picks year chooser (uses season-based picks file, but UI lets you pick year for grouping)
    year = int(draft.get("pick_year", datetime.datetime.now().year) or datetime.datetime.now().year)
    year = st.selectbox("Année des choix (pour filtrer l’affichage)", [year, year+1, year+2, year+3], index=0, key=f"tx_pick_year__{season_lbl}")
    draft["pick_year"]=year

    ap_labels, ap_meta = tx_build_pick_options(owner_a, season_lbl, year, locks, keep_pick_keys)
    bp_labels, bp_meta = tx_build_pick_options(owner_b, season_lbl, year, locks, keep_pick_keys)

    def _pick_labels_from_keys(keys, meta):
        out=[]
        ks=set(keys or [])
        for lbl, info in meta.items():
            if info.get("pick_key") in ks:
                out.append(lbl)
        return out

    with left:
        st.markdown("### Choix de repêchage (R1–R7)")
        a_pick_sel = st.multiselect("Choix inclus", options=ap_labels, default=_pick_labels_from_keys(draft.get("a_picks", []), ap_meta), key=f"tx_a_picks__{season_lbl}")
    with right:
        st.markdown("### Choix de repêchage (R1–R7)")
        b_pick_sel = st.multiselect("Choix inclus", options=bp_labels, default=_pick_labels_from_keys(draft.get("b_picks", []), bp_meta), key=f"tx_b_picks__{season_lbl}")

    # Update draft canonical keys
    draft["ret_a"]=int(ret_a or 0); draft["ret_b"]=int(ret_b or 0)
    draft["cash_a"]=int(cash_a or 0); draft["cash_b"]=int(cash_b or 0)
    draft["a_players"]=[a_meta[l]["player_key"] for l in a_sel if l in a_meta]
    draft["b_players"]=[b_meta[l]["player_key"] for l in b_sel if l in b_meta]
    draft["a_picks"]=[ap_meta[l]["pick_key"] for l in a_pick_sel if l in ap_meta]
    draft["b_picks"]=[bp_meta[l]["pick_key"] for l in b_pick_sel if l in bp_meta]

    st.divider()
    st.markdown("## Résumé")
    st.write(f"**{owner_a}** donne: {len(draft['a_players'])} joueur(s), {len(draft['a_picks'])} pick(s)")
    st.write(f"**{owner_b}** donne: {len(draft['b_players'])} joueur(s), {len(draft['b_picks'])} pick(s)")

    # Preview pills (simple)
    if draft["a_players"] or draft["a_picks"] or draft["b_players"] or draft["b_picks"]:
        st.markdown("### 👀 Aperçu visuel")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f"**{owner_a} → {owner_b}**")
            for lbl in a_sel:
                base=a_meta.get(lbl,{}).get("base",lbl)
                st.markdown(f"- 👤 {base}")
            for lbl in a_pick_sel:
                base=ap_meta.get(lbl,{}).get("base",lbl)
                st.markdown(f"- 🎯 {base}")
        with c2:
            st.markdown(f"**{owner_b} → {owner_a}**")
            for lbl in b_sel:
                base=b_meta.get(lbl,{}).get("base",lbl)
                st.markdown(f"- 👤 {base}")
            for lbl in b_pick_sel:
                base=bp_meta.get(lbl,{}).get("base",lbl)
                st.markdown(f"- 🎯 {base}")

    st.divider()
    dry_run = st.checkbox("🧪 Simulation seulement (ne crée pas de pending)", value=False, key=f"tx_dry__{season_lbl}")
    confirm = st.checkbox("✅ Je confirme que je veux soumettre cette transaction", value=False, key=f"tx_confirm__{season_lbl}")

    errs = tx_validate_draft(owner_a, owner_b, a_sel, b_sel, a_pick_sel, b_pick_sel, locks, a_meta, b_meta, ap_meta, bp_meta)

    b1, b2 = st.columns([1,1])
    with b1:
        if st.button("📨 Soumettre (en attente d’approbation)", key=f"tx_submit__{season_lbl}", disabled=bool(errs) or (not confirm)):
            if errs:
                for e in errs:
                    st.error(e)
                st.stop()
            if dry_run:
                st.success("Simulation OK (aucune transaction enregistrée).")
                st.stop()
            trade = tx_make_trade_payload(season_lbl, owner_a, owner_b, a_sel, b_sel, a_pick_sel, b_pick_sel, a_meta, b_meta, ap_meta, bp_meta, ret_a, ret_b, cash_a, cash_b)
            tx_save_pending(season_lbl, trade)
            st.success(f"Transaction #{trade['id']} soumise. En attente d’approbation.")
            do_rerun()
    with b2:
        if st.button("🧹 Vider le brouillon", key=f"tx_clear__{season_lbl}"):
            tx_clear_draft(season_lbl)
            do_rerun()

    if errs:
        for e in errs:
            st.warning(e)

    st.divider()
    tx_render_pending_section(season_lbl)
