import streamlit as st
import pandas as pd
import io
import os
from datetime import datetime
from streamlit_sortables import sort_items

# 1. CONFIGURATION
st.set_page_config(page_title="Calculateur Fantrax 2025", layout="wide")

DB_FILE = "historique_fantrax_v2.csv"
PLAYERS_DB_FILE = "Hockey_Players.csv"

# Initialisation des plafonds dans la session
if 'cap_gc' not in st.session_state: st.session_state['cap_gc'] = 95500000
if 'cap_ce' not in st.session_state: st.session_state['cap_ce'] = 47750000

# 2. FONCTIONS DE NETTOYAGE
def clean_salary_values(series):
    return pd.to_numeric(
        series.astype(str).str.replace(r'[\$,\s\xa0]', '', regex=True), 
        errors='coerce'
    ).fillna(0).astype(int)

def format_currency(val):
    return f"{int(val or 0):,}".replace(",", " ") + "$"

# 3. CHARGEMENT DES DONNÉES
@st.cache_data
def charger_base_joueurs():
    if not os.path.exists(PLAYERS_DB_FILE): return pd.DataFrame()
    try:
        df = pd.read_csv(PLAYERS_DB_FILE).fillna("N/A")
        df.columns = [c.strip() for c in df.columns]
        df.rename(columns={'Player': 'Joueur', 'Salary': 'Salaire', 'Position': 'Pos', 'Team': 'Équipe'}, inplace=True)
        df['Salaire'] = clean_salary_values(df['Salaire'])
        df['Display'] = df['Joueur'] + " (" + df['Équipe'].astype(str) + ") - " + df['Salaire'].apply(format_currency)
        return df
    except: return pd.DataFrame()

if 'historique' not in st.session_state:
    st.session_state['historique'] = pd.read_csv(DB_FILE) if os.path.exists(DB_FILE) else pd.DataFrame()

# 4. BARRE LATÉRALE (MASSE SALARIALE)
st.sidebar.header("💰 Masse Salariale")
st.session_state['cap_gc'] = st.sidebar.number_input("Plafond Grand Club", value=st.session_state['cap_gc'], step=500000)
st.session_state['cap_ce'] = st.sidebar.number_input("Plafond Club École", value=st.session_state['cap_ce'], step=100000)

st.sidebar.markdown("---")
fichiers = st.sidebar.file_uploader("📥 Importer CSV Fantrax", type="csv", accept_multiple_files=True)

if fichiers:
    dfs = []
    for f in fichiers:
        content = f.getvalue().decode('utf-8-sig')
        lines = content.splitlines()
        def extract(keyword):
            idx = next((i for i, l in enumerate(lines) if keyword in l), -1)
            return pd.read_csv(io.StringIO("\n".join(lines[idx+1:])), sep=None, engine='python', on_bad_lines='skip') if idx != -1 else pd.DataFrame()
        
        df_m = pd.concat([extract('Skaters'), extract('Goalies')], ignore_index=True)
        if not df_m.empty:
            c_p = next((c for c in df_m.columns if 'player' in c.lower() or 'joueur' in c.lower()), "Joueur")
            c_s = next((c for c in df_m.columns if 'salary' in c.lower() or 'salaire' in c.lower()), "Salaire")
            c_st = next((c for c in df_m.columns if 'status' in c.lower() or 'statut' in c.lower()), "Statut")
            
            df_m['Salaire_Clean'] = clean_salary_values(df_m[c_s])
            df_m['Salaire_Clean'] = df_m['Salaire_Clean'].apply(lambda x: x*1000 if 0 < x < 100000 else x)
            
            temp = pd.DataFrame({
                'Joueur': df_m[c_p].fillna("Inconnu"),
                'Salaire': df_m['Salaire_Clean'],
                'Statut': df_m[c_st].apply(lambda x: "Club École" if "MIN" in str(x).upper() else "Grand Club") if c_st in df_m.columns else "Grand Club",
                'Pos': df_m['Pos'].fillna("N/A") if 'Pos' in df_m.columns else "N/A",
                'Propriétaire': f.name.replace('.csv', '')
            })
            dfs.append(temp)
    if dfs:
        new_data = pd.concat([st.session_state['historique']] + dfs).drop_duplicates(subset=['Joueur', 'Propriétaire'], keep='last')
        st.session_state['historique'] = new_data
        new_data.to_csv(DB_FILE, index=False)
        st.sidebar.success("✅ Importation réussie")

# 5. SIMULATEUR
base_joueurs = charger_base_joueurs()
if not st.session_state['historique'].empty:
    tab1, tab2 = st.tabs(["📊 Dashboard", "⚖️ Simulateur"])
    
    with tab2:
        eq = st.selectbox("Équipe", sorted(st.session_state['historique']['Propriétaire'].unique()))
        df_sim = st.session_state['historique'][st.session_state['historique']['Propriétaire'] == eq].copy().fillna("N/A")
        df_sim['Display'] = df_sim['Joueur'].astype(str) + " (" + df_sim['Pos'].astype(str) + ") - " + df_sim['Salaire'].apply(format_currency)
        
        l_gc = df_sim[df_sim['Statut'] == "Grand Club"]['Display'].tolist()
        l_ce = df_sim[df_sim['Statut'] == "Club École"]['Display'].tolist()

        # --- DRAG AND DROP (CORRECTION INDEXATION) ---
        updated = sort_items([
            {'header': '🏙️ GRAND CLUB', 'items': l_gc}, 
            {'header': '🏫 CLUB ÉCOLE', 'items': l_ce}
        ], multi_containers=True, direction='horizontal')
        
        if updated and len(updated) >= 2:
            it_gc = updated[0]['items']
            it_ce = updated[1]['items']
        else:
            it_gc, it_ce = l_gc, l_ce

        def get_t(items):
            return sum(int(str(i).split('-')[-1].replace('$', '').replace(' ', '').replace('\xa0', '').strip()) for i in items if '-' in str(i))

        m_gc, m_ce = get_t(it_gc), get_t(it_ce)

        st.divider()
        c1, c2 = st.columns(2)
        c1.metric("Grand Club", format_currency(m_gc), delta=format_currency(st.session_state['cap_gc'] - m_gc))
        c2.metric("Club École", format_currency(m_ce), delta=format_currency(st.session_state['cap_ce'] - m_ce))

st.markdown("""<style>.stSortablesItem { background-color: #1E3A8A !important; color: white !important; padding: 8px !important; border-radius: 6px !important; font-size: 14px; }</style>""", unsafe_allow_html=True)
