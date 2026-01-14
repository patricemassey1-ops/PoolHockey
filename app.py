from __future__ import annotations

import os
import io
import re
import pandas as pd
import streamlit as st
from datetime import datetime
from zoneinfo import ZoneInfo

# =====================================================
# 1. CONFIGURATION & CONSTANTES
# =====================================================
st.set_page_config(page_title="PMS - Gestion Admin", layout="wide")

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

REQUIRED_COLS = ["Propriétaire", "Joueur", "Pos", "Equipe", "Salaire", "Level", "Statut", "Slot", "IR Date"]
SLOT_ACTIF = "Actif"
SLOT_BANC = "Banc"
SLOT_IR = "Blessé"
STATUT_GC = "Grand Club"
STATUT_CE = "Club École"

# =====================================================
# 2. MOTEUR D'IMPORTATION ROBUSTE (ANTI-CRASH)
# =====================================================

def clean_salary_value(v):
    if pd.isna(v): return 0
    s = str(v).replace("$", "").replace(",", "").replace("\xa0", "").strip()
    s = re.sub(r'\s+', '', s)
    try: return int(float(s))
    except: return 0

def parse_fantrax_sections(uploaded_file, team_owner):
    """
    Découpe le fichier Fantrax en deux blocs (Skaters / Goalies) 
    pour éviter l'erreur 'Expected X fields, saw Y'.
    """
    raw_text = uploaded_file.read().decode("utf-8", errors="ignore")
    lines = raw_text.splitlines()
    
    skater_rows = []
    goalie_rows = []
    current_mode = None # 1 pour Skaters, 2 pour Goalies
    headers_s = None
    headers_g = None

    for line in lines:
        parts = [p.strip().replace('"', '') for p in line.split(',')]
        if not parts or parts == ['']: continue
        
        # Détection des sections
        if "Skaters" in line:
            current_mode = 1
            continue
        elif "Goalies" in line:
            current_mode = 2
            continue
            
        # Détection des en-têtes (contient Player)
        if "player" in line.lower():
            if current_mode == 1: headers_s = [p.lower() for p in parts]
            else: headers_g = [p.lower() for p in parts]
            continue

        # Extraction des données
        if current_mode == 1 and headers_s and len(parts) == len(headers_s):
            skater_rows.append(dict(zip(headers_s, parts)))
        elif current_mode == 2 and headers_g and len(parts) == len(headers_g):
            goalie_rows.append(dict(zip(headers_g, parts)))

    # Fusion des données
    df_raw = pd.DataFrame(skater_rows + goalie_rows)
    if df_raw.empty: return pd.DataFrame()

    # Mapping PMS
    def find_col(aliases):
        for c in df_raw.columns:
            if any(a in c for a in aliases): return c
        return None

    c_p = find_col(['player', 'joueur'])
    c_t = find_col(['team', 'equipe'])
    c_pos = find_col(['pos', 'position'])
    c_sal = find_col(['salary', 'salaire', 'cap hit', 'aav'])
    c_stat = find_col(['status', 'statut'])

    df_final = pd.DataFrame()
    df_final["Joueur"] = df_raw[c_p]
    df_final["Equipe"] = df_raw[c_t] if c_t else "N/A"
    df_final["Pos"] = df_raw[c_pos].apply(lambda x: str(x).upper()[0] if pd.notna(x) else "F")
    df_final["Salaire"] = df_raw[c_sal].apply(clean_salary_value)
    df_final["Propriétaire"] = team_owner
    
    # Logique Statut/Slot
    if c_stat:
        df_final["Statut"] = df_raw[c_stat].apply(lambda x: STATUT_CE if "min" in str(x).lower() else STATUT_GC)
        df_final["Slot"] = df_raw[c_stat].apply(lambda x: "Actif" if "act" in str(x).lower() else "Banc")
    else:
        df_final["Statut"] = STATUT_GC
        df_final["Slot"] = "Actif"

    df_final["Level"] = df_raw.get("level", "0")
    df_final["IR Date"] = ""

    for col in REQUIRED_COLS:
        if col not in df_final.columns: df_final[col] = ""
            
    return df_final[REQUIRED_COLS].dropna(subset=["Joueur"])

