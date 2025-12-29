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

# 2. GESTION DES DONNÉES
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
    if os.path.exists(file):
        try:
            df = pd.read_csv(file).fillna("N/A")
            df.columns = [c.strip() for c in df.columns]
            df.rename(columns={'Player': 'Joueur', 'Salary': 'Salaire', 'Position': 'Pos', 'Team': 'Equipe_NHL'}, inplace=True)
            df['Salaire'] = pd.to_numeric(df['Salaire'].astype(str).str.replace(r'[^\d]', '', regex=True), errors='coerce').fillna(0)
            df.loc[df['Salaire'] < 100000, 'Salaire'] *= 1000
            return df
        except: return pd.DataFrame(columns=['Joueur', 'Salaire', 'Pos', 'Equipe_NHL'])
    return pd.DataFrame(columns=['Joueur', 'Salaire', 'Pos', 'Equipe_NHL'])

if 'historique' not in st.session_state:
    st.session_state.historique = load_initial_data(DB_FILE, ['Joueur', 'Salaire', 'Statut', 'Pos', 'Equipe_NHL', 'Propriétaire'])
if 'rachats' not in st.session_state:
    st.session_state.rachats = load_initial_data(BUYOUT_FILE, ['Propriétaire', 'Joueur', 'Impact'])
if 'db_joueurs' not in st.session_state:
    st.session_state.db_joueurs = load_players_db(PLAYERS_DB_FILE)

def format_currency(val):
    return f"{int(val):,}".replace(",", " ") + "$" if val else "0$"

# 3. BARRE LATÉRALE
with st.sidebar:
    st.header("🚀 Système 2025")
    cap_gc = st.number_input("Plafond Grand Club", value=95500000, step=500000)
    cap_ce = st.number_input("Plafond Club École", value=47750000, step=100000)
    
    files = st.file_uploader("Importer CSV Fantrax", type="csv", accept_multiple_files=True)
    if files:
        new_dfs = []
        for f in files:
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
                    'Joueur': df_raw[col_p], 'Salaire': sal_clean,
                    'Statut': df_raw[col_st].apply(lambda x: "Club École" if "MIN" in str(x).upper() else "Grand Club") if col_st in df_raw.columns else "Grand Club",
                    'Pos': df_raw['Pos'] if 'Pos' in df_raw.columns else "N/A",
                    'Equipe_NHL': df_raw[col_tm] if col_tm in df_raw.columns else "N/A",
                    'Propriétaire': f.name.replace('.csv', '')
                })
                new_dfs.append(temp)
        if new_dfs:
            st.session_state.historique = pd.concat([st.session_state.historique] + new_dfs).drop_duplicates(subset=['Joueur', 'Propriétaire'], keep='last')
            save_all()
            st.rerun()

# 4. ONGLETS PRINCIPAUX
tab1, tab2, tab3 = st.tabs(["📊 Dashboard", "⚖️ Simulateur", "🛠️ Gestion"])

with tab1:
    if not st.session_state.historique.empty:
        for team in sorted(st.session_state.historique['Propriétaire'].unique()):
            with st.expander(f"📋 {team}"):
                df_t = st.session_state.historique[st.session_state.historique['Propriétaire'] == team]
                st.dataframe(df_t[['Joueur', 'Pos', 'Equipe_NHL', 'Salaire', 'Statut']].style.format({'Salaire': format_currency}), use_container_width=True)
                m_gc = df_t[df_t['Statut'] == "Grand Club"]['Salaire'].sum()
                m_ce = df_t[df_t['Statut'] == "Club École"]['Salaire'].sum()
                r_imp = st.session_state.rachats[st.session_state.rachats['Propriétaire'] == team]['Impact'].sum()
                c1, c2, c3 = st.columns(3)
                c1.metric("Masse GC (+Rachats)", format_currency(m_gc + r_imp), delta=format_currency(cap_gc - (m_gc + r_imp)))
                c2.metric("Masse École", format_currency(m_ce), delta=format_currency(cap_ce - m_ce))
                c3.metric("Total Pénalités", format_currency(r_imp))

