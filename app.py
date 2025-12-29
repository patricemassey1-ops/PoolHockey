import streamlit as st
import pandas as pd
import io
import os
from streamlit_sortables import sort_items

# 1. CONFIGURATION & CACHE
st.set_page_config(page_title="Simulateur Pro 2025", layout="wide")

DB_FILE = "historique_fantrax_v2.csv"
BUYOUT_FILE = "rachats_v2.csv"

@st.cache_data
def load_data(file, columns):
    if os.path.exists(file):
        return pd.read_csv(file)
    return pd.DataFrame(columns=columns)

# Chargement rapide initial
if 'historique' not in st.session_state:
    st.session_state.historique = load_data(DB_FILE, ['Joueur', 'Salaire', 'Statut', 'Pos', 'Propriétaire'])
if 'rachats' not in st.session_state:
    st.session_state.rachats = load_data(BUYOUT_FILE, ['Propriétaire', 'Joueur', 'Impact'])

# 2. FONCTIONS OPTIMISÉES
def format_currency(val):
    return f"{int(val):,}".replace(",", " ") + "$" if val else "0$"

def save_all():
    st.session_state.historique.to_csv(DB_FILE, index=False)
    st.session_state.rachats.to_csv(BUYOUT_FILE, index=False)

# 3. BARRE LATÉRALE
with st.sidebar:
    st.header("⚙️ Configuration")
    cap_gc = st.number_input("Plafond GC", value=95500000, step=500000)
    cap_ce = st.number_input("Plafond École", value=47750000, step=100000)
    
    uploaded_files = st.file_uploader("Importer CSV", accept_multiple_files=True)
    if uploaded_files and st.button("Lancer l'importation"):
        all_new = []
        for f in uploaded_files:
            content = f.getvalue().decode('utf-8-sig').splitlines()
            # Extraction rapide
            idx = next((i for i, l in enumerate(content) if 'Skaters' in l or 'Goalies' in l), -1)
            if idx != -1:
                df = pd.read_csv(io.StringIO("\n".join(content[idx+1:])))
                # Nettoyage vectorisé (rapide)
                df['Salaire'] = pd.to_numeric(df.filter(like='alary').iloc[:,0].astype(str).str.replace(r'[^\d]', '', regex=True), errors='coerce').fillna(0)
                df.loc[df['Salaire'] < 100000, 'Salaire'] *= 1000
                
                temp = pd.DataFrame({
                    'Joueur': df.filter(like='layer').iloc[:,0],
                    'Salaire': df['Salaire'],
                    'Statut': "Grand Club",
                    'Pos': df['Pos'] if 'Pos' in df.columns else "N/A",
                    'Propriétaire': f.name.replace('.csv', '')
                })
                all_new.append(temp)
        if all_new:
            st.session_state.historique = pd.concat([st.session_state.historique] + all_new).drop_duplicates(subset=['Joueur', 'Propriétaire'], keep='last')
            save_all()
            st.rerun()

# 4. DASHBOARD (CALCULS VECTORISÉS)
tab1, tab2, tab3 = st.tabs(["📊 Dashboard", "⚖️ Simulateur", "🛠️ Gestion"])

with tab1:
    if not st.session_state.historique.empty:
        # Groupby rapide pour les statistiques
        df = st.session_state.historique
        stats = df.groupby(['Propriétaire', 'Statut'])['Salaire'].sum().unstack(fill_value=0).reset_index()
        
        # Ajout des rachats
        r_sum = st.session_state.rachats.groupby('Propriétaire')['Impact'].sum().reset_index()
        stats = stats.merge(r_sum, on='Propriétaire', how='left').fillna(0)
        
        stats['Total GC'] = stats.get('Grand Club', 0) + stats['Impact']
        stats['Espace'] = cap_gc - stats['Total GC']
        
        st.dataframe(stats.style.format(format_currency, subset=['Grand Club', 'Club École', 'Impact', 'Total GC', 'Espace']), use_container_width=True)

# 5. SIMULATEUR (DRAG & DROP)
with tab2:
    teams = sorted(st.session_state.historique['Propriétaire'].unique())
    if teams:
        eq = st.selectbox("Équipe", teams)
        dff = st.session_state.historique[st.session_state.historique['Propriétaire'] == eq].fillna(0)
        
        # Formatage minimal pour éviter la surcharge JSON
        dff['label'] = dff['Joueur'] + " | " + dff['Salaire'].apply(lambda x: f"{int(x/1000)}k")
        
        l_gc = dff[dff['Statut'] == "Grand Club"]['label'].tolist()
        l_ce = dff[dff['Statut'] == "Club École"]['label'].tolist()

        res = sort_items([{'header': 'GC', 'items': l_gc}, {'header': 'ÉCOLE', 'items': l_ce}], multi_containers=True, key=eq)

        # Calcul instantané
        def quick_sum(items):
            return sum(int(str(x).split('|')[-1].replace('k','').strip()) * 1000 for x in items if '|' in str(x))
        
        s_gc, s_ce = quick_sum(res['items']), quick_sum(res['items'])
        p_imp = st.session_state.rachats[st.session_state.rachats['Propriétaire'] == eq]['Impact'].sum()
        
        c1, c2 = st.columns(2)
        c1.metric("Masse GC (+Rachats)", format_currency(s_gc + p_imp), delta=format_currency(cap_gc - (s_gc + p_imp)))
        c2.metric("Masse École", format_currency(s_ce), delta=format_currency(cap_ce - s_ce))

# 6. GESTION (RACHAT 50%)
with tab3:
    if not st.session_state.historique.empty:
        with st.form("rachat"):
            t_sel = st.selectbox("Équipe", teams)
            j_df = st.session_state.historique[st.session_state.historique['Propriétaire'] == t_sel]
            j_sel = st.selectbox("Joueur", j_df['Joueur'].tolist())
            if st.form_submit_button("Racheter (50% pénalité)"):
                sal = j_df[j_df['Joueur'] == j_sel]['Salaire'].values[0]
                # Update Rachats
                new_r = pd.DataFrame([{'Propriétaire': t_sel, 'Joueur': j_sel, 'Impact': int(sal * 0.5)}])
                st.session_state.rachats = pd.concat([st.session_state.rachats, new_r], ignore_index=True)
                # Remove Player
                st.session_state.historique = st.session_state.historique[~((st.session_state.historique.Joueur == j_sel) & (st.session_state.historique.Propriétaire == t_sel))]
                save_all()
                st.rerun()
