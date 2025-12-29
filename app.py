import streamlit as st
import pandas as pd
import io
import os
from streamlit_sortables import sort_items

# 1. CONFIGURATION & CACHE
st.set_page_config(page_title="Simulateur Fantrax 2025", layout="wide")

DB_FILE = "historique_fantrax_v2.csv"
BUYOUT_FILE = "rachats_v2.csv"

def save_all():
    st.session_state.historique.to_csv(DB_FILE, index=False)
    st.session_state.rachats.to_csv(BUYOUT_FILE, index=False)

@st.cache_data
def load_initial_data(file, columns):
    if os.path.exists(file):
        try: return pd.read_csv(file)
        except: return pd.DataFrame(columns=columns)
    return pd.DataFrame(columns=columns)

if 'historique' not in st.session_state:
    st.session_state.historique = load_initial_data(DB_FILE, ['Joueur', 'Salaire', 'Statut', 'Pos', 'Equipe_NHL', 'Propriétaire'])
if 'rachats' not in st.session_state:
    st.session_state.rachats = load_initial_data(BUYOUT_FILE, ['Propriétaire', 'Joueur', 'Impact'])

def format_currency(val):
    return f"{int(val):,}".replace(",", " ") + "$" if val else "0$"

# 2. IMPORTATION AUTOMATIQUE
with st.sidebar:
    st.header("🚀 Importation Automatique")
    cap_gc = st.number_input("Plafond Grand Club", value=95500000, step=500000)
    cap_ce = st.number_input("Plafond Club École", value=47750000, step=100000)
    
    uploaded_files = st.file_uploader("Glissez vos fichiers Fantrax ici", type="csv", accept_multiple_files=True)
    if uploaded_files:
        new_dfs = []
        for f in uploaded_files:
            content = f.getvalue().decode('utf-8-sig').splitlines()
            idx = next((i for i, l in enumerate(content) if any(x in l for x in ['Skaters', 'Goalies', 'Player'])), -1)
            if idx != -1:
                df_raw = pd.read_csv(io.StringIO("\n".join(content[idx+1:])), sep=None, engine='python', on_bad_lines='skip')
                col_p = next((c for c in df_raw.columns if 'player' in c.lower()), "Player")
                col_s = next((c for c in df_raw.columns if 'salary' in c.lower()), "Salary")
                col_st = next((c for c in df_raw.columns if 'status' in c.lower()), "Status")
                col_tm = next((c for c in df_raw.columns if 'team' in c.lower()), "Team")
                
                sal_clean = pd.to_numeric(df_raw[col_s].astype(str).str.replace(r'[^\d]', '', regex=True), errors='coerce').fillna(0)
                sal_clean = sal_clean.apply(lambda x: x*1000 if 0 < x < 100000 else x)
                
                temp = pd.DataFrame({
                    'Joueur': df_raw[col_p],
                    'Salaire': sal_clean,
                    'Statut': df_raw[col_st].apply(lambda x: "Club École" if "MIN" in str(x).upper() else "Grand Club") if col_st in df_raw.columns else "Grand Club",
                    'Pos': df_raw['Pos'] if 'Pos' in df_raw.columns else "N/A",
                    'Equipe_NHL': df_raw[col_tm] if col_tm in df_raw.columns else "N/A",
                    'Propriétaire': f.name.replace('.csv', '')
                })
                new_dfs.append(temp)
        if new_dfs:
            st.session_state.historique = pd.concat([st.session_state.historique] + new_dfs).drop_duplicates(subset=['Joueur', 'Propriétaire'], keep='last')
            save_all()
            st.sidebar.success("✅ Importé et Sauvegardé")

# 3. ONGLETS
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

