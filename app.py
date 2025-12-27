import streamlit as st
import pandas as pd
import io

st.set_page_config(page_title="Calculateur Fantrax 2025", layout="wide")

st.title("🏒 Analyseur Fantrax avec Historique")

# --- INITIALISATION DE L'HISTORIQUE ---
if 'historique_equipes' not in st.session_state:
    st.session_state['historique_equipes'] = pd.DataFrame()

# --- CONFIGURATION DES PLAFONDS ---
col_cap1, col_cap2 = st.columns(2)
with col_cap1:
    CAP_GRAND_CLUB = st.number_input("Plafond Grand Club ($)", min_value=0, value=95500000, step=1000000)
with col_cap2:
    CAP_CLUB_ECOLE = st.number_input("Plafond Club École ($)", min_value=0, value=47750000, step=100000)

# --- IMPORTATION ---
fichiers_telecharges = st.file_uploader("Importez vos fichiers CSV Fantrax", type="csv", accept_multiple_files=True)

def format_currency(val):
    if pd.isna(val): return "0 $"
    return f"{int(val):,}".replace(",", " ") + " $"

def pos_sort_order(pos_text):
    pos = str(pos_text).upper()
    if 'G' in pos: return 2
    if 'D' in pos: return 1
    return 0

# Traitement des fichiers importés
if fichiers_telecharges:
    nouvelles_donnees = []
    for fichier in fichiers_telecharges:
        try:
            content = fichier.getvalue().decode('utf-8-sig')
            lines = content.splitlines()

            def extract_table(lines, keyword):
                idx = next((i for i, l in enumerate(lines) if keyword in l), -1)
                if idx == -1: return pd.DataFrame()
                h_idx = next((i for i in range(idx + 1, len(lines)) if any(kw in lines[i] for kw in ["ID", "Player", "Salary"])), -1)
                if h_idx == -1: return pd.DataFrame()
                df = pd.read_csv(io.StringIO("\n".join(lines[h_idx:])), sep=None, engine='python', on_bad_lines='skip')
                if 'ID' in df.columns:
                    df = df[df['ID'].astype(str).str.strip().str.startswith(('0','1','2','3','4','5','6','7','8','9','*'))]
                return df

            df = pd.concat([extract_table(lines, 'Skaters'), extract_table(lines, 'Goalies')], ignore_index=True)
            
            c_player = next((c for c in df.columns if 'player' in c.lower() or 'joueur' in c.lower()), None)
            c_status = next((c for c in df.columns if 'status' in c.lower() or 'statut' in c.lower()), None)
            c_salary = next((c for c in df.columns if 'salary' in c.lower() or 'salaire' in c.lower()), None)
            c_pos = next((c for c in df.columns if 'pos' in c.lower() or 'eligible' in c.lower()), None)

            if c_status and c_salary and c_player:
                df[c_salary] = pd.to_numeric(df[c_salary].astype(str).replace(r'[\$,\s]', '', regex=True), errors='coerce').fillna(0) * 1000
                df['Catégorie'] = df[c_status].apply(lambda x: "Club École" if "MIN" in str(x).upper() else "Grand Club")
                
                temp_df = pd.DataFrame({
                    'Joueur': df[c_player], 'Salaire': df[c_salary], 'Statut': df['Catégorie'],
                    'Pos': df[c_pos] if c_pos else "N/A", 'Propriétaire': fichier.name.replace('.csv', ''),
                    'pos_order': 0
                })
                temp_df['pos_order'] = temp_df['Pos'].apply(pos_sort_order)
                nouvelles_donnees.append(temp_df)
        except Exception as e:
            st.error(f"Erreur avec {fichier.name}: {e}")

    if nouvelles_donnees:
        # Fusionner avec l'historique existant en évitant les doublons (écrase si même nom de fichier)
        df_new = pd.concat(nouvelles_donnees)
        if not st.session_state['historique_equipes'].empty:
            # On retire les anciennes versions des équipes que l'on vient d'importer
            noms_nouveaux = df_new['Propriétaire'].unique()
            historique_filtre = st.session_state['historique_equipes'][~st.session_state['historique_equipes']['Propriétaire'].isin(noms_nouveaux)]
            st.session_state['historique_equipes'] = pd.concat([historique_filtre, df_new])
        else:
            st.session_state['historique_equipes'] = df_new

