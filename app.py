import streamlit as st
import pandas as pd
import io
import os
from datetime import datetime
from streamlit_sortables import sort_items

st.set_page_config(page_title="Calculateur Fantrax 2025", layout="wide")

DB_FILE = "historique_fantrax_v2.csv"

# --- FONCTIONS ---
def charger_historique():
    if os.path.exists(DB_FILE):
        return pd.read_csv(DB_FILE)
    return pd.DataFrame()

def sauvegarder_historique(df):
    df.to_csv(DB_FILE, index=False)

def format_currency(val):
    if pd.isna(val): return "0 $"
    return f"{int(val):,}".replace(",", " ") + " $"

def pos_sort_order(pos_text):
    pos = str(pos_text).upper()
    if 'G' in pos: return 2
    if 'D' in pos: return 1
    return 0 

if 'historique' not in st.session_state:
    st.session_state['historique'] = charger_historique()

st.title("🏒 Analyseur Fantrax 2025")

# --- BARRE LATÉRALE ---
st.sidebar.header("⚙️ Configuration")
CAP_GRAND_CLUB = st.sidebar.number_input("Plafond Grand Club ($)", value=95500000, step=500000)
CAP_CLUB_ECOLE = st.sidebar.number_input("Plafond Club École ($)", value=47750000, step=100000)

st.sidebar.markdown("---")
st.sidebar.header("💸 Rachats (Buyouts)")
st.sidebar.info("Le salaire saisi sera soustrait de la masse salariale.")

with st.sidebar.expander("Rachat Grand Club"):
    nom_buyout_gc = st.text_input("Nom du joueur (GC)", key="nbgc")
    montant_buyout_gc = st.number_input("Montant à déduire (GC)", value=0, step=50000, key="mbgc")

with st.sidebar.expander("Rachat Club École"):
    nom_buyout_ce = st.text_input("Nom du joueur (CE)", key="nbce")
    montant_buyout_ce = st.number_input("Montant à déduire (CE)", value=0, step=50000, key="mbce")

# --- LOGIQUE D'IMPORTATION ---
fichiers_telecharges = st.file_uploader("Importer des CSV Fantrax", type="csv", accept_multiple_files=True)
if fichiers_telecharges:
    dfs_a_ajouter = []
    horodatage = datetime.now().strftime("%d-%m %H:%M")
    for fichier in fichiers_telecharges:
        try:
            content = fichier.getvalue().decode('utf-8-sig')
            lines = content.splitlines()
            def extract_table(lines, keyword):
                idx = next((i for i, l in enumerate(lines) if keyword in l), -1)
                if idx == -1: return pd.DataFrame()
                h_idx = next((i for i in range(idx + 1, len(lines)) if any(kw in lines[i] for kw in ["ID", "Player", "Salary"])), -1)
                if h_idx == -1: return pd.DataFrame()
                df_raw = pd.read_csv(io.StringIO("\n".join(lines[h_idx:])), sep=None, engine='python', on_bad_lines='skip')
                if 'ID' in df_raw.columns:
                    df_raw = df_raw[df_raw['ID'].astype(str).str.strip().str.startswith(('0','1','2','3','4','5','6','7','8','9','*'))]
                return df_raw
            df_merged = pd.concat([extract_table(lines, 'Skaters'), extract_table(lines, 'Goalies')], ignore_index=True)
            c_player = next((c for c in df_merged.columns if 'player' in c.lower() or 'joueur' in c.lower()), None)
            c_status = next((c for c in df_merged.columns if 'status' in c.lower() or 'statut' in c.lower()), None)
            c_salary = next((c for c in df_merged.columns if 'salary' in c.lower() or 'salaire' in c.lower()), None)
            c_pos = next((c for c in df_merged.columns if 'pos' in c.lower() or 'eligible' in c.lower()), None)
            if c_status and c_salary and c_player:
                df_merged[c_salary] = pd.to_numeric(df_merged[c_salary].astype(str).replace(r'[\$,\s]', '', regex=True), errors='coerce').fillna(0) * 1000
                df_merged['Catégorie'] = df_merged[c_status].apply(lambda x: "Club École" if "MIN" in str(x).upper() else "Grand Club")
                nom_equipe_unique = f"{fichier.name.replace('.csv', '')} ({horodatage})"
                temp_df = pd.DataFrame({
                    'Joueur': df_merged[c_player], 'Salaire': df_merged[c_salary], 'Statut': df_merged['Catégorie'],
                    'Pos': df_merged[c_pos] if c_pos else "N/A", 'Propriétaire': nom_equipe_unique,
                    'pos_order': df_merged[c_pos].apply(pos_sort_order) if c_pos else 0
                })
                dfs_a_ajouter.append(temp_df)
        except Exception as e:
            st.error(f"Erreur : {e}")
    if dfs_a_ajouter:
        st.session_state['historique'] = pd.concat([st.session_state['historique'], pd.concat(dfs_a_ajouter)], ignore_index=True)
        sauvegarder_historique(st.session_state['historique'])
        st.success("Importation réussie")

