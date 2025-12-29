import streamlit as st
import pandas as pd
import io
import os
from streamlit_sortables import sort_items

# 1. CONFIGURATION DU SYSTÈME
st.set_page_config(page_title="Simulateur Fantrax 2025", layout="wide")

DB_FILE = "historique_fantrax_v2.csv"
BUYOUT_FILE = "rachats_v2.csv"
PLAYERS_DB_FILE = "Hockey_Players.csv"

def save_all():
    """Sauvegarde immédiate sur le disque"""
    st.session_state.historique.to_csv(DB_FILE, index=False)
    st.session_state.rachats.to_csv(BUYOUT_FILE, index=False)

@st.cache_data
def load_initial_data(file, columns):
    if os.path.exists(file):
        try:
            df = pd.read_csv(file)
            return df.fillna({'Joueur': 'Inconnu', 'Salaire': 0, 'Pos': 'N/A', 'Equipe_NHL': 'N/A', 'Statut': 'Grand Club'})
        except: return pd.DataFrame(columns=columns)
    return pd.DataFrame(columns=columns)

# Initialisation des données
if 'historique' not in st.session_state:
    st.session_state.historique = load_initial_data(DB_FILE, ['Joueur', 'Salaire', 'Statut', 'Pos', 'Equipe_NHL', 'Propriétaire'])
if 'rachats' not in st.session_state:
    st.session_state.rachats = load_initial_data(BUYOUT_FILE, ['Propriétaire', 'Joueur', 'Impact'])
if 'db_joueurs' not in st.session_state:
    st.session_state.db_joueurs = load_initial_data(PLAYERS_DB_FILE, ['Player', 'Salary', 'Position', 'Team'])

def format_currency(val):
    return f"{int(val or 0):,}".replace(",", " ") + "$"

# 2. BARRE LATÉRALE - IMPORTATION ROBUSTE (CORRECTION NORDICUES.CSV)
with st.sidebar:
    st.header("⚙️ Configuration 2025")
    cap_gc = st.number_input("Plafond Grand Club", value=95500000, step=500000)
    cap_ce = st.number_input("Plafond Club École", value=47750000, step=100000)
    
    st.divider()
    uploaded_files = st.file_uploader("📁 Déposer CSV Fantrax", type="csv", accept_multiple_files=True)
    
    if uploaded_files:
        new_dfs = []
        for f in uploaded_files:
            try:
                # Lecture brute pour trouver l'en-tête de manière flexible
                content = f.getvalue().decode('utf-8-sig').splitlines()
                idx = -1
                for i, line in enumerate(content):
                    if any(key in line for key in ['Player', 'Skaters', 'Goalies', 'Joueur', 'Salary']):
                        idx = i
                        break
                
                if idx != -1:
                    # Utilisation de sep=None pour gérer , ou ; automatiquement
                    csv_data = io.StringIO("\n".join(content[idx:]))
                    df_raw = pd.read_csv(csv_data, sep=None, engine='python', on_bad_lines='skip').fillna("N/A")
                    df_raw.columns = [str(c).strip() for c in df_raw.columns] # Nettoyage colonnes

                    # Mapping flexible
                    col_p = next((c for c in df_raw.columns if 'player' in c.lower() or 'joueur' in c.lower()), None)
                    col_s = next((c for c in df_raw.columns if 'salary' in c.lower() or 'salaire' in c.lower()), None)
                    col_st = next((c for c in df_raw.columns if 'status' in c.lower() or 'statut' in c.lower()), None)
                    
                    if col_p and col_s:
                        sal = pd.to_numeric(df_raw[col_s].astype(str).str.replace(r'[^\d]', '', regex=True), errors='coerce').fillna(0)
                        sal = sal.apply(lambda x: x*1000 if 0 < x < 100000 else x)
                        
                        temp = pd.DataFrame({
                            'Joueur': df_raw[col_p].astype(str).str.strip(),
                            'Salaire': sal.astype(int),
                            'Statut': df_raw[col_st].apply(lambda x: "Club École" if "MIN" in str(x).upper() else "Grand Club") if col_st else "Grand Club",
                            'Pos': df_raw['Pos'].astype(str) if 'Pos' in df_raw.columns else "N/A",
                            'Equipe_NHL': df_raw['Team'].astype(str) if 'Team' in df_raw.columns else "N/A",
                            'Propriétaire': f.name.replace('.csv', '')
                        })
                        new_dfs.append(temp)
                else:
                    st.error(f"Format non reconnu dans {f.name}")
            except Exception as e:
                st.error(f"Erreur sur {f.name}: {e}")
        
        if new_dfs:
            st.session_state.historique = pd.concat([st.session_state.historique] + new_dfs).drop_duplicates(subset=['Joueur', 'Propriétaire'], keep='last')
            save_all()
            st.sidebar.success(f"✅ {len(new_dfs)} fichiers importés")
            st.rerun()

# 3. ONGLETS PRINCIPAUX
tab1, tab2, tab3 = st.tabs(["📊 Dashboard", "⚖️ Simulateur", "🛠️ Gestion"])

# --- DASHBOARD ---
with tab1:
    if not st.session_state.historique.empty:
        stats = st.session_state.historique.groupby(['Propriétaire', 'Statut'])['Salaire'].sum().unstack(fill_value=0).reset_index()
        r_sum = st.session_state.rachats.groupby('Propriétaire')['Impact'].sum().reset_index()
        stats = stats.merge(r_sum, on='Propriétaire', how='left').fillna(0)
        for c in ['Grand Club', 'Club École', 'Impact']: 
            if c not in stats.columns: stats[c] = 0
        stats['Total GC'] = stats['Grand Club'] + stats['Impact']
        stats['Espace GC'] = cap_gc - stats['Total GC']
        st.dataframe(stats.style.format(format_currency, subset=['Grand Club', 'Club École', 'Impact', 'Total GC', 'Espace GC']), use_container_width=True)

