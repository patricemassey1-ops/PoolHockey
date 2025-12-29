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
        return pd.read_csv(file).fillna(0)
    return pd.DataFrame(columns=columns)

def sauvegarder_donnees(df, file):
    df.to_csv(file, index=False)

# OPTION 1 : Protection contre les valeurs NaN dans la fonction de formatage
def format_currency(val):
    if pd.isna(val) or val == "": 
        return "0 $"
    return f"{int(val):,}".replace(",", " ") + " $"

# Initialisation de la session
if 'historique' not in st.session_state:
    st.session_state['historique'] = charger_donnees(DB_FILE, ['Joueur', 'Salaire', 'Statut', 'Pos', 'Propriétaire', 'pos_order'])
if 'rachats' not in st.session_state:
    st.session_state['rachats'] = charger_donnees(BUYOUT_FILE, ['Propriétaire', 'Joueur', 'Impact'])
if 'db_joueurs' not in st.session_state:
    if os.path.exists(PLAYERS_DB_FILE):
        df_players = pd.read_csv(PLAYERS_DB_FILE)
        # OPTION 2 : Nettoyage immédiat des colonnes numériques
        if 'Salary' in df_players.columns:
            df_players['Salary'] = pd.to_numeric(df_players['Salary'], errors='coerce').fillna(0)
        
        df_players.rename(columns={'Player': 'Joueur', 'Salary': 'Salaire', 'Position': 'Pos', 'Team': 'Equipe_NHL'}, inplace=True, errors='ignore')
        
        # Ajout du search_label sécurisé (Ligne qui causait l'erreur)
        if not df_players.empty:
            df_players['Equipe_NHL'] = df_players['Equipe_NHL'].fillna("N/A")
            df_players['Joueur'] = df_players['Joueur'].fillna("Inconnu")
            df_players['search_label'] = (
                df_players['Joueur'].astype(str) + 
                " (" + df_players['Equipe_NHL'].astype(str) + ") - " + 
                df_players['Salaire'].apply(format_currency)
            )
        st.session_state['db_joueurs'] = df_players
    else:
        st.session_state['db_joueurs'] = pd.DataFrame()

# --- BARRE LATÉRALE : CONFIGURATION ---
st.sidebar.header("⚙️ Paramètres de la Ligue")
CAP_GC = st.sidebar.number_input("Plafond Grand Club ($)", min_value=0, value=95500000, step=1000000)
CAP_CE = st.sidebar.number_input("Plafond Club École ($)", min_value=0, value=47750000, step=100000)

if st.sidebar.button("🗑️ Effacer tout l'historique"):
    st.session_state['historique'] = pd.DataFrame(columns=['Joueur', 'Salaire', 'Statut', 'Pos', 'Propriétaire', 'pos_order'])
    st.session_state['rachats'] = pd.DataFrame(columns=['Propriétaire', 'Joueur', 'Impact'])
    sauvegarder_donnees(st.session_state['historique'], DB_FILE)
    sauvegarder_donnees(st.session_state['rachats'], BUYOUT_FILE)
    st.rerun()

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
            c_player = next((c for c in df_merged.columns if 'player' in c.lower()), "Player")
            c_status = next((c for c in df_merged.columns if 'status' in c.lower()), "Status")
            c_salary = next((c for c in df_merged.columns if 'salary' in c.lower()), "Salary")
            c_pos = next((c for c in df_merged.columns if 'pos' in c.lower()), "Pos")

            if not df_merged.empty:
                # Nettoyage robuste du salaire lors de l'import
                df_merged[c_salary] = pd.to_numeric(df_merged[c_salary].astype(str).replace(r'[\$,\s]', '', regex=True), errors='coerce').fillna(0)
                df_merged[c_salary] = df_merged[c_salary].apply(lambda x: x*1000 if x < 100000 else x)
                
                temp_df = pd.DataFrame({
                    'Joueur': df_merged[c_player], 
                    'Salaire': df_merged[c_salary], 
                    'Statut': df_merged[c_status].apply(lambda x: "Club École" if "MIN" in str(x).upper() else "Grand Club"),
                    'Pos': df_merged[c_pos].fillna("N/A"), 
                    'Propriétaire': f"{fichier.name.replace('.csv', '')} ({horodatage})"
                })
                dfs_a_ajouter.append(temp_df)
        except Exception as e: st.error(f"Erreur import: {e}")

    if dfs_a_ajouter:
        st.session_state['historique'] = pd.concat([st.session_state['historique']] + dfs_a_ajouter, ignore_index=True)
        sauvegarder_donnees(st.session_state['historique'], DB_FILE)
        st.rerun()

