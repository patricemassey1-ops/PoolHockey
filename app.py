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

# PLAFONDS SALARIAUX (par défaut)
DEFAULT_PLAFOND_GRAND_CLUB = 95_500_000
DEFAULT_PLAFOND_CLUB_ECOLE = 47_750_000

# --- FONCTIONS DE CHARGEMENT / SAUVEGARDE ---
@st.cache_data(ttl=300)  # Cache pour 5 minutes
def charger_donnees(file, columns):
    if os.path.exists(file):
        df = pd.read_csv(file).fillna(0)
        return df.drop_duplicates()
    return pd.DataFrame(columns=columns)

def sauvegarder_donnees(df, file):
    df.drop_duplicates().to_csv(file, index=False)
    # Invalider le cache après sauvegarde
    charger_donnees.clear()

def format_currency(val):
    if pd.isna(val) or val == "": 
        return "0 $"
    try:
        return f"{int(float(val)):,}".replace(",", " ") + " $"
    except:
        return "0 $"

@st.cache_data(ttl=300)
def charger_db_joueurs():
    """Charge la base de données des joueurs avec cache"""
    if os.path.exists(PLAYERS_DB_FILE):
        df_players = pd.read_csv(PLAYERS_DB_FILE)
        df_players.rename(columns={'Player': 'Joueur', 'Salary': 'Salaire', 'Position': 'Pos', 'Team': 'Equipe_NHL'}, inplace=True, errors='ignore')
        
        df_players['Salaire'] = pd.to_numeric(df_players['Salaire'], errors='coerce').fillna(0)
        df_players = df_players.drop_duplicates(subset=['Joueur', 'Equipe_NHL'])
        
        df_players['search_label'] = (
            df_players['Joueur'].astype(str) + 
            " (" + df_players['Equipe_NHL'].astype(str).fillna("N/A") + ") - " + 
            df_players['Salaire'].apply(format_currency)
        )
        return df_players
    return pd.DataFrame()

# Initialisation de la session (optimisée)
if 'historique' not in st.session_state:
    st.session_state['historique'] = charger_donnees(DB_FILE, ['Joueur', 'Salaire', 'Statut', 'Pos', 'Propriétaire', 'pos_order'])

if 'rachats' not in st.session_state:
    st.session_state['rachats'] = charger_donnees(BUYOUT_FILE, ['Propriétaire', 'Joueur', 'Impact'])

if 'db_joueurs' not in st.session_state:
    st.session_state['db_joueurs'] = charger_db_joueurs()

# --- LOGIQUE D'IMPORTATION ---
st.sidebar.header("⚙️ Configuration")
PLAFOND_GRAND_CLUB = st.sidebar.number_input(
    "💰 Plafond Grand Club ($)", 
    min_value=0, 
    value=DEFAULT_PLAFOND_GRAND_CLUB,
    step=100_000,
    format="%d"
)
PLAFOND_CLUB_ECOLE = st.sidebar.number_input(
    "🎓 Plafond Club École ($)", 
    min_value=0, 
    value=DEFAULT_PLAFOND_CLUB_ECOLE,
    step=100_000,
    format="%d"
)

st.sidebar.divider()

fichiers_telecharges = st.sidebar.file_uploader("📥 Importer CSV Fantrax", type="csv", accept_multiple_files=True)

if fichiers_telecharges:
    with st.spinner("⏳ Import en cours..."):
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
            except Exception as e: 
                st.error(f"Erreur import {fichier.name}: {e}")

        if dfs_a_ajouter:
            new_data = pd.concat(dfs_a_ajouter, ignore_index=True)
            st.session_state['historique'] = pd.concat([st.session_state['historique'], new_data], ignore_index=True).drop_duplicates(subset=['Joueur', 'Propriétaire'], keep='last')
            sauvegarder_donnees(st.session_state['historique'], DB_FILE)
            st.success(f"✅ {len(fichiers_telecharges)} fichier(s) importé(s) avec succès!")
            st.rerun()

# --- TABS (Dashboard & Sim) ---
tab1, tab2, tab3 = st.tabs(["📊 Dashboard", "⚖️ Simulateur", "🛠️ Gestion"])

with tab1:
    if not st.session_state['historique'].empty:
        st.header("📊 Masse Salariale par Propriétaire")
        
        # Optimisation: éviter les copies inutiles
        df_f = st.session_state['historique'].drop_duplicates()
        df_f['Salaire'] = pd.to_numeric(df_f['Salaire'], errors='coerce').fillna(0)
        
        # Grouper par propriétaire et statut
        summary = df_f.groupby(['Propriétaire', 'Statut'], as_index=False)['Salaire'].sum()
        summary = summary.pivot(index='Propriétaire', columns='Statut', values='Salaire').fillna(0).reset_index()
        
        # Renommer les colonnes si elles existent
        if 'Grand Club' not in summary.columns:
            summary['Grand Club'] = 0
        if 'Club École' not in summary.columns:
            summary['Club École'] = 0
            
        # Calculer les montants restants
        summary['Restant Grand Club'] = PLAFOND_GRAND_CLUB - summary['Grand Club']
        summary['Restant Club École'] = PLAFOND_CLUB_ECOLE - summary['Club École']
        
        # Calculer le total et le restant total
        summary['Total'] = summary['Grand Club'] + summary['Club École']
        plafond_total = PLAFOND_GRAND_CLUB + PLAFOND_CLUB_ECOLE
        summary['Restant Total'] = plafond_total - summary['Total']
        
        # Afficher les plafonds en haut
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("🏒 Plafond Grand Club", format_currency(PLAFOND_GRAND_CLUB))
        with col2:
            st.metric("🎓 Plafond Club École", format_currency(PLAFOND_CLUB_ECOLE))
        with col3:
            st.metric("💰 Plafond Total", format_currency(plafond_total))
        
        st.divider()
        
        # Préparer l'affichage avec formatage (optimisé)
        display_df = summary.copy()
        for col in ['Grand Club', 'Restant Grand Club', 'Club École', 'Restant Club École', 'Total', 'Restant Total']:
            display_df[col] = display_df[col].apply(format_currency)
        
        # Réorganiser les colonnes
        display_df = display_df[['Propriétaire', 'Grand Club', 'Restant Grand Club', 
                                  'Club École', 'Restant Club École', 'Total', 'Restant Total']]
        
        st.dataframe(display_df, use_container_width=True, hide_index=True)
        
        # Afficher les alertes pour les dépassements
        st.subheader("⚠️ Alertes")
        alertes = []
        for _, row in summary.iterrows():
            if row['Restant Grand Club'] < 0:
                alertes.append(f"🚨 **{row['Propriétaire']}** dépasse le plafond du Grand Club de **{format_currency(abs(row['Restant Grand Club']))}**")
            if row['Restant Club École'] < 0:
                alertes.append(f"🚨 **{row['Propriétaire']}** dépasse le plafond du Club École de **{format_currency(abs(row['Restant Club École']))}**")
            if row['Restant Total'] < 0:
                alertes.append(f"🚨 **{row['Propriétaire']}** dépasse le plafond total de **{format_currency(abs(row['Restant Total']))}**")
        
        if alertes:
            for alerte in alertes:
                st.error(alerte)
        else:
            st.success("✅ Aucun dépassement de plafond salarial")
    else:
        st.info("Aucune donnée disponible. Importez un fichier CSV via la barre latérale.")

with tab2:
    st.header("⚖️ Simulateur de Transactions")
    st.info("Fonctionnalité à venir")

with tab3:
    st.header("🛠️ Gestion des Données")
    st.info("Fonctionnalité à venir")
