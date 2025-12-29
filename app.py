import streamlit as st
import pandas as pd
import io
import os
from datetime import datetime
from streamlit_sortables import sort_items

# 1. CONFIGURATION DE LA PAGE
st.set_page_config(page_title="Calculateur Fantrax 2025", layout="wide")

DB_FILE = "historique_fantrax_v2.csv"
PLAYERS_DB_FILE = "Hockey_Players.csv"

# 2. INITIALISATION DE LA MARGE (PLAFONDS CONSERVÉS)
if 'cap_gc' not in st.session_state:
    st.session_state['cap_gc'] = 95500000
if 'cap_ce' not in st.session_state:
    st.session_state['cap_ce'] = 47750000

# 3. FONCTIONS DE NETTOYAGE ET FORMATAGE
def clean_salary_values(series):
    """Nettoyage vectorisé des salaires (2025)"""
    return pd.to_numeric(
        series.astype(str).str.replace(r'[\$,\s\xa0]', '', regex=True), 
        errors='coerce'
    ).fillna(0).astype(int)

def format_currency(val):
    return f"{int(val or 0):,}".replace(",", " ") + "$"

def pos_sort_order(pos_text):
    pos = str(pos_text).upper()
    if 'G' in pos: return 2
    if 'D' in pos: return 1
    return 0 

# 4. CHARGEMENT DES DONNÉES
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

if 'historique' not in st.session_state:
    if os.path.exists(DB_FILE):
        st.session_state['historique'] = pd.read_csv(DB_FILE)
    else:
        st.session_state['historique'] = pd.DataFrame()

# 5. BARRE LATÉRALE (SIDEBAR)
st.sidebar.header("⚙️ Configuration des Plafonds")
st.session_state['cap_gc'] = st.sidebar.number_input("Plafond Grand Club ($)", value=st.session_state['cap_gc'], step=500000)
st.session_state['cap_ce'] = st.sidebar.number_input("Plafond Club École ($)", value=st.session_state['cap_ce'], step=100000)

st.sidebar.markdown("---")
fichiers = st.sidebar.file_uploader("📥 Importer CSV Fantrax", type="csv", accept_multiple_files=True)
if fichiers and st.sidebar.button("Lancer l'importation"):
    dfs_a_ajouter = []
    for f in fichiers:
        content = f.getvalue().decode('utf-8-sig')
        lines = content.splitlines()
        def extract_table(lines, keyword):
            idx = next((i for i, l in enumerate(lines) if keyword in l), -1)
            if idx == -1: return pd.DataFrame()
            return pd.read_csv(io.StringIO("\n".join(lines[idx+1:])), sep=None, engine='python', on_bad_lines='skip')
        
        df_merged = pd.concat([extract_table(lines, 'Skaters'), extract_table(lines, 'Goalies')], ignore_index=True)
        c_player = next((c for c in df_merged.columns if 'player' in c.lower() or 'joueur' in c.lower()), None)
        c_salary = next((c for c in df_merged.columns if 'salary' in c.lower() or 'salaire' in c.lower()), None)
        c_status = next((c for c in df_merged.columns if 'status' in c.lower() or 'statut' in c.lower()), None)
        c_pos = next((c for c in df_merged.columns if 'pos' in c.lower()), None)
        c_team = next((c for c in df_merged.columns if 'team' in c.lower() or 'éqp' in c.lower()), None)

        if c_player and c_salary:
            df_merged['Salaire_Clean'] = clean_salary_values(df_merged[c_salary])
            df_merged['Salaire_Clean'] = df_merged['Salaire_Clean'].apply(lambda x: x*1000 if 0 < x < 100000 else x)
            temp_df = pd.DataFrame({
                'Joueur': df_merged[c_player], 'Salaire': df_merged['Salaire_Clean'],
                'Statut': df_merged[c_status].apply(lambda x: "Club École" if "MIN" in str(x).upper() else "Grand Club") if c_status else "Grand Club",
                'Pos': df_merged[c_pos] if c_pos else "N/A", 'Équipe_NHL': df_merged[c_team] if c_team else "N/A",
                'Propriétaire': f.name.replace('.csv', '')
            })
            dfs_a_ajouter.append(temp_df)
    if dfs_a_ajouter:
        st.session_state['historique'] = pd.concat([st.session_state['historique'], pd.concat(dfs_a_ajouter)], ignore_index=True).drop_duplicates(subset=['Joueur', 'Propriétaire'], keep='last')
        st.session_state['historique'].to_csv(DB_FILE, index=False)
        st.rerun()

# 6. AFFICHAGE PRINCIPAL
base_joueurs = charger_base_joueurs()

