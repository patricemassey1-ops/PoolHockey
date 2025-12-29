import streamlit as st
import pandas as pd
import io
import os
from datetime import datetime
import plotly.express as px  # New: requires 'pip install plotly'

st.set_page_config(page_title="Calculateur Fantrax 2025", layout="wide")

DB_FILE = "historique_fantrax_v2.csv"

# --- FUNCTIONS ---
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

# Initialisation
if 'historique' not in st.session_state:
    st.session_state['historique'] = charger_historique()

st.title("🏒 Analyseur Fantrax Pro : 2025")

# --- SIDEBAR: CONFIG & EXPORT ---
st.sidebar.header("⚙️ Configuration")
CAP_GRAND_CLUB = st.sidebar.number_input("Plafond Grand Club ($)", value=95500000, step=500000)
CAP_CLUB_ECOLE = st.sidebar.number_input("Plafond Club École ($)", value=47750000, step=100000)

if not st.session_state['historique'].empty:
    st.sidebar.markdown("---")
    st.sidebar.header("💾 Exportation")
    # Export to Excel
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
        st.session_state['historique'].to_excel(writer, index=False, sheet_name='Data')
    st.sidebar.download_button(label="📥 Télécharger l'historique (Excel)", data=buffer, file_name=f"fantrax_export_{datetime.now().strftime('%Y%m%d')}.xlsx")

# --- IMPORTATION ---
with st.expander("📤 Importer de nouveaux fichiers CSV Fantrax"):
    fichiers_telecharges = st.file_uploader("Fichiers CSV", type="csv", accept_multiple_files=True)
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
                        'Joueur': df_merged[c_player], 
                        'Salaire': df_merged[c_salary], 
                        'Statut': df_merged['Catégorie'],
                        'Pos': df_merged[c_pos] if c_pos else "N/A", 
                        'Propriétaire': nom_equipe_unique,
                        'pos_order': df_merged[c_pos].apply(pos_sort_order) if c_pos else 0
                    })
                    dfs_a_ajouter.append(temp_df)
            except Exception as e:
                st.error(f"Erreur avec {fichier.name}: {e}")

        if dfs_a_ajouter:
            df_new = pd.concat(dfs_a_ajouter)
            st.session_state['historique'] = pd.concat([st.session_state['historique'], df_new], ignore_index=True)
            sauvegarder_historique(st.session_state['historique'])
            st.success("Données ajoutées !")

# --- MAIN INTERFACE ---
if not st.session_state['historique'].empty:
    tabs = st.tabs(["📊 Tableau de Bord", "⚖️ Simulateur de Mouvements", "📜 Historique & Gestion"])

    # TAB 1: DASHBOARD
    with tabs[0]:
        df_f = st.session_state['historique']
        summary = df_f.groupby(['Propriétaire', 'Statut'])['Salaire'].sum().unstack(fill_value=0).reset_index()
        for col in ['Grand Club', 'Club École']:
            if col not in summary.columns: summary[col] = 0
        
        st.subheader("État des Masses Salariales")
        st.dataframe(
            summary.style.format({'Grand Club': format_currency, 'Club École': format_currency})
            .applymap(lambda v: 'background-color: #721c24;' if v > CAP_GRAND_CLUB else 'background-color: #155724;', subset=['Grand Club'])
            .applymap(lambda v: 'background-color: #721c24;' if v > CAP_CLUB_ECOLE else 'background-color: #155724;', subset=['Club École']),
            use_container_width=True, hide_index=True
        )

        fig = px.bar(summary, x='Propriétaire', y=['Grand Club', 'Club École'], 
                     title="Répartition des Salaires par Équipe", barmode='group',
                     color_discrete_map={'Grand Club': '#1f77b4', 'Club École': '#ff7f0e'})
        st.plotly_chart(fig, use_container_width=True)

    # TAB 2: SIMULATOR (THE NEW FUNCTIONALITY)
    with tabs[1]:
        st.subheader("🔄 Simulateur de Changement de Statut")
        equipe_sim = st.selectbox("Sélectionner l'équipe à tester", options=df_f['Propriétaire'].unique())
        
        df_sim = df_f[df_f['Propriétaire'] == equipe_sim].copy()
        
        st.info("Cochez les joueurs pour les déplacer (Grand Club <-> Club École) et voir l'impact immédiat.")
        
        # Multiselect to move players
        players_to_move = st.multiselect("Sélectionner des joueurs à déplacer", options=df_sim['Joueur'].tolist())
        
        # Apply logic for simulation
        df_sim['Statut_Simulé'] = df_sim.apply(
            lambda x: ("Club École" if x['Statut'] == "Grand Club" else "Grand Club") 
            if x['Joueur'] in players_to_move else x['Statut'], axis=1
        )

        sim_g = df_sim[df_sim['Statut_Simulé'] == "Grand Club"]['Salaire'].sum()
        sim_c = df_sim[df_sim['Statut_Simulé'] == "Club École"]['Salaire'].sum()

        c1, c2 = st.columns(2)
        c1.metric("Simulé: Grand Club", format_currency(sim_g), delta=format_currency(CAP_GRAND_CLUB - sim_g))
        c2.metric("Simulé: Club École", format_currency(sim_c), delta=format_currency(CAP_CLUB_ECOLE - sim_c))
        
        st.table(df_sim[df_sim['Joueur'].isin(players_to_move)][['Joueur', 'Statut', 'Statut_Simulé', 'Salaire']])

    # TAB 3: MANAGEMENT
    with tabs[2]:
        # Reuse your existing expander logic here
        for eq in sorted(df_f['Propriétaire'].unique(), reverse=True):
            with st.expander(f"📂 {eq}"):
                # [Your existing display code...]
                st.write(f"Détails complets pour {eq}")
                if st.button(f"Supprimer {eq}", key=eq):
                    st.session_state['historique'] = st.session_state['historique'][st.session_state['historique']['Propriétaire'] != eq]
                    sauvegarder_historique(st.session_state['historique'])
                    st.rerun()

else:
    st.info("Importez un fichier CSV pour activer les fonctionnalités.")
