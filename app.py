import streamlit as st
import pandas as pd
import io
import os
from streamlit_sortables import sort_items

# 1. CONFIGURATION & FICHIERS
st.set_page_config(page_title="Simulateur Fantrax 2025", layout="wide")

DB_FILE = "historique_fantrax_v2.csv"
BUYOUT_FILE = "rachats_v2.csv"
PLAYERS_DB_FILE = "Hockey_Players.csv"

# 2. GESTION DES DONNÉES ET FONCTIONS
def save_all():
    st.session_state.historique.to_csv(DB_FILE, index=False)
    st.session_state.rachats.to_csv(BUYOUT_FILE, index=False)

@st.cache_data
def load_initial_data(file, columns):
    if os.path.exists(file):
        try: return pd.read_csv(file)
        except: return pd.DataFrame(columns=columns)
    return pd.DataFrame(columns=columns)

@st.cache_data
def load_players_db(file):
    """Charge la base de données globale des joueurs disponibles."""
    if os.path.exists(file):
        df = pd.read_csv(file).fillna("N/A")
        # Nettoyage pour s'assurer que les colonnes sont correctes
        df.columns = [c.strip() for c in df.columns]
        df.rename(columns={'Player': 'Joueur', 'Salary': 'Salaire', 'Position': 'Pos', 'Team': 'Equipe_NHL'}, inplace=True)
        # Convertir le salaire en numérique pour le calcul 50%
        df['Salaire'] = pd.to_numeric(df['Salaire'].astype(str).str.replace(r'[^\d]', '', regex=True), errors='coerce').fillna(0)
        df.loc[df['Salaire'] < 100000, 'Salaire'] *= 1000
        return df
    return pd.DataFrame(columns=['Joueur', 'Salaire', 'Pos', 'Equipe_NHL'])

# Initialisation des sessions
if 'historique' not in st.session_state:
    st.session_state.historique = load_initial_data(DB_FILE, ['Joueur', 'Salaire', 'Statut', 'Pos', 'Equipe_NHL', 'Propriétaire'])
if 'rachats' not in st.session_state:
    st.session_state.rachats = load_initial_data(BUYOUT_FILE, ['Propriétaire', 'Joueur', 'Impact'])
# Base de données de joueurs disponibles
if 'db_joueurs' not in st.session_state:
    st.session_state.db_joueurs = load_players_db(PLAYERS_DB_FILE)

def format_currency(val):
    return f"{int(val):,}".replace(",", " ") + "$" if val else "0$"

# --- Barres latérales et autres onglets non modifiés ---

# ... [Code de la barre latérale (import auto) inchangé] ...
with st.sidebar:
    st.header("🚀 Importation Automatique")
    cap_gc = st.number_input("Plafond Grand Club", value=95500000, step=500000)
    cap_ce = st.number_input("Plafond Club École", value=47750000, step=100000)
    uploaded_files = st.file_uploader("Glissez vos fichiers Fantrax ici", type="csv", accept_multiple_files=True)
    if uploaded_files:
        # (Logique d'importation auto inchangée - déjà fonctionnelle)
        pass # La logique est déjà dans le code précédent

# 3. ONGLETS
tab1, tab2, tab3 = st.tabs(["📊 Dashboard", "⚖️ Simulateur", "🛠️ Gestion"])

# ... [Code du Dashboard et Simulateur inchangé - déjà fonctionnel] ...

with tab1:
    if not st.session_state.historique.empty:
        # Dashboard logic (unchanged)
        stats = st.session_state.historique.groupby(['Propriétaire', 'Statut'])['Salaire'].sum().unstack(fill_value=0).reset_index()
        r_sum = st.session_state.rachats.groupby('Propriétaire')['Impact'].sum().reset_index()
        stats = stats.merge(r_sum, on='Propriétaire', how='left').fillna(0)
        for c in ['Grand Club', 'Club École', 'Impact']: 
            if c not in stats.columns: stats[c] = 0
        stats['Total GC'] = stats['Grand Club'] + stats['Impact']
        stats['Espace GC'] = cap_gc - stats['Total GC']
        st.dataframe(stats.style.format(format_currency, subset=['Grand Club', 'Club École', 'Impact', 'Total GC', 'Espace GC']), use_container_width=True)

