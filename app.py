import streamlit as st
import pandas as pd
import io
import os
from datetime import datetime
from streamlit_sortables import sort_items

# --- CONFIGURATION ---
st.set_page_config(page_title="Calculateur Fantrax 2025", layout="wide")

DB_FILE = "historique_fantrax_v2.csv"
BUYOUT_FILE = "rachats_v2.csv"
PLAYERS_DB_FILE = "Hockey_Players.csv"

# --- FONCTIONS DE CHARGEMENT / SAUVEGARDE ---
def charger_donnees(file, columns):
    if os.path.exists(file):
        df = pd.read_csv(file).fillna(0)
        return df.drop_duplicates() # Retirer doublons au chargement
    return pd.DataFrame(columns=columns)

def sauvegarder_donnees(df, file):
    df.drop_duplicates().to_csv(file, index=False) # Retirer doublons avant sauvegarde

def format_currency(val):
    if pd.isna(val) or val == "": 
        return "0 $"
    try:
        return f"{int(float(val)):,}".replace(",", " ") + " $"
    except:
        return "0 $"

# Initialisation de la session
if 'historique' not in st.session_state:
    st.session_state['historique'] = charger_donnees(DB_FILE, ['Joueur', 'Salaire', 'Statut', 'Pos', 'Propriétaire', 'pos_order'])
if 'rachats' not in st.session_state:
    st.session_state['rachats'] = charger_donnees(BUYOUT_FILE, ['Propriétaire', 'Joueur', 'Impact'])
if 'db_joueurs' not in st.session_state:
    if os.path.exists(PLAYERS_DB_FILE):
        df_players = pd.read_csv(PLAYERS_DB_FILE)
        df_players.rename(columns={'Player': 'Joueur', 'Salary': 'Salaire', 'Position': 'Pos', 'Team': 'Equipe_NHL'}, inplace=True, errors='ignore')
        
        # Nettoyage et suppression des doublons dans la DB des joueurs
        df_players['Salaire'] = pd.to_numeric(df_players['Salaire'], errors='coerce').fillna(0)
        df_players = df_players.drop_duplicates(subset=['Joueur', 'Equipe_NHL']) # Doublons par nom/équipe
        
        df_players['search_label'] = (
            df_players['Joueur'].astype(str) + 
            " (" + df_players['Equipe_NHL'].astype(str).fillna("N/A") + ") - " + 
            df_players['Salaire'].apply(format_currency)
        )
        st.session_state['db_joueurs'] = df_players
    else:
        st.session_state['db_joueurs'] = pd.DataFrame()

# --- LOGIQUE D'IMPORTATION ---
fichiers_telecharges = st.sidebar.file_uploader("📥 Importer CSV Fantrax", type="csv", accept_multiple_files=True)

if fichiers_telecharges:
    dfs_a_ajouter = []
    horodatage = datetime.now().strftime("%d-%m %H:%M")
    for fichier in fichiers_telecharges:
        try:
            content = fichier.getvalue().decode('utf-8-sig')
            lines = content.splitlines()

            def extract_table(lines, keyword):
                idx = next((i for i, l in enumerate(lines) if keyword in l), -1)
                if idx == -1: return pd.DataFrame()
                h_idx = next((i for i in range(idx + 1, len(lines)) if any(kw in lines[i] for kw in ["ID", "Player", "Salary"])), -1)
                if h_idx == -1: return pd.DataFrame()
                return pd.read_csv(io.StringIO("\n".join(lines[h_idx:])), sep=None, engine='python', on_bad_lines='skip')

            df_merged = pd.concat([extract_table(lines, 'Skaters'), extract_table(lines, 'Goalies')], ignore_index=True)
            
            if not df_merged.empty:
                c_player = next((c for c in df_merged.columns if 'player' in c.lower()), "Player")
                c_status = next((c for c in df_merged.columns if 'status' in c.lower()), "Status")
                c_salary = next((c for c in df_merged.columns if 'salary' in c.lower()), "Salary")
                c_pos = next((c for c in df_merged.columns if 'pos' in c.lower()), "Pos")

                df_merged[c_salary] = pd.to_numeric(df_merged[c_salary].astype(str).replace(r'[\$,\s]', '', regex=True), errors='coerce').fillna(0)
                df_merged[c_salary] = df_merged[c_salary].apply(lambda x: x*1000 if x < 100000 else x)
                
                temp_df = pd.DataFrame({
                    'Joueur': df_merged[c_player].astype(str), 
                    'Salaire': df_merged[c_salary], 
                    'Statut': df_merged[c_status].apply(lambda x: "Club École" if "MIN" in str(x).upper() else "Grand Club"),
                    'Pos': df_merged[c_pos].fillna("N/A").astype(str), 
                    'Propriétaire': f"{fichier.name.replace('.csv', '')} ({horodatage})"
                })
                dfs_a_ajouter.append(temp_df)
        except Exception as e: st.error(f"Erreur import: {e}")

    if dfs_a_ajouter:
        new_data = pd.concat(dfs_a_ajouter, ignore_index=True)
        # On fusionne et on retire les doublons exacts (Joueur + Propriétaire)
        st.session_state['historique'] = pd.concat([st.session_state['historique'], new_data], ignore_index=True).drop_duplicates(subset=['Joueur', 'Propriétaire'], keep='last')
        sauvegarder_donnees(st.session_state['historique'], DB_FILE)
        st.rerun()

# --- TABS (Dashboard & Sim) ---
tab1, tab2, tab3 = st.tabs(["📊 Dashboard", "⚖️ Simulateur", "🛠️ Gestion"])

with tab1:
    if not st.session_state['historique'].empty:
        st.header("📊 Masse Salariale")
        # Suppression des doublons visuels avant le groupement
        df_f = st.session_state['historique'].drop_duplicates().copy()
        df_f['Salaire'] = pd.to_numeric(df_f['Salaire'], errors='coerce').fillna(0)
        
        summary = df_f.groupby(['Propriétaire', 'Statut'])['Salaire'].sum().unstack(fill_value=0).reset_index()
        # ... (reste du code identique au précédent)
