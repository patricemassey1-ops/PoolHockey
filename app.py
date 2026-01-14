from __future__ import annotations

import os
import io
import re
import requests
import pandas as pd
import streamlit as st
from datetime import datetime
from zoneinfo import ZoneInfo

# =====================================================
# 1. CONFIGURATION & CONSTANTES
# =====================================================
st.set_page_config(page_title="PMS - Pool Hockey", layout="wide")

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

REQUIRED_COLS = ["Propriétaire", "Joueur", "Pos", "Equipe", "Salaire", "Level", "Statut", "Slot", "IR Date"]
SLOT_ACTIF = "Actif"
STATUT_GC = "Grand Club"
TZ_TOR = ZoneInfo("America/Toronto")

# Barème de points NHL
SCORING_RULES = {
    "F": {"goals": 3, "assists": 2},
    "D": {"goals": 5, "assists": 3},
    "G": {"wins": 5, "shutouts": 5, "saves": 0.05}
}

# =====================================================
# 2. FONCTIONS DE NETTOYAGE & PARSING (ROBUSTE)
# =====================================================

def clean_salary(val):
    """Nettoie les salaires (ex: '4 750 000 $' -> 4750000)"""
    if pd.isna(val): return 0
    s = str(val).replace("$", "").replace(",", "").replace("\xa0", "").strip()
    # Gère les formats avec espaces (ex: 4 750 000)
    s = re.sub(r'\s+', '', s)
    try: return int(float(s))
    except: return 0

def parse_fantrax_robust(uploaded_file, team_owner):
    """
    Lit les fichiers Fantrax qui contiennent plusieurs sections (Skaters/Goalies).
    Extrait les données en ignorant les lignes de titres parasites.
    """
    raw_bytes = uploaded_file.read()
    raw_text = raw_bytes.decode("utf-8", errors="ignore")
    lines = raw_text.splitlines()
    
    # On cherche les indices des en-têtes
    skater_header_idx = -1
    goalie_header_idx = -1
    
    for i, line in enumerate(lines):
        low = line.lower()
        if '"player"' in low or 'player' in low:
            if skater_header_idx == -1: 
                skater_header_idx = i
            else: 
                goalie_header_idx = i

    def extract_df(start_idx, end_idx=None):
        if start_idx == -1: return pd.DataFrame()
        content = "\n".join(lines[start_idx:end_idx])
        df = pd.read_csv(io.StringIO(content), sep=",", quotechar='"')
        # Nettoyage des noms de colonnes
        df.columns = [c.strip().replace('"', '') for c in df.columns]
        return df

    # Extraction des deux blocs
    df_skaters = extract_df(skater_header_idx, goalie_header_idx - 1 if goalie_header_idx != -1 else None)
    df_goalies = extract_df(goalie_header_idx)

    # Fusion
    df_all = pd.concat([df_skaters, df_goalies], ignore_index=True)
    
    # Mapping des colonnes Fantrax -> PMS
    mapping = {
        'Player': 'Joueur',
        'Team': 'Equipe',
        'Pos': 'Pos',
        'Salary': 'Salaire'
    }
    
    df_final = pd.DataFrame()
    for target, keyword in mapping.items():
        # Cherche la colonne qui contient le mot clé (insensible à la casse)
        match = [c for c in df_all.columns if keyword.lower() in c.lower()]
        if match: df_final[target] = df_all[match[0]]
    
    # Nettoyage final
    df_final["Propriétaire"] = team_owner
    df_final["Salaire"] = df_final["Salary"].apply(clean_salary)
    df_final["Statut"] = STATUT_GC
    df_final["Slot"] = df_all["Status"].apply(lambda x: "Actif" if "Act" in str(x) else "Banc")
    df_final["Level"] = "STD"
    df_final["IR Date"] = ""
    
    # Renommer pour correspondre à REQUIRED_COLS
    df_final = df_final.rename(columns={'Player': 'Joueur', 'Team': 'Equipe', 'Position': 'Pos'})
    
    for col in REQUIRED_COLS:
        if col not in df_final.columns: df_final[col] = ""
            
    return df_final[REQUIRED_COLS].dropna(subset=["Joueur"])