# --- AFFICHAGE SI DONNÉES PRÉSENTES ---
if not st.session_state['historique_equipes'].empty:
    df_final = st.session_state['historique_equipes']

    # --- RÉSUMÉ ---
    st.header("📊 Résumé des Masses Salariales")
    summary = df_final.groupby(['Propriétaire', 'Statut'])['Salaire'].sum().unstack(fill_value=0).reset_index()
    for c in ['Grand Club', 'Club École']:
        if c not in summary.columns: summary[c] = 0

    def style_cap_grand(val):
        color = 'green' if val <= CAP_GRAND_CLUB else 'red'
        return f'color: {color}; font-weight: bold;'

    def style_cap_ecole(val):
        color = 'green' if val <= CAP_CLUB_ECOLE else 'red'
        return f'color: {color}; font-weight: bold;'

    st.dataframe(
        summary.style.format({'Grand Club': format_currency, 'Club École': format_currency})
        .applymap(style_cap_grand, subset=['Grand Club'])
        .applymap(style_cap_ecole, subset=['Club École']),
        use_container_width=True, hide_index=True
    )

    st.divider()

    # --- GESTION DE L'HISTORIQUE (Suppression) ---
    st.sidebar.header("⚙️ Gérer l'historique")
    equipes_dispo = sorted(df_final['Propriétaire'].unique())
    equipe_a_supprimer = st.sidebar.selectbox("Sélectionner une équipe à retirer", ["-- Choisir --"] + equipes_dispo)
    
    if st.sidebar.button("❌ Supprimer l'équipe"):
        if equipe_a_supprimer != "-- Choisir --":
            st.session_state['historique_equipes'] = df_final[df_final['Propriétaire'] != equipe_a_supprimer]
            st.rerun()

    # --- DÉTAILS PAR ÉQUIPE ---
    st.header("👤 Détails des Effectifs")
    for eq in equipes_dispo:
        with st.expander(f"📂 Équipe : {eq}"):
            col_grand, col_ecole = st.columns(2)
            df_eq = df_final[df_final['Propriétaire'] == eq]
            
            with col_grand:
                st.subheader("⭐ Grand Club")
                df_gc = df_eq[df_eq['Statut'] == 'Grand Club'].sort_values(['pos_order', 'Salaire'], ascending=[True, False])
                st.table(df_gc[['Joueur', 'Pos', 'Salaire']].assign(Salaire=df_gc['Salaire'].apply(format_currency)))
                
                m_gc = df_gc['Salaire'].sum()
                color_gc = "normal" if m_gc <= CAP_GRAND_CLUB else "inverse"
                st.metric("Masse Grand Club", format_currency(m_gc), delta=format_currency(CAP_GRAND_CLUB - m_gc), delta_color=color_gc)

            with col_ecole:
                st.subheader("🎓 Club École")
                df_ce = df_eq[df_eq['Statut'] == 'Club École'].sort_values(['pos_order', 'Salaire'], ascending=[True, False])
                st.table(df_ce[['Joueur', 'Pos', 'Salaire']].assign(Salaire=df_ce['Salaire'].apply(format_currency)))
                
                m_ce = df_ce['Salaire'].sum()
                color_ce = "normal" if m_ce <= CAP_CLUB_ECOLE else "inverse"
                st.metric("Masse Club École", format_currency(m_ce), delta=format_currency(CAP_CLUB_ECOLE - m_ce), delta_color=color_ce)
else:
    st.info("En attente de fichiers CSV pour analyse...")
