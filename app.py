import streamlit as st
import pandas as pd
import io
import os
from datetime import datetime
from streamlit_sortables import sort_items

st.set_page_config(page_title="Calculateur Fantrax 2025", layout="wide")

DB_FILE = "historique_fantrax_v2.csv"
PLAYERS_DB_FILE = "Hockey_Players.csv"

# --- FONCTIONS DE NETTOYAGE ---
def clean_salary(val):
    if pd.isna(val) or val == "": return 0
    s = str(val).replace('$', '').replace(',', '').replace(' ', '').replace('\xa0', '').strip()
    try:
        return int(float(s))
    except:
        return 0

def format_currency(val):
    if pd.isna(val): return "0 $"
    return f"{int(val):,}".replace(",", " ") + "$"

# --- CHARGEMENT DES FICHIERS ---
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
            
            rename_dict = {
                'Player': 'Joueur', 'Salary': 'Salaire', 'Position': 'Pos', 
                'Team': 'Équipe', 'Équipe': 'Équipe', 'player': 'Joueur', 'salary': 'Salaire'
            }
            df_base.rename(columns=rename_dict, inplace=True)
            
            if 'Équipe' not in df_base.columns:
                df_base['Équipe'] = 'N/A'
            
            df_base['Salaire'] = df_base['Salaire'].apply(clean_salary)
            df_base['Display'] = df_base.apply(
                lambda row: f"{row['Joueur']} ({row['Équipe']} - {row['Pos']}) - {format_currency(row['Salaire'])}", axis=1
            )
            return df_base
        except Exception as e:
            st.error(f"Erreur Hockey_Players.csv: {e}")
            return pd.DataFrame()
    return pd.DataFrame()

