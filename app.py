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
# 2. FONCTIONS DE NETTOYAGE & PARSING
# =====================================================

def clean_salary(val):
    """Nettoie les salaires (ex: '4 750 000 $' -> 4750000)"""
    if pd.isna(val): return 0
    s = str(val).replace("$", "").replace(",", "").replace("\xa0", "").strip()
    s = re.sub(r'\s+', '', s) # Enlever tous les espaces
    try:
        return int(float(s))
    except:
        return 0

def parse_fantrax_robust(uploaded_file, team_owner):
    """Analyse robuste du CSV Fantrax avec détection automatique des colonnes."""
    raw_bytes = uploaded_file.read()
    raw_text = raw_bytes.decode("utf-8", errors="ignore")
    lines = raw_text.splitlines()
    
    # 1. Trouver les lignes d'en-tête (cherche 'Player')
    indices = [i for i, line in enumerate(lines) if "player" in line.lower()]
    
    if not indices:
        st.error("Le fichier ne semble pas contenir de colonne 'Player'.")
        return pd.DataFrame()

    # 2. Extraire et combiner les blocs (Skaters + Goalies)
    dfs = []
    for idx in indices:
        # On lit à partir de cet en-tête jusqu'à la prochaine ligne vide ou fin
        content = "\n".join(lines[idx:])
        temp_df = pd.read_csv(io.StringIO(content), sep=",", quotechar='"')
        # Nettoyer les noms de colonnes (enlever les guillemets et espaces)
        temp_df.columns = [c.strip().replace('"', '') for c in temp_df.columns]
        dfs.append(temp_df)

    df_all = pd.concat(dfs, ignore_index=True)
    
    # 3. Mapping intelligent des colonnes (Alias)
    # On cherche dans df_all quelle colonne correspond à nos besoins
    def find_col(possible_names):
        for col in df_all.columns:
            if any(name.lower() in col.lower() for name in possible_names):
                return col
        return None

    c_joueur = find_col(['player', 'joueur', 'name'])
    c_equipe = find_col(['team', 'equipe', 'équipe'])
    c_pos = find_col(['pos', 'position'])
    c_salaire = find_col(['salary', 'salaire', 'cap hit', 'aav', 'cap-hit'])
    c_status = find_col(['status', 'statut'])

    if not c_joueur:
        st.error("Colonne 'Joueur' introuvable.")
        return pd.DataFrame()

    # 4. Création du DataFrame final PMS
    df_final = pd.DataFrame()
    df_final["Joueur"] = df_all[c_joueur]
    df_final["Equipe"] = df_all[c_equipe] if c_equipe else "N/A"
    df_final["Pos"] = df_all[c_pos] if c_pos else "F"
    df_final["Salaire"] = df_all[c_salaire].apply(clean_salary) if c_salaire else 0
    df_final["Propriétaire"] = team_owner
    df_final["Statut"] = STATUT_GC
    
    # Déterminer le Slot (Actif / Banc) basé sur l'export Fantrax
    if c_status:
        df_final["Slot"] = df_all[c_status].apply(lambda x: "Actif" if "act" in str(x).lower() else "Banc")
    else:
        df_final["Slot"] = "Actif"

    df_final["Level"] = "STD"
    df_final["IR Date"] = ""
    
    # Compléter les colonnes manquantes pour correspondre à REQUIRED_COLS
    for col in REQUIRED_COLS:
        if col not in df_final.columns: df_final[col] = ""
            
    return df_final[REQUIRED_COLS].dropna(subset=["Joueur"])

def save_data(df):
    season = st.session_state.get("season", "2024-2025")
    path = os.path.join(DATA_DIR, f"fantrax_{season}.csv")
    df.to_csv(path, index=False)
    st.session_state["data"] = df

# =====================================================
# 3. INTERFACE & NAVIGATION
# =====================================================

def render_tab_leaderboard():
    st.markdown("<div class='pms-broadcast-bar'><h1>🏆 Classement Général</h1></div>", unsafe_allow_html=True)
    df = st.session_state.get("data", pd.DataFrame())
    if df.empty:
        st.info("Aucun joueur. Importez un alignement dans l'onglet Admin.")
    else:
        st.dataframe(df, use_container_width=True, hide_index=True)

def render_tab_admin():
    st.title("🛠️ Gestion Admin")
    
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
                st.write(f"✅ {len(df_preview)} joueurs détectés.")
                st.dataframe(df_preview.head(5), use_container_width=True)
                
                if st.button(f"Confirmer l'import pour {target_team}", type="primary"):
                    df_cur = st.session_state.get("data", pd.DataFrame(columns=REQUIRED_COLS))
                    # Remplacer l'ancien alignement par le nouveau
                    df_cur = df_cur[df_cur["Propriétaire"] != target_team]
                    df_final = pd.concat([df_cur, df_preview], ignore_index=True)
                    save_data(df_final)
                    st.success(f"Alignement {target_team} mis à jour !")
                    st.rerun()
        except Exception as e:
            st.error(f"Erreur lors de l'analyse : {e}")

# =====================================================
# 4. MAIN & LOGO
# =====================================================

def main():
    if "data" not in st.session_state:
        path = os.path.join(DATA_DIR, "fantrax_2024-2025.csv")
        if os.path.exists(path):
            st.session_state["data"] = pd.read_csv(path)
        else:
            st.session_state["data"] = pd.DataFrame(columns=REQUIRED_COLS)

    st.sidebar.title("🏒 PMS Pool")
    st.session_state["season"] = st.sidebar.selectbox("Saison", ["2024-2025", "2025-2026"])
    
    teams = ["Whalers", "Nordiques", "Cracheurs", "Prédateurs", "Red Wings", "Canadiens"]
    selected_team = st.sidebar.selectbox("Mon Équipe", teams, key="selected_team")
    
    # Affichage du logo d'équipe (cherché dans /data)
    logo_path = os.path.join(DATA_DIR, f"{selected_team}_Logo.png")
    if os.path.exists(logo_path):
        st.sidebar.image(logo_path, use_container_width=True)

    is_admin = (selected_team.lower() == "whalers")
    menu = ["🏆 Classement", "🧾 Alignement"]
    if is_admin: menu.append("🛠️ Gestion Admin")
    
    choice = st.sidebar.radio("Navigation", menu)

    if choice == "🏆 Classement":
        render_tab_leaderboard()
    elif choice == "🧾 Alignement":
        st.header(f"Alignement : {selected_team}")
        df = st.session_state["data"]
        team_df = df[df["Propriétaire"] == selected_team]
        if team_df.empty:
            st.info("Aucun joueur pour cette équipe.")
        else:
            st.dataframe(team_df, use_container_width=True, hide_index=True)
    elif choice == "🛠️ Gestion Admin":
        render_tab_admin()

if __name__ == "__main__":
    main()