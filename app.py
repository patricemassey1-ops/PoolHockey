import streamlit as st
import pandas as pd
import io
import os
from streamlit_sortables import sort_items

# 1. CONFIGURATION
st.set_page_config(page_title="Simulateur Fantrax 2025", layout="wide")

DB_FILE = "historique_fantrax_v2.csv"
BUYOUT_FILE = "rachats_v2.csv"

# Initialisation des plafonds et sessions
if 'cap_gc' not in st.session_state: st.session_state['cap_gc'] = 95500000
if 'cap_ce' not in st.session_state: st.session_state['cap_ce'] = 47750000

if 'historique' not in st.session_state:
    if os.path.exists(DB_FILE):
        st.session_state['historique'] = pd.read_csv(DB_FILE).fillna({"Salaire": 0, "Pos": "N/A", "Statut": "Grand Club"})
    else:
        st.session_state['historique'] = pd.DataFrame(columns=['Joueur', 'Salaire', 'Statut', 'Pos', 'Propriétaire'])

if 'rachats' not in st.session_state:
    st.session_state['rachats'] = pd.read_csv(BUYOUT_FILE) if os.path.exists(BUYOUT_FILE) else pd.DataFrame(columns=['Propriétaire', 'Joueur', 'Impact'])

# 2. FONCTIONS UTILES
def clean_salary_values(series):
    return pd.to_numeric(series.astype(str).str.replace(r'[\$,\s\xa0]', '', regex=True), errors='coerce').fillna(0).astype(int)

def format_currency(val):
    return f"{int(val or 0):,}".replace(",", " ") + "$"

# 3. BARRE LATÉRALE (IMPORTATION RÉACTIVÉE)
st.sidebar.header("📥 Importation & Paramètres")
st.session_state['cap_gc'] = st.sidebar.number_input("Plafond Grand Club", value=st.session_state['cap_gc'], step=500000)
st.session_state['cap_ce'] = st.sidebar.number_input("Plafond Club École", value=st.session_state['cap_ce'], step=100000)

fichiers = st.sidebar.file_uploader("Importer CSV Fantrax", type="csv", accept_multiple_files=True)
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
            
            s_clean = clean_salary_values(df_m[c_s])
            s_clean = s_clean.apply(lambda x: x*1000 if 0 < x < 100000 else x)
            
            temp = pd.DataFrame({
                'Joueur': df_m[c_p].fillna("Inconnu"),
                'Salaire': s_clean,
                'Statut': df_m[c_st].apply(lambda x: "Club École" if "MIN" in str(x).upper() else "Grand Club") if c_st in df_m.columns else "Grand Club",
                'Pos': df_m['Pos'].fillna("N/A") if 'Pos' in df_m.columns else "N/A",
                'Propriétaire': f.name.replace('.csv', '')
            })
            dfs.append(temp)
    if dfs:
        st.session_state['historique'] = pd.concat([st.session_state['historique']] + dfs).drop_duplicates(subset=['Joueur', 'Propriétaire'], keep='last')
        st.session_state['historique'].to_csv(DB_FILE, index=False)
        st.sidebar.success("✅ Importation réussie")
        st.rerun()

# 4. ONGLETS PRINCIPAUX
tab1, tab2, tab3 = st.tabs(["📊 Dashboard", "⚖️ Simulateur", "🛠️ Gestion & Rachats"])

# --- DASHBOARD ---
with tab1:
    if not st.session_state['historique'].empty:
        dash_data = []
        for team in sorted(st.session_state['historique']['Propriétaire'].unique()):
            df_t = st.session_state['historique'][st.session_state['historique']['Propriétaire'] == team]
            m_gc = df_t[df_t['Statut'] == "Grand Club"]['Salaire'].sum()
            m_ce = df_t[df_t['Statut'] == "Club École"]['Salaire'].sum()
            r_imp = st.session_state['rachats'][st.session_state['rachats']['Propriétaire'] == team]['Impact'].sum()
            
            dash_data.append({
                'Équipe': team, 
                'Masse GC (+Rachats)': m_gc + r_imp, 
                'Espace GC': st.session_state['cap_gc'] - (m_gc + r_imp),
                'Masse École': m_ce,
                'Pénalités (50%)': r_imp
            })
        st.table(pd.DataFrame(dash_data).style.format(subset=[c for c in pd.DataFrame(dash_data).columns if c != 'Équipe'], formatter=format_currency))

