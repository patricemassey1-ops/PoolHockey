import streamlit as st
import pandas as pd
import io
import os
from datetime import datetime
from streamlit_sortables import sort_items

st.set_page_config(page_title="Calculateur Fantrax 2025", layout="wide")

DB_FILE = "historique_fantrax_v2.csv"

# --- FONCTIONS ---
def charger_historique():
    if os.path.exists(DB_FILE):
        return pd.read_csv(DB_FILE)
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

if 'historique' not in st.session_state:
    st.session_state['historique'] = charger_historique()

if 'buyouts' not in st.session_state:
    st.session_state['buyouts'] = {}

st.title("🏒 Analyseur Fantrax 2025")

# --- BARRE LATÉRALE ---
st.sidebar.header("⚙️ Configuration Globale")
CAP_GRAND_CLUB = st.sidebar.number_input("Plafond Grand Club ($)", value=95500000, step=500000)
CAP_CLUB_ECOLE = st.sidebar.number_input("Plafond Club École ($)", value=47750000, step=100000)

# --- LOGIQUE D'IMPORTATION ---
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
            st.error(f"Erreur sur {fichier.name}: {e}")

    if dfs_a_ajouter:
        nouveau_df = pd.concat([st.session_state['historique'], pd.concat(dfs_a_ajouter)], ignore_index=True)
        st.session_state['historique'] = sauvegarder_historique(nouveau_df)
        st.success("Importation réussie.")

# --- AFFICHAGE ---
if not st.session_state['historique'].empty:
    df_f = st.session_state['historique']
    tab1, tab2 = st.tabs(["📊 Tableau de Bord", "⚖️ Simulateur Avancé"]) 

    with tab1:
        summary = df_f.groupby(['Propriétaire', 'Statut'])['Salaire'].sum().unstack(fill_value=0).reset_index()
        st.dataframe(summary, use_container_width=True)

    with tab2:
        st.header("🔄 Outil de Transfert & Simulateur de Rachat")
        equipe_choisie = st.selectbox("Équipe à simuler", options=sorted(df_f['Propriétaire'].unique()))
        
        if equipe_choisie not in st.session_state['buyouts']:
            st.session_state['buyouts'][equipe_choisie] = {'gc_player': None, 'ce_player': None}

        df_sim = df_f[df_f['Propriétaire'] == equipe_choisie].copy()
        
        # --- SECTION DES RACHATS (LOGIQUE 50%) ---
        st.subheader(f"💰 Rachats de contrats (Déduction de 50%)")
        col_r1, col_r2 = st.columns(2)
        
        with col_r1:
            joueurs_gc = df_sim[df_sim['Statut'] == "Grand Club"]
            choix_gc = st.selectbox("Sélectionner un joueur à racheter (GC)", options=[None] + joueurs_gc['Joueur'].tolist(), format_func=lambda x: "---" if x is None else x, key=f"sel_gc_{equipe_choisie}")
            if choix_gc:
                sal_gc = joueurs_gc[joueurs_gc['Joueur'] == choix_gc]['Salaire'].values[0]
                deduction_gc = sal_gc / 2
                st.warning(f"Rachat {choix_gc} : -{format_currency(deduction_gc)} (50%)")
                if st.button("Annuler rachat GC"): 
                    st.rerun()
            else: deduction_gc = 0

        with col_r2:
            joueurs_ce = df_sim[df_sim['Statut'] == "Club École"]
            choix_ce = st.selectbox("Sélectionner un joueur à racheter (CE)", options=[None] + joueurs_ce['Joueur'].tolist(), format_func=lambda x: "---" if x is None else x, key=f"sel_ce_{equipe_choisie}")
            if choix_ce:
                sal_ce = joueurs_ce[joueurs_ce['Joueur'] == choix_ce]['Salaire'].values[0]
                deduction_ce = sal_ce / 2
                st.warning(f"Rachat {choix_ce} : -{format_currency(deduction_ce)} (50%)")
                if st.button("Annuler rachat CE"):
                    st.rerun()
            else: deduction_ce = 0

        # --- DRAG AND DROP ---
        list_gc = [f"{r['Joueur']} ({r['Pos']}) - {format_currency(r['Salaire'])}" for _, r in df_sim[df_sim['Statut'] == "Grand Club"].iterrows()]
        list_ce = [f"{r['Joueur']} ({r['Pos']}) - {format_currency(r['Salaire'])}" for _, r in df_sim[df_sim['Statut'] == "Club École"].iterrows()]

        updated_sort = sort_items([{'header': '🏙️ GRAND CLUB', 'items': list_gc}, {'header': '🏫 CLUB ÉCOLE', 'items': list_ce}], multi_containers=True, direction='horizontal')
        
        col_gc_final = updated_sort[0]['items'] if updated_sort else list_gc
        col_ce_final = updated_sort[1]['items'] if updated_sort else list_ce

        def extract_salary(player_list):
            total = 0
            for item in player_list:
                try:
                    s_str = item.split('-')[-1].replace('$', '').replace(' ', '').replace(',', '').strip()
                    total += int(s_str)
                except: continue
            return total

        masse_gc_pure = extract_salary(col_gc_final)
        masse_ce_pure = extract_salary(col_ce_final)
        
        sim_g = masse_gc_pure - deduction_gc
        sim_c = masse_ce_pure - deduction_ce

        st.markdown("---")
        res1, res2 = st.columns(2)
        res1.metric("Masse Grand Club (Net)", format_currency(sim_g), delta=format_currency(CAP_GRAND_CLUB - sim_g), delta_color="normal" if sim_g <= CAP_GRAND_CLUB else "inverse")
        res2.metric("Masse Club École (Net)", format_currency(sim_c), delta=format_currency(CAP_CLUB_ECOLE - sim_c), delta_color="normal" if sim_c <= CAP_CLUB_ECOLE else "inverse")

        st.markdown("""<style>.stSortablesItem { background-color: #1E3A8A !important; color: white !important; border-radius: 5px !important; padding: 8px !important; margin-bottom: 5px !important; }</style>""", unsafe_allow_html=True)
else:
    st.info("Veuillez importer un fichier CSV Fantrax.")
