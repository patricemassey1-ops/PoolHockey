from __future__ import annotations

import os
import io
import re
import json
import html
import base64
import requests
import pandas as pd
import streamlit as st
from datetime import datetime
from zoneinfo import ZoneInfo

# =====================================================
# 1. CONFIGURATION & CONSTANTES
# =====================================================
st.set_page_config(page_title="PMS - Fantasy Hockey Pool", layout="wide")

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

REQUIRED_COLS = ["Propriétaire", "Joueur", "Pos", "Equipe", "Salaire", "Level", "Statut", "Slot", "IR Date"]
SLOT_ACTIF = "Actif"
SLOT_BANC = "Banc"
SLOT_IR = "Blessé"
STATUT_GC = "Grand Club"
STATUT_CE = "Club École"

TZ_TOR = ZoneInfo("America/Toronto")

# Barème de points par défaut
SCORING_RULES = {
    "F": {"goals": 3, "assists": 2, "plusMinus": 0.5, "powerPlayPoints": 1, "shots": 0.1},
    "D": {"goals": 5, "assists": 3, "plusMinus": 1, "powerPlayPoints": 1, "shots": 0.2},
    "G": {"wins": 5, "shutouts": 5, "saves": 0.05, "goalsAgainst": -1}
}

# =====================================================
# 2. STYLE CSS
# =====================================================
THEME_CSS = """<style>
    .leaderboard-card { background: rgba(255,255,255,0.04); border-radius: 14px; padding: 15px; margin-bottom: 8px; border: 1px solid rgba(255,255,255,0.1); }
    .salaryCell { white-space: nowrap; text-align: right; font-weight: 900; }
    .pms-broadcast-bar { border-radius: 18px; padding: 18px 16px; background: linear-gradient(90deg, rgba(255,255,255,0.05), rgba(255,255,255,0.02), rgba(255,255,255,0.05)); border: 1px solid rgba(255,255,255,0.10); box-shadow: 0 14px 40px rgba(0,0,0,0.30); text-align: center;}
</style>"""
st.markdown(THEME_CSS, unsafe_allow_html=True)

# =====================================================
# 3. MOTEUR DE POINTAGE NHL API
# =====================================================

def sync_nhl_stats():
    """Récupère les stats depuis l'API NHL et calcule les points."""
    try:
        s_resp = requests.get("https://api-web.nhl.com/v1/skater-stats-now").json()
        skaters = pd.DataFrame(s_resp['data'])
        g_resp = requests.get("https://api-web.nhl.com/v1/goalie-stats-now").json()
        goalies = pd.DataFrame(g_resp['data'])

        points_map = {}
        for _, r in skaters.iterrows():
            name = f"{r['firstName']} {r['lastName']}".lower().strip()
            pos = "D" if r['positionCode'] == "D" else "F"
            rules = SCORING_RULES[pos]
            pts = (r.get('goals', 0)*rules['goals'] + r.get('assists', 0)*rules['assists'] + 
                   r.get('plusMinus', 0)*rules['plusMinus'] + r.get('powerPlayPoints', 0)*rules['powerPlayPoints'])
            points_map[name] = round(pts, 2)

        for _, r in goalies.iterrows():
            name = f"{r['firstName']} {r['lastName']}".lower().strip()
            rules = SCORING_RULES["G"]
            pts = (r.get('wins', 0)*rules['wins'] + r.get('shutouts', 0)*rules['shutouts'] + 
                   r.get('saves', 0)*rules['saves'] + r.get('goalsAgainst', 0)*rules['goalsAgainst'])
            points_map[name] = round(pts, 2)

        cache_path = os.path.join(DATA_DIR, "points_cache.csv")
        pd.DataFrame(list(points_map.items()), columns=['player', 'pts']).to_csv(cache_path, index=False)
        return True
    except Exception as e:
        st.error(f"Erreur API NHL: {e}")
        return False

def get_player_points(name: str) -> float:
    path = os.path.join(DATA_DIR, "points_cache.csv")
    if not os.path.exists(path): return 0.0
    df = pd.read_csv(path)
    match = df[df['player'] == name.lower().strip()]
    return float(match['pts'].values[0]) if not match.empty else 0.0

# =====================================================
# 4. FONCTIONS DE GESTION DES DONNÉES (IMPORT ROBUSTE)
# =====================================================

def clean_salary(val):
    if pd.isna(val): return 0
    s = str(val).replace("$", "").replace(" ", "").replace(",", "").replace("\xa0", "")
    try: return int(float(s))
    except: return 0

