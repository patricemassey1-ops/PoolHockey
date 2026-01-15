from __future__ import annotations

import os
import io
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


# =====================================================
# SAFE IMAGE (évite MediaFileHandler: Missing file)
# =====================================================
def safe_image(image, *args, **kwargs):
    try:
        if isinstance(image, str):
            p = image.strip()
            if p and os.path.exists(p):
                return st.image(p, *args, **kwargs)
            cap = kwargs.get("caption", "")
            if cap:
                st.caption(cap)
            return None
        return st.image(image, *args, **kwargs)
    except Exception:
        cap = kwargs.get("caption", "")
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
# --- plafonds par défaut (évite cap=0)
if "PLAFOND_GC" not in st.session_state or int(st.session_state.get("PLAFOND_GC") or 0) <= 0:
    st.session_state["PLAFOND_GC"] = 95_500_000
if "PLAFOND_CE" not in st.session_state or int(st.session_state.get("PLAFOND_CE") or 0) <= 0:
    st.session_state["PLAFOND_CE"] = 47_750_000

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
THEME_CSS = """<style>

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
   GM TAB (migré depuis st.markdown <style> inline)
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
}

</style>
"""

def apply_theme():
    """Injecte le CSS UNE seule fois par run."""
    if st.session_state.get('_theme_css_injected', False):
        return
    st.markdown(THEME_CSS, unsafe_allow_html=True)
    st.session_state['_theme_css_injected'] = True

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
    # Guard: éviter plusieurs rerun dans le même run
    if st.session_state.get("_rerun_requested", False):
        return
    st.session_state["_rerun_requested"] = True
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

_picked_tab = st.sidebar.radio(
    "Navigation",
    NAV_TABS,
    index=_cur_idx,
    key="sb_nav_radio",
)

if _picked_tab != st.session_state.get("active_tab"):
    st.session_state["active_tab"] = _picked_tab

# ✅ Variable utilisée par le routing plus bas
active_tab = st.session_state.get("active_tab", NAV_TABS[0])

st.sidebar.divider()
st.sidebar.markdown("### 🏒 Équipe")

teams = sorted(list(LOGOS.keys())) if "LOGOS" in globals() else []
if not teams:
    teams = ["Whalers"]

cur_team = get_selected_team().strip() or teams[0]
if cur_team not in teams:
    cur_team = teams[0]

chosen_team = st.sidebar.selectbox(
    "Choisir une équipe",
    teams,
    index=teams.index(cur_team),
    key="sb_team_select",
)

if chosen_team and chosen_team != cur_team:
    pick_team(chosen_team)

logo_path = team_logo_path(get_selected_team())
if logo_path:
    st.sidebar.image(logo_path, use_container_width=True)


if st.sidebar.button("👀 Prévisualiser l’alignement GC", use_container_width=True, key="sb_preview_gc"):
    st.session_state["gc_preview_open"] = True
    st.session_state["active_tab"] = "🧾 Alignement"
    do_rerun()

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



