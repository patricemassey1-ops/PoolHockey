from __future__ import annotations

import os
import io
import re
import pandas as pd
import requests
import streamlit as st
from datetime import datetime
from zoneinfo import ZoneInfo

# =====================================================
# CONFIGURATION & CONSTANTES
# =====================================================
st.set_page_config(page_title="PMS - Gestion de Ligue", layout="wide")

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

REQUIRED_COLS = ["Propriétaire", "Joueur", "Pos", "Equipe", "Salaire", "Level", "Statut", "Slot", "IR Date"]
SLOT_ACTIF = "Actif"
STATUT_GC = "Grand Club"

# Barème de points NHL
SCORING_RULES = {
    "F": {"goals": 3, "assists": 2, "plusMinus": 0.5},
    "D": {"goals": 5, "assists": 3, "plusMinus": 1},
    "G": {"wins": 5, "shutouts": 5, "saves": 0.05, "goalsAgainst": -1}
}

# =====================================================
# FONCTIONS DE NETTOYAGE ET IMPORTATION
# =====================================================

def clean_salary(val):
    """Nettoie les chaînes de caractères de salaire (ex: '1 250 000 $' -> 1250000)"""
    if pd.isna(val): return 0
    s = str(val).replace("$", "").replace(" ", "").replace(",", "")
    try: return int(float(s))
    except: return 0

def parse_fantrax_csv(uploaded_file, team_owner):
    """Lit le CSV et mappe les colonnes vers notre format standard."""
    df_raw = pd.read_csv(uploaded_file)
    
    # Mapping des colonnes Fantrax vers les nôtres
    # On cherche les colonnes qui contiennent ces mots-clés
    mapping = {
        'Player': 'Joueur',
        'Team': 'Equipe',
        'Position': 'Pos',
        'Salary': 'Salaire'
    }
    
    df_new = pd.DataFrame()
    
    # Identification intelligente des colonnes
    for raw_col in df_raw.columns:
        for key, target in mapping.items():
            if key.lower() in raw_col.lower():
                df_new[target] = df_raw[raw_col]
    
    # Ajout des colonnes par défaut
    df_new["Propriétaire"] = team_owner
    df_new["Salaire"] = df_new["Salaire"].apply(clean_salary)
    df_new["Statut"] = STATUT_GC
    df_new["Slot"] = SLOT_ACTIF
    df_new["Level"] = "STD"
    df_new["IR Date"] = ""
    
    # S'assurer que toutes les colonnes requises sont là
    for col in REQUIRED_COLS:
        if col not in df_new.columns:
            df_new[col] = ""
            
    return df_new[REQUIRED_COLS]

def save_data(df):
    season = st.session_state.get("season", "2024-2025")
    path = os.path.join(DATA_DIR, f"fantrax_{season}.csv")
    df.to_csv(path, index=False)
    st.session_state["data"] = df

# =====================================================
# 🛠️ ONGLET ADMIN (IMPORTATION)
# =====================================================

def render_tab_admin():
    st.title("🛠️ Gestion Admin (Whalers)")
    
    # --- SECTION 1 : SYNCHRO ---
    with st.expander("🔄 Synchronisation NHL Live", expanded=False):
        if st.button("Mettre à jour les scores NHL"):
            st.info("Appel API NHL en cours...")
            # (Insérer ici ta fonction sync_nhl_stats déjà créée)

    st.divider()

    # --- SECTION 2 : IMPORTATION ---
    st.subheader("📥 Importer des Joueurs (CSV)")
    st.write("Téléchargez un export Fantrax pour mettre à jour l'alignement d'une équipe.")
    
    teams = ["Whalers", "Nordiques", "Cracheurs", "Prédateurs", "Red Wings", "Canadiens"]
    col_t, col_f = st.columns([1, 2])
    
    with col_t:
        target_team = st.selectbox("Équipe cible", teams)
    
    with col_f:
        file = st.file_uploader("Choisir le fichier CSV", type=["csv"])

    if file:
        df_preview = parse_fantrax_csv(file, target_team)
        st.write(f"🔍 Aperçu de l'importation ({len(df_preview)} joueurs détectés) :")
        st.dataframe(df_preview.head(10), use_container_width=True)
        
        if st.button(f"Confirmer l'importation pour les {target_team}", type="primary"):
            # Charger les données globales
            df_global = st.session_state.get("data", pd.DataFrame(columns=REQUIRED_COLS))
            
            # Supprimer les anciens joueurs de cette équipe
            df_global = df_global[df_global["Propriétaire"] != target_team]
            
            # Ajouter les nouveaux
            df_final = pd.concat([df_global, df_preview], ignore_index=True)
            
            # Sauvegarder
            save_data(df_final)
            st.success(f"✅ Alignement des {target_team} mis à jour !")
            st.rerun()

# =====================================================
# 🏆 CLASSEMENT & LOGIQUE APP
# =====================================================

def main():
    if "data" not in st.session_state:
        # Charger le fichier de la saison par défaut
        path = os.path.join(DATA_DIR, "fantrax_2024-2025.csv")
        if os.path.exists(path):
            st.session_state["data"] = pd.read_csv(path)
        else:
            st.session_state["data"] = pd.DataFrame(columns=REQUIRED_COLS)

    # Sidebar
    st.sidebar.title("🏒 PMS Pool")
    st.session_state["season"] = st.sidebar.selectbox("Saison", ["2024-2025", "2025-2026"])
    
    teams = ["Whalers", "Nordiques", "Cracheurs", "Prédateurs", "Red Wings", "Canadiens"]
    selected_team = st.sidebar.selectbox("Mon Équipe", teams, key="selected_team")
    
    is_admin = (selected_team.lower() == "whalers")
    
    menu = ["🏆 Classement", "🧾 Alignement"]
    if is_admin:
        menu.append("🛠️ Gestion Admin")
    
    choice = st.sidebar.radio("Navigation", menu)

    if choice == "🏆 Classement":
        st.title("🏆 Classement")
        st.dataframe(st.session_state["data"], use_container_width=True) # Simple view for now
    elif choice == "🧾 Alignement":
        st.title(f"Alignement de {selected_team}")
        df = st.session_state["data"]
        st.dataframe(df[df["Propriétaire"] == selected_team], use_container_width=True)
    elif choice == "🛠️ Gestion Admin":
        render_tab_admin()

if __name__ == "__main__":
    main()