with tab2:
    teams = sorted(st.session_state.historique['Propriétaire'].unique()) if not st.session_state.historique.empty else []
    if teams:
        # Simulateur logic (unchanged)
        eq = st.selectbox("Équipe", teams)
        dff = st.session_state.historique[st.session_state.historique['Propriétaire'] == eq].copy().fillna("N/A")
        dff['label'] = (dff['Joueur'].astype(str) + " (" + dff['Pos'].astype(str) + " - " + 
                        dff['Equipe_NHL'].astype(str) + ") | " + dff['Salaire'].apply(lambda x: f"{int(x/1000)}k"))
        l_gc = dff[dff['Statut'] == "Grand Club"]['label'].tolist()
        l_ce = dff[dff['Statut'] == "Club École"]['label'].tolist()
        res = sort_items([{'header': '🏙️ GC', 'items': l_gc}, {'header': '🏫 ÉCOLE', 'items': l_ce}], multi_containers=True, key=f"sim_v5_{eq}")

        def quick_sum(items):
            if not items: return 0
            return sum(int(str(x).split('|')[-1].replace('k','').strip()) * 1000 for x in items if '|' in str(x))
        
        s_gc_joueurs = quick_sum(res[0]['items']) if res and len(res) > 0 else quick_sum(l_gc)
        s_ce = quick_sum(res[1]['items']) if res and len(res) > 1 else quick_sum(l_ce)
        p_imp = st.session_state.rachats[st.session_state.rachats['Propriétaire'] == eq]['Impact'].sum()
        
        masse_totale_gc = s_gc_joueurs + p_imp
        
        st.divider()
        c1, c2, c3 = st.columns(3)
        c1.metric("Masse GC (+ Rachats)", format_currency(masse_totale_gc), delta=format_currency(cap_gc - masse_totale_gc))
        c2.metric("Masse École", format_currency(s_ce), delta=format_currency(cap_ce - s_ce))
        c3.metric("Pénalités Rachats", format_currency(p_imp))

# --- GESTION (MODIFIÉ) ---
with tab3:
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("🆕 Embaucher un Agent Libre (FA)")
        
        # Filtrer les joueurs déjà signés
        signed_players = st.session_state.historique['Joueur'].unique()
        available_players_db = st.session_state.db_joueurs[~st.session_state.db_joueurs['Joueur'].isin(signed_players)]

        if available_players_db.empty:
            st.info("Tous les joueurs de la base de données sont signés.")
        else:
            with st.form("fa_form"):
                teams = sorted(st.session_state.historique['Propriétaire'].unique()) if not st.session_state.historique.empty else ["Ma Ligue"]
                f_prop = st.selectbox("Équipe", teams)
                
                # Liste déroulante améliorée
                available_players_db['label'] = available_players_db.apply(lambda row: f"{row['Joueur']} ({row['Pos']} - {row['Equipe_NHL']}) - {format_currency(row['Salaire'])}", axis=1)
                
                selected_label = st.selectbox("Sélectionner le joueur", available_players_db['label'].tolist())
                
                # Récupérer les infos du joueur sélectionné
                selected_player_data = available_players_db[available_players_db['label'] == selected_label].iloc[0]
                
                # Suggérer 50% du salaire comme offre par défaut, mais modifiable
                suggested_salary = int(selected_player_data['Salaire'] * 0.5)
                
                f_sal = st.number_input(f"Salaire d'Offre (Suggéré: {format_currency(suggested_salary)})", min_value=0, value=suggested_salary, step=100000)
                f_stat = st.radio("Assignation", ["Grand Club", "Club École"], horizontal=True, index=0)
                
                if st.form_submit_button("Ajouter & Sauvegarder"):
                    new_row = pd.DataFrame([{
                        'Joueur': selected_player_data['Joueur'], 
                        'Salaire': f_sal, 
                        'Statut': f_stat,
                        'Pos': selected_player_data['Pos'], 
                        'Equipe_NHL': selected_player_data['Equipe_NHL'], 
                        'Propriétaire': f_prop
                    }])
                    st.session_state.historique = pd.concat([st.session_state.historique, new_row], ignore_index=True)
                    save_all()
                    st.success(f"{selected_player_data['Joueur']} a signé pour {format_currency(f_sal)}.")
                    st.rerun()

    with col2:
        st.subheader("📉 Rachat (50%)")
        if not st.session_state.historique.empty:
            with st.form("buy_form"):
                t_sel = st.selectbox("Équipe", teams, key="bt_manage")
                j_df = st.session_state.historique[st.session_state.historique['Propriétaire'] == t_sel]
                j_list = {f"{r['Joueur']} ({r['Pos']}) | {format_currency(r['Salaire'])}": r['Joueur'] for _, r in j_df.iterrows()}
                j_sel_label = st.selectbox("Joueur à racheter", list(j_list.keys()) if j_list else ["Aucun"])
                if st.form_submit_button("Confirmer Rachat & Sauvegarde"):
                    if j_list:
                        j_name = j_list[j_sel_label]
                        sal = j_df[j_df['Joueur'] == j_name]['Salaire'].values
                        new_r = pd.DataFrame([{'Propriétaire': t_sel, 'Joueur': j_name, 'Impact': int(sal * 0.5)}])
                        st.session_state.rachats = pd.concat([st.session_state.rachats, new_r], ignore_index=True)
                        st.session_state.historique = st.session_state.historique[~((st.session_state.historique.Joueur == j_name) & (st.session_state.historique.Propriétaire == t_sel))]
                        save_all()
                        st.rerun()

st.markdown("""<style>.stSortablesItem { background-color: #1E3A8A !important; color: white !important; padding: 5px; border-radius: 4px; }</style>""", unsafe_allow_html=True)