# --- SIMULATEUR (CORRIGÉ) ---
with tab2:
    teams = sorted(st.session_state.historique['Propriétaire'].unique()) if not st.session_state.historique.empty else []
    if teams:
        eq = st.selectbox("Équipe", teams)
        dff = st.session_state.historique[st.session_state.historique['Propriétaire'] == eq].copy().fillna("N/A")
        dff['label'] = (dff['Joueur'].astype(str) + " (" + dff['Pos'].astype(str) + " - " + 
                        dff['Equipe_NHL'].astype(str) + ") | " + dff['Salaire'].apply(lambda x: f"{int(x/1000)}k"))
        
        l_gc = dff[dff['Statut'] == "Grand Club"]['label'].tolist()
        l_ce = dff[dff['Statut'] == "Club École"]['label'].tolist()

        # Correction ici : sort_items avec multi_containers renvoie une liste de listes
        res = sort_items([
            {'header': '🏙️ GRAND CLUB', 'items': l_gc}, 
            {'header': '🏫 CLUB ÉCOLE', 'items': l_ce}
        ], multi_containers=True, key=f"sim_v3_{eq}")

        def quick_sum(items):
            return sum(int(str(x).split('|')[-1].replace('k','').strip()) * 1000 for x in items if '|' in str(x))
        
        # Accès sécurisé aux listes retournées
        s_gc = quick_sum(res[0]) if res and len(res) > 0 else quick_sum(l_gc)
        s_ce = quick_sum(res[1]) if res and len(res) > 1 else quick_sum(l_ce)
        p_imp = st.session_state.rachats[st.session_state.rachats['Propriétaire'] == eq]['Impact'].sum()
        
        st.divider()
        c1, c2, c3 = st.columns(3)
        c1.metric("Masse GC (+Rachats)", format_currency(s_gc + p_imp), delta=format_currency(cap_gc - (s_gc + p_imp)))
        c2.metric("Masse École", format_currency(s_ce), delta=format_currency(cap_ce - s_ce))
        c3.metric("Rachats (50%)", format_currency(p_imp))

# --- GESTION ---
with tab3:
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("🆕 Embauche FA")
        with st.form("fa_form"):
            f_prop = st.selectbox("Équipe", teams if teams else ["Ligue"])
            f_nom = st.text_input("Nom")
            f_pos = st.selectbox("Pos", ["C", "LW", "RW", "D", "G"])
            f_nhl = st.text_input("Équipe NHL")
            f_sal = st.number_input("Salaire", min_value=0)
            if st.form_submit_button("Ajouter & Sauvegarder"):
                new_p = pd.DataFrame([{'Joueur': f_nom, 'Salaire': f_sal, 'Statut': "Grand Club", 'Pos': f_pos, 'Equipe_NHL': f_nhl.upper(), 'Propriétaire': f_prop}])
                st.session_state.historique = pd.concat([st.session_state.historique, new_p], ignore_index=True)
                save_all()
                st.rerun()

    with col2:
        st.subheader("📉 Rachat (50%)")
        if teams:
            with st.form("buy_form"):
                t_sel = st.selectbox("Équipe", teams, key="bt_manage")
                j_df = st.session_state.historique[st.session_state.historique['Propriétaire'] == t_sel]
                j_sel = st.selectbox("Joueur", j_df['Joueur'].tolist())
                if st.form_submit_button("Racheter"):
                    sal = j_df[j_df['Joueur'] == j_sel]['Salaire'].values[0]
                    new_r = pd.DataFrame([{'Propriétaire': t_sel, 'Joueur': j_sel, 'Impact': int(sal * 0.5)}])
                    st.session_state.rachats = pd.concat([st.session_state.rachats, new_r], ignore_index=True)
                    st.session_state.historique = st.session_state.historique[~((st.session_state.historique.Joueur == j_sel) & (st.session_state.historique.Propriétaire == t_sel))]
                    save_all()
                    st.rerun()

st.markdown("""<style>.stSortablesItem { background-color: #1E3A8A !important; color: white !important; padding: 5px; border-radius: 4px; }</style>""", unsafe_allow_html=True)
