import streamlit as st
import pandas as pd
import io
import os
from datetime import datetime

st.set_page_config(page_title="Calculateur Fantrax 2025", layout="wide")

DB_FILE = "historique_fantrax_v3.csv"

# --- FONCTIONS DE CHARGEMENT / SAUVEGARDE ---
def charger_historique():
    if os.path.exists(DB_FILE):
        return pd.read_csv(DB_FILE)
    return pd.DataFrame()

def sauvegarder_historique(df):
    df.to_csv(DB_FILE, index=False)

if 'historique' not in st.session_state:
    st.session_state['historique'] = charger_historique()

st.title("🏒 Analyseur Fantrax : Suivi des Effectifs")

# --- CONFIGURATION DES PLAFONDS ---
col_cap1, col_cap2 = st.columns(2)
with col_cap1:
    CAP_GRAND_CLUB = st.number_input("Plafond Grand Club ($)", min_value=0, value=95500000, step=1000000)
with col_cap2:
    CAP_CLUB_ECOLE = st.number_input("Plafond Club École ($)", min_value=0, value=47750000, step=100000)

fichiers_telecharges = st.file_uploader("Importer des CSV Fantrax", type="csv", accept_multiple_files=True)

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
    # Horodatage précis pour l'ID unique
    now = datetime.now()
    horodatage = now.strftime("%d-%m %H:%M")
    timestamp_tri = now.timestamp() # Pour trier chronologiquement
    
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
                salary_val = pd.to_numeric(df_merged[c_salary].astype(str).replace(r'[\$,\s]', '', regex=True), errors='coerce').fillna(0) * 1000
                nom_base = fichier.name.replace('.csv', '')
                
                temp_df = pd.DataFrame({
                    'Joueur': df_merged[c_player], 
                    'Salaire': salary_val, 
                    'Statut': df_merged[c_status].apply(lambda x: "Club École" if "MIN" in str(x).upper() else "Grand Club"),
                    'Pos': df_merged[c_pos] if c_pos else "N/A", 
                    'Propriétaire': f"{nom_base} ({horodatage})",
                    'Équipe_Nom': nom_base,
                    'Date_Import': horodatage,
                    'Timestamp': timestamp_tri,
                    'pos_order': df_merged[c_pos].apply(pos_sort_order) if c_pos else 0
                })
                dfs_a_ajouter.append(temp_df)
        except Exception as e:
            st.error(f"Erreur avec {fichier.name}: {e}")

    if dfs_a_ajouter:
        st.session_state['historique'] = pd.concat([st.session_state['historique'], pd.concat(dfs_a_ajouter)], ignore_index=True)
        sauvegarder_historique(st.session_state['historique'])
        st.rerun()

# --- SIDEBAR GESTION ---
st.sidebar.header("⚙️ Options")
if not st.session_state['historique'].empty:
    eq_list = sorted(st.session_state['historique']['Propriétaire'].unique(), reverse=True)
    eq_suppr = st.sidebar.selectbox("Supprimer une version", ["-- Choisir --"] + eq_list)
    if st.sidebar.button("❌ Supprimer"):
        if eq_suppr != "-- Choisir --":
            st.session_state['historique'] = st.session_state['historique'][st.session_state['historique']['Propriétaire'] != eq_suppr]
            sauvegarder_historique(st.session_state['historique'])
            st.rerun()
    if st.sidebar.button("⚠️ Vider l'historique"):
        st.session_state['historique'] = pd.DataFrame()
        sauvegarder_historique(st.session_state['historique'])
        st.rerun()

