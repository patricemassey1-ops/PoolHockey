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

# =====================================================
# 2. FONCTIONS DE NETTOYAGE & PARSING (FIXED)
# =====================================================

def clean_salary(val):
    if pd.isna(val): return 0
    s = str(val).replace("$", "").replace(",", "").replace("\xa0", "").strip()
    s = re.sub(r'\s+', '', s)
    try:
        return int(float(s))
    except:
        return 0

def parse_fantrax_robust(uploaded_file, team_owner):
    """
    Analyse le CSV de façon ultra-robuste pour éviter l'erreur 'Expected X fields, saw Y'.
    """
    raw_bytes = uploaded_file.read()
    raw_text = raw_bytes.decode("utf-8", errors="ignore")
    lines = raw_text.splitlines()
    
    data_rows = []
    current_columns = []
    
    # 1. Parcourir le fichier ligne par ligne pour extraire les données
    for line in lines:
        # Nettoyer la ligne (enlever espaces et guillemets inutiles)
        parts = [p.strip().replace('"', '') for p in line.split(',')]
        
        # Détecter une ligne d'en-tête (contient "Player" ou "Joueur")
        if any("player" in p.lower() or "joueur" in p.lower() for p in parts):
            current_columns = parts
            continue
            
        # Si on a un en-tête et que la ligne a le même nombre d'éléments
        if current_columns and len(parts) == len(current_columns):
            # Créer un dictionnaire pour cette ligne
            row_dict = dict(zip(current_columns, parts))
            # On ne garde que si le nom du joueur n'est pas vide
            if row_dict.get("Player") or row_dict.get("Joueur"):
                data_rows.append(row_dict)

    if not data_rows:
        st.error("Aucune donnée de joueur n'a pu être extraite. Vérifiez le format du CSV.")
        return pd.DataFrame()

    df_all = pd.DataFrame(data_rows)
    
    # 2. Mapping intelligent des colonnes (Recherche de synonymes)
    def find_col(possible_names):
        for col in df_all.columns:
            if any(name.lower() in col.lower() for name in possible_names):
                return col
        return None

    c_joueur = find_col(['player', 'joueur', 'name'])
    c_equipe = find_col(['team', 'equipe', 'équipe'])
    c_pos = find_col(['pos', 'position'])
    c_salaire = find_col(['salary', 'salaire', 'cap hit', 'aav'])
    c_status = find_col(['status', 'statut'])

    # 3. Construction du DataFrame final
    df_final = pd.DataFrame()
    df_final["Joueur"] = df_all[c_joueur]
    df_final["Equipe"] = df_all[c_equipe] if c_equipe else "N/A"
    df_final["Pos"] = df_all[c_pos] if c_pos else "F"
    df_final["Salaire"] = df_all[c_salaire].apply(clean_salary) if c_salaire else 0
    df_final["Propriétaire"] = team_owner
    df_final["Statut"] = STATUT_GC
    
    if c_status:
        df_final["Slot"] = df_all[c_status].apply(lambda x: "Actif" if "act" in str(x).lower() else "Banc")
    else:
        df_final["Slot"] = "Actif"

    df_final["Level"] = "STD"
    df_final["IR Date"] = ""
    
    for col in REQUIRED_COLS:
        if col not in df_final.columns: df_final[col] = ""
            
    return df_final[REQUIRED_COLS].dropna(subset=["Joueur"])

# =====================================================
# 3. INTERFACE ADMIN
# =====================================================

def render_tab_admin():
    st.title("🛠️ Gestion Admin")
    
    st.subheader("📥 Importer un alignement Fantrax")
    teams = ["Whalers", "Nordiques", "Cracheurs", "Prédateurs", "Red Wings", "Canadiens"]
    
    col1, col2 = st.columns([1, 2])
    with col1:
        target_team = st.selectbox("Équipe destinataire", teams)
    with col2:
        file = st.file_uploader("Fichier CSV Fantrax", type=["csv", "txt"])

    if file:
        try:
            # On utilise le parsing ligne par ligne pour éviter l'erreur de tokenization
            df_preview = parse_fantrax_robust(file, target_team)
            
            if not df_preview.empty:
                st.write(f"✅ {len(df_preview)} joueurs détectés pour les {target_team}")
                st.dataframe(df_preview.head(5), use_container_width=True)
                
                if st.button(f"Confirmer l'importation pour {target_team}", type="primary"):
                    # Charger data existante
                    path = os.path.join(DATA_DIR, f"fantrax_{st.session_state['season']}.csv")
                    if os.path.exists(path):
                        df_global = pd.read_csv(path)
                    else:
                        df_global = pd.DataFrame(columns=REQUIRED_COLS)
                    
                    # Remplacer
                    df_global = df_global[df_global["Propriétaire"] != target_team]
                    df_final = pd.concat([df_global, df_preview], ignore_index=True)
                    
                    # Sauvegarder
                    df_final.to_csv(path, index=False)
                    st.session_state["data"] = df_final
                    st.success("Données enregistrées !")
                    st.rerun()
        except Exception as e:
            st.error(f"Erreur lors de l'analyse : {e}")

# =====================================================
# 4. LOGIQUE PRINCIPALE
# =====================================================

def main():
    if "season" not in st.session_state: st.session_state["season"] = "2024-2025"
    
    path = os.path.join(DATA_DIR, f"fantrax_{st.session_state['season']}.csv")
    if "data" not in st.session_state:
        if os.path.exists(path):
            st.session_state["data"] = pd.read_csv(path)
        else:
            st.session_state["data"] = pd.DataFrame(columns=REQUIRED_COLS)

    st.sidebar.title("🏒 PMS Pool")
    st.session_state["season"] = st.sidebar.selectbox("Saison", ["2024-2025", "2025-2026"])
    
    teams = ["Whalers", "Nordiques", "Cracheurs", "Prédateurs", "Red Wings", "Canadiens"]
    selected_team = st.sidebar.selectbox("Mon Équipe", teams, key="selected_team")
    
    # Gestion des logos (Automatique)
    logo_path = os.path.join(DATA_DIR, f"{selected_team}_Logo.png")
    if os.path.exists(logo_path):
        st.sidebar.image(logo_path, use_container_width=True)

    is_admin = (selected_team.lower() == "whalers")
    menu = ["🏆 Classement", "🧾 Alignement"]
    if is_admin: menu.append("🛠️ Gestion Admin")
    
    choice = st.sidebar.radio("Navigation", menu)

    if choice == "🏆 Classement":
        st.markdown("<div class='pms-broadcast-bar'><h1>🏆 Classement Général</h1></div>", unsafe_allow_html=True)
        st.dataframe(st.session_state["data"], use_container_width=True, hide_index=True)
    elif choice == "🧾 Alignement":
        st.header(f"Alignement : {selected_team}")
        df = st.session_state["data"]
        st.dataframe(df[df["Propriétaire"] == selected_team], use_container_width=True, hide_index=True)
    elif choice == "🛠️ Gestion Admin":
        render_tab_admin()

if __name__ == "__main__":
    main()