def save_data(df):
    season = st.session_state.get("season", "2024-2025")
    path = os.path.join(DATA_DIR, f"fantrax_{season}.csv")
    df.to_csv(path, index=False)
    st.session_state["data"] = df

# =====================================================
# 3. INTERFACE TABS
# =====================================================

def render_tab_leaderboard():
    st.markdown("<div class='pms-broadcast-bar'><h1>🏆 Classement Général</h1></div>", unsafe_allow_html=True)
    df = st.session_state.get("data", pd.DataFrame())
    if df.empty:
        st.info("Aucune donnée. Importez des joueurs via l'onglet Admin.")
        return
    st.dataframe(df, use_container_width=True, hide_index=True)

def render_tab_admin():
    st.title("🛠️ Gestion Admin (Whalers)")
    
    st.subheader("📥 Importer un alignement Fantrax")
    teams = ["Whalers", "Nordiques", "Cracheurs", "Prédateurs", "Red Wings", "Canadiens"]
    
    col1, col2 = st.columns([1, 2])
    with col1:
        target_team = st.selectbox("Équipe destinataire", teams)
    with col2:
        file = st.file_uploader("Fichier CSV Fantrax", type=["csv"])

    if file:
        try:
            df_preview = parse_fantrax_robust(file, target_team)
            if not df_preview.empty:
                st.write(f"✅ {len(df_preview)} joueurs détectés pour {target_team}")
                st.dataframe(df_preview.head(5), use_container_width=True)
                
                if st.button(f"Enregistrer l'alignement {target_team}", type="primary"):
                    df_cur = st.session_state.get("data", pd.DataFrame(columns=REQUIRED_COLS))
                    # On remplace l'ancien alignement de l'équipe
                    df_cur = df_cur[df_cur["Propriétaire"] != target_team]
                    df_final = pd.concat([df_cur, df_preview], ignore_index=True)
                    save_data(df_final)
                    st.success("Données enregistrées !")
                    st.rerun()
        except Exception as e:
            st.error(f"Erreur lors de l'analyse : {e}")

# =====================================================
# 4. MAIN ROUTING
# =====================================================

def main():
    # Chargement initial
    if "data" not in st.session_state:
        path = os.path.join(DATA_DIR, "fantrax_2024-2025.csv")
        st.session_state["data"] = pd.read_csv(path) if os.path.exists(path) else pd.DataFrame(columns=REQUIRED_COLS)

    # Sidebar
    st.sidebar.title("🏒 PMS Pool")
    st.session_state["season"] = st.sidebar.selectbox("Saison", ["2024-2025", "2025-2026"])
    
    teams = ["Whalers", "Nordiques", "Cracheurs", "Prédateurs", "Red Wings", "Canadiens"]
    selected_team = st.sidebar.selectbox("Mon Équipe", teams, key="selected_team")
    
    # Affichage du Logo
    logo_path = os.path.join(DATA_DIR, f"{selected_team}_Logo.png")
    if os.path.exists(logo_path):
        st.sidebar.image(logo_path, use_container_width=True)
    
    # Navigation
    is_admin = (selected_team.lower() == "whalers")
    menu = ["🏆 Classement", "🧾 Alignement"]
    if is_admin: menu.append("🛠️ Gestion Admin")
    
    choice = st.sidebar.radio("Navigation", menu)

    if choice == "🏆 Classement":
        render_tab_leaderboard()
    elif choice == "🧾 Alignement":
        st.header(f"Alignement : {selected_team}")
        df = st.session_state["data"]
        st.dataframe(df[df["Propriétaire"] == selected_team], use_container_width=True, hide_index=True)
    elif choice == "🛠️ Gestion Admin":
        render_tab_admin()

if __name__ == "__main__":
    main()