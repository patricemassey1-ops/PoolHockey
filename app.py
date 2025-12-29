import streamlit as st
import pandas as pd
import io
import os
from datetime import datetime

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
    
    # Correction: Assigner les onglets à des variables distinctes
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
        st.markdown("Utilisez le menu déroulant dans la colonne **`Statut`** pour changer l'affectation d'un joueur et voir l'impact sur le cap.")

        # 1. Sélection de l'équipe
        equipe_sim_choisie = st.selectbox("Sélectionner l'équipe à simuler", options=df_f['Propriétaire'].unique(), key='simulateur_equipe')
        
        df_sim = df_f[df_f['Propriétaire'] == equipe_sim_choisie].copy()
        
        # 2. Utilisation de st.data_editor pour permettre l'édition du statut
        df_sim = df_sim.sort_values(['pos_order', 'Statut', 'Salaire'], ascending=[True, False, False])
        
        edited_data = st.data_editor(
            df_sim[['Joueur', 'Pos', 'Salaire', 'Statut']],
            column_config={
                "Statut": st.column_config.SelectboxColumn(
                    "Statut",
                    help="Déplacer le joueur entre les clubs",
                    width="medium",
                    options=["Grand Club", "Club École"],
                    required=True,
                ),
                "Salaire": st.column_config.Column(format="%.0f $"),
            },
            hide_index=True,
            use_container_width=True,
            key=f'editor_{equipe_sim_choisie}'
        )

        # 3. Calculer les totaux simulés à partir des données éditées
        sim_g = edited_data[edited_data['Statut'] == "Grand Club"]['Salaire'].sum()
        sim_c = edited_data[edited_data['Statut'] == "Club École"]['Salaire'].sum()

        st.markdown("---")
        c1, c2 = st.columns(2)
        
        # Affichage des métriques de plafond simulées
        c1.metric(
            "Simulé: Grand Club", 
            format_currency(sim_g), 
            delta=format_currency(CAP_GRAND_CLUB - sim_g), 
            delta_color="normal" if sim_g <= CAP_GRAND_CLUB else "inverse"
        )
        c2.metric(
            "Simulé: Club École", 
            format_currency(sim_c), 
            delta=format_currency(CAP_CLUB_ECOLE - sim_c),
            delta_color="normal" if sim_c <= CAP_CLUB_ECOLE else "inverse"
        )

else:
    st.info("Importez un fichier CSV pour activer les fonctionnalités.")
