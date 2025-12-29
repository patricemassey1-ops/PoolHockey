import streamlit as st
import pandas as pd
import io
import os
from streamlit_sortables import sort_items

# 1. CONFIGURATION & CACHE
st.set_page_config(page_title="Simulateur Pro 2025", layout="wide")

DB_FILE = "historique_fantrax_v2.csv"
BUYOUT_FILE = "rachats_v2.csv"
PLAYERS_DB_FILE = "Hockey_Players.csv"

def save_all():
    st.session_state.historique.to_csv(DB_FILE, index=False)
    st.session_state.rachats.to_csv(BUYOUT_FILE, index=False)

@st.cache_data
def load_data(file, cols):
    if os.path.exists(file):
        try: return pd.read_csv(file).fillna("N/A")
        except: return pd.DataFrame(columns=cols)
    return pd.DataFrame(columns=cols)

# Initialisation des données
if 'historique' not in st.session_state:
    st.session_state.historique = load_data(DB_FILE, ['Joueur', 'Salaire', 'Statut', 'Pos', 'Equipe_NHL', 'Propriétaire'])
if 'rachats' not in st.session_state:
    st.session_state.rachats = load_data(BUYOUT_FILE, ['Propriétaire', 'Joueur', 'Impact'])
if 'db_joueurs' not in st.session_state:
    st.session_state.db_joueurs = load_data(PLAYERS_DB_FILE, ['Player', 'Salary', 'Position', 'Team'])

def format_currency(val):
    return f"{int(val):,}".replace(",", " ") + "$" if val else "0$"

# 2. BARRE LATÉRALE - IMPORTATION ROBUSTE
with st.sidebar:
    st.header("📥 Importation")
    cap_gc = st.number_input("Plafond GC", value=95500000)
    cap_ce = st.number_input("Plafond École", value=47750000)
    
    files = st.file_uploader("Fichiers Fantrax", type="csv", accept_multiple_files=True)
    if files and st.button("Lancer Import"):
        all_new = []
        for f in files:
            content = f.getvalue().decode('utf-8-sig').splitlines()
            # On ignore tout avant l'en-tête réel
            idx = next((i for i, l in enumerate(content) if 'Player' in l or 'Skaters' in l), 0)
            try:
                # Correction ParserError: on saute les lignes corrompues
                df = pd.read_csv(io.StringIO("\n".join(content[idx+1:])), sep=None, engine='python', on_bad_lines='skip')
                
                c_p = next((c for c in df.columns if 'player' in c.lower()), df.columns[0])
                c_s = next((c for c in df.columns if 'salary' in c.lower()), df.columns[1])
                
                df['S_Clean'] = pd.to_numeric(df[c_s].astype(str).str.replace(r'[^\d]', '', regex=True), errors='coerce').fillna(0)
                df.loc[df['S_Clean'] < 100000, 'S_Clean'] *= 1000
                
                temp = pd.DataFrame({
                    'Joueur': df[c_p], 'Salaire': df['S_Clean'],
                    'Statut': "Grand Club", 'Pos': df['Pos'] if 'Pos' in df.columns else "N/A",
                    'Equipe_NHL': df['Team'] if 'Team' in df.columns else "N/A",
                    'Propriétaire': f.name.replace('.csv', '')
                })
                all_new.append(temp)
            except Exception as e: st.error(f"Erreur sur {f.name}: {e}")
        
        if all_new:
            st.session_state.historique = pd.concat([st.session_state.historique] + all_new).drop_duplicates(subset=['Joueur', 'Propriétaire'], keep='last')
            save_all()
            st.rerun()

# 3. ONGLETS
tab1, tab2, tab3 = st.tabs(["📊 Dashboard", "⚖️ Simulateur", "🛠️ Gestion"])

# --- DASHBOARD ---
with tab1:
    if not st.session_state.historique.empty:
        df = st.session_state.historique
        stats = df.groupby(['Propriétaire', 'Statut'])['Salaire'].sum().unstack(fill_value=0).reset_index()
        r_sum = st.session_state.rachats.groupby('Propriétaire')['Impact'].sum().reset_index()
        stats = stats.merge(r_sum, on='Propriétaire', how='left').fillna(0)
        
        for c in ['Grand Club', 'Club École', 'Impact']: 
            if c not in stats.columns: stats[c] = 0
            
        stats['Total GC'] = stats['Grand Club'] + stats['Impact']
        stats['Espace'] = cap_gc - stats['Total GC']
        st.dataframe(stats.style.format(format_currency, subset=['Grand Club', 'Club École', 'Impact', 'Total GC', 'Espace']), use_container_width=True)

