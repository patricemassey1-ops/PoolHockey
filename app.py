import streamlit as st
import pandas as pd
import io
import os
from streamlit_sortables import sort_items

# 1. CONFIGURATION
st.set_page_config(page_title="Simulateur Fantrax 2025", layout="wide")

DB_FILE = "historique_fantrax_v2.csv"
BUYOUT_FILE = "rachats_v2.csv"

# Initialisation des sessions
if 'cap_gc' not in st.session_state: st.session_state['cap_gc'] = 95500000
if 'cap_ce' not in st.session_state: st.session_state['cap_ce'] = 47750000

if 'historique' not in st.session_state:
    if os.path.exists(DB_FILE):
        st.session_state['historique'] = pd.read_csv(DB_FILE).fillna({"Salaire": 0, "Pos": "N/A", "Statut": "Grand Club"})
    else:
        st.session_state['historique'] = pd.DataFrame(columns=['Joueur', 'Salaire', 'Statut', 'Pos', 'Propriétaire'])

if 'rachats' not in st.session_state:
    st.session_state['rachats'] = pd.read_csv(BUYOUT_FILE) if os.path.exists(BUYOUT_FILE) else pd.DataFrame(columns=['Propriétaire', 'Joueur', 'Impact'])

def format_currency(val):
    return f"{int(val or 0):,}".replace(",", " ") + "$"

# --- LOGIQUE DES ONGLETS ---
tab1, tab2, tab3 = st.tabs(["📊 Dashboard", "⚖️ Simulateur", "🛠️ Gestion & Rachats"])

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
                'Masse GC (+Pénalités)': m_gc + r_impact, 
                'Espace GC': st.session_state['cap_gc'] - (m_gc + r_impact),
                'Club École': m_ce,
                'Total Pénalités (50%)': r_impact
            })
        st.dataframe(pd.DataFrame(dash_data).style.format(subset=[c for c in pd.DataFrame(dash_data).columns if c != 'Équipe'], formatter=format_currency), use_container_width=True)

# --- TAB 2: SIMULATEUR ---
with tab2:
    if not st.session_state['historique'].empty:
        eq = st.selectbox("Équipe à simuler", sorted(st.session_state['historique']['Propriétaire'].unique()), key="sim_select")
        df_sim = st.session_state['historique'][st.session_state['historique']['Propriétaire'] == eq].copy().fillna(0)
        
        df_sim['Disp'] = df_sim['Joueur'].astype(str) + " (" + df_sim['Pos'].astype(str) + ") - " + df_sim['Salaire'].apply(format_currency)
        l_gc = df_sim[df_sim['Statut'] == "Grand Club"]['Disp'].tolist()
        l_ce = df_sim[df_sim['Statut'] == "Club École"]['Disp'].tolist()

        updated = sort_items([
            {'header': '🏙️ GRAND CLUB', 'items': [str(x) for x in l_gc]}, 
            {'header': '🏫 CLUB ÉCOLE', 'items': [str(x) for x in l_ce]}
        ], multi_containers=True, key=f"sort_{eq}")

        def parse_sal(items):
            return sum(int(str(i).split('-')[-1].replace('$', '').replace(' ', '').replace('\xa0', '').strip()) for i in items if '-' in str(i))
        
        m_gc_sim = parse_sal(updated[0]['items']) if updated else 0
        m_ce_sim = parse_sal(updated[1]['items']) if updated else 0
        r_impact = st.session_state['rachats'][st.session_state['rachats']['Propriétaire'] == eq]['Impact'].sum()

        st.divider()
        c1, c2, c3 = st.columns(3)
        c1.metric("Masse GC (+ Rachats)", format_currency(m_gc_sim + r_impact), delta=format_currency(st.session_state['cap_gc'] - (m_gc_sim + r_impact)))
        c2.metric("Masse Club École", format_currency(m_ce_sim), delta=format_currency(st.session_state['cap_ce'] - m_ce_sim))
        c3.metric("Pénalités Rachats", format_currency(r_impact))

# --- TAB 3: GESTION (RACHATS AVEC PÉNALITÉ 50%) ---
with tab3:
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("📉 Racheter un contrat (Pénalité 50%)")
        all_teams = sorted(st.session_state['historique']['Propriétaire'].unique())
        b_team = st.selectbox("Sélectionner l'équipe", all_teams, key="buyout_team_select")
        
        # Filtrer les joueurs de l'équipe choisie (GC et École)
        joueurs_equipe = st.session_state['historique'][st.session_state['historique']['Propriétaire'] == b_team]
        
        if not joueurs_equipe.empty:
            # Liste déroulante des joueurs avec leur salaire pour info
            dict_joueurs = {f"{row['Joueur']} ({row['Statut']} - {format_currency(row['Salaire'])})": row['Salaire'] 
                           for _, row in joueurs_equipe.iterrows()}
            
            selected_player_label = st.selectbox("Joueur à racheter", list(dict_joueurs.keys()))
            original_salary = dict_joueurs[selected_player_label]
            penalite = int(original_salary * 0.50)
            
            st.info(f"Salaire actuel: {format_currency(original_salary)}  \n**Pénalité calculée (50%): {format_currency(penalite)}**")
            
            if st.button("Confirmer le rachat"):
                player_name = selected_player_label.split(' (')[0]
                
                # 1. Ajouter aux rachats
                new_buyout = pd.DataFrame([{'Propriétaire': b_team, 'Joueur': player_name, 'Impact': penalite}])
                st.session_state['rachats'] = pd.concat([st.session_state['rachats'], new_buyout], ignore_index=True)
                st.session_state['rachats'].to_csv(BUYOUT_FILE, index=False)
                
                # 2. Supprimer du club (historique)
                st.session_state['historique'] = st.session_state['historique'][
                    ~((st.session_state['historique']['Joueur'] == player_name) & 
                      (st.session_state['historique']['Propriétaire'] == b_team))
                ]
                st.session_state['historique'].to_csv(DB_FILE, index=False)
                
                st.success(f"Rachat effectué pour {player_name}. Le joueur a été retiré de l'effectif.")
                st.rerun()
        else:
            st.write("Aucun joueur trouvé dans cette équipe.")

    with col2:
        st.subheader("🆕 Ajouter un Agent Libre (FA)")
        with st.form("fa_form"):
            f_team = st.selectbox("Équipe", all_teams)
            f_name = st.text_input("Nom complet")
            f_sal = st.number_input("Salaire annuel ($)", min_value=0, step=100000)
            f_pos = st.selectbox("Position", ["F", "D", "G"])
            f_stat = st.selectbox("Assignation", ["Grand Club", "Club École"])
            if st.form_submit_button("Ajouter à l'équipe"):
                new_fa = pd.DataFrame([{'Joueur': f_name, 'Salaire': f_sal, 'Statut': f_stat, 'Pos': f_pos, 'Propriétaire': f_team}])
                st.session_state['historique'] = pd.concat([st.session_state['historique'], new_fa], ignore_index=True)
                st.session_state['historique'].to_csv(DB_FILE, index=False)
                st.success(f"{f_name} ajouté !")
                st.rerun()

st.markdown("""<style>.stSortablesItem { background-color: #1E3A8A !important; color: white !important; padding: 8px !important; border-radius: 6px !important; }</style>""", unsafe_allow_html=True)