def render_tab_autonomes(show_header: bool = True, lock_dest_to_owner: bool = True, scope: str = "autonomes"):
    """Recherche + sélection (max 5) + embauche — version idiotproof.

    Principes:
    - La sélection est stockée en session_state par (scope, saison, propriétaire). Elle ne dépend PAS des filtres.
    - Aucun widget n'est réinitialisé en écrivant dans st.session_state[key] après création.
    - Règle stricte: JAMAIS embauchable si (NHL GP < 84) OU (Level == ELC)
    """
    import pandas as pd
    import streamlit as st
    import re

    # ---------- contexte (owner/season) ----------
    season_lbl = str(st.session_state.get("season", "") or "").strip()

    owner = ""
    if "get_selected_team" in globals() and callable(globals()["get_selected_team"]):
        try:
            owner = str(globals()["get_selected_team"]() or "").strip()
        except Exception:
            owner = ""
    if not owner:
        owner = str(st.session_state.get("selected_team", "") or "").strip()

    # owners list (si admin non lock)
    df_league = st.session_state.get("data")
    owners = []
    if isinstance(df_league, pd.DataFrame) and (not df_league.empty) and ("Propriétaire" in df_league.columns):
        owners = sorted(df_league["Propriétaire"].dropna().astype(str).str.strip().unique().tolist())
    if not owners and "LOGOS" in globals():
        try:
            owners = sorted(list(globals()["LOGOS"].keys()))
        except Exception:
            owners = []
    if not owners and owner:
        owners = [owner]

    dest_owner = owner if lock_dest_to_owner else st.selectbox(
        "Équipe destination",
        owners if owners else [""],
        index=(owners.index(owner) if owner in owners else 0),
        key=f"fa_dest_owner__{scope}__{season_lbl}__{owner or 'x'}",
    )

    # ---------- players db ----------
    df_db = st.session_state.get("players_db")
    if not isinstance(df_db, pd.DataFrame) or df_db.empty:
        df_db = st.session_state.get("players")
    if not isinstance(df_db, pd.DataFrame) or df_db.empty:
        st.info("Base joueurs introuvable (players_db).")
        return

    name_col = "Player" if "Player" in df_db.columns else ("Joueur" if "Joueur" in df_db.columns else None)
    if not name_col:
        st.error("La base joueurs doit contenir 'Player' ou 'Joueur'.")
        return

    team_col = "Team" if "Team" in df_db.columns else ("Équipe" if "Équipe" in df_db.columns else None)
    pos_col  = "Position" if "Position" in df_db.columns else ("Pos" if "Pos" in df_db.columns else None)
    level_col = "Level" if "Level" in df_db.columns else None

    nhl_gp_col = None
    for c in ["NHL GP", "NHL_GP", "NHLGP", "GP"]:
        if c in df_db.columns:
            nhl_gp_col = c
            break

    cap_col = None
    for c in ["Cap Hit", "CapHit", "Salaire", "Salary", "AAV"]:
        if c in df_db.columns:
            cap_col = c
            break

    # helpers
    def _strip(x) -> str:
        return str(x or "").strip()

    def _cap_to_int(v) -> int:
        if "_cap_to_int" in globals() and callable(globals()["_cap_to_int"]):
            try:
                return int(globals()["_cap_to_int"](v))
            except Exception:
                pass
        try:
            return int(float(v))
        except Exception:
            return 0

    def _money(v: int) -> str:
        if "money" in globals() and callable(globals()["money"]):
            try:
                return globals()["money"](int(v or 0))
            except Exception:
                pass
        return f"{int(v or 0):,}$".replace(",", " ")

    # normalisation nom pour owned mapping
    def _norm_name(s: str) -> str:
        s = _strip(s).lower()
        s = re.sub(r"\s+", " ", s)
        # support "Nom, Prénom" -> "prénom nom"
        if "," in s:
            parts = [p.strip() for p in s.split(",", 1)]
            if len(parts) == 2 and parts[0] and parts[1]:
                s = f"{parts[1]} {parts[0]}".strip()
        # si ton projet a déjà un normaliseur, on l'utilise
        if "_norm_player_key" in globals() and callable(globals()["_norm_player_key"]):
            try:
                return str(globals()["_norm_player_key"](s) or "").strip().lower()
            except Exception:
                return s
        return s

    # ---------- owned mapping ----------
    owner_map = {}
    if isinstance(df_league, pd.DataFrame) and (not df_league.empty) and ("Joueur" in df_league.columns) and ("Propriétaire" in df_league.columns):
        tmp = df_league.copy()
        tmp["_k"] = tmp["Joueur"].astype(str).map(_norm_name)
        for _, rr in tmp.iterrows():
            k = _strip(rr.get("_k", ""))
            if k:
                owner_map[k] = _strip(rr.get("Propriétaire", ""))

    def owned_to(player_name: str) -> str:
        return owner_map.get(_norm_name(player_name), "")

    # ---------- state keys (par owner+season+scope) ----------
    sel_key = f"fa_sel__{scope}__{season_lbl}__{owner or 'x'}"
    if sel_key not in st.session_state or not isinstance(st.session_state.get(sel_key), list):
        st.session_state[sel_key] = []
    selected = [_strip(x) for x in (st.session_state.get(sel_key) or []) if _strip(x)]
    selected = selected[:5]
    st.session_state[sel_key] = selected

    # ---------- header ----------
    if show_header:
        st.subheader("👤 Joueurs autonomes" if scope == "autonomes" else "➕ Ajout de joueurs")
        st.caption("Recherche → Ajouter (max 5) → Confirmer l’embauche. La sélection reste même si tu changes de recherche/onglet.")

    # ---------- sidebar action (si tu changes d'onglet par erreur) ----------
    try:
        if selected:
            st.sidebar.divider()
            st.sidebar.markdown("### ✅ Embauche en attente")
            st.sidebar.caption(f"{len(selected)}/5 joueur(s) sélectionné(s)")
            if st.sidebar.button("Aller confirmer l’embauche", use_container_width=True, key=f"fa_go_confirm__{scope}__{season_lbl}__{owner or 'x'}"):
                # on essaie de renvoyer vers l'onglet autonomes si ton routing l'utilise
                if "active_tab" in st.session_state:
                    # essayer label courant
                    st.session_state["active_tab"] = "👤 Joueurs autonomes"
                if "do_rerun" in globals() and callable(globals()["do_rerun"]):
                    globals()["do_rerun"]()
                st.rerun()
    except Exception:
        pass

    # ---------- sélection UI ----------
    st.markdown(f"### ✅ Sélection ({len(selected)} / 5)")
    if not selected:
        st.info("Aucun joueur sélectionné. Tape un nom ci-dessous, puis clique **Ajouter**.")
    else:
        for pname in selected:
            own = owned_to(pname)
            left, right = st.columns([8, 2], vertical_alignment="center")
            with left:
                if own:
                    st.markdown(f"🔴 **{pname}** — Appartenant à **{own}**")
                else:
                    st.markdown(f"✅ **{pname}**")
            with right:
                if st.button("Retirer", key=f"fa_remove__{scope}__{season_lbl}__{owner or 'x'}__{pname}", use_container_width=True):
                    st.session_state[sel_key] = [x for x in selected if _strip(x).lower() != _strip(pname).lower()]
                    if "do_rerun" in globals() and callable(globals()["do_rerun"]):
                        globals()["do_rerun"]()
                    st.rerun()

    st.divider()

    # ---------- filtres ----------
    f1, f2, f3 = st.columns([5, 3, 3], vertical_alignment="center")
    with f1:
        q_name = st.text_input("Nom / Prénom", value="", key=f"fa_q__{scope}__{season_lbl}__{owner or 'x'}").strip()
    with f2:
        team_vals = ["Toutes"]
        if team_col:
            try:
                team_vals += sorted(df_db[team_col].dropna().astype(str).str.strip().unique().tolist())
            except Exception:
                pass
        team_pick = st.selectbox("Équipe", team_vals, index=0, key=f"fa_team__{scope}__{season_lbl}__{owner or 'x'}")
    with f3:
        lvl_vals = ["Tous"]
        if level_col:
            try:
                lvl_vals += sorted(df_db[level_col].dropna().astype(str).str.strip().unique().tolist())
            except Exception:
                pass
        lvl_pick = st.selectbox("Level (Contrat)", lvl_vals, index=0, key=f"fa_lvl__{scope}__{season_lbl}__{owner or 'x'}")

    exclure = st.checkbox(
        "Exclure les joueurs selon les critères (NHL GP < 84 ou Level = ELC)",
        value=True,
        key=f"fa_excl__{scope}__{season_lbl}__{owner or 'x'}",
    )

    # aucun résultat tant que rien tapé
    if not q_name:
        st.info("Commence à taper un nom (ou début de nom) dans **Nom / Prénom** pour afficher des résultats.")
        return

    # ---------- build results ----------
    dff = df_db.copy()
    dff["_name"] = dff[name_col].astype(str).str.strip()
    mask = dff["_name"].str.lower().str.contains(q_name.lower(), na=False)

    if team_col and team_pick != "Toutes":
        mask = mask & (dff[team_col].astype(str).str.strip().eq(team_pick))
    if level_col and lvl_pick != "Tous":
        mask = mask & (dff[level_col].astype(str).str.strip().eq(lvl_pick))

    dff = dff[mask].copy()
    if dff.empty:
        st.warning("Aucun joueur ne correspond à ta recherche / filtres.")
        return

    # derive columns
    def _gp(v) -> int:
        try:
            return int(float(v))
        except Exception:
            return 0

    dff["_gp"] = dff[nhl_gp_col].apply(_gp) if nhl_gp_col and nhl_gp_col in dff.columns else 0
    dff["_lvl"] = dff[level_col].astype(str).str.strip() if level_col and level_col in dff.columns else ""
    dff["_owned"] = dff["_name"].apply(owned_to)
    dff["_reason"] = ""
    dff.loc[dff["_gp"] < 84, "_reason"] = "NHL GP < 84"
    dff.loc[dff["_lvl"].astype(str).str.upper().eq("ELC"), "_reason"] = dff["_reason"].where(dff["_reason"]=="", dff["_reason"] + " + ") + "ELC"

    dff["_jouable"] = (dff["_gp"] >= 84) & (~dff["_lvl"].astype(str).str.upper().eq("ELC"))
    dff["_cap"] = dff[cap_col].apply(_cap_to_int) if cap_col and cap_col in dff.columns else 0

    if exclure:
        dff = dff[dff["_jouable"]].copy()
        if dff.empty:
            st.warning("Aucun joueur jouable avec ces critères (NHL GP ≥ 84 et Level ≠ ELC).")
            return

    # tri: sélectionnés en haut, puis jouables, puis cap desc, puis nom
    sel_set = set([_strip(x).lower() for x in selected])
    dff["_is_sel"] = dff["_name"].astype(str).str.strip().str.lower().isin(sel_set)
    dff = dff.sort_values(by=["_is_sel", "_jouable", "_cap", "_name"], ascending=[False, False, False, True], kind="mergesort")

    # ---------- results table (fantrax-like) ----------
    st.markdown("### 🔎 Résultats")
    st.caption("Colonnes: ✅ Jouable (NHL GP ≥ 84 et Level ≠ ELC) • 🔴 Appartenant à (déjà dans une équipe) • Raison (si non-jouable).")

    maxed = len(selected) >= 5

    # header row
    hcols = st.columns([3.2, 1.0, 1.2, 1.0, 1.0, 1.3, 1.5], vertical_alignment="center")
    hcols[0].markdown("**Joueur**")
    hcols[1].markdown("**Pos**")
    hcols[2].markdown("**Équipe**")
    hcols[3].markdown("**NHL GP**")
    hcols[4].markdown("**Level**")
    hcols[5].markdown("**Appartenant à**")
    hcols[6].markdown("**Action**")

    show = dff.head(25).copy()
    for i, rr in show.iterrows():
        pname = _strip(rr.get("_name",""))
        if not pname:
            continue
        pos = _strip(rr.get(pos_col,"")) if pos_col and pos_col in show.columns else ""
        team = _strip(rr.get(team_col,"")) if team_col and team_col in show.columns else ""
        gp = int(rr.get("_gp",0) or 0)
        lvl = _strip(rr.get("_lvl",""))
        own = _strip(rr.get("_owned",""))
        jouable = bool(rr.get("_jouable", False))
        reason = _strip(rr.get("_reason",""))

        already = pname.strip().lower() in sel_set

        # action state: can add only if not maxed, not already, not owned, and jouable
        can_add = (not maxed) and (not already) and (not own) and jouable

        row = st.columns([3.2, 1.0, 1.2, 1.0, 1.0, 1.3, 1.5], vertical_alignment="center")

        # style badges
        badge = "✅" if jouable else "❌"
        name_txt = f"{badge} {pname}"
        if own:
            name_txt = f"🔴 {name_txt}"

        # add subtle row highlight
        if (not jouable) or own:
            row[0].markdown(f"<div style='padding:6px 8px;border-radius:10px;background:rgba(239,68,68,0.10);'>{name_txt}<br/><span style='opacity:.85;font-size:12px'>{reason if reason else ''}</span></div>", unsafe_allow_html=True)
        else:
            row[0].markdown(name_txt)

        row[1].markdown(pos or "—")
        row[2].markdown(team or "—")
        row[3].markdown(str(gp))
        row[4].markdown(lvl or "—")
        row[5].markdown(own or "—")

        # action button
        if already:
            row[6].button("✓ Ajouté", key=f"fa_added__{scope}__{season_lbl}__{owner or 'x'}__{pname}", disabled=True, use_container_width=True, type="primary")
        else:
            row[6].button(
                "➕ Ajouter",
                key=f"fa_add__{scope}__{season_lbl}__{owner or 'x'}__{pname}",
                disabled=(not can_add),
                use_container_width=True,
                type="primary" if can_add else "secondary",
                help=("Max 5 atteint" if maxed else ("Déjà à une équipe" if own else ("Non jouable" if not jouable else ""))),
            )
            # handle add click
            if st.session_state.get(f"fa_add__{scope}__{season_lbl}__{owner or 'x'}__{pname}") is True:
                # Streamlit buttons don't set session_state to True persistently; they return True, so we handle with return value.
                pass
        # Proper click handling: buttons return bool, so re-render using if statement above is tricky in columns; do it explicitly:
        # (We can't get return value after .button called in a variable? We'll do it now.)
        # NOTE: We'll re-call button with same key would break; so we implement with local var:
        # can't here. We'll instead implement using st.button return value directly below.
    # Re-render loop with proper click returns: do second pass with return values would be heavy.
    # Instead, we handle add clicks with a dedicated minimal list of buttons below:

    # ---------- quick add via selectbox (idiotproof fallback) ----------
    # When user wants super-simple adding without row buttons.
    st.write("")
    st.markdown("#### ➕ Ajouter depuis les résultats")
    # Only list addable players from current results page
    addable = show[(show["_jouable"] == True) & (show["_owned"].astype(str).str.strip() == "")].copy()
    addable["_label"] = addable["_name"].astype(str).str.strip() + "  •  " + addable["_cap"].astype(int).map(_money)
    opts = addable["_label"].tolist()

    add_pick_key = f"fa_addpick__{scope}__{season_lbl}__{owner or 'x'}"
    picked_lbl = st.selectbox("Choisir un joueur à ajouter", [""] + opts, index=0, key=add_pick_key, disabled=maxed)
    if picked_lbl:
        st.success("🟢 À ajouter à la sélection")
    if st.button("Ajouter à la sélection", key=f"fa_add_btn__{scope}__{season_lbl}__{owner or 'x'}", disabled=(not picked_lbl) or maxed, use_container_width=True, type="primary"):
        if picked_lbl:
            pname = picked_lbl.split("  •  ")[0].strip()
            # validate again
            if owned_to(pname):
                st.error("Impossible: ce joueur appartient déjà à une équipe.")
                st.stop()
            # strict rule
            rowp = dff[dff["_name"].astype(str).str.strip().eq(pname)].head(1)
            if not rowp.empty:
                jouable = bool(rowp.iloc[0].get("_jouable", False))
                if not jouable:
                    st.error("Impossible: joueur NON jouable (NHL GP < 84 ou Level = ELC).")
                    st.stop()
            cur = [_strip(x) for x in (st.session_state.get(sel_key) or []) if _strip(x)]
            if pname.lower() not in [x.lower() for x in cur]:
                cur.append(pname)
            st.session_state[sel_key] = cur[:5]
            if "do_rerun" in globals() and callable(globals()["do_rerun"]):
                globals()["do_rerun"]()
            st.rerun()

    st.divider()

    # ---------- embauche / confirm ----------
    st.markdown("### 📝 Embauche")
    assign_state_key = f"fa_assign__{scope}__{season_lbl}__{owner or 'x'}"
    assign = st.radio("Affectation", ["GC", "Banc", "CE"], horizontal=True, key=assign_state_key)

    # validate selected: none owned, none non-jouable
    owned_selected = [p for p in selected if owned_to(p)]
    non_jouable_selected = []
    if selected:
        for p in selected:
            sub = dff[dff["_name"].astype(str).str.strip().eq(p)].head(1)
            if not sub.empty:
                if not bool(sub.iloc[0].get("_jouable", False)):
                    non_jouable_selected.append(p)
            else:
                # if not in current filter, check in df_db quickly
                sub2 = df_db[df_db[name_col].astype(str).str.strip().eq(p)].head(1)
                if not sub2.empty:
                    gp = int(float(sub2.iloc[0].get(nhl_gp_col, 0) or 0)) if nhl_gp_col else 0
                    lvl = str(sub2.iloc[0].get(level_col, "") or "").strip()
                    if gp < 84 or lvl.upper() == "ELC":
                        non_jouable_selected.append(p)

    disable_confirm = (not selected) or bool(owned_selected) or bool(non_jouable_selected)

    if owned_selected:
        st.warning("🔴 Déjà à une équipe: " + ", ".join(owned_selected[:10]))
    if non_jouable_selected:
        st.warning("❌ NON jouable (NHL GP < 84 ou Level = ELC): " + ", ".join(non_jouable_selected[:10]))

    if st.button(
        "✅ Confirmer l’embauche",
        type="primary",
        use_container_width=True,
        key=f"fa_confirm__{scope}__{season_lbl}__{owner or 'x'}",
        disabled=disable_confirm,
        help=("Corrige la sélection avant de confirmer." if disable_confirm else ""),
    ):
        # charge df_all
        df_all = st.session_state.get("data")
        if not isinstance(df_all, pd.DataFrame):
            df_all = pd.DataFrame(columns=globals().get("REQUIRED_COLS", ["Propriétaire","Joueur","Équipe","Pos","Salaire","Statut","Slot","Level"]))

        # clean
        if "clean_data" in globals() and callable(globals()["clean_data"]):
            try:
                df_all = globals()["clean_data"](df_all)
            except Exception:
                pass

        # affectation
        STATUT_GC = globals().get("STATUT_GC", "GC")
        STATUT_CE = globals().get("STATUT_CE", "CE")
        SLOT_ACTIF = globals().get("SLOT_ACTIF", "Actif")
        SLOT_BANC  = globals().get("SLOT_BANC", "Banc")
        SLOT_MINEUR = globals().get("SLOT_MINEUR", "Mineur")

        if assign == "GC":
            statut_val, slot_val = STATUT_GC, SLOT_ACTIF
        elif assign == "Banc":
            statut_val, slot_val = STATUT_GC, SLOT_BANC
        else:
            statut_val, slot_val = STATUT_CE, SLOT_MINEUR

        added = 0
        skipped = []

        for p in selected:
            if owned_to(p):
                skipped.append(p); continue

            sub = df_db[df_db[name_col].astype(str).str.strip().eq(p)].head(1)
            if sub.empty:
                skipped.append(p); continue
            r0 = sub.iloc[0].to_dict()

            gp = int(float(r0.get(nhl_gp_col, 0) or 0)) if nhl_gp_col else 0
            lvl = str(r0.get(level_col, "") or "").strip() if level_col else ""
            if gp < 84 or lvl.upper() == "ELC":
                skipped.append(p); continue

            pos = str(r0.get(pos_col, "") or "").strip() if pos_col else ""
            team = str(r0.get(team_col, "") or "").strip() if team_col else ""
            sal = _cap_to_int(r0.get(cap_col, 0)) if cap_col else 0

            new_row = {
                "Propriétaire": str(dest_owner),
                "Joueur": str(p),
                "Équipe": team,
                "Pos": pos,
                "Salaire": int(sal or 0),
                "Statut": statut_val,
                "Slot": slot_val,
                "Level": lvl,
            }
            # ensure required cols
            REQUIRED = globals().get("REQUIRED_COLS", [])
            if isinstance(REQUIRED, (list, tuple)) and REQUIRED:
                for c in REQUIRED:
                    if c not in new_row:
                        new_row[c] = ""
            df_all = pd.concat([df_all, pd.DataFrame([new_row])], ignore_index=True)
            added += 1

        st.session_state["data"] = df_all
        if "rebuild_plafonds" in globals() and callable(globals()["rebuild_plafonds"]):
            try:
                st.session_state["plafonds"] = globals()["rebuild_plafonds"](df_all)
            except Exception:
                pass

        # clear selection
        st.session_state[sel_key] = []
        if skipped:
            st.warning("Ignorés: " + ", ".join(skipped[:10]))
        st.success(f"Embauche complétée ✅ — {added} joueur(s) ajouté(s) à {dest_owner}.")
        if "do_rerun" in globals() and callable(globals()["do_rerun"]):
            globals()["do_rerun"]()
        st.rerun()