# --- INTERFACE PRINCIPALE ---
tab1, tab2, tab3 = st.tabs(["📊 Dashboard Consolidé", "⚖️ Simulateur d'Alignement", "🛠️ Gestion (Rachats & JA)"])

# --- TAB 1 : DASHBOARD ---
with tab1:
    if not st.session_state['historique'].empty:
        st.header("📊 Masse Salariale de la Ligue")
        df_f = st.session_state['historique'].copy()
        # Assurer que Salaire est numérique
        df_f['Salaire'] = pd.to_numeric(df_f['Salaire'], errors='coerce').fillna(0)
        
        summary = df_f.groupby(['Propriétaire', 'Statut'])['Salaire'].sum().unstack(fill_value=0).reset_index()
        
        rachats_summary = st.session_state['rachats'].groupby('Propriétaire')['Impact'].sum().reset_index()
        summary = summary.merge(rachats_summary, on='Propriétaire', how='left').fillna(0)
        
        for c in ['Grand Club', 'Club École', 'Impact']: 
            if c not in summary.columns: summary[c] = 0

        summary['Total Grand Club'] = summary['Grand Club'] + summary['Impact']
        summary['Espace Cap'] = CAP_GC - summary['Total Grand Club']

        st.dataframe(
            summary.style.format({c: format_currency for c in summary.columns if c != 'Propriétaire'}),
            use_container_width=True, hide_index=True
        )

# --- TAB 2 : SIMULATEUR ---
with tab2:
    equipes = sorted(st.session_state['historique']['Propriétaire'].unique(), reverse=True)
    if equipes:
        eq_selected = st.selectbox("Sélectionner une équipe", equipes)
        df_sim = st.session_state['historique'][st.session_state['historique']['Propriétaire'] == eq_selected].copy()
        
        # Nettoyage avant affichage dans le sortable
        df_sim['Salaire'] = pd.to_numeric(df_sim['Salaire'], errors='coerce').fillna(0)
        df_sim['label'] = df_sim['Joueur'] + " (" + df_sim['Pos'] + ") | " + df_sim['Salaire'].apply(lambda x: f"{int(x/1000)}k")
        
        l_gc = df_sim[df_sim['Statut'] == "Grand Club"]['label'].tolist()
        l_ce = df_sim[df_sim['Statut'] == "Club École"]['label'].tolist()

        res = sort_items([{'header': '🏙️ GRAND CLUB', 'items': l_gc}, {'header': '🏫 CLUB ÉCOLE', 'items': l_ce}], multi_containers=True, key=f"sim_{eq_selected}")

        def calculate_drag_sum(items):
            return sum(int(x.split('|')[-1].replace('k','').strip()) * 1000 for x in items if '|' in x)

        s_gc = calculate_drag_sum(res[0]['items'] if res else l_gc)
        s_ce = calculate_drag_sum(res[1]['items'] if res else l_ce)
        p_imp = st.session_state['rachats'][st.session_state['rachats']['Propriétaire'] == eq_selected]['Impact'].sum()

        st.divider()
        c1, c2, c3 = st.columns(3)
        c1.metric("Masse GC (+ Rachats)", format_currency(s_gc + p_imp), delta=format_currency(CAP_GC - (s_gc + p_imp)))
        c2.metric("Masse École", format_currency(s_ce), delta=format_currency(CAP_CE - s_ce))
        c3.metric("Total Pénalités", format_currency(p_imp))

# --- TAB 3 : GESTION (RACHATS & JA) ---
with tab3:
    # Le reste de votre code pour les rachats...
    pass
