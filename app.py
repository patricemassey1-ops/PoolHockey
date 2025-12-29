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
        try:
            return pd.read_csv(file)
        except:
            return pd.DataFrame(columns=columns)
    return pd.DataFrame(columns=columns)

if 'historique' not in st.session_state:
    st.session_state.historique = load_data(DB_FILE, ['Joueur', 'Salaire', 'Statut', 'Pos', 'Propriétaire'])
if 'rachats' not in st.session_state:
    st.session_state.rachats = load_data(BUYOUT_FILE, ['Propriétaire', 'Joueur', 'Impact'])

def format_currency(val):
    return f"{int(val):,}".replace(",", " ") + "$" if val else "0$"

def save_all():
    st.session_state.historique.to_csv(DB_FILE, index=False)
    st.session_state.rachats.to_csv(BUYOUT_FILE, index=False)

# 2. BARRE LATÉRALE - IMPORTATION ROBUSTE
with st.sidebar:
    st.header("⚙️ Configuration")
    cap_gc = st.number_input("Plafond GC", value=95500000, step=500000)
    cap_ce = st.number_input("Plafond École", value=47750000, step=100000)
    
    uploaded_files = st.file_uploader("Importer CSV Fantrax", accept_multiple_files=True)
    if uploaded_files and st.button("Lancer l'importation"):
        all_new = []
        for f in uploaded_files:
            content = f.getvalue().decode('utf-8-sig').splitlines()
            # Cherche la ligne de début des données
            idx = next((i for i, l in enumerate(content) if 'Skaters' in l or 'Goalies' in l or 'Player' in l), -1)
            
            if idx != -1:
                try:
                    # Correction ICI : utilisation de sep=None et engine='python' pour gérer les erreurs de parsing
                    csv_data = io.StringIO("\n".join(content[idx+1:]))
                    df = pd.read_csv(csv_data, sep=None, engine='python', on_bad_lines='skip')
                    
                    if not df.empty:
                        # Identifier les colonnes par mots-clés (plus flexible)
                        col_player = next((c for c in df.columns if 'player' in c.lower()), df.columns[0])
                        col_salary = next((c for c in df.columns if 'salary' in c.lower()), None)
                        
                        # Nettoyage du salaire
                        if col_salary:
                            df['Sal_Clean'] = pd.to_numeric(df[col_salary].astype(str).str.replace(r'[^\d]', '', regex=True), errors='coerce').fillna(0)
                        else:
                            df['Sal_Clean'] = 0
                            
                        # Ajustement des salaires k -> millions
                        df.loc[df['Sal_Clean'] < 100000, 'Sal_Clean'] *= 1000
                        
                        temp = pd.DataFrame({
                            'Joueur': df[col_player],
                            'Salaire': df['Sal_Clean'],
                            'Statut': "Grand Club",
                            'Pos': df['Pos'] if 'Pos' in df.columns else "N/A",
                            'Propriétaire': f.name.replace('.csv', '')
                        })
                        all_new.append(temp)
                except Exception as e:
                    st.error(f"Erreur sur le fichier {f.name}: {e}")

        if all_new:
            st.session_state.historique = pd.concat([st.session_state.historique] + all_new).drop_duplicates(subset=['Joueur', 'Propriétaire'], keep='last')
            save_all()
            st.success("Importation terminée")
            st.rerun()

# 3. ONGLETS PRINCIPAUX
tab1, tab2, tab3 = st.tabs(["📊 Dashboard", "⚖️ Simulateur", "🛠️ Gestion"])

# DASHBOARD
with tab1:
    if not st.session_state.historique.empty:
        df = st.session_state.historique
        stats = df.groupby(['Propriétaire', 'Statut'])['Salaire'].sum().unstack(fill_value=0).reset_index()
        r_sum = st.session_state.rachats.groupby('Propriétaire')['Impact'].sum().reset_index()
        stats = stats.merge(r_sum, on='Propriétaire', how='left').fillna(0)
        
        # S'assurer que les colonnes existent
        for col in ['Grand Club', 'Club École', 'Impact']:
            if col not in stats.columns: stats[col] = 0
            
        stats['Total GC'] = stats['Grand Club'] + stats['Impact']
        stats['Espace'] = cap_gc - stats['Total GC']
        
        st.dataframe(stats.style.format(format_currency, subset=['Grand Club', 'Club École', 'Impact', 'Total GC', 'Espace']), use_container_width=True)

# SIMULATEUR
with tab2:
    teams = sorted(st.session_state.historique['Propriétaire'].unique()) if not st.session_state.historique.empty else []
    if teams:
        eq = st.selectbox("Équipe", teams)
        dff = st.session_state.historique[st.session_state.historique['Propriétaire'] == eq].copy().fillna(0)
        
        dff['label'] = dff['Joueur'].astype(str) + " | " + dff['Salaire'].apply(lambda x: f"{int(x/1000)}k")
        l_gc = dff[dff['Statut'] == "Grand Club"]['label'].tolist()
        l_ce = dff[dff['Statut'] == "Club École"]['label'].tolist()

        res = sort_items([{'header': '🏙️ GC', 'items': l_gc}, {'header': '🏫 ÉCOLE', 'items': l_ce}], multi_containers=True, key=f"sim_{eq}")

        def quick_sum(items):
            return sum(int(str(x).split('|')[-1].replace('k','').strip()) * 1000 for x in items if '|' in str(x))
        
        # Correction indexation sort_items
        s_gc = quick_sum(res[0]['items']) if res else 0
        s_ce = quick_sum(res[1]['items']) if res else 0
        p_imp = st.session_state.rachats[st.session_state.rachats['Propriétaire'] == eq]['Impact'].sum()
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Masse GC (+Rachats)", format_currency(s_gc + p_imp), delta=format_currency(cap_gc - (s_gc + p_imp)))
        c2.metric("Masse École", format_currency(s_ce), delta=format_currency(cap_ce - s_ce))
        c3.metric("Pénalités (50%)", format_currency(p_imp))

# GESTION
with tab3:
    if not st.session_state.historique.empty:
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("📉 Rachat de contrat")
            with st.form("rachat_form"):
                t_sel = st.selectbox("Équipe", teams)
                j_df = st.session_state.historique[st.session_state.historique['Propriétaire'] == t_sel]
                j_sel = st.selectbox("Joueur", j_df['Joueur'].tolist())
                if st.form_submit_button("Racheter (Pénalité 50%)"):
                    sal = j_df[j_df['Joueur'] == j_sel]['Salaire'].values[0]
                    # Update Rachats
                    new_r = pd.DataFrame([{'Propriétaire': t_sel, 'Joueur': j_sel, 'Impact': int(sal * 0.5)}])
                    st.session_state.rachats = pd.concat([st.session_state.rachats, new_r], ignore_index=True)
                    # Supprimer le joueur
                    st.session_state.historique = st.session_state.historique[~((st.session_state.historique.Joueur == j_sel) & (st.session_state.historique.Propriétaire == t_sel))]
                    save_all()
                    st.rerun()