def sauvegarder_historique(df):
    df = df.drop_duplicates(subset=['Joueur', 'Propriétaire'], keep='last')
    df.to_csv(DB_FILE, index=False)
    return df

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
                return pd.read_csv(io.StringIO("\n".join(lines[h_idx:])), sep=None, engine='python', on_bad_lines='skip')
            
            df_merged = pd.concat([extract_table(lines, 'Skaters'), extract_table(lines, 'Goalies')], ignore_index=True)
            c_player = next((c for c in df_merged.columns if 'player' in c.lower() or 'joueur' in c.lower()), None)
            c_salary = next((c for c in df_merged.columns if 'salary' in c.lower() or 'salaire' in c.lower()), None)
            c_pos = next((c for c in df_merged.columns if 'pos' in c.lower() or 'eligible' in c.lower()), None)
            c_team = next((c for c in df_merged.columns if 'team' in c.lower() or 'éqp' in c.lower()), None)
            c_status = next((c for c in df_merged.columns if 'status' in c.lower() or 'statut' in c.lower()), None)

            if c_salary and c_player:
                df_merged['Salaire_Clean'] = df_merged[c_salary].apply(clean_salary)
                df_merged['Salaire_Clean'] = df_merged['Salaire_Clean'].apply(lambda x: x*1000 if 0 < x < 100000 else x)
                df_merged['Catégorie'] = df_merged[c_status].apply(lambda x: "Club École" if "MIN" in str(x).upper() else "Grand Club")
                nom_eq = fichier.name.replace('.csv', '')
                
                temp_df = pd.DataFrame({
                    'Joueur': df_merged[c_player], 'Salaire': df_merged['Salaire_Clean'], 'Statut': df_merged['Catégorie'],
                    'Pos': df_merged[c_pos] if c_pos else "N/A", 'Équipe_NHL': df_merged[c_team] if c_team else "N/A",
                    'Propriétaire': nom_eq, 'pos_order': df_merged[c_pos].apply(pos_sort_order) if c_pos else 0
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
        st.dataframe(summary.style.format({c: format_currency for c in summary.columns if c != 'Propriétaire'}), use_container_width=True)

    with tab2:
        st.header("🔄 Outil de Transfert & Simulateur")
        eq_sel = st.selectbox("Équipe à simuler", options=sorted(df_f['Propriétaire'].unique()))
        df_sim = df_f[df_f['Propriétaire'] == eq_sel].copy()

        # --- AJOUT JOUEUR AUTONOME ---
        st.subheader("➕ Ajouter un (Joueur Autonome)")
        if not base_joueurs.empty:
            c1, c2 = st.columns([0.6, 0.4])
            with c1:
                p_display = st.selectbox("Chercher un joueur autonome", options=[None] + base_joueurs['Display'].tolist(), key=f"p_{eq_sel}")
            if p_display:
                row = base_joueurs[base_joueurs['Display'] == p_display].iloc[0]
                with c2:
                    dest = st.selectbox("Affectation", options=["Grand Club", "Club École"], key=f"d_{eq_sel}")
                if st.button(f"Ajouter {row['Joueur']} (Joueur Autonome)"):
                    new_row = pd.DataFrame([{'Joueur': f"{row['Joueur']} (Joueur Autonome)", 'Salaire': row['Salaire'], 'Statut': dest, 'Pos': row['Pos'], 'Équipe_NHL': row['Équipe'], 'Propriétaire': eq_sel, 'pos_order': pos_sort_order(row['Pos'])}])
                    st.session_state['historique'] = sauvegarder_historique(pd.concat([st.session_state['historique'], new_row]))
                    st.rerun()

        st.markdown("---")

        # --- RACHATS ---
        st.subheader("💰 Rachats (50%)")
        df_sim['Display'] = df_sim.apply(lambda r: f"{r['Joueur']} ({r.get('Équipe_NHL', 'N/A')} - {r['Pos']}) - {format_currency(r['Salaire'])}", axis=1)
        cr1, cr2 = st.columns(2)
        with cr1:
            ch_gc = st.multiselect("Rachats Grand Club", options=df_sim[df_sim['Statut']=="Grand Club"]['Display'].tolist(), key=f"rgc_{eq_sel}")
            d_gc = sum([clean_salary(c.split('-')[-1]) for c in ch_gc]) / 2
        with cr2:
            ch_ce = st.multiselect("Rachats Club École", options=df_sim[df_sim['Statut']=="Club École"]['Display'].tolist(), key=f"rce_{eq_sel}")
            d_ce = sum([clean_salary(c.split('-')[-1]) for c in ch_ce]) / 2

        st.markdown("---")

        # --- DRAG AND DROP (CORRIGÉ) ---
        l_gc = df_sim[df_sim['Statut'] == "Grand Club"]['Display'].tolist()
        l_ce = df_sim[df_sim['Statut'] == "Club École"]['Display'].tolist()

        updated = sort_items([{'header': '🏙️ GRAND CLUB', 'items': l_gc}, {'header': '🏫 CLUB ÉCOLE', 'items': l_ce}], multi_containers=True, direction='horizontal')
        
        if updated and len(updated) >= 2:
            items_gc = updated[0]['items']
            items_ce = updated[1]['items']
        else:
            items_gc, items_ce = l_gc, l_ce

        def get_tot(plist):
            return sum([clean_salary(i.split('-')[-1]) for i in plist])

        sim_g = get_tot(items_gc) - d_gc
        sim_c = get_tot(items_ce) - d_ce

        st.divider()
        res1, res2 = st.columns(2)
        res1.metric("Grand Club (Net)", format_currency(sim_g), delta=format_currency(CAP_GRAND_CLUB - sim_g), delta_color="normal" if sim_g <= CAP_GRAND_CLUB else "inverse")
        res2.metric("Club École (Net)", format_currency(sim_c), delta=format_currency(CAP_CLUB_ECOLE - sim_c), delta_color="normal" if sim_c <= CAP_CLUB_ECOLE else "inverse")

        st.markdown("""<style>.stSortablesItem { background-color: #1E3A8A !important; color: white !important; border-radius: 5px !important; padding: 8px !important; margin-bottom: 5px !important; }</style>""", unsafe_allow_html=True)
else:
    st.info("Importez un fichier CSV Fantrax pour commencer.")