# --- AFFICHAGE PRINCIPAL ---
if not st.session_state['historique'].empty:
    df_f = st.session_state['historique']
    
    tab1, tab2 = st.tabs(["📊 Tableau de Bord", "⚖️ Simulateur Avancé"]) 

    with tab1:
        st.header("Résumé des Masses Salariales")
        summary = df_f.groupby(['Propriétaire', 'Statut'])['Salaire'].sum().unstack(fill_value=0).reset_index()
        for col in ['Grand Club', 'Club École']:
            if col not in summary.columns: summary[col] = 0
        st.dataframe(summary.style.format({'Grand Club': format_currency, 'Club École': format_currency}), use_container_width=True)

        st.header("Détails des Effectifs")
        for eq in sorted(df_f['Propriétaire'].unique(), reverse=True):
            with st.expander(f"📂 {eq}"):
                col_a, col_b = st.columns(2)
                df_e = df_f[df_f['Propriétaire'] == eq]
                with col_a:
                    st.write("**Grand Club**")
                    st.table(df_e[df_e['Statut'] == "Grand Club"][['Joueur', 'Salaire']].assign(Salaire=lambda x: x['Salaire'].apply(format_currency)))
                with col_b:
                    st.write("**Club École**")
                    st.table(df_e[df_e['Statut'] == "Club École"][['Joueur', 'Salaire']].assign(Salaire=lambda x: x['Salaire'].apply(format_currency)))

    with tab2:
        st.header("🔄 Outil de Transfert Interactif")
        equipe_sim_choisie = st.selectbox("Sélectionner l'équipe à simuler", options=df_f['Propriétaire'].unique(), key='simulateur_equipe')
        
        df_sim = df_f[df_f['Propriétaire'] == equipe_sim_choisie].copy()
        
        list_grand_club = [f"{row['Joueur']} ({format_currency(row['Salaire'])})" for _, row in df_sim[df_sim['Statut'] == "Grand Club"].iterrows()]
        list_club_ecole = [f"{row['Joueur']} ({format_currency(row['Salaire'])})" for _, row in df_sim[df_sim['Statut'] == "Club École"].iterrows()]

        st.info("💡 Glissez-déposez les joueurs. Les rachats saisis dans la barre latérale sont déduits automatiquement.")
        
        sort_data = [
            {'header': '🏙️ GRAND CLUB', 'items': list_grand_club},
            {'header': '🏫 CLUB ÉCOLE', 'items': list_club_ecole}
        ]

        updated_sort = sort_items(sort_data, multi_containers=True, direction='horizontal')

        def extract_salary(player_list):
            total = 0
            for item in player_list:
                try:
                    s_str = item.split('(')[-1].replace('$', '').replace(' ', '').replace(')', '')
                    total += int(s_str)
                except: continue
            return total

        # Calcul des masses avec déduction des rachats
        sim_g = extract_salary(updated_sort[0]['items']) - montant_buyout_gc
        sim_c = extract_salary(updated_sort[1]['items']) - montant_buyout_ce

        st.markdown("---")
        c1, c2 = st.columns(2)
        
        c1.metric(
            "Masse Grand Club", 
            format_currency(max(0, sim_g)), 
            delta=format_currency(CAP_GRAND_CLUB - sim_g), 
            delta_color="normal" if sim_g <= CAP_GRAND_CLUB else "inverse"
        )
        if montant_buyout_gc > 0:
            c1.caption(f"⚠️ Dont rachat : {nom_buyout_gc} (-{format_currency(montant_buyout_gc)})")

        c2.metric(
            "Masse Club École", 
            format_currency(max(0, sim_c)), 
            delta=format_currency(CAP_CLUB_ECOLE - sim_c),
            delta_color="normal" if sim_c <= CAP_CLUB_ECOLE else "inverse"
        )
        if montant_buyout_ce > 0:
            c2.caption(f"⚠️ Dont rachat : {nom_buyout_ce} (-{format_currency(montant_buyout_ce)})")

        st.markdown("""
            <style>
            .stSortablesItem { background-color: #1E3A8A !important; color: white !important; border-radius: 5px !important; padding: 8px !important; margin-bottom: 5px !important; }
            </style>
            """, unsafe_allow_html=True)
else:
    st.info("Importez un fichier CSV pour activer les fonctionnalités.")
