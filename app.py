import streamlit as st
import pandas as pd
import io
import os
from datetime import datetime
from streamlit_sortables import sort_items

st.set_page_config(page_title="Calculateur Fantrax 2025", layout="wide")

DB_FILE = "historique_fantrax_v2.csv"
PLAYERS_DB_FILE = "Hockey_Players.csv"

# --- FONCTIONS ---
def charger_historique():
    if os.path.exists(DB_FILE):
        return pd.read_csv(DB_FILE)
    return pd.DataFrame()

def charger_base_joueurs():
    if os.path.exists(PLAYERS_DB_FILE):
        df_base = pd.read_csv(PLAYERS_DB_FILE)
        df_base.columns = [c.strip() for c in df_base.columns]
        rename_dict = {'Player': 'Joueur', 'Salary': 'Salaire', 'Position': 'Pos', 'player': 'Joueur', 'salary': 'Salaire', 'pos': 'Pos'}
        df_base.rename(columns=rename_dict, inplace=True)
        return df_base
    return pd.DataFrame()

def sauvegarder_historique(df):
    df = df.drop_duplicates(subset=['Joueur', 'Propriétaire'], keep='last')
    df.to_csv(DB_FILE, index=False)
    return df

def format_currency(val):
    if pd.isna(val): return "0 $"
    return f"{int(val):,}".replace(",", " ") + "$"

def pos_sort_order(pos_text):
    pos = str(pos_text).upper()
    if 'G' in pos: return 2
    if 'D' in pos: return 1
    return 0 

# Initialisation
if 'historique' not in st.session_state:
    st.session_state['historique'] = charger_historique()

if 'base_joueurs' not in st.session_state:
    st.session_state['base_joueurs'] = charger_base_joueurs()

st.title("🏒 Analyseur Fantrax 2025")

# --- SIDEBAR ---
st.sidebar.header("⚙️ Configuration")
CAP_GRAND_CLUB = st.sidebar.number_input("Plafond Grand Club ($)", value=95500000, step=500000)
CAP_CLUB_ECOLE = st.sidebar.number_input("Plafond Club École ($)", value=47750000, step=100000)

# --- IMPORTATION ---
fichiers_telecharges = st.file_uploader("Importer des CSV Fantrax", type="csv", accept_multiple_files=True)
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
                df_raw = pd.read_csv(io.StringIO("\n".join(lines[h_idx:])), sep=None, engine='python', on_bad_lines='skip')
                if 'ID' in df_raw.columns:
                    df_raw = df_raw[df_raw['ID'].astype(str).str.strip().str.startswith(('0','1','2','3','4','5','6','7','8','9','*'))]
                return df_raw
            
            df_merged = pd.concat([extract_table(lines, 'Skaters'), extract_table(lines, 'Goalies')], ignore_index=True)
            c_player = next((c for c in df_merged.columns if 'player' in c.lower() or 'joueur' in c.lower()), None)
            c_status = next((c for c in df_merged.columns if 'status' in c.lower() or 'statut' in c.lower()), None)
            c_salary = next((c for c in df_merged.columns if 'salary' in c.lower() or 'salaire' in c.lower()), None)
            c_pos = next((c for c in df_merged.columns if 'pos' in c.lower() or 'eligible' in c.lower()), None)
            
            if c_status and c_salary and c_player:
                df_merged[c_salary] = pd.to_numeric(df_merged[c_salary].astype(str).replace(r'[\$,\s]', '', regex=True), errors='coerce').fillna(0) * 1000
                df_merged['Catégorie'] = df_merged[c_status].apply(lambda x: "Club École" if "MIN" in str(x).upper() else "Grand Club")
                nom_equipe = fichier.name.replace('.csv', '')
                temp_df = pd.DataFrame({
                    'Joueur': df_merged[c_player], 'Salaire': df_merged[c_salary], 'Statut': df_merged['Catégorie'],
                    'Pos': df_merged[c_pos] if c_pos else "N/A", 'Propriétaire': nom_equipe,
                    'pos_order': df_merged[c_pos].apply(pos_sort_order) if c_pos else 0
                })
                dfs_a_ajouter.append(temp_df)
        except Exception as e:
            st.error(f"Erreur : {e}")

    if dfs_a_ajouter:
        st.session_state['historique'] = sauvegarder_historique(pd.concat([st.session_state['historique'], pd.concat(dfs_a_ajouter)], ignore_index=True))
        st.rerun()

