import streamlit as st
import pandas as pd
import io
import os
from streamlit_sortables import sort_items

# 1. CONFIGURATION & CACHE
st.set_page_config(page_title="Simulateur Fantrax 2025", layout="wide")

DB_FILE = "historique_fantrax_v2.csv"
BUYOUT_FILE = "rachats_v2.csv"

@st.cache_data
def load_data(file, columns):
    if os.path.exists(file):
        try: return pd.read_csv(file)
        except: return pd.DataFrame(columns=columns)
    return pd.DataFrame(columns=columns)

if 'historique' not in st.session_state:
    st.session_state.historique = load_data(DB_FILE, ['Joueur', 'Salaire', 'Statut', 'Pos', 'Equipe_NHL', 'Propriétaire'])
if 'rachats' not in st.session_state:
    st.session_state.rachats = load_data(BUYOUT_FILE, ['Propriétaire', 'Joueur', 'Impact'])

def format_currency(val):
    return f"{int(val):,}".replace(",", " ") + "$" if val else "0$"

def save_all():
    st.session_state.historique.to_csv(DB_FILE, index=False)
    st.session_state.rachats.to_csv(BUYOUT_FILE, index=False)

# 2. IMPORTATION AVEC LOGIQUE ACT/MIN
with st.sidebar:
    st.header("⚙️ Configuration 2025")
    cap_gc = st.number_input("Plafond Grand Club", value=95500000, step=500000)
    cap_ce = st.number_input("Plafond Club École", value=47750000, step=100000)
    
    files = st.sidebar.file_uploader("CSV Fantrax", accept_multiple_files=True)
    if files and st.sidebar.button("Lancer l'importation"):
        all_new = []
        for f in files:
            content = f.getvalue().decode('utf-8-sig').splitlines()
            idx = next((i for i, l in enumerate(content) if any(x in l for x in ['Skaters', 'Goalies', 'Player'])), -1)
            if idx != -1:
                df = pd.read_csv(io.StringIO("\n".join(content[idx+1:])), sep=None, engine='python', on_bad_lines='skip')
                
                # Détection des colonnes
                col_p = next((c for c in df.columns if 'player' in c.lower()), "Player")
                col_s = next((c for c in df.columns if 'salary' in c.lower()), "Salary")
                col_st = next((c for c in df.columns if 'status' in c.lower()), "Status")
                col_tm = next((c for c in df.columns if 'team' in c.lower()), "Team")
                
                # Nettoyage Salaire
                df['Sal_Clean'] = pd.to_numeric(df[col_s].astype(str).str.replace(r'[^\d]', '', regex=True), errors='coerce').fillna(0)
                df.loc[df['Sal_Clean'] < 100000, 'Sal_Clean'] *= 1000
                
                # Logique ACT / MIN
                # Act = Grand Club, Min = Club École
                def determine_statut(val):
                    v = str(val).upper()
                    return "Club École" if "MIN" in v else "Grand Club"

                temp = pd.DataFrame({
                    'Joueur': df[col_p],
                    'Salaire': df['Sal_Clean'],
                    'Statut': df[col_st].apply(determine_statut) if col_st in df.columns else "Grand Club",
                    'Pos': df['Pos'] if 'Pos' in df.columns else "N/A",
                    'Equipe_NHL': df[col_tm] if col_tm in df.columns else "N/A",
                    'Propriétaire': f.name.replace('.csv', '')
                })
                all_new.append(temp)
        
        if all_new:
            st.session_state.historique = pd.concat([st.session_state.historique] + all_new).drop_duplicates(subset=['Joueur', 'Propriétaire'], keep='last')
            save_all()
            st.rerun()

# 3. DASHBOARD
tab1, tab2, tab3 = st.tabs(["📊 Dashboard", "⚖️ Simulateur", "🛠️ Gestion"])

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

# 4. SIMULATEUR (AFFICHAGE ENRICHI)
with tab2:
    teams = sorted(st.session_state.historique['Propriétaire'].unique()) if not st.session_state.historique.empty else []
    if teams:
        eq = st.selectbox("Équipe", teams)
        dff = st.session_state.historique[st.session_state.historique['Propriétaire'] == eq].copy().fillna("N/A")
        
        # Format d'affichage : NOM (POS - NHL) - SALAIRE
        dff['label'] = (dff['Joueur'].astype(str) + " (" + dff['Pos'].astype(str) + " - " + 
                        dff['Equipe_NHL'].astype(str) + ") | " + dff['Salaire'].apply(lambda x: f"{int(x/1000)}k"))
        
        l_gc = dff[dff['Statut'] == "Grand Club"]['label'].tolist()
        l_ce = dff[dff['Statut'] == "Club École"]['label'].tolist()

        res = sort_items([{'header': '🏙️ GRAND CLUB', 'items': l_gc}, {'header': '🏫 CLUB ÉCOLE', 'items': l_ce}], multi_containers=True, key=f"sim_{eq}")

        def quick_sum(items):
            return sum(int(str(x).split('|')[-1].replace('k','').strip()) * 1000 for x in items if '|' in str(x))
        
        s_gc = quick_sum(res[0]['items'])
        s_ce = quick_sum(res[1]['items'])
        p_imp = st.session_state.rachats[st.session_state.rachats['Propriétaire'] == eq]['Impact'].sum()
        
        st.divider()
        c1, c2, c3 = st.columns(3)
        c1.metric("Masse GC (+Rachats)", format_currency(s_gc + p_imp), delta=format_currency(cap_gc - (s_gc + p_imp)))
        c2.metric("Masse École", format_currency(s_ce), delta=format_currency(cap_ce - s_ce))
        c3.metric("Pénalités Rachats", format_currency(p_imp))

# 5. GESTION DES RACHATS (50%)
with tab3:
    if not st.session_state.historique.empty:
        st.subheader("📉 Effectuer un rachat (Pénalité 50%)")
        with st.form("buyout"):
            t_sel = st.selectbox("Équipe", teams)
            j_df = st.session_state.historique[st.session_state.historique['Propriétaire'] == t_sel]
            j_sel = st.selectbox("Joueur à racheter", j_df['Joueur'].tolist())
            if st.form_submit_button("Confirmer le rachat"):
                sal = j_df[j_df['Joueur'] == j_sel]['Salaire'].values[0]
                # Ajouter pénalité
                new_r = pd.DataFrame([{'Propriétaire': t_sel, 'Joueur': j_sel, 'Impact': int(sal * 0.5)}])
                st.session_state.rachats = pd.concat([st.session_state.rachats, new_r], ignore_index=True)
                # Supprimer le joueur
                st.session_state.historique = st.session_state.historique[~((st.session_state.historique.Joueur == j_sel) & (st.session_state.historique.Propriétaire == t_sel))]
                save_all()
                st.rerun()

st.markdown("""<style>.stSortablesItem { background-color: #1E3A8A !important; color: white !important; font-size: 13px !important; }</style>""", unsafe_allow_html=True)
