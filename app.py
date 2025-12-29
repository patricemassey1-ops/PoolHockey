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

# --- FONCTIONS DE NETTOYAGE ---
def clean_salary_values(series):
    """Nettoyage vectorisé ultra-rapide des colonnes de salaire."""
    return pd.to_numeric(
        series.astype(str)
        .str.replace(r'[\$,\s\xa0]', '', regex=True), 
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
        # Lecture optimisée
        df = pd.read_csv(PLAYERS_DB_FILE)
        df.columns = [c.strip() for c in df.columns]
        
        # Harmonisation des colonnes
        rename_dict = {'Player': 'Joueur', 'Salary': 'Salaire', 'Position': 'Pos', 'Team': 'Équipe', 'Équipe': 'Équipe'}
        df.rename(columns=rename_dict, inplace=True)
        
        # Nettoyage des données
        df['Salaire'] = clean_salary_values(df['Salaire'])
        
        # Création de la colonne d'affichage
        df['Display'] = df['Joueur'] + " (" + df.get('Équipe', 'N/A') + " - " + df['Pos'] + ") - " + df['Salaire'].apply(format_currency)
        return df
    except Exception as e:
        st.error(f"Erreur Hockey_Players.csv : {e}")
        return pd.DataFrame()

def charger_historique():
    if os.path.exists(DB_FILE):
        return pd.read_csv(DB_FILE)
    return pd.DataFrame()

# --- INITIALISATION ---
if 'historique' not in st.session_state:
    st.session_state['historique'] = charger_historique()

base_joueurs = charger_base_joueurs()

st.title("🏒 Analyseur Fantrax 2025")

# --- IMPORTATION ---
with st.sidebar.expander("📥 Importation Fantrax"):
    fichiers = st.file_uploader("Fichiers CSV", type="csv", accept_multiple_files=True)
    if fichiers and st.button("Lancer l'import"):
        dfs_a_ajouter = []
        for f in fichiers:
            content = f.getvalue().decode('utf-8-sig')
            lines = content.splitlines()
            
            # Extraction Skaters & Goalies
            def extract_table(lines, keyword):
                idx = [i for i, l in enumerate(lines) if keyword in l]
                if not idx: return pd.DataFrame()
                start = idx[0] + 1
                return pd.read_csv(io.StringIO("\n".join(lines[start:])), sep=None, engine='python', on_bad_lines='skip')

            df_merged = pd.concat([extract_table(lines, 'Skaters'), extract_table(lines, 'Goalies')], ignore_index=True)
            
            # Détection des colonnes
            c_player = next((c for c in df_merged.columns if 'player' in c.lower() or 'joueur' in c.lower()), None)
            c_salary = next((c for c in df_merged.columns if 'salary' in c.lower() or 'salaire' in c.lower()), None)
            c_status = next((c for c in df_merged.columns if 'status' in c.lower() or 'statut' in c.lower()), None)
            c_pos = next((c for c in df_merged.columns if 'pos' in c.lower()), None)
            c_team = next((c for c in df_merged.columns if 'team' in c.lower() or 'éqp' in c.lower()), None)

            if c_player and c_salary:
                df_merged['Salaire_Clean'] = clean_salary_values(df_merged[c_salary])
                # Correction si Fantrax exporte en milliers
                df_merged['Salaire_Clean'] = df_merged['Salaire_Clean'].apply(lambda x: x*1000 if 0 < x < 100000 else x)
                
                temp_df = pd.DataFrame({
                    'Joueur': df_merged[c_player],
                    'Salaire': df_merged['Salaire_Clean'],
                    'Statut': df_merged[c_status].apply(lambda x: "Club École" if "MIN" in str(x).upper() else "Grand Club") if c_status else "Grand Club",
                    'Pos': df_merged[c_pos] if c_pos else "N/A",
                    'Équipe_NHL': df_merged[c_team] if c_team else "N/A",
                    'Propriétaire': f.name.replace('.csv', '')
                })
                dfs_a_ajouter.append(temp_df)
        
        if dfs_a_ajouter:
            new_hist = pd.concat([st.session_state['historique'], pd.concat(dfs_a_ajouter)], ignore_index=True)
            st.session_state['historique'] = new_hist.drop_duplicates(subset=['Joueur', 'Propriétaire'], keep='last')
            st.session_state['historique'].to_csv(DB_FILE, index=False)
            st.rerun()

# --- AFFICHAGE ---
if not st.session_state['historique'].empty:
    tab1, tab2 = st.tabs(["📊 Dashboard", "⚖️ Simulateur"])
    
    with tab1:
        st.header("Résumé des Masses")
        summary = st.session_state['historique'].pivot_table(index='Propriétaire', columns='Statut', values='Salaire', aggfunc='sum', fill_value=0)
        st.dataframe(summary.style.format(format_currency), use_container_width=True)

    with tab2:
        equipe = st.selectbox("Équipe", sorted(st.session_state['historique']['Propriétaire'].unique()))
        df_sim = st.session_state['historique'][st.session_state['historique']['Propriétaire'] == equipe].copy()
        
        # Ajout Joueur Autonome
        st.subheader("➕ Ajouter un (Joueur Autonome)")
        if not base_joueurs.empty:
            c_a1, c_a2 = st.columns([0.7, 0.3])
            with c_a1:
                p_auto = st.selectbox("Sélectionner un joueur autonome", [None] + base_joueurs['Display'].tolist(), key=f"auto_{equipe}")
            if p_auto:
                row = base_joueurs[base_joueurs['Display'] == p_auto].iloc[0]
                with c_a2:
                    dest = st.selectbox("Affectation", ["Grand Club", "Club École"], key=f"dest_{equipe}")
                if st.button("Ajouter à l'équipe"):
                    new_row = pd.DataFrame([{'Joueur': f"{row['Joueur']} (Autonome)", 'Salaire': row['Salaire'], 'Statut': dest, 'Pos': row['Pos'], 'Équipe_NHL': row['Équipe'], 'Propriétaire': equipe}])
                    st.session_state['historique'] = pd.concat([st.session_state['historique'], new_row], ignore_index=True)
                    st.session_state['historique'].to_csv(DB_FILE, index=False)
                    st.rerun()

        st.divider()
        
        # Simulateur de transfert
        df_sim['Display'] = df_sim['Joueur'] + " (" + df_sim.get('Équipe_NHL', 'N/A') + " - " + df_sim['Pos'] + ") - " + df_sim['Salaire'].apply(format_currency)
        
        col1, col2 = st.columns(2)
        with col1:
            rachats_gc = st.multiselect("Rachats GC (50%)", df_sim[df_sim['Statut']=="Grand Club"]['Display'], key=f"r_gc_{equipe}")
        with col2:
            rachats_ce = st.multiselect("Rachats CE (50%)", df_sim[df_sim['Statut']=="Club École"]['Display'], key=f"r_ce_{equipe}")

        # Drag and Drop
        l_gc = df_sim[df_sim['Statut'] == "Grand Club"]['Display'].tolist()
        l_ce = df_sim[df_sim['Statut'] == "Club École"]['Display'].tolist()

        updated = sort_items([{'header': '🏙️ GC', 'items': l_gc}, {'header': '🏫 CE', 'items': l_ce}], multi_containers=True)
        
        def get_total(items):
            tot = 0
            for i in items:
                try: tot += int(i.split('-')[-1].replace('$', '').replace(' ', '').replace('\xa0', ''))
                except: continue
            return tot

        m_gc = get_total(updated['items'] if updated else l_gc) - (get_total(rachats_gc) / 2)
        m_ce = get_total(updated['items'] if updated else l_ce) - (get_total(rachats_ce) / 2)

        res1, res2 = st.columns(2)
        res1.metric("Masse Grand Club", format_currency(m_gc), delta=format_currency(95500000 - m_gc))
        res2.metric("Masse Club École", format_currency(m_ce), delta=format_currency(47750000 - m_ce))

st.markdown("""<style>.stSortablesItem { background-color: #1E3A8A !important; color: white !important; padding: 10px !important; margin: 5px !important; border-radius: 8px !important; }</style>""", unsafe_allow_html=True)
