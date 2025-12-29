import streamlit as st
import pandas as pd
import io
import os
from datetime import datetime
from streamlit_sortables import sort_items

# Configuration de la page
st.set_page_config(page_title="Calculateur Fantrax 2025", layout="wide")

DB_FILE = "historique_fantrax_v2.csv"
PLAYERS_DB_FILE = "Hockey_Players.csv"

# --- INITIALISATION DU SESSION STATE (La Marge) ---
if 'cap_gc' not in st.session_state:
    st.session_state['cap_gc'] = 95500000
if 'cap_ce' not in st.session_state:
    st.session_state['cap_ce'] = 47750000

# --- FONCTIONS DE NETTOYAGE ---
def clean_salary_values(series):
    return pd.to_numeric(
        series.astype(str).str.replace(r'[\$,\s\xa0]', '', regex=True), 
        errors='coerce'
    ).fillna(0).astype(int)

def format_currency(val):
    return f"{int(val or 0):,}".replace(",", " ") + "$"

# --- CHARGEMENT DES FICHIERS ---
@st.cache_data(show_spinner="Chargement de la base joueurs...")
def charger_base_joueurs():
    if not os.path.exists(PLAYERS_DB_FILE):
        return pd.DataFrame()
    try:
        df = pd.read_csv(PLAYERS_DB_FILE)
        df.columns = [c.strip() for c in df.columns]
        rename_dict = {'Player': 'Joueur', 'Salary': 'Salaire', 'Position': 'Pos', 'Team': 'Équipe'}
        df.rename(columns=rename_dict, inplace=True)
        df['Salaire'] = clean_salary_values(df['Salaire'])
        df['Display'] = df['Joueur'] + " (" + df.get('Équipe', 'N/A') + " - " + df['Pos'] + ") - " + df['Salaire'].apply(format_currency)
        return df
    except Exception as e:
        st.error(f"Erreur Hockey_Players.csv : {e}")
        return pd.DataFrame()

# --- SIDEBAR (CONSERVATION DU PLAFOND) ---
st.sidebar.header("⚙️ Configuration des Plafonds")
st.session_state['cap_gc'] = st.sidebar.number_input(
    "Plafond Grand Club ($)", 
    value=st.session_state['cap_gc'], 
    step=500000
)
st.session_state['cap_ce'] = st.sidebar.number_input(
    "Plafond Club École ($)", 
    value=st.session_state['cap_ce'], 
    step=100000
)

# --- LOGIQUE D'IMPORTATION ---
if 'historique' not in st.session_state:
    if os.path.exists(DB_FILE): st.session_state['historique'] = pd.read_csv(DB_FILE)
    else: st.session_state['historique'] = pd.DataFrame()

fichiers = st.sidebar.file_uploader("📥 Importer Fantrax", type="csv", accept_multiple_files=True)
if fichiers and st.sidebar.button("Lancer l'import"):
    dfs = []
    for f in fichiers:
        content = f.getvalue().decode('utf-8-sig')
        lines = content.splitlines()
        def extract_table(lines, keyword):
            idx = next((i for i, l in enumerate(lines) if keyword in l), -1)
            if idx == -1: return pd.DataFrame()
            return pd.read_csv(io.StringIO("\n".join(lines[idx+1:])), sep=None, engine='python', on_bad_lines='skip')
        
        df_merged = pd.concat([extract_table(lines, 'Skaters'), extract_table(lines, 'Goalies')], ignore_index=True)
        c_player = next((c for c in df_merged.columns if 'player' in c.lower()), None)
        c_salary = next((c for c in df_merged.columns if 'salary' in c.lower()), None)
        
        if c_player and c_salary:
            df_merged['Salaire_Clean'] = clean_salary_values(df_merged[c_salary])
            df_merged['Salaire_Clean'] = df_merged['Salaire_Clean'].apply(lambda x: x*1000 if 0 < x < 100000 else x)
            temp_df = pd.DataFrame({
                'Joueur': df_merged[c_player], 'Salaire': df_merged['Salaire_Clean'],
                'Statut': "Grand Club", 'Propriétaire': f.name.replace('.csv', '')
            })
            dfs.append(temp_df)
    if dfs:
        st.session_state['historique'] = pd.concat([st.session_state['historique']] + dfs).drop_duplicates(subset=['Joueur', 'Propriétaire'], keep='last')
        st.session_state['historique'].to_csv(DB_FILE, index=False)
        st.rerun()

# --- AFFICHAGE ---
base_joueurs = charger_base_joueurs()
if not st.session_state['historique'].empty:
    tab1, tab2 = st.tabs(["📊 Dashboard", "⚖️ Simulateur"])
    
    with tab1:
        st.header("Résumé des Masses")
        summary = st.session_state['historique'].pivot_table(index='Propriétaire', columns='Statut', values='Salaire', aggfunc='sum', fill_value=0)
        st.dataframe(summary.style.format(format_currency), use_container_width=True)

    with tab2:
        equipe = st.selectbox("Équipe", sorted(st.session_state['historique']['Propriétaire'].unique()))
        df_sim = st.session_state['historique'][st.session_state['historique']['Propriétaire'] == equipe].copy()
        
        # Outil de rachat et transfert...
        df_sim['Display'] = df_sim['Joueur'] + " - " + df_sim['Salaire'].apply(format_currency)
        
        col1, col2 = st.columns(2)
        with col1: rachats_gc = st.multiselect("Rachats GC (50%)", df_sim['Display'], key=f"r_gc_{equipe}")
        with col2: rachats_ce = st.multiselect("Rachats CE (50%)", df_sim['Display'], key=f"r_ce_{equipe}")

        # Drag and Drop
        l_gc = df_sim['Display'].tolist() # Simplifié pour l'exemple
        updated = sort_items([{'header': '🏙️ GC', 'items': l_gc}, {'header': '🏫 CE', 'items': []}], multi_containers=True)
        
        def get_tot(items):
            return sum([int(str(i).split('-')[-1].replace('$', '').replace(' ', '').replace('\xa0', '').strip()) for i in items if '-' in str(i)])

        m_gc = get_tot(updated['items'] if updated else l_gc) - (get_tot(rachats_gc) / 2)
        m_ce = get_tot(updated['items'] if updated else []) - (get_tot(rachats_ce) / 2)

        res1, res2 = st.columns(2)
        # UTILISATION DES VALEURS CONSERVÉES DANS LA MARGE (Session State)
        res1.metric("Grand Club", format_currency(m_gc), delta=format_currency(st.session_state['cap_gc'] - m_gc))
        res2.metric("Club École", format_currency(m_ce), delta=format_currency(st.session_state['cap_ce'] - m_ce))

st.markdown("""<style>.stSortablesItem { background-color: #1E3A8A !important; color: white !important; padding: 10px !important; margin: 5px !important; border-radius: 8px !important; }</style>""", unsafe_allow_html=True)
