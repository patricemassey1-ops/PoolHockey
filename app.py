import streamlit as st
import pandas as pd
import io
import os
from streamlit_sortables import sort_items

# 1. CONFIGURATION
st.set_page_config(page_title="Calculateur Fantrax 2025", layout="wide")

DB_FILE = "historique_fantrax_v2.csv"
PLAYERS_DB_FILE = "Hockey_Players.csv"
BUYOUT_FILE = "rachats_v2.csv"

# Initialisation des sessions
if 'cap_gc' not in st.session_state: st.session_state['cap_gc'] = 95500000
if 'cap_ce' not in st.session_state: st.session_state['cap_ce'] = 47750000

# Chargement sécurisé de l'historique
if 'historique' not in st.session_state:
    if os.path.exists(DB_FILE):
        st.session_state['historique'] = pd.read_csv(DB_FILE).fillna({"Salaire": 0, "Pos": "N/A", "Statut": "Grand Club"})
    else:
        st.session_state['historique'] = pd.DataFrame(columns=['Joueur', 'Salaire', 'Statut', 'Pos', 'Propriétaire'])

if 'rachats' not in st.session_state:
    if os.path.exists(BUYOUT_FILE):
        st.session_state['rachats'] = pd.read_csv(BUYOUT_FILE)
    else:
        st.session_state['rachats'] = pd.DataFrame(columns=['Propriétaire', 'Joueur', 'Impact', 'Fin'])

# 2. FONCTIONS DE NETTOYAGE
def clean_salary_values(series):
    return pd.to_numeric(series.astype(str).str.replace(r'[\$,\s\xa0]', '', regex=True), errors='coerce').fillna(0).astype(int)

def format_currency(val):
    return f"{int(val or 0):,}".replace(",", " ") + "$"

# 3. BARRE LATÉRALE
st.sidebar.header("💰 Paramètres Ligue 2025")
st.session_state['cap_gc'] = st.sidebar.number_input("Plafond Grand Club", value=st.session_state['cap_gc'], step=500000)
st.session_state['cap_ce'] = st.sidebar.number_input("Plafond Club École", value=st.session_state['cap_ce'], step=100000)

fichiers = st.sidebar.file_uploader("📥 Importer CSV Fantrax", type="csv", accept_multiple_files=True)
if fichiers:
    dfs = []
    for f in fichiers:
        content = f.getvalue().decode('utf-8-sig')
        lines = content.splitlines()
        def extract(keyword):
            idx = next((i for i, l in enumerate(lines) if keyword in l), -1)
            return pd.read_csv(io.StringIO("\n".join(lines[idx+1:])), sep=None, engine='python', on_bad_lines='skip') if idx != -1 else pd.DataFrame()
        
        df_m = pd.concat([extract('Skaters'), extract('Goalies')], ignore_index=True)
        if not df_m.empty:
            c_p = next((c for c in df_m.columns if 'player' in c.lower() or 'joueur' in c.lower()), "Joueur")
            c_s = next((c for c in df_m.columns if 'salary' in c.lower() or 'salaire' in c.lower()), "Salaire")
            c_st = next((c for c in df_m.columns if 'status' in c.lower() or 'statut' in c.lower()), "Statut")
            
            df_m['S_Clean'] = clean_salary_values(df_m[c_s])
            df_m['S_Clean'] = df_m['S_Clean'].apply(lambda x: x*1000 if 0 < x < 100000 else x)
            
            temp = pd.DataFrame({
                'Joueur': df_m[c_p].fillna("Inconnu"),
                'Salaire': df_m['S_Clean'],
                'Statut': df_m[c_st].apply(lambda x: "Club École" if "MIN" in str(x).upper() else "Grand Club") if c_st in df_m.columns else "Grand Club",
                'Pos': df_m['Pos'].fillna("N/A") if 'Pos' in df_m.columns else "N/A",
                'Propriétaire': f.name.replace('.csv', '')
            })
            dfs.append(temp)
    if dfs:
        st.session_state['historique'] = pd.concat([st.session_state['historique']] + dfs).drop_duplicates(subset=['Joueur', 'Propriétaire'], keep='last')
        st.session_state['historique'].to_csv(DB_FILE, index=False)
        st.sidebar.success("✅ Importation réussie")

# 4. LOGIQUE DES ONGLETS
tab1, tab2, tab3 = st.tabs(["📊 Dashboard", "⚖️ Simulateur", "🛠️ Gestion (Rachats & FA)"])