# --- AFFICHAGE ---
if not st.session_state['historique'].empty:
    df_f = st.session_state['historique']

    # 1. RÉSUMÉ : Uniquement la version la plus récente de chaque équipe
    st.header("📊 Situation Actuelle (Derniers Imports)")
    
    # On trouve le timestamp maximum pour chaque équipe de base
    idx_recents = df_f.groupby('Équipe_Nom')['Timestamp'].transform(max) == df_f['Timestamp']
    df_recents = df_f[idx_recents]
    
    summary = df_recents.groupby(['Équipe_Nom', 'Statut'])['Salaire'].sum().unstack(fill_value=0).reset_index()
    for col in ['Grand Club', 'Club École']:
        if col not in summary.columns: summary[col] = 0

    st.dataframe(
        summary.style.format({'Grand Club': format_currency, 'Club École': format_currency})
        .applymap(lambda v: 'color: #00FF00;' if v <= CAP_GRAND_CLUB else 'color: red;', subset=['Grand Club'])
        .applymap(lambda v: 'color: #00FF00;' if v <= CAP_CLUB_ECOLE else 'color: red;', subset=['Club École']),
        use_container_width=True, hide_index=True
    )

    st.divider()

    # 2. DÉTAILS : Historique complet avec dates
    st.header("👤 Historique Complet des Effectifs")
    # Tri par date (plus récent en haut)
    versions = sorted(df_f['Propriétaire'].unique(), key=lambda x: df_f[df_f['Propriétaire']==x]['Timestamp'].iloc[0], reverse=True)
    
    for v in versions:
        with st.expander(f"📅 {v}"):
            c1, c2 = st.columns(2)
            df_v = df_f[df_f['Propriétaire'] == v]
            
            with c1:
                st.markdown("⭐ **Grand Club**")
                df_g = df_v[df_v['Statut'] == "Grand Club"].sort_values(['pos_order', 'Salaire'], ascending=[True, False])
                st.table(df_g[['Joueur', 'Pos', 'Salaire']].assign(Salaire=df_g['Salaire'].apply(format_currency)))
                m_g = df_g['Salaire'].sum()
                st.metric("Total", format_currency(m_g), delta=format_currency(CAP_GRAND_CLUB - m_g), delta_color="normal" if m_g <= CAP_GRAND_CLUB else "inverse")

            with c2:
                st.markdown("🎓 **Club École**")
                df_c = df_v[df_v['Statut'] == "Club École"].sort_values(['pos_order', 'Salaire'], ascending=[True, False])
                st.table(df_c[['Joueur', 'Pos', 'Salaire']].assign(Salaire=df_c['Salaire'].apply(format_currency)))
                m_c = df_c['Salaire'].sum()
                st.metric("Total", format_currency(m_c), delta=format_currency(CAP_CLUB_ECOLE - m_c), delta_color="normal" if m_c <= CAP_CLUB_ECOLE else "inverse")
else:
    st.info("Aucune donnée disponible.")
import streamlit as st
import pandas as pd
import io
import os
from datetime import datetime

st.set_page_config(page_title="Calculateur Fantrax 2025", layout="wide")

DB_FILE = "historique_fantrax_v2.csv"

# --- FONCTIONS DE CHARGEMENT / SAUVEGARDE ---
def charger_historique():
    if os.path.exists(DB_FILE):
        return pd.read_csv(DB_FILE)
    return pd.DataFrame()

def sauvegarder_historique(df):
    df.to_csv(DB_FILE, index=False)

# Initialisation de la session
if 'historique' not in st.session_state:
    st.session_state['historique'] = charger_historique()

st.title("🏒 Analyseur Fantrax : Historique par Date & Heure")

# --- CONFIGURATION DES PLAFONDS ---
col_cap1, col_cap2 = st.columns(2)
with col_cap1:
    CAP_GRAND_CLUB = st.number_input("Plafond Grand Club ($)", min_value=0, value=95500000, step=1000000)
with col_cap2:
    CAP_CLUB_ECOLE = st.number_input("Plafond Club École ($)", min_value=0, value=47750000, step=100000)

# --- IMPORTATION ---
fichiers_telecharges = st.file_uploader("Importer des CSV Fantrax", type="csv", accept_multiple_files=True)

def format_currency(val):
    if pd.isna(val): return "0 $"
    return f"{int(val):,}".replace(",", " ") + " $"

