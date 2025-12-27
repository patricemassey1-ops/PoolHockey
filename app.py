import streamlit as st
import pandas as pd
import io
import os

st.set_page_config(page_title="Calculateur Fantrax 2025", layout="wide")

DB_FILE = "historique_fantrax.csv"

# --- FONCTIONS DE CHARGEMENT / SAUVEGARDE ---
def charger_historique():
    if os.path.exists(DB_FILE):
        try:
            return pd.read_csv(DB_FILE)
        except:
            return pd.DataFrame()
    return pd.DataFrame()

def sauvegarder_historique(df):
    df.to_csv(DB_FILE, index=False)

# Initialisation de la session
if 'historique' not in st.session_state:
    st.session_state['historique'] = charger_historique()

st.title("🏒 Analyseur Fantrax : Grand Club & Club École")

# --- CONFIGURATION DES PLAFONDS ---
col_cap1, col_cap2 = st.columns(2)
with col_cap1:
    CAP_GRAND_CLUB = st.number_input("Plafond Grand Club ($)", min_value=0, value=95500000, step=1000000)
with col_cap2:
    CAP_CLUB_ECOLE = st.number_input("Plafond Club École ($)", min_value=0, value=47750000, step=100000)

# --- IMPORTATION ---
fichiers_telecharges = st.file_uploader("Importer des nouveaux CSV", type="csv", accept_multiple_files=True)

def format_currency(val):
    if pd.isna(val): return "0 $"
    return f"{int(val):,}".replace(",", " ") + " $"

def pos_sort_order(pos_text):
    pos = str(pos_text).upper()
    if 'G' in pos: return 2
    if 'D' in pos: return 1
    return 0

if fichiers_telecharges:
    dfs_a_ajouter = []
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
                
                temp_df = pd.DataFrame({
                    'Joueur': df_merged[c_player], 'Salaire': df_merged[c_salary], 'Statut': df_merged['Catégorie'],
                    'Pos': df_merged[c_pos] if c_pos else "N/A", 'Propriétaire': fichier.name.replace('.csv', ''),
                    'pos_order': df_merged[c_pos].apply(pos_sort_order) if c_pos else 0
                })
                dfs_a_ajouter.append(temp_df)
        except Exception as e:
            st.error(f"Erreur avec {fichier.name}: {e}")

    if dfs_a_ajouter:
        df_new = pd.concat(dfs_a_ajouter)
        hist_actuel = st.session_state['historique']
        
        # REMPLACER LES DOUBLONS (L'importation écrase la précédente de la même équipe)
        noms_nouveaux = df_new['Propriétaire'].unique()
        if not hist_actuel.empty:
            hist_actuel = hist_actuel[~hist_actuel['Propriétaire'].isin(noms_nouveaux)]
            
        st.session_state['historique'] = pd.concat([hist_actuel, df_new], ignore_index=True)
        sauvegarder_historique(st.session_state['historique'])
        st.rerun()

# --- GESTION DE L'HISTORIQUE (SIDEBAR) ---
st.sidebar.header("⚙️ Gestion des données")
if not st.session_state['historique'].empty:
    equipes_dispo = sorted(st.session_state['historique']['Propriétaire'].unique())
    eq_suppr = st.sidebar.selectbox("Retirer une équipe de l'historique", ["-- Choisir --"] + equipes_dispo)
    
    if st.sidebar.button("❌ Supprimer définitivement"):
        if eq_suppr != "-- Choisir --":
            st.session_state['historique'] = st.session_state['historique'][st.session_state['historique']['Propriétaire'] != eq_suppr]
            sauvegarder_historique(st.session_state['historique'])
            st.rerun()

# --- AFFICHAGE ---
if not st.session_state['historique'].empty:
    df_f = st.session_state['historique']

    # 1. RÉSUMÉ
    st.header("📊 Résumé Global")
    summary = df_f.groupby(['Propriétaire', 'Statut'])['Salaire'].sum().unstack(fill_value=0).reset_index()
    for col in ['Grand Club', 'Club École']:
        if col not in summary.columns: summary[col] = 0

    st.dataframe(
        summary.style.format({'Grand Club': format_currency, 'Club École': format_currency})
        .applymap(lambda v: 'color: #00FF00;' if v <= CAP_GRAND_CLUB else 'color: red;', subset=['Grand Club'])
        .applymap(lambda v: 'color: #00FF00;' if v <= CAP_CLUB_ECOLE else 'color: red;', subset=['Club École']),
        use_container_width=True, hide_index=True
    )

    # 2. DÉTAILS
    st.header("👤 Détails par Équipe")
    for eq in sorted(df_f['Propriétaire'].unique()):
        with st.expander(f"📂 Effectif : {eq}"):
            c1, c2 = st.columns(2)
            df_e = df_f[df_f['Propriétaire'] == eq]
            
            with c1:
                st.markdown("⭐ **Grand Club**")
                df_g = df_e[df_e['Statut'] == "Grand Club"].sort_values(['pos_order', 'Salaire'], ascending=[True, False])
                st.table(df_g[['Joueur', 'Pos', 'Salaire']].assign(Salaire=df_g['Salaire'].apply(format_currency)))
                m_g = df_g['Salaire'].sum()
                st.metric("Total", format_currency(m_g), delta=format_currency(CAP_GRAND_CLUB - m_g), delta_color="normal" if m_g <= CAP_GRAND_CLUB else "inverse")

            with c2:
                st.markdown("🎓 **Club École**")
                df_c = df_e[df_e['Statut'] == "Club École"].sort_values(['pos_order', 'Salaire'], ascending=[True, False])
                st.table(df_c[['Joueur', 'Pos', 'Salaire']].assign(Salaire=df_c['Salaire'].apply(format_currency)))
                m_c = df_c['Salaire'].sum()
                st.metric("Total", format_currency(m_c), delta=format_currency(CAP_CLUB_ECOLE - m_c), delta_color="normal" if m_c <= CAP_CLUB_ECOLE else "inverse")
else:
    st.info("Aucune donnée dans l'historique. Importez des fichiers CSV pour commencer.")