# --- SIMULATEUR ---
with tab2:
    if not st.session_state['historique'].empty:
        eq = st.selectbox("Choisir Équipe", sorted(st.session_state['historique']['Propriétaire'].unique()))
        df_sim = st.session_state['historique'][st.session_state['historique']['Propriétaire'] == eq].copy().fillna(0)
        
        df_sim['Disp'] = df_sim['Joueur'].astype(str) + " (" + df_sim['Pos'].astype(str) + ") - " + df_sim['Salaire'].apply(format_currency)
        l_gc = df_sim[df_sim['Statut'] == "Grand Club"]['Disp'].tolist()
        l_ce = df_sim[df_sim['Statut'] == "Club École"]['Disp'].tolist()

        updated = sort_items([
            {'header': '🏙️ GRAND CLUB', 'items': [str(x) for x in l_gc]}, 
            {'header': '🏫 CLUB ÉCOLE', 'items': [str(x) for x in l_ce]}
        ], multi_containers=True, key=f"sort_{eq}")

        def parse_val(items):
            return sum(int(str(i).split('-')[-1].replace('$', '').replace(' ', '').replace('\xa0', '').strip()) for i in items if '-' in str(i))
        
        m_gc_s, m_ce_s = parse_val(updated[0]['items']), parse_val(updated[1]['items'])
        r_imp = st.session_state['rachats'][st.session_state['rachats']['Propriétaire'] == eq]['Impact'].sum()

        st.divider()
        c1, c2, c3 = st.columns(3)
        c1.metric("Masse GC (+ Rachats)", format_currency(m_gc_s + r_imp), delta=format_currency(st.session_state['cap_gc'] - (m_gc_s + r_imp)))
        c2.metric("Masse École", format_currency(m_ce_s), delta=format_currency(st.session_state['cap_ce'] - m_ce_s))
        c3.metric("Rachats Actifs", format_currency(r_imp))

# --- GESTION (RACHATS & FA) ---
with tab3:
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("📉 Racheter un joueur (50%)")
        all_t = sorted(st.session_state['historique']['Propriétaire'].unique()) if not st.session_state['historique'].empty else []
        if all_t:
            b_t = st.selectbox("Équipe", all_t, key="bt")
            df_joueurs = st.session_state['historique'][st.session_state['historique']['Propriétaire'] == b_t]
            
            if not df_joueurs.empty:
                # Création d'une liste propre pour la sélection
                j_list = {f"{r['Joueur']} ({format_currency(r['Salaire'])})": (r['Joueur'], r['Salaire']) for _, r in df_joueurs.iterrows()}
                sel_label = st.selectbox("Joueur", list(j_list.keys()))
                j_nom, j_sal = j_list[sel_label]
                penalite = int(j_sal * 0.5)
                
                st.warning(f"Action : Le joueur sera supprimé et une pénalité de {format_currency(penalite)} sera ajoutée.")
                
                if st.button("Confirmer le Rachat"):
                    # 1. Ajouter la pénalité
                    new_b = pd.DataFrame([{'Propriétaire': b_t, 'Joueur': j_nom, 'Impact': penalite}])
                    st.session_state['rachats'] = pd.concat([st.session_state['rachats'], new_b], ignore_index=True)
                    st.session_state['rachats'].to_csv(BUYOUT_FILE, index=False)
                    
                    # 2. Retirer de l'historique
                    st.session_state['historique'] = st.session_state['historique'][~((st.session_state['historique']['Joueur'] == j_nom) & (st.session_state['historique']['Propriétaire'] == b_t))]
                    st.session_state['historique'].to_csv(DB_FILE, index=False)
                    st.rerun()

    with col2:
        st.subheader("🆕 Ajouter Agent Libre")
        with st.form("fa"):
            f_t = st.selectbox("Équipe", all_t) if all_t else st.text_input("Nom Équipe")
            f_n = st.text_input("Nom Joueur")
            f_s = st.number_input("Salaire", min_value=0, step=100000)
            f_p = st.selectbox("Pos", ["F", "D", "G"])
            if st.form_submit_button("Ajouter"):
                new_f = pd.DataFrame([{'Joueur': f_n, 'Salaire': f_s, 'Statut': "Grand Club", 'Pos': f_p, 'Propriétaire': f_t}])
                st.session_state['historique'] = pd.concat([st.session_state['historique'], new_f], ignore_index=True)
                st.session_state['historique'].to_csv(DB_FILE, index=False)
                st.rerun()

st.markdown("""<style>.stSortablesItem { background-color: #1E3A8A !important; color: white !important; padding: 5px; border-radius: 4px; }</style>""", unsafe_allow_html=True)
