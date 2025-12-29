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

@st.cache_data
def charger_base_joueurs_autonomes():
    if os.path.exists(PLAYERS_DB_FILE):
        try:
            df_base = pd.read_csv(PLAYERS_DB_FILE)
            df_base.columns = [c.strip() for c in df_base.columns]
            rename_dict = {'Player': 'Joueur', 'Salary': 'Salaire', 'Position': 'Pos', 'player': 'Joueur', 'salary': 'Salaire', 'pos': 'Pos'}
            df_base.rename(columns=rename_dict, inplace=True)
            # Ajout d'une colonne formatée pour l'affichage
            df_base['Display'] = df_base.apply(lambda row: f"{row['Joueur']} ({row['Pos']}) - {format_currency(row['Salaire'])}", axis=1)
            return df_base
        except Exception as e:
            st.error(f"Erreur de lecture de Hockey_Players.csv: {e}")
            return pd.DataFrame()
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

base_joueurs = charger_base_joueurs_autonomes()

st.title("🏒 Analyseur Fantrax 2025")

# --- SIDEBAR ---
st.sidebar.header("⚙️ Configuration")
CAP_GRAND_CLUB = st.sidebar.number_input("Plafond Grand Club ($)", value=95500000, step=500000)
CAP_CLUB_ECOLE = st.sidebar.number_input("Plafond Club École ($)", value=47750000, step=100000)

# --- IMPORTATION ---
fichiers_telecharges = st.file_uploader("Importer des CSV Fantrax (Rosters)", type="csv", accept_multiple_files=True)
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
        st.subheader("➕ Ajouter un (Joueur Autonome)")
        if not base_joueurs.empty:
            col_a1, col_a2 = st.columns([0.6, 0.4])
            with col_a1:
                # Utilise 'Display' pour l'affichage, mais renvoie 'Joueur'
                choix_p_display = st.selectbox("Sélectionner un joueur autonome", 
                                               options=[None] + base_joueurs['Display'].tolist(), 
                                               format_func=lambda x: x if x is not None else "---",
                                               key=f"p_{equipe_choisie}")
            
            if choix_p_display:
                # Retrouve le nom réel du joueur à partir de la sélection display
                nom_joueur_reel = choix_p_display.split(' (')[0]
                row = base_joueurs[base_joueurs['Joueur'] == nom_joueur_reel].iloc
                
                with col_a2:
                    dest = st.selectbox("Affecter au", options=["Grand Club", "Club École"], key=f"d_{equipe_choisie}")
                
                if st.button(f"Ajouter {nom_joueur_reel} (Joueur Autonome)"):
                    nouvelle_ligne = pd.DataFrame([{
                        'Joueur': f"{nom_joueur_reel} (Joueur Autonome)", 
                        'Salaire': row['Salaire'].values[0], # Accéder à la valeur
                        'Statut': dest, 
                        'Pos': row['Pos'].values[0],
                        'Propriétaire': equipe_choisie, 
                        'pos_order': pos_sort_order(row['Pos'].values[0])
                    }])
                    st.session_state['historique'] = sauvegarder_historique(pd.concat([st.session_state['historique'], nouvelle_ligne]))
                    st.rerun()
        else:
            st.warning("⚠️ Aucun fichier Hockey_Players.csv trouvé pour les joueurs autonomes.")

        st.markdown("---")

        # --- RACHATS ---
        st.subheader("💰 Rachats (50%)")
        col_r1, col_r2 = st.columns(2)
        
        # Préparer les listes de display pour les rachats
        joueurs_gc_df = df_sim[df_sim['Statut'] == "Grand Club"]
        joueurs_gc_df['Display'] = joueurs_gc_df.apply(lambda row: f"{row['Joueur']} ({row['Pos']}) - {format_currency(row['Salaire'])}", axis=1)
        
        joueurs_ce_df = df_sim[df_sim['Statut'] == "Club École"]
        joueurs_ce_df['Display'] = joueurs_ce_df.apply(lambda row: f"{row['Joueur']} ({row['Pos']}) - {format_currency(row['Salaire'])}", axis=1)

        with col_r1:
            choix_gc = st.multiselect("Rachats Grand Club", options=joueurs_gc_df['Display'].tolist(), key=f"r_gc_{equipe_choisie}")
            # Retrouver les salaires à partir des noms de joueurs sélectionnés
            noms_gc = [c.split(' (')[0] for c in choix_gc]
            total_deduction_gc = joueurs_gc_df[joueurs_gc_df['Joueur'].isin(noms_gc)]['Salaire'].sum() / 2
            ded_gc = total_deduction_gc

        with col_r2:
            choix_ce = st.multiselect("Rachats Club École", options=joueurs_ce_df['Display'].tolist(), key=f"r_ce_{equipe_choisie}")
            noms_ce = [c.split(' (')[0] for c in choix_ce]
            total_deduction_ce = joueurs_ce_df[joueurs_ce_df['Joueur'].isin(noms_ce)]['Salaire'].sum() / 2
            ded_ce = total_deduction_ce

        st.markdown("---")

        # --- INTERACTIVE DRAG AND DROP ---
        list_gc_init = [f"{r['Joueur']} ({r['Pos']}) - {format_currency(r['Salaire'])}" for _, r in df_sim[df_sim['Statut'] == "Grand Club"].iterrows()]
        list_ce_init = [f"{r['Joueur']} ({r['Pos']}) - {format_currency(r['Salaire'])}" for _, r in df_sim[df_sim['Statut'] == "Club École"].iterrows()]

        updated = sort_items([
            {'header': '🏙️ GRAND CLUB', 'items': list_gc_init}, 
            {'header': '🏫 CLUB ÉCOLE', 'items': list_ce_init}
        ], multi_containers=True, direction='horizontal')
        
        if updated:
            col_gc_items = updated['items']
            col_ce_items = updated['items']
        else:
            col_gc_items = list_gc_init
            col_ce_items = list_ce_init

        def extract_salary(plist):
            tot = 0
            for i in plist:
                try: 
                    s = i.split('-')[-1].replace('$', '').replace(' ', '').replace(',', '').strip()
                    tot += int(s)
                except: continue
            return tot

        sim_g = extract_salary(col_gc_items) - ded_gc
        sim_c = extract_salary(col_ce_items) - ded_ce

        st.divider()
        res1, res2 = st.columns(2)
        res1.metric("Grand Club (Net)", format_currency(sim_g), delta=format_currency(CAP_GRAND_CLUB - sim_g), delta_color="normal" if sim_g <= CAP_GRAND_CLUB else "inverse")
        res2.metric("Club École (Net)", format_currency(sim_c), delta=format_currency(CAP_CLUB_ECOLE - sim_c), delta_color="normal" if sim_c <= CAP_CLUB_ECOLE else "inverse")

        st.markdown("""<style>.stSortablesItem { background-color: #1E3A8A !important; color: white !important; border-radius: 5px !important; padding: 8px !important; margin-bottom: 5px !important; }</style>""", unsafe_allow_html=True)
else:
    st.info("Veuillez importer un fichier CSV Fantrax pour commencer.")