if not st.session_state['historique'].empty:
    tab1, tab2 = st.tabs(["📊 Tableau de Bord", "⚖️ Simulateur Avancé"])
    
    with tab1:
        st.header("Résumé des Masses")
        summary = st.session_state['historique'].pivot_table(index='Propriétaire', columns='Statut', values='Salaire', aggfunc='sum', fill_value=0)
        st.dataframe(summary.style.format(format_currency), use_container_width=True)

    with tab2:
        equipe = st.selectbox("Sélectionner l'équipe", options=sorted(st.session_state['historique']['Propriétaire'].unique()))
        df_sim = st.session_state['historique'][st.session_state['historique']['Propriétaire'] == equipe].copy()
        
        # AJOUT JOUEUR AUTONOME
        st.subheader("➕ Ajouter un (Joueur Autonome)")
        if not base_joueurs.empty:
            c_a1, c_a2 = st.columns([0.7, 0.3])
            with c_a1:
                p_auto = st.selectbox("Rechercher dans Hockey_Players.csv", [None] + base_joueurs['Display'].tolist(), key=f"auto_{equipe}")
            if p_auto:
                row = base_joueurs[base_joueurs['Display'] == p_auto].iloc[0]
                with c_a2:
                    dest = st.selectbox("Assigner à", ["Grand Club", "Club École"], key=f"dest_{equipe}")
                if st.button("Ajouter à l'équipe"):
                    new_row = pd.DataFrame([{'Joueur': f"{row['Joueur']} (Autonome)", 'Salaire': row['Salaire'], 'Statut': dest, 'Pos': row['Pos'], 'Équipe_NHL': row['Équipe'], 'Propriétaire': equipe}])
                    st.session_state['historique'] = pd.concat([st.session_state['historique'], new_row], ignore_index=True)
                    st.session_state['historique'].to_csv(DB_FILE, index=False)
                    st.rerun()

        st.divider()

        # PRÉPARATION DES LISTES POUR LE SIMULATEUR
        df_sim['Display'] = df_sim['Joueur'] + " (" + df_sim.get('Équipe_NHL', 'N/A') + " - " + df_sim['Pos'] + ") - " + df_sim['Salaire'].apply(format_currency)
        
        # RACHATS (BUYOUTS)
        st.subheader("💰 Rachats (50%)")
        col_r1, col_r2 = st.columns(2)
        with col_r1:
            rachats_gc = st.multiselect("Rachats Grand Club", df_sim[df_sim['Statut']=="Grand Club"]['Display'], key=f"r_gc_{equipe}")
        with col_r2:
            rachats_ce = st.multiselect("Rachats Club École", df_sim[df_sim['Statut']=="Club École"]['Display'], key=f"r_ce_{equipe}")

        # TRANSFERT INTERACTIF (DRAG AND DROP)
        st.subheader("🔄 Transferts")
        l_gc_init = df_sim[df_sim['Statut'] == "Grand Club"]['Display'].tolist()
        l_ce_init = df_sim[df_sim['Statut'] == "Club École"]['Display'].tolist()

        updated = sort_items([
            {'header': '🏙️ GRAND CLUB', 'items': l_gc_init}, 
            {'header': '🏫 CLUB ÉCOLE', 'items': l_ce_init}
        ], multi_containers=True, direction='horizontal')
        
        # Correction d'indexation pour la liste retournée
        if updated and len(updated) >= 2:
            items_gc, items_ce = updated[0]['items'], updated[1]['items']
        else:
            items_gc, items_ce = l_gc_init, l_ce_init

        # CALCUL DES TOTAUX
        def get_tot(items):
            tot = 0
            for i in items:
                try: tot += int(str(i).split('-')[-1].replace('$', '').replace(' ', '').replace('\xa0', '').strip())
                except: continue
            return tot

        m_gc = get_tot(items_gc) - (get_tot(rachats_gc) / 2)
        m_ce = get_tot(items_ce) - (get_tot(rachats_ce) / 2)

        # AFFICHAGE DES RÉSULTATS (COMPARAISON À LA MARGE)
        st.markdown("---")
        res1, res2 = st.columns(2)
        res1.metric("Grand Club (Net)", format_currency(m_gc), delta=format_currency(st.session_state['cap_gc'] - m_gc), delta_color="normal" if m_gc <= st.session_state['cap_gc'] else "inverse")
        res2.metric("Club École (Net)", format_currency(m_ce), delta=format_currency(st.session_state['cap_ce'] - m_ce), delta_color="normal" if m_ce <= st.session_state['cap_ce'] else "inverse")

st.markdown("""<style>.stSortablesItem { background-color: #1E3A8A !important; color: white !important; padding: 8px !important; margin-bottom: 4px !important; border-radius: 6px !important; font-size: 14px; }</style>""", unsafe_allow_html=True)