def parse_fantrax_csv(uploaded_file, team_owner):
    """Analyse robuste du CSV Fantrax en cherchant l'en-tête."""
    raw_bytes = uploaded_file.read()
    raw_text = raw_bytes.decode("utf-8", errors="ignore")
    lines = raw_text.splitlines()
    uploaded_file.seek(0)

    header_idx = -1
    separator = ","
    for i, line in enumerate(lines):
        if ";" in line: separator = ";"
        low = line.lower()
        if ("player" in low or "joueur" in low) and ("salary" in low or "cap hit" in low):
            header_idx = i
            break
            
    if header_idx == -1:
        st.error("En-tête (Player/Salary) introuvable dans le fichier.")
        return pd.DataFrame()

    try:
        df_raw = pd.read_csv(io.StringIO("\n".join(lines[header_idx:])), sep=separator)
        
        mapping = {
            'Joueur': ['player', 'joueur', 'name'],
            'Equipe': ['team', 'equipe', 'équipe'],
            'Pos': ['pos', 'position'],
            'Salaire': ['salary', 'cap hit', 'aav', 'salaire']
        }
        
        df_new = pd.DataFrame()
        for target, keywords in mapping.items():
            for col in df_raw.columns:
                if any(k in col.lower() for k in keywords):
                    df_new[target] = df_raw[col]
                    break
        
        df_new["Propriétaire"] = team_owner
        df_new["Salaire"] = df_new["Salaire"].apply(clean_salary) if "Salaire" in df_new.columns else 0
        df_new["Statut"] = STATUT_GC
        df_new["Slot"] = SLOT_ACTIF
        df_new["Level"] = "STD"
        df_new["IR Date"] = ""
        
        for col in REQUIRED_COLS:
            if col not in df_new.columns: df_new[col] = ""
            
        return df_new[REQUIRED_COLS].dropna(subset=["Joueur"])
    except Exception as e:
        st.error(f"Erreur de lecture : {e}")
        return pd.DataFrame()

def save_data(df):
    season = st.session_state.get("season", "2024-2025")
    path = os.path.join(DATA_DIR, f"fantrax_{season}.csv")
    df.to_csv(path, index=False)
    st.session_state["data"] = df

# =====================================================
# 5. INTERFACE UTILISATEUR (TABS)
# =====================================================

def render_tab_leaderboard():
    st.markdown("<div class='pms-broadcast-bar'><h1>🏆 Classement Général</h1></div>", unsafe_allow_html=True)
    df = st.session_state["data"]
    if df.empty:
        st.info("Aucune donnée. Importez des joueurs en mode Admin.")
        return

    df['Pts'] = df['Joueur'].apply(get_player_points)
    standings = df[df['Slot'] == SLOT_ACTIF].groupby("Propriétaire")['Pts'].sum().reset_index()
    standings = standings.sort_values(by="Pts", ascending=False).reset_index(drop=True)

    for i, row in standings.iterrows():
        medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else f"#{i+1}"
        st.markdown(f"""<div class='leaderboard-card'><b>{medal} {row['Propriétaire']}</b> : {row['Pts']:.2f} PTS</div>""", unsafe_allow_html=True)

def render_tab_admin():
    st.title("🛠️ Gestion Admin (Whalers Only)")
    
    # Synchro NHL
    with st.expander("🔄 Synchronisation NHL Live"):
        if st.button("Mettre à jour les scores NHL", type="primary"):
            if sync_nhl_stats(): st.success("Scores mis à jour !")

    st.divider()

    # Importation
    st.subheader("📥 Importer un alignement")
    teams = ["Whalers", "Nordiques", "Cracheurs", "Prédateurs", "Red Wings", "Canadiens"]
    c1, c2 = st.columns([1, 2])
    target_team = c1.selectbox("Équipe destinataire", teams)
    file = c2.file_uploader("Fichier CSV Fantrax", type=["csv"])

    if file:
        df_preview = parse_fantrax_csv(file, target_team)
        if not df_preview.empty:
            st.write("🔍 Aperçu (10 premiers) :")
            st.dataframe(df_preview.head(10), use_container_width=True)
            if st.button(f"Enregistrer pour {target_team}", type="primary"):
                df_global = st.session_state["data"]
                df_global = df_global[df_global["Propriétaire"] != target_team]
                df_final = pd.concat([df_global, df_preview], ignore_index=True)
                save_data(df_final)
                st.success("✅ Données enregistrées !")
                st.rerun()

# =====================================================
# 6. ROUTAGE PRINCIPAL
# =====================================================

def main():
    # Initialisation session
    season = "2024-2025"
    if "season" not in st.session_state: st.session_state["season"] = season
    
    path = os.path.join(DATA_DIR, f"fantrax_{st.session_state['season']}.csv")
    if "data" not in st.session_state:
        st.session_state["data"] = pd.read_csv(path) if os.path.exists(path) else pd.DataFrame(columns=REQUIRED_COLS)

    # Sidebar
    st.sidebar.title("🏒 PMS Pool")
    selected_team = st.sidebar.selectbox("Mon Équipe", ["Whalers", "Nordiques", "Cracheurs", "Prédateurs", "Red Wings", "Canadiens"])
    
    is_admin = (selected_team == "Whalers")
    menu = ["🏆 Classement", "🧾 Alignement"]
    if is_admin: menu.append("🛠️ Gestion Admin")
    
    choice = st.sidebar.radio("Navigation", menu)

    if choice == "🏆 Classement":
        render_tab_leaderboard()
    elif choice == "🧾 Alignement":
        st.title(f"🧾 Alignement : {selected_team}")
        df = st.session_state["data"]
        team_df = df[df["Propriétaire"] == selected_team]
        if team_df.empty:
            st.info("Aucun joueur. Demandez à l'Admin d'importer votre fichier.")
        else:
            team_df['Pts'] = team_df['Joueur'].apply(get_player_points)
            st.dataframe(team_df[['Slot', 'Pos', 'Joueur', 'Equipe', 'Pts', 'Salaire']], use_container_width=True, hide_index=True)
    elif choice == "🛠️ Gestion Admin":
        render_tab_admin()

if __name__ == "__main__":
    main()