# --- SIMULATEUR (OPTIMISÉ 2025) ---
@st.fragment
def render_simulator():
    teams = sorted(st.session_state.historique['Propriétaire'].unique())
    if not teams: return
    eq = st.selectbox("Équipe", teams)
    dff = st.session_state.historique[st.session_state.historique['Propriétaire'] == eq].copy()
    
    # Label ultra-léger pour éviter les lenteurs
    dff['label'] = dff['Joueur'] + " | " + dff['Pos'] + " | " + dff['Salaire'].apply(lambda x: f"{int(x/1000)}k")
    
    l_gc = dff[dff['Statut'] == "Grand Club"]['label'].tolist()
    l_ce = dff[dff['Statut'] == "Club École"]['label'].tolist()

    res = sort_items([{'header': '🏙️ GC', 'items': l_gc}, {'header': '🏫 ÉCOLE', 'items': l_ce}], multi_containers=True, key=f"sim_{eq}")

    def quick_sum(items):
        return sum(int(x.split('|')[-1].replace('k','').strip()) * 1000 for x in items if '|' in x)

    s_gc = quick_sum(res[0]) if res else quick_sum(l_gc)
    s_ce = quick_sum(res[1]) if res else quick_sum(l_ce)
    p_imp = st.session_state.rachats[st.session_state.rachats['Propriétaire'] == eq]['Impact'].sum()

    st.divider()
    c1, c2, c3 = st.columns(3)
    c1.metric("Masse GC (+Rachats)", format_currency(s_gc + p_imp), delta=format_currency(cap_gc - (s_gc + p_imp)))
    c2.metric("Masse École", format_currency(s_ce))
    c3.metric("Pénalités", format_currency(p_imp))

with tab2: render_simulator()

# --- GESTION (EMBAUCHE & RACHAT) ---
with tab3:
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("🆕 Embauche JA (100% + Pénalité 50%)")
        available = st.session_state.db_joueurs.copy()
        if not available.empty:
            available['label'] = available['Player'] + " (" + available['Position'] + ") - " + available['Salary'].astype(str)
            with st.form("fa_form"):
                f_prop = st.selectbox("Équipe", sorted(st.session_state.historique['Propriétaire'].unique()))
                sel = st.selectbox("Joueur DB", available['label'].tolist())
                if st.form_submit_button("Signer le joueur"):
                    p_data = available[available['label'] == sel].iloc[0]
                    sal = pd.to_numeric(str(p_data['Salary']).replace(r'[^\d]', '', regex=True), errors='coerce') or 0
                    if sal < 100000: sal *= 1000
                    
                    # 1. Ajouter Joueur (Salaire Complet)
                    new_p = pd.DataFrame([{'Joueur': p_data['Player'], 'Salaire': sal, 'Statut': "Grand Club", 'Pos': p_data['Position'], 'Equipe_NHL': p_data['Team'], 'Propriétaire': f_prop}])
                    st.session_state.historique = pd.concat([st.session_state.historique, new_p])
                    # 2. Pénalité 50%
                    new_r = pd.DataFrame([{'Propriétaire': f_prop, 'Joueur': f"JA: {p_data['Player']}", 'Impact': int(sal * 0.5)}])
                    st.session_state.rachats = pd.concat([st.session_state.rachats, new_r])
                    save_all()
                    st.rerun()

    with col2:
        st.subheader("📉 Rachat (Pénalité 50%)")
        with st.form("buy_form"):
            t_sel = st.selectbox("Équipe", sorted(st.session_state.historique['Propriétaire'].unique()), key="q_t")
            j_df = st.session_state.historique[st.session_state.historique['Propriétaire'] == t_sel]
            j_sel = st.selectbox("Joueur", j_df['Joueur'].tolist())
            if st.form_submit_button("Racheter"):
                row = j_df[j_df['Joueur'] == j_sel].iloc[0]
                new_r = pd.DataFrame([{'Propriétaire': t_sel, 'Joueur': j_sel, 'Impact': int(row['Salaire'] * 0.5)}])
                st.session_state.rachats = pd.concat([st.session_state.rachats, new_r])
                st.session_state.historique = st.session_state.historique[~((st.session_state.historique.Joueur == j_sel) & (st.session_state.historique.Propriétaire == t_sel))]
                save_all()
                st.rerun()

st.markdown("""<style>.stSortablesItem { background-color: #1E3A8A !important; color: white !important; font-size: 11px; padding: 4px; }</style>""", unsafe_allow_html=True)