# --- SIMULATEUR ---
with tab2:
    teams = sorted(st.session_state.historique['Propriétaire'].unique()) if not st.session_state.historique.empty else []
    if teams:
        eq = st.selectbox("Sélectionner une équipe", teams, key="sim_selector")
        dff = st.session_state.historique[st.session_state.historique['Propriétaire'] == eq].copy().fillna("N/A")
        dff['label'] = dff['Joueur'].astype(str) + " | " + dff['Pos'].astype(str) + " | " + dff['Salaire'].apply(lambda x: f"{int(x/1000)}k")
        
        l_gc = dff[dff['Statut'] == "Grand Club"]['label'].tolist()
        l_ce = dff[dff['Statut'] == "Club École"]['label'].tolist()

        res = sort_items([{'header': '🏙️ GRAND CLUB', 'items': l_gc}, {'header': '🏫 CLUB ÉCOLE', 'items': l_ce}], multi_containers=True, key=f"sim_v2025_{eq}")

        def quick_sum(items):
            if not items or not isinstance(items, list): return 0
            total = 0
            for x in items:
                if isinstance(x, str) and '|' in x:
                    try: total += int(x.split('|')[-1].replace('k','').strip()) * 1000
                    except: pass
            return total
        
        s_gc_joueurs = quick_sum(res[0]) if (res and len(res) > 0) else quick_sum(l_gc)
        s_ce_joueurs = quick_sum(res[1]) if (res and len(res) > 1) else quick_sum(l_ce)
        p_imp = st.session_state.rachats[st.session_state.rachats['Propriétaire'] == eq]['Impact'].sum()
        
        st.divider()
        c1, c2, c3 = st.columns(3)
        c1.metric("Masse GC (+ Pénalités)", format_currency(s_gc_joueurs + p_imp), delta=format_currency(cap_gc - (s_gc_joueurs + p_imp)))
        c2.metric("Masse Club École", format_currency(s_ce_joueurs))
        c3.metric("Total Pénalités (50%)", format_currency(p_imp))

# --- GESTION ---
with tab3:
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("🆕 Embauche Agent Libre (JA)")
        available = st.session_state.db_joueurs.copy().fillna("N/A")
        if not available.empty:
            available['label'] = available['Player'].astype(str) + " (" + available['Position'].astype(str) + ") - " + available['Salary'].astype(str)
            with st.form("fa_form"):
                f_prop = st.selectbox("Équipe Acquéreuse", teams if teams else ["Ma Ligue"])
                sel = st.selectbox("Chercher un joueur", available['label'].tolist())
                f_stat = st.radio("Assignation", ["Grand Club", "Club École"], horizontal=True)
                
                if st.form_submit_button("Signer (Complet + 50% Pénalité)"):
                    p_data = available[available['label'] == sel].iloc[0]
                    sal = pd.to_numeric(str(p_data['Salary']).replace(r'[^\d]', '', regex=True), errors='coerce') or 0
                    if 0 < sal < 100000: sal *= 1000
                    
                    new_p = pd.DataFrame([{'Joueur': p_data['Player'], 'Salaire': sal, 'Statut': f_stat, 'Pos': p_data['Position'], 'Equipe_NHL': p_data['Team'], 'Propriétaire': f_prop}])
                    st.session_state.historique = pd.concat([st.session_state.historique, new_p], ignore_index=True)
                    new_r = pd.DataFrame([{'Propriétaire': f_prop, 'Joueur': f"Pénalité JA: {p_data['Player']}", 'Impact': int(sal * 0.5)}])
                    st.session_state.rachats = pd.concat([st.session_state.rachats, new_r], ignore_index=True)
                    save_all()
                    st.rerun()

    with col2:
        st.subheader("📉 Racheter un Contrat")
        if teams:
            with st.form("buy_form"):
                t_sel = st.selectbox("Sélectionner l'équipe", teams, key="bt_manage")
                j_df = st.session_state.historique[st.session_state.historique['Propriétaire'] == t_sel]
                j_list = {f"{r['Joueur']} ({r['Pos']}) | {format_currency(r['Salaire'])}": (r['Joueur'], r['Salaire']) for _, r in j_df.iterrows()}
                j_sel_label = st.selectbox("Joueur à racheter", list(j_list.keys()) if j_list else ["Aucun"])
                
                if st.form_submit_button("Confirmer Rachat (50%)"):
                    if j_list and j_sel_label != "Aucun":
                        j_name, j_sal = j_list[j_sel_label]
                        new_r = pd.DataFrame([{'Propriétaire': t_sel, 'Joueur': j_name, 'Impact': int(j_sal * 0.5)}])
                        st.session_state.rachats = pd.concat([st.session_state.rachats, new_r], ignore_index=True)
                        st.session_state.historique = st.session_state.historique[~((st.session_state.historique.Joueur == j_name) & (st.session_state.historique.Propriétaire == t_sel))]
                        save_all()
                        st.rerun()

st.markdown("""<style>.stSortablesItem { background-color: #1E3A8A !important; color: white !important; font-size: 11px; padding: 4px; border-radius: 4px; }</style>""", unsafe_allow_html=True)