def _strip_accents(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))

def _norm_player_key(s: str) -> str:
    """Normalise un nom pour matching robuste (accents, ponctuation, espaces)."""
    s = _strip_accents(str(s or "")).lower().strip()
    # garde lettres/chiffres/espaces seulement
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _player_key_variants(name: str) -> set[str]:
    """Retourne plusieurs variantes de clé (prenom nom / nom prenom / avec virgule)."""
    raw = str(name or "").strip()
    base = _norm_player_key(raw)
    out = set()
    if base:
        out.add(base)

    # Variante si format "Nom, Prenom ..."
    if "," in raw:
        parts = [p.strip() for p in raw.split(",", 1)]
        if len(parts) == 2:
            last = _norm_player_key(parts[0])
            first = _norm_player_key(parts[1])
            if last and first:
                out.add(f"{last} {first}".strip())
                out.add(f"{first} {last}".strip())

    # Variante inverse si format "Prenom ... Nom"
    toks = base.split()
    if len(toks) >= 2:
        first = " ".join(toks[:-1])
        last = toks[-1]
        out.add(f"{first} {last}".strip())
        out.add(f"{last} {first}".strip())

    return {k for k in out if k}


@st.cache_data(show_spinner=False)
def _players_level_map(pdb_path: str) -> dict[str, str]:
    """Construit un mapping {clé_normalisée -> Level (STD/ELC)} depuis Hockey.players.csv."""
    try:
        players = pd.read_csv(pdb_path)
    except Exception:
        return {}

    if players is None or players.empty:
        return {}

    # Colonne nom joueur
    name_col = None
    for c in ["Player", "Joueur", "Name", "Nom", "player", "joueur", "name", "nom"]:
        if c in players.columns:
            name_col = c
            break
    if not name_col:
        # fallback: première colonne qui ressemble à un nom
        name_col = players.columns[0]

    # Colonne Level
    level_col = None
    for c in ["Level", "level", "LEVEL"]:
        if c in players.columns:
            level_col = c
            break
    if not level_col:
        return {}

    m: dict[str, str] = {}
    for _, r in players.iterrows():
        nm = str(r.get(name_col, "") or "").strip()
        lvl = str(r.get(level_col, "") or "").strip().upper()

        if lvl not in ("STD", "ELC"):
            continue

        for k in _player_key_variants(nm):
            if k and k not in m:
                m[k] = lvl

    return m