with tab2:
    teams = sorted(st.session_state.historique['Propriétaire'].unique()) if not st.session_state.historique.empty else []
    if teams:
        eq = st.selectbox("Équipe", teams, key="sim_v2025")
        dff = st.session_state.historique[st.session_state.historique['Propriétaire'] == eq].copy().fillna("N/A")
        dff['label'] = dff['Joueur'].astype(str) + " (" + dff['Pos'].astype(str) + " - " + dff['Equipe_NHL'].astype(str) + ") | " + dff['Salaire'].apply(lambda x: f"{int(x/1000)}k")
        l_gc = dff[dff['Statut'] == "Grand Club"]['label'].tolist()
        l_ce = dff[dff['Statut'] == "Club École"]['label'].tolist()
        res = sort_items([{'header': '🏙️ GC', 'items': l_gc}, {'header': '🏫 ÉCOLE', 'items': l_ce}], multi_containers=True, key=f"drag_{eq}")
        
        def quick_sum(items):
            return sum(int(str(x).split('|')[-1].replace('k','').strip()) * 1000 for x in items if '|' in str(x))
        
        s_gc_joueurs = quick_sum(res) if res and len(res) > 0 else quick_sum(l_gc)
        s_ce = quick_sum(res) if res and len(res) > 1 else quick_sum(l_ce)
        p_imp = st.session_state.rachats[st.session_state.rachats['Propriétaire'] == eq]['Impact'].sum()
        
        st.divider()
        c1, c2, c3 = st.columns(3)
        c1.metric("Total Grand Club", format_currency(s_gc_joueurs + p_imp), delta=format_currency(cap_gc - (s_gc_joueurs + p_imp)))
        c2.metric("Club École", format_currency(s_ce), delta=format_currency(cap_ce - s_ce))
        c3.metric("Pénalités", format_currency(p_imp))

with tab3:
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("🆕 Embauche Agent Libre (JA)")
        available = st.session_state.db_joueurs.copy()
        if not available.empty:
            available['label'] = available.apply(lambda r: f"{r['Joueur']} ({r['Pos']} - {r['Equipe_NHL']}) | {format_currency(r['Salaire'])}", axis=1)
            with st.form("fa_form"):
                f_prop = st.selectbox("Équipe", teams if teams else ["Ligue"])
                sel_label = st.selectbox("Sélectionner Joueur", available['label'].tolist())
                f_stat = st.radio("Assignation", ["Grand Club", "Club École"], horizontal=True)
                if st.form_submit_button("Signer (Salaire complet + 50% pénalité)"):
                    p_row = available[available['label'] == sel_label].iloc[0]
                    # 1. Ajouter joueur (100%)
                    new_p = pd.DataFrame([{'Joueur': p_row['Joueur'], 'Salaire': p_row['Salaire'], 'Statut': f_stat, 'Pos': p_row['Pos'], 'Equipe_NHL': p_row['Equipe_NHL'], 'Propriétaire': f_prop}])
                    st.session_state.historique = pd.concat([st.session_state.historique, new_p], ignore_index=True)
                    # 2. Ajouter Pénalité (50%)
                    new_r = pd.DataFrame([{'Propriétaire': f_prop, 'Joueur': f"Pénalité JA: {p_row['Joueur']}", 'Impact': int(p_row['Salaire'] * 0.5)}])
                    st.session_state.rachats = pd.concat([st.session_state.rachats, new_r], ignore_index=True)
                    save_all()
                    st.rerun()
    with col2:
        st.subheader("📉 Rachat")
        if teams:
            with st.form("buy_form"):
                t_sel = st.selectbox("Équipe", teams, key="bt_m")
                j_df = st.session_state.historique[st.session_state.historique['Propriétaire'] == t_sel]
                j_list = {f"{r['Joueur']} | {format_currency(r['Salaire'])}": (r['Joueur'], r['Salaire']) for _, r in j_df.iterrows()}
                j_sel = st.selectbox("Joueur", list(j_list.keys()) if j_list else ["Aucun"])
                if st.form_submit_button("Confirmer Rachat"):
                    if j_list:
                        nom, sal = j_list[j_sel]
                        new_r = pd.DataFrame([{'Propriétaire': t_sel, 'Joueur': nom, 'Impact': int(sal * 0.5)}])
                        st.session_state.rachats = pd.concat([st.session_state.rachats, new_r], ignore_index=True)
                        st.session_state.historique = st.session_state.historique[~((st.session_state.historique.Joueur == nom) & (st.session_state.historique.Propriétaire == t_sel))]
                        save_all()
                        st.rerun()

st.markdown("""<style>.stSortablesItem { background-color: #1E3A8A !important; color: white !important; font-size: 13px !important; padding: 5px; border-radius: 4px; }</style>""", unsafe_allow_html=True)