def pos_sort_order(pos_text):
    pos = str(pos_text).upper()
    if 'G' in pos: return 2
    if 'D' in pos: return 1
    return 0 # F

if fichiers_telecharges:
    dfs_a_ajouter = []
    # Générer le suffixe de date et heure une seule fois pour cette importation
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
                
                # Nom de l'équipe unique avec date et heure
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
        st.success(f"Importation réussie à {horodatage}")

# --- GESTION DE L'HISTORIQUE (SIDEBAR) ---
st.sidebar.header("⚙️ Gestion des données")
if not st.session_state['historique'].empty:
    # On trie pour avoir les plus récents en haut dans la sidebar
    equipes_dispo = sorted(st.session_state['historique']['Propriétaire'].unique(), reverse=True)
    eq_suppr = st.sidebar.selectbox("Supprimer une version spécifique", ["-- Choisir --"] + equipes_dispo)
    
    if st.sidebar.button("❌ Supprimer définitivement"):
        if eq_suppr != "-- Choisir --":
            st.session_state['historique'] = st.session_state['historique'][st.session_state['historique']['Propriétaire'] != eq_suppr]
            sauvegarder_historique(st.session_state['historique'])
            st.rerun()
    
    if st.sidebar.button("⚠️ Effacer tout l'historique"):
        st.session_state['historique'] = pd.DataFrame()
        sauvegarder_historique(st.session_state['historique'])
        st.rerun()

# --- AFFICHAGE ---
if not st.session_state['historique'].empty:
    df_f = st.session_state['historique']

    # 1. RÉSUMÉ GLOBAL
    st.header("📊 Résumé des Importations")
    summary = df_f.groupby(['Propriétaire', 'Statut'])['Salaire'].sum().unstack(fill_value=0).reset_index()
    for col in ['Grand Club', 'Club École']:
        if col not in summary.columns: summary[col] = 0

    st.dataframe(
        summary.style.format({'Grand Club': format_currency, 'Club École': format_currency})
        .applymap(lambda v: 'color: red;' if v > CAP_GRAND_CLUB else 'color: #00FF00;', subset=['Grand Club'])
        .applymap(lambda v: 'color: red;' if v > CAP_CLUB_ECOLE else 'color: #00FF00;', subset=['Club École']),
        use_container_width=True, hide_index=True
    )

    # 2. DÉTAILS PAR ÉQUIPE
    st.header("👤 Détails des Effectifs")
    # Affichage par ordre alphabétique inverse pour voir les plus récents en premier
    for eq in sorted(df_f['Propriétaire'].unique(), reverse=True):
        with st.expander(f"📂 {eq}"):
            c1, c2 = st.columns(2)
            df_e = df_f[df_f['Propriétaire'] == eq]
            
            with c1:
                st.markdown("⭐ **Grand Club**")
                df_g = df_e[df_e['Statut'] == "Grand Club"].sort_values(['pos_order', 'Salaire'], ascending=[True, False])
                st.table(df_g[['Joueur', 'Pos', 'Salaire']].assign(Salaire=df_g['Salaire'].apply(format_currency)))
                m_g = df_g['Salaire'].sum()
                st.metric("Masse", format_currency(m_g), delta=format_currency(CAP_GRAND_CLUB - m_g), delta_color="normal" if m_g <= CAP_GRAND_CLUB else "inverse")

            with c2:
                st.markdown("🎓 **Club École**")
                df_c = df_e[df_e['Statut'] == "Club École"].sort_values(['pos_order', 'Salaire'], ascending=[True, False])
                st.table(df_c[['Joueur', 'Pos', 'Salaire']].assign(Salaire=df_c['Salaire'].apply(format_currency)))
                m_c = df_c['Salaire'].sum()
                st.metric("Masse", format_currency(m_c), delta=format_currency(CAP_CLUB_ECOLE - m_c), delta_color="normal" if m_c <= CAP_CLUB_ECOLE else "inverse")
else:
    st.info("Aucun historique détecté. Importez vos fichiers CSV pour commencer.")