def force_level_from_players(df: pd.DataFrame) -> pd.DataFrame:
    """Compat helper (v38→v39): applique l'enrichissement Level (STD/ELC) depuis /data/Hockey.players.csv."""
    try:
        if "apply_players_level" in globals() and callable(globals()["apply_players_level"]):
            return apply_players_level(df)
    except Exception:
        pass
    return df



# =====================================================
# v35 — LEVEL ENRICH (central helper)
#   Source de vérité: Hockey.Players.csv
#   Ajoute:
#     - Level (override)
#     - Level_found (bool) : trouvé dans DB
#     - Level_src (str)    : 'Hockey.Players.csv' si trouvé sinon ''
# =====================================================
def apply_players_level(df: pd.DataFrame, pdb_path: str) -> pd.DataFrame:
    """Force df['Level'] à partir de Hockey.players.csv (STD/ELC)."""
    if df is None or df.empty or "Joueur" not in df.columns:
        return df

    out = df.copy()
    if "Level" not in out.columns:
        out["Level"] = ""

    level_map = _players_level_map(pdb_path)
    if not level_map:
        return out

    def _resolve(name: str) -> str:
        for k in _player_key_variants(name):
            v = level_map.get(k, "")
            if v:
                return v
        return ""

    mapped = out["Joueur"].astype(str).apply(_resolve)
    mask = mapped.astype(str).str.strip().ne("")
    out.loc[mask, "Level"] = mapped[mask]
    return out

