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

# Initialisation des états
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
        st.header("Résumé des Masses")
        summary = df_f.groupby(['Propriétaire', 'Statut'])['Salaire'].sum().unstack(fill_value=0).reset_index()
        st.dataframe(summary, use_container_width=True)

    with tab2:
        st.header("🔄 Outil de Transfert & Rachats")
        equipe_choisie = st.selectbox("Équipe à simuler", options=sorted(df_f['Propriétaire'].unique()))
        
        if equipe_choisie not in st.session_state['buyouts']:
            st.session_state['buyouts'][equipe_choisie] = {'gc_nom': '', 'gc_val': 0, 'ce_nom': '', 'ce_val': 0}

        # --- SECTION DES RACHATS ---
        st.subheader(f"💰 Rachats de contrats - {equipe_choisie}")
        col_r1, col_r2 = st.columns(2)
        with col_r1:
            st.session_state['buyouts'][equipe_choisie]['gc_nom'] = st.text_input("Joueur racheté (Grand Club)", value=st.session_state['buyouts'][equipe_choisie]['gc_nom'], key=f"ngc_{equipe_choisie}")
            st.session_state['buyouts'][equipe_choisie]['gc_val'] = st.number_input("Déduire de la Masse GC", value=st.session_state['buyouts'][equipe_choisie]['gc_val'], step=10000, key=f"vgc_{equipe_choisie}")
        with col_r2:
            st.session_state['buyouts'][equipe_choisie]['ce_nom'] = st.text_input("Joueur racheté (Club École)", value=st.session_state['buyouts'][equipe_choisie]['ce_nom'], key=f"nce_{equipe_choisie}")
            st.session_state['buyouts'][equipe_choisie]['ce_val'] = st.number_input("Déduire de la Masse CE", value=st.session_state['buyouts'][equipe_choisie]['ce_val'], step=10000, key=f"vce_{equipe_choisie}")

        # --- DRAG AND DROP ---
        df_sim = df_f[df_f['Propriétaire'] == equipe_choisie].copy()
        list_gc = [f"{r['Joueur']} ({r['Pos']}) - {format_currency(r['Salaire'])}" for _, r in df_sim[df_sim['Statut'] == "Grand Club"].iterrows()]
        list_ce = [f"{r['Joueur']} ({r['Pos']}) - {format_currency(r['Salaire'])}" for _, r in df_sim[df_sim['Statut'] == "Club École"].iterrows()]

        sort_data = [
            {'header': '🏙️ GRAND CLUB', 'items': list_gc},
            {'header': '🏫 CLUB ÉCOLE', 'items': list_ce}
        ]

        # APPEL DU COMPOSANT
        updated_sort = sort_items(sort_data, multi_containers=True, direction='horizontal')
        
        # CORRECTION DE L'ERREUR TYPESCRIPT (Accès par index [0] et [1])
        if updated_sort and len(updated_sort) >= 2:
            col_gc_final = updated_sort[0]['items']
            col_ce_final = updated_sort[1]['items']
        else:
            col_gc_final = list_gc
            col_ce_final = list_ce

        def extract_salary(player_list):
            total = 0
            for item in player_list:
                try:
                    s_str = item.split('-')[-1].replace('$', '').replace(' ', '').replace(',', '').strip()
                    total += int(s_str)
                except: continue
            return total

        # --- CALCULS FINAUX ---
        m_gc = st.session_state['buyouts'][equipe_choisie]['gc_val']
        m_ce = st.session_state['buyouts'][equipe_choisie]['ce_val']
        
        masse_gc_pure = extract_salary(col_gc_final)
        masse_ce_pure = extract_salary(col_ce_final)
        
        sim_g = masse_gc_pure - m_gc
        sim_c = masse_ce_pure - m_ce

        st.markdown("---")
        res1, res2 = st.columns(2)
        
        res1.metric("Masse Grand Club (Net)", format_currency(sim_g), delta=format_currency(CAP_GRAND_CLUB - sim_g), delta_color="normal" if sim_g <= CAP_GRAND_CLUB else "inverse")
        if m_gc > 0:
            res1.error(f"📉 Brut: {format_currency(masse_gc_pure)} | Rachat: -{format_currency(m_gc)}")
        
        res2.metric("Masse Club École (Net)", format_currency(sim_c), delta=format_currency(CAP_CLUB_ECOLE - sim_c), delta_color="normal" if sim_c <= CAP_CLUB_ECOLE else "inverse")
        if m_ce > 0:
            res2.error(f"📉 Brut: {format_currency(masse_ce_pure)} | Rachat: -{format_currency(m_ce)}")

        st.markdown("""<style>.stSortablesItem { background-color: #1E3A8A !important; color: white !important; border-radius: 5px !important; padding: 8px !important; margin-bottom: 5px !important; }</style>""", unsafe_allow_html=True)
else:
    st.info("Veuillez importer un fichier CSV Fantrax.")
