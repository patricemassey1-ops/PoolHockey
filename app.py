from __future__ import annotations

import os
import io
import re
import unicodedata
import json
import html
import base64
import hashlib
import requests  # Added for NHL API calls
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components


# =====================================================
# CONFIGURATION & SCORING RULES
# =====================================================
SCORING_RULES = {
    "F": {"goals": 3, "assists": 2, "plusMinus": 0.5, "powerPlayPoints": 1, "shots": 0.1},
    "D": {"goals": 5, "assists": 3, "plusMinus": 1, "powerPlayPoints": 1, "shots": 0.2},
    "G": {"wins": 5, "shutouts": 5, "saves": 0.05, "goalsAgainst": -1}
}

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
# PATHS — repo local (Streamlit Cloud safe)
# =====================================================
APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

def _resolve_local_logo(candidates: list[str]) -> str:
    search_dirs = [APP_DIR, os.getcwd(), os.path.join(os.getcwd(), "data"), os.path.join(APP_DIR, "data")]
    for name in candidates:
        for d in search_dirs:
            p = os.path.join(d, name)
            if os.path.exists(p):
                return p
    return os.path.join(APP_DIR, candidates[0]) 

LOGO_POOL_FILE = _resolve_local_logo(["logo_pool.png","Logo_Pool.png","LOGO_POOL.png"])
GM_LOGO_FILE = _resolve_local_logo(["gm_logo.png","GM_LOGO.png"])

# =====================================================
# STREAMLIT CONFIG
# =====================================================
st.set_page_config(page_title="PMS", layout="wide")
if "PLAFOND_GC" not in st.session_state or int(st.session_state.get("PLAFOND_GC") or 0) <= 0:
    st.session_state["PLAFOND_GC"] = 95_500_000
if "PLAFOND_CE" not in st.session_state or int(st.session_state.get("PLAFOND_CE") or 0) <= 0:
    st.session_state["PLAFOND_CE"] = 47_750_000

# =====================================================
# 🏆 LIVE SCORING ENGINE (NHL API)
# =====================================================
def sync_nhl_stats():
    """Fetches stats from the NHL API and saves to points_cache.csv"""
    try:
        # Fetch Skaters (F/D)
        s_resp = requests.get("https://api-web.nhl.com/v1/skater-stats-now").json()
        skaters = pd.DataFrame(s_resp['data'])
        # Fetch Goalies (G)
        g_resp = requests.get("https://api-web.nhl.com/v1/goalie-stats-now").json()
        goalies = pd.DataFrame(g_resp['data'])

        points_map = {}

        for _, r in skaters.iterrows():
            name = f"{r['firstName']} {r['lastName']}".lower().strip()
            pos = "D" if r['positionCode'] == "D" else "F"
            rules = SCORING_RULES[pos]
            pts = (r.get('goals', 0) * rules['goals'] + 
                   r.get('assists', 0) * rules['assists'] + 
                   r.get('plusMinus', 0) * rules['plusMinus'] +
                   r.get('powerPlayPoints', 0) * rules['powerPlayPoints'] +
                   r.get('shots', 0) * rules['shots'])
            points_map[name] = round(pts, 2)

        for _, r in goalies.iterrows():
            name = f"{r['firstName']} {r['lastName']}".lower().strip()
            rules = SCORING_RULES["G"]
            pts = (r.get('wins', 0) * rules['wins'] + 
                   r.get('shutouts', 0) * rules['shutouts'] + 
                   r.get('saves', 0) * rules['saves'] + 
                   r.get('goalsAgainst', 0) * rules['goalsAgainst'])
            points_map[name] = round(pts, 2)

        cache_df = pd.DataFrame(list(points_map.items()), columns=['player', 'pts'])
        cache_df.to_csv(os.path.join(DATA_DIR, "points_cache.csv"), index=False)
        return True
    except Exception as e:
        st.error(f"Erreur API NHL: {e}")
        return False

def get_cached_points(name: str) -> float:
    """Retrieves points for a player from the local cache file."""
    path = os.path.join(DATA_DIR, "points_cache.csv")
    if not os.path.exists(path): return 0.0
    try:
        df = pd.read_csv(path)
        match = df[df['player'] == name.lower().strip()]
        return float(match['pts'].values[0]) if not match.empty else 0.0
    except: return 0.0

# =====================================================
# THEME & CSS
# =====================================================
THEME_CSS = """<style>
.leaderboard-card { background: rgba(255,255,255,0.04); border-radius: 14px; padding: 16px; margin-bottom: 8px; border: 1px solid rgba(255,255,255,0.1); }
.levelBadge { display:inline-block; padding:2px 10px; border-radius:999px; font-weight:800; font-size:0.82rem; background: rgba(255,255,255,0.06); }
.salaryCell { white-space: nowrap; text-align: right; font-weight: 900; }
.pms-broadcast-bar { border-radius: 18px; padding: 18px 16px; background: linear-gradient(90deg, rgba(255,255,255,0.05), rgba(255,255,255,0.02), rgba(255,255,255,0.05)); border: 1px solid rgba(255,255,255,0.10); box-shadow: 0 14px 40px rgba(0,0,0,0.30); text-align: center;}
</style>"""
st.markdown(THEME_CSS, unsafe_allow_html=True)