# =====================================================
# ROUTING — MAIN ENGINE (idiotproof)
#   ✅ 1 seule logique de routing
#   ✅ évite écran noir (aucune tab rendue)
# =====================================================

def render_admin_section():
    """Section Admin minimaliste (import Fantrax)."""
    st.subheader("🛠️ Gestion Admin — Import Fantrax")
    st.caption("Importe un CSV Fantrax et écrase les données de la saison active.")

    uploaded_file = st.file_uploader("Choisir un CSV Fantrax", type=["csv"], key="admin_fantrax_uploader")
    if not uploaded_file:
        return

    try:
        df_new = parse_fantrax(uploaded_file)
    except Exception as e:
        st.error(f"Erreur d'importation: {e}")
        return

    st.markdown("#### Aperçu de l'importation")
    st.dataframe(df_new.head(25), use_container_width=True)

    if st.button("✅ Confirmer l'importation (écrase les données actuelles)", type="primary", use_container_width=True, key="admin_confirm_import"):
        st.session_state["data"] = df_new
        try:
            st.session_state["plafonds"] = rebuild_plafonds(df_new)
        except Exception:
            pass
        try:
            persist_data(df_new, st.session_state.get("season", ""))
        except Exception:
            pass
        st.success("Données importées avec succès ✅")
        if "do_rerun" in globals() and callable(globals()["do_rerun"]):
            do_rerun()
        st.rerun()


def main():
    # 1) Styles
    try:
        apply_theme()
    except Exception:
        pass

    # 2) Auth: require_password() fait déjà st.stop() si non authed.
    if not st.session_state.get("authed", True):
        return

    # 3) Routing
    tab = str(globals().get("active_tab", st.session_state.get("active_tab", "🏠 Home")))

    if tab == "🏠 Home":
        st.subheader("🏠 Home — Tableau de bord")
        df_p = st.session_state.get("plafonds")
        if isinstance(df_p, pd.DataFrame) and not df_p.empty:
            build_tableau_ui(df_p)
        else:
            st.info("Charge des données (Admin → Import) pour voir les masses salariales.")

    elif tab == "🧾 Alignement":
        owner = str(get_selected_team() or "").strip()
        st.subheader(f"🧾 Alignement — {owner or '—'}")

        df = st.session_state.get("data")
        if not isinstance(df, pd.DataFrame) or df.empty:
            st.warning("Aucun joueur trouvé. Va dans 🛠️ Gestion Admin → Import.")
            return

        if not owner:
            st.info("Sélectionne une équipe dans la barre de gauche.")
            return

        # Filtre propriétaire (robuste aux espaces)
        dprop = df[df["Propriétaire"].astype(str).str.strip().eq(owner)].copy()
        if dprop.empty:
            st.warning("Aucune ligne pour ce propriétaire dans les données.")
            return

        # Alertes (caps, IR, banc)
        try:
            total_gc = float(dprop[dprop["Statut"] == STATUT_GC]["Salaire"].fillna(0).astype(float).sum())
        except Exception:
            total_gc = 0.0
        try:
            total_ce = float(dprop[dprop["Statut"] == STATUT_CE]["Salaire"].fillna(0).astype(float).sum())
        except Exception:
            total_ce = 0.0
        ir_count = int((dprop["Slot"] == SLOT_IR).sum()) if "Slot" in dprop.columns else 0
        banc_count = int((dprop["Slot"] == SLOT_BANC).sum()) if "Slot" in dprop.columns else 0

        try:
            show_status_alerts(
                total_gc=total_gc, cap_gc=int(st.session_state.get("PLAFOND_GC", 0) or 0),
                total_ce=total_ce, cap_ce=int(st.session_state.get("PLAFOND_CE", 0) or 0),
                ir_count=ir_count,
                banc_count=banc_count
            )
        except Exception:
            pass

        # Roster lists (clicables)
        st.markdown("### Grand Club — Actifs")
        act = dprop[(dprop["Statut"] == STATUT_GC) & (dprop["Slot"] == SLOT_ACTIF)]
        picked = roster_click_list(act, owner, "gc_actif")
        if picked:
            set_move_ctx(owner, picked, "gc_actif")
            st.rerun()

        st.markdown("### Grand Club — Banc / Réservistes")
        bnc = dprop[(dprop["Statut"] == STATUT_GC) & (dprop["Slot"] == SLOT_BANC)]
        picked_b = roster_click_list(bnc, owner, "gc_banc")
        if picked_b:
            set_move_ctx(owner, picked_b, "gc_banc")
            st.rerun()

        st.markdown("### Club École — Mineurs")
        mineur = dprop[dprop["Statut"] == STATUT_CE]
        picked_m = roster_click_list(mineur, owner, "ce_list")
        if picked_m:
            set_move_ctx(owner, picked_m, "ce_list")
            st.rerun()

        st.markdown("### 🩹 IR — Blessés")
        ir_players = dprop[dprop["Slot"] == SLOT_IR]
        picked_i = roster_click_list(ir_players, owner, "ir_list")
        if picked_i:
            set_move_ctx(owner, picked_i, "ir_list")
            st.rerun()

    elif tab == "🧊 GM":
        render_tab_gm(show_header=True)

    elif tab == "👤 Joueurs autonomes":
        render_tab_autonomes(show_header=True, lock_dest_to_owner=True)

    elif tab == "🕘 Historique":
        st.subheader("🕘 Historique")
        h = st.session_state.get("history")
        if isinstance(h, pd.DataFrame) and not h.empty:
            if "timestamp" in h.columns:
                try:
                    h2 = h.copy()
                    h2["timestamp_dt"] = pd.to_datetime(h2["timestamp"], errors="coerce")
                    h2 = h2.sort_values("timestamp_dt", ascending=False)
                except Exception:
                    h2 = h
            else:
                h2 = h
            st.dataframe(h2, use_container_width=True)
        else:
            st.info("Aucun historique pour cette saison.")

    elif tab == "⚖️ Transactions":
        st.subheader("⚖️ Transactions")
        st.info("À venir: écran transactions centralisé (réclamations, échanges, etc.).")

    elif tab == "🛠️ Gestion Admin":
        if _is_admin_whalers():
            render_admin_section()
        else:
            st.warning("Accès Admin refusé.")

    elif tab == "🧠 Recommandations":
        st.subheader("🧠 Recommandations")
        st.info("Analyse de l'alignement en cours…")
        st.success("OK — aucune règle critique détectée (placeholder).")

    else:
        st.warning(f"Onglet inconnu: {tab}")


# =====================================================
# EXEC — Toujours appeler main() en fin de script
# =====================================================
main()