# --- AFFICHAGE ---
if not st.session_state['historique'].empty:
    df_f = st.session_state['historique']
    tab1, tab2 = st.tabs(["📊 Tableau de Bord", "⚖️ Simulateur Avancé"]) 

    with tab1:
        st.header("Résumé des Masses")
        summary = df_f.groupby(['Propriétaire', 'Statut'])['Salaire'].sum().unstack(fill_value=0).reset_index()
        st.dataframe(summary, use_container_width=True)

    with tab2:
        st.header("🔄 Outil de Transfert & Simulateur")
        equipe_choisie = st.selectbox("Équipe à simuler", options=sorted(df_f['Propriétaire'].unique()))
        df_sim = df_f[df_f['Propriétaire'] == equipe_choisie].copy()

        # --- AJOUT JOUEUR AUTONOME ---
        st.subheader("➕ Ajouter un joueur autonome")
        if not st.session_state['base_joueurs'].empty:
            col_a1, col_a2 = st.columns([0.6, 0.4])
            with col_a1:
                choix_p = st.selectbox("Joueur disponible (Hockey_Players.csv)", options=[None] + sorted(st.session_state['base_joueurs']['Joueur'].tolist()), key=f"p_{equipe_choisie}")
            if choix_p:
                row = st.session_state['base_joueurs'][st.session_state['base_joueurs']['Joueur'] == choix_p].iloc[0]
                with col_a2:
                    dest = st.selectbox("Affectation", options=["Grand Club", "Club École"], key=f"d_{equipe_choisie}")
                st.write(f"Pos: **{row['Pos']}** | Salaire: **{format_currency(row['Salaire'])}**")
                if st.button(f"Ajouter à l'équipe"):
                    nouvelle_ligne = pd.DataFrame([{'Joueur': row['Joueur'], 'Salaire': row['Salaire'], 'Statut': dest, 'Pos': row['Pos'], 'Propriétaire': equipe_choisie, 'pos_order': pos_sort_order(row['Pos'])}])
                    st.session_state['historique'] = sauvegarder_historique(pd.concat([st.session_state['historique'], nouvelle_ligne]))
                    st.rerun()
        else:
            st.warning("Fichier Hockey_Players.csv introuvable à la racine du dépôt.")

        st.markdown("---")

        # --- RACHATS MULTIPLES ---
        st.subheader("💰 Rachats (Déduction 50%)")
        col_r1, col_r2 = st.columns(2)
        with col_r1:
            joueurs_gc_df = df_sim[df_sim['Statut'] == "Grand Club"]
            choix_gc = st.multiselect("Rachats Grand Club", options=joueurs_gc_df['Joueur'].tolist(), key=f"r_gc_{equipe_choisie}")
            ded_gc = joueurs_gc_df[joueurs_gc_df['Joueur'].isin(choix_gc)]['Salaire'].sum() / 2
        with col_r2:
            joueurs_ce_df = df_sim[df_sim['Statut'] == "Club École"]
            choix_ce = st.multiselect("Rachats Club École", options=joueurs_ce_df['Joueur'].tolist(), key=f"r_ce_{equipe_choisie}")
            ded_ce = joueurs_ce_df[joueurs_ce_df['Joueur'].isin(choix_ce)]['Salaire'].sum() / 2

        st.markdown("---")

        # --- DRAG AND DROP ---
        list_gc_init = [f"{r['Joueur']} ({r['Pos']}) - {format_currency(r['Salaire'])}" for _, r in df_sim[df_sim['Statut'] == "Grand Club"].iterrows()]
        list_ce_init = [f"{r['Joueur']} ({r['Pos']}) - {format_currency(r['Salaire'])}" for _, r in df_sim[df_sim['Statut'] == "Club École"].iterrows()]

        updated = sort_items([
            {'header': '🏙️ GRAND CLUB', 'items': list_gc_init}, 
            {'header': '🏫 CLUB ÉCOLE', 'items': list_ce_init}
        ], multi_containers=True, direction='horizontal')
        
        # Correction d'accès aux colonnes par index
        if updated:
            col_gc_items = updated[0]['items']
            col_ce_items = updated[1]['items']
        else:
            col_gc_items = list_gc_init
            col_ce_items = list_ce_init

        def extract_salary(plist):
            tot = 0
            for i in plist:
                try: 
                    # Extraction après le tiret "-"
                    s = i.split('-')[-1].replace('$', '').replace(' ', '').replace(',', '').replace('\xa0', '').strip()
                    tot += int(s)
                except: continue
            return tot

        sim_g = extract_salary(col_gc_items) - ded_gc
        sim_c = extract_salary(col_ce_items) - ded_ce

        res1, res2 = st.columns(2)
        res1.metric("Grand Club (Net)", format_currency(sim_g), delta=format_currency(CAP_GRAND_CLUB - sim_g), delta_color="normal" if sim_g <= CAP_GRAND_CLUB else "inverse")
        res2.metric("Club École (Net)", format_currency(sim_c), delta=format_currency(CAP_CLUB_ECOLE - sim_c), delta_color="normal" if sim_c <= CAP_CLUB_ECOLE else "inverse")

        st.markdown("""<style>.stSortablesItem { background-color: #1E3A8A !important; color: white !important; border-radius: 5px !important; padding: 8px !important; margin-bottom: 5px !important; }</style>""", unsafe_allow_html=True)
else:
    st.info("Importez un fichier CSV Fantrax pour commencer.")