# =====================================================
# DATE & UTILITIES
# =====================================================
MOIS_FR = ["", "janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
TZ_TOR = ZoneInfo("America/Montreal")
REQUIRED_COLS = ["Propriétaire", "Joueur", "Pos", "Equipe", "Salaire", "Level", "Statut", "Slot", "IR Date"]

SLOT_ACTIF = "Actif"
SLOT_BANC = "Banc"
SLOT_IR = "Blessé"
STATUT_GC = "Grand Club"
STATUT_CE = "Club École"

def money(v) -> str:
    try: return f"{int(v):,}".replace(",", " ") + " $"
    except: return "0 $"

def normalize_pos(pos: str) -> str:
    p = str(pos or "").upper()
    if "G" in p: return "G"
    if "D" in p: return "D"
    return "F"

def get_selected_team() -> str:
    return str(st.session_state.get("selected_team") or "").strip()

# =====================================================
# 🏆 TAB: CLASSEMENT (LEADERBOARD)
# =====================================================
def render_tab_leaderboard():
    st.markdown("<div class='pms-broadcast-bar'><h1>🏆 Classement de la Ligue</h1></div>", unsafe_allow_html=True)
    st.write("")
    
    df = st.session_state.get("data")
    if df is None or df.empty:
        st.info("Aucun joueur n'est actuellement dans la ligue.")
        return

    # Attach live points
    df['Pts'] = df['Joueur'].apply(get_cached_points)
    
    # Leaderboard logic: Sum points for "Actif" players only
    active_players = df[df['Slot'] == SLOT_ACTIF].copy()
    standings = active_players.groupby("Propriétaire")['Pts'].sum().reset_index()
    standings = standings.sort_values(by="Pts", ascending=False).reset_index(drop=True)

    c1, c2 = st.columns([2, 1])
    with c1:
        for i, row in standings.iterrows():
            medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else f"#{i+1}"
            st.markdown(f"""
            <div class="leaderboard-card">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <div style="font-size:1.2rem; font-weight:bold;">{medal} {row['Propriétaire']}</div>
                    <div style="font-size:1.6rem; font-weight:900; color:#22c55e;">{row['Pts']:.2f} <span style="font-size:0.8rem; opacity:0.6;">PTS</span></div>
                </div>
            </div>
            """, unsafe_allow_html=True)
    with c2:
        st.subheader("💡 Info")
        st.write("Le pointage est basé sur les statistiques réelles de la NHL.")
        st.caption("Seuls les joueurs en position 'Actif' accumulent des points pour leur propriétaire.")
        st.divider()
        with st.expander("Consulter le barème"):
            st.write("**Attaquants**: B=3, P=2, +/-=0.5")
            st.write("**Défenseurs**: B=5, P=3, +/-=1")
            st.write("**Gardiens**: V=5, BL=5, Arr=0.05")

# =====================================================
# MAIN APP ROUTING
# =====================================================
def pick_team(team: str):
    st.session_state["selected_team"] = team
    st.rerun()

def load_data():
    season = st.session_state.get("season", "2024-2025")
    path = os.path.join(DATA_DIR, f"fantrax_{season}.csv")
    if os.path.exists(path):
        return pd.read_csv(path)
    return pd.DataFrame(columns=REQUIRED_COLS)

# =====================================================
# START APP
# =====================================================
if "data" not in st.session_state:
    st.session_state["data"] = load_data()

# --- SIDEBAR ---
st.sidebar.title("🏒 PMS Pool")
saisons = ["2024-2025", "2025-2026"]
season_pick = st.sidebar.selectbox("Saison", saisons, key="sb_season_select")
st.session_state["season"] = season_pick

teams = ["Whalers", "Nordiques", "Cracheurs", "Prédateurs", "Red Wings", "Canadiens"]
cur_team = get_selected_team() or teams[0]
chosen_team = st.sidebar.selectbox("Équipe", teams, index=teams.index(cur_team))
if chosen_team != cur_team:
    pick_team(chosen_team)

# Navigation
is_admin = (chosen_team.lower() == "whalers")
NAV_TABS = ["🏆 Classement", "🧾 Alignement", "🧊 GM", "👤 Joueurs autonomes", "🕘 Historique", "⚖️ Transactions"]
if is_admin:
    NAV_TABS.append("🛠️ Gestion Admin")

active_tab = st.sidebar.radio("Navigation", NAV_TABS)

# --- ROUTING ---
if active_tab == "🏆 Classement":
    render_tab_leaderboard()

elif active_tab == "🧾 Alignement":
    st.header(f"🧾 Alignement: {chosen_team}")
    df = st.session_state["data"]
    dprop = df[df["Propriétaire"] == chosen_team].copy()
    if not dprop.empty:
        dprop['Pts'] = dprop['Joueur'].apply(get_cached_points)
        st.dataframe(dprop[['Slot', 'Pos', 'Joueur', 'Pts', 'Salaire']], use_container_width=True, hide_index=True)
    else:
        st.info("Aucun joueur pour cette équipe.")

elif active_tab == "🛠️ Gestion Admin" and is_admin:
    st.header("🛠️ Gestion Admin (Whalers)")
    
    with st.expander("🔄 Synchronisation NHL Live", expanded=True):
        st.write("Récupérer les statistiques réelles de la NHL pour mettre à jour les points.")
        if st.button("Mettre à jour les scores", type="primary", use_container_width=True):
            with st.spinner("Appel à l'API NHL..."):
                if sync_nhl_stats():
                    st.success("Points mis à jour !")
                    st.rerun()
    
    st.divider()
    st.write("### Gestion des fichiers")
    # Place your existing Admin CSV import logic here

else:
    st.title(active_tab)
    st.info("Contenu en cours de développement.")