# =====================================================
# 3. INTERFACE ADMIN (STYLE CAPTURE)
# =====================================================

def render_tab_admin():
    st.markdown("## 🛠️ Gestion Admin - Importation")
    st.write("Importez un fichier exporté de Fantrax pour remplir l'alignement d'une équipe.")
    
    # Layout en colonnes comme sur l'image
    col_team, col_file = st.columns([1, 2])
    
    with col_team:
        teams = ["Whalers", "Nordiques", "Cracheurs", "Prédateurs", "Red Wings", "Canadiens"]
        target_team = st.selectbox("Équipe cible", teams)
        
    with col_file:
        file = st.file_uploader("Fichier CSV Fantrax", type=["csv"])

    if file:
        df_new = parse_fantrax_sections(file, target_team)
        
        if not df_new.empty:
            st.divider()
            st.success(f"✅ Fichier analysé : {len(df_new)} joueurs trouvés pour {target_team}.")
            
            # Affichage d'un aperçu
            st.dataframe(df_new.head(10), use_container_width=True, hide_index=True)
            
            # Bouton d'action final
            if st.button(f"🚀 Mettre à jour l'alignement des {target_team}", type="primary"):
                # Fusion avec les données existantes
                df_global = st.session_state.get("data", pd.DataFrame(columns=REQUIRED_COLS))
                
                # On enlève les anciens joueurs de l'équipe cible
                df_global = df_global[df_global["Propriétaire"] != target_team]
                
                # On ajoute les nouveaux
                df_final = pd.concat([df_global, df_new], ignore_index=True)
                
                # Sauvegarde physique
                season = st.session_state.get("season", "2024-2025")
                save_path = os.path.join(DATA_DIR, f"fantrax_{season}.csv")
                df_final.to_csv(save_path, index=False)
                
                st.session_state["data"] = df_final
                st.balloons()
                st.success(f"L'alignement de l'équipe {target_team} a été mis à jour avec succès !")
                st.rerun()

# =====================================================
# 4. LOGIQUE PRINCIPALE
# =====================================================

def main():
    # Initialisation de la saison
    if "season" not in st.session_state:
        st.session_state["season"] = "2024-2025"
        
    # Chargement des données
    path = os.path.join(DATA_DIR, f"fantrax_{st.session_state['season']}.csv")
    if "data" not in st.session_state:
        if os.path.exists(path):
            st.session_state["data"] = pd.read_csv(path)
        else:
            st.session_state["data"] = pd.DataFrame(columns=REQUIRED_COLS)

    # --- SIDEBAR ---
    st.sidebar.title("🏒 PMS Pool")
    st.session_state["season"] = st.sidebar.selectbox("Saison", ["2024-2025", "2025-2026"])
    
    selected_team = st.sidebar.selectbox("Mon Équipe", ["Whalers", "Nordiques", "Cracheurs", "Prédateurs", "Red Wings", "Canadiens"])
    
    nav_options = ["🏆 Classement", "🧾 Alignement"]
    if selected_team == "Whalers":
        nav_options.append("🛠️ Gestion Admin")
        
    choice = st.sidebar.radio("Navigation", nav_options)

    # --- ROUTING ---
    if choice == "🛠️ Gestion Admin":
        render_tab_admin()
    elif choice == "🧾 Alignement":
        # Affichage simplifié pour test
        st.header(f"Alignement : {selected_team}")
        df = st.session_state["data"]
        st.dataframe(df[df["Propriétaire"] == selected_team], use_container_width=True)
    else:
        st.title("🏆 Classement")
        st.write("Sélectionnez 'Gestion Admin' pour importer vos premiers fichiers.")

if __name__ == "__main__":
    main()