# --- TAB 1: DASHBOARD ---
with tab1:
    if not st.session_state['historique'].empty:
        st.subheader("État Global de la Ligue 2025")
        dash_data = []
        for team in sorted(st.session_state['historique']['Propriétaire'].unique()):
            temp_team = st.session_state['historique'][st.session_state['historique']['Propriétaire'] == team]
            m_gc = temp_team[temp_team['Statut'] == "Grand Club"]['Salaire'].sum()
            m_ce = temp_team[temp_team['Statut'] == "Club École"]['Salaire'].sum()
            r_impact = st.session_state['rachats'][st.session_state['rachats']['Propriétaire'] == team]['Impact'].sum()
            
            dash_data.append({
                'Équipe': team, 
                'Masse GC (+Rachats)': m_gc + r_impact, 
                'Espace GC': st.session_state['cap_gc'] - (m_gc + r_impact),
                'Club École': m_ce,
                'Rachats Actifs': r_impact
            })
        
        st.dataframe(pd.DataFrame(dash_data).style.format({
            'Masse GC (+Rachats)': format_currency, 
            'Espace GC': format_currency, 
            'Club École': format_currency, 
            'Rachats Actifs': format_currency
        }), use_container_width=True)

# --- TAB 2: SIMULATEUR (CORRECTION NaN APPLIQUÉE) ---
with tab2:
    if not st.session_state['historique'].empty:
        eq = st.selectbox("Choisir une équipe", sorted(st.session_state['historique']['Propriétaire'].unique()))
        
        # Nettoyage CRUCIAL pour éviter l'erreur JSON "NaN"
        df_sim = st.session_state['historique'][st.session_state['historique']['Propriétaire'] == eq].copy()
        df_sim = df_sim.fillna({"Joueur": "Inconnu", "Pos": "N/A", "Salaire": 0})
        
        # Préparation des chaînes de caractères (tout en string pour le JSON)
        df_sim['Disp'] = df_sim['Joueur'].astype(str) + " (" + df_sim['Pos'].astype(str) + ") - " + df_sim['Salaire'].apply(format_currency)
        
        l_gc = df_sim[df_sim['Statut'] == "Grand Club"]['Disp'].tolist()
        l_ce = df_sim[df_sim['Statut'] == "Club École"]['Disp'].tolist()

        # Sortables avec clé unique pour éviter les conflits de cache
        updated = sort_items([
            {'header': '🏙️ GRAND CLUB', 'items': [str(x) for x in l_gc]}, 
            {'header': '🏫 CLUB ÉCOLE', 'items': [str(x) for x in l_ce]}
        ], multi_containers=True, key=f"sort_{eq}")

        # Calcul des masses basées sur le déplacement
        def parse_sal(items):
            return sum(int(str(i).split('-')[-1].replace('$', '').replace(' ', '').replace('\xa0', '').strip()) for i in items if '-' in str(i))
        
        m_gc = parse_sal(updated[0]['items']) if updated else 0
        m_ce = parse_sal(updated[1]['items']) if updated else 0
        r_impact = st.session_state['rachats'][st.session_state['rachats']['Propriétaire'] == eq]['Impact'].sum()

        st.divider()
        c1, c2, c3 = st.columns(3)
        c1.metric("Masse GC (+ Rachats)", format_currency(m_gc + r_impact), delta=format_currency(st.session_state['cap_gc'] - (m_gc + r_impact)))
        c2.metric("Masse Club École", format_currency(m_ce), delta=format_currency(st.session_state['cap_ce'] - m_ce))
        c3.metric("Rachats", format_currency(r_impact))

# --- TAB 3: GESTION ---
with tab3:
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("🆕 Ajouter un Joueur (FA)")
        with st.form("add_player"):
            f_team = st.selectbox("Équipe", sorted(st.session_state['historique']['Propriétaire'].unique()))
            f_name = st.text_input("Nom")
            f_pos = st.selectbox("Pos", ["F", "D", "G"])
            f_sal = st.number_input("Salaire ($)", min_value=0, step=50000)
            if st.form_submit_button("Ajouter"):
                new_p = pd.DataFrame([{'Joueur': f_name, 'Salaire': f_sal, 'Statut': "Grand Club", 'Pos': f_pos, 'Propriétaire': f_team}])
                st.session_state['historique'] = pd.concat([st.session_state['historique'], new_p], ignore_index=True)
                st.session_state['historique'].to_csv(DB_FILE, index=False)
                st.success("Ajouté.")

    with col2:
        st.subheader("📉 Enregistrer un Rachat")
        with st.form("buyout_form"):
            b_team = st.selectbox("Équipe concernée", sorted(st.session_state['historique']['Propriétaire'].unique()))
            b_name = st.text_input("Joueur racheté")
            b_impact = st.number_input("Impact Annuel ($)", min_value=0)
            if st.form_submit_button("Valider Rachat"):
                new_b = pd.DataFrame([{'Propriétaire': b_team, 'Joueur': b_name, 'Impact': b_impact, 'Fin': 2026}])
                st.session_state['rachats'] = pd.concat([st.session_state['rachats'], new_b], ignore_index=True)
                st.session_state['rachats'].to_csv(BUYOUT_FILE, index=False)
                st.rerun()

st.markdown("""<style>.stSortablesItem { background-color: #1E3A8A !important; color: white !important; padding: 8px !important; border-radius: 6px !important; }</style>""", unsafe_allow_html=True)
