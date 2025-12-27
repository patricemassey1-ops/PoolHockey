import streamlit as st
import pandas as pd
import os
import glob
from datetime import datetime

# --- CONFIGURATION DE LA PAGE ---
st.set_page_config(page_title="Gestionnaire Masse Salariale - Fantrax 2025", layout="wide")

# --- CONFIGURATION DES FICHIERS ---
SAVE_FILE = "historique_masse_salariale.csv"
DOWNLOAD_PATH = os.path.expanduser("~/Downloads")

# --- 1. CHARGEMENT / SAUVEGARDE DES DONNÉES PERMANENTES ---
def charger_donnees():
    if os.path.exists(SAVE_FILE):
        return pd.read_csv(SAVE_FILE).to_dict('records')
    return []

def sauvegarder_donnees(donnees):
    df = pd.DataFrame(donnees)
    df.to_csv(SAVE_FILE, index=False)

# Initialisation de la session avec les données du fichier local
if 'historique_salaires' not in st.session_state:
    st.session_state['historique_salaires'] = charger_donnees()

if 'last_uploaded_files' not in st.session_state:
    st.session_state['last_uploaded_files'] = {}

equipes = [
    "Canadiens Montréal", "Red Wings Détroit", "Nordiques Québec", 
    "Prédateurs Nashville", "Whalers Hartford", "Cracheurs Anonymes Lima"
]

# --- 2. FONCTION DE CALCUL ROBUSTE ---
def calculer_salaire(file_source):
    try:
        df = None
        for sep in [',', ';']:
            for enc in ['utf-8', 'latin1']:
                try:
                    if isinstance(file_source, str):
                        temp_df = pd.read_csv(file_source, sep=sep, skiprows=1, on_bad_lines='skip', engine='python', encoding=enc)
                    else:
                        file_source.seek(0)
                        temp_df = pd.read_csv(file_source, sep=sep, skiprows=1, on_bad_lines='skip', engine='python', encoding=enc)
                    if temp_df.shape[1] >= 8:
                        df = temp_df
                        break
                except: continue
            if df is not None: break
        if df is not None:
            # Filtre Colonne F ('Min') et Somme Colonne H
            df.iloc[:, 5] = df.iloc[:, 5].astype(str).str.strip()
            mask = df.iloc[:, 5].str.contains("Min", case=False, na=False)
            col_h = df.loc[mask].iloc[:, 7].astype(str).str.replace(r'[ \$]', '', regex=True).str.replace(',', '.')
            return pd.to_numeric(col_h, errors='coerce').fillna(0).sum() * 1_000_000
    except: return None

# --- 3. INTERFACE UTILISATEUR ---
st.header("🏒 Gestionnaire de la Masse Salariale du club école")
st.caption("Calcul des salaires (Millions $) | Début à la ligne 2 | Sauvegarde automatique")

tab1, tab2 = st.tabs(["⚡ Scan Dossier Downloads", "📂 Importation Individuelle"])

with tab1:
    if st.button("🔄 Lancer le Scan Automatique"):
        csv_files = glob.glob(os.path.join(DOWNLOAD_PATH, "*.csv"))
        date_now = datetime.now().strftime("%d/%m/%Y %H:%M")
        for nom in equipes:
            mot_cle = nom.split()[0].lower()
            f_trouve = next((f for f in csv_files if mot_cle in os.path.basename(f).lower()), None)
            if f_trouve:
                val = calculer_salaire(f_trouve)
                if val is not None:
                    st.session_state['historique_salaires'].append({"Date": date_now, "Équipe": nom, "Salaires Mineurs": val})
        sauvegarder_donnees(st.session_state['historique_salaires'])
        st.rerun()

with tab2:
    for nom in equipes:
        c1, c2 = st.columns([1, 1])
        c1.write(f"**{nom}**")
        up_file = c2.file_uploader(f"Uploader {nom}", type="csv", key=f"up_{nom}", label_visibility="collapsed")
        if up_file:
            file_id = f"{nom}_{up_file.name}_{up_file.size}"
            if st.session_state['last_uploaded_files'].get(nom) != file_id:
                val = calculer_salaire(up_file)
                if val is not None:
                    st.session_state['historique_salaires'].append({
                        "Date": datetime.now().strftime("%d/%m/%Y %H:%M"), 
                        "Équipe": nom, 
                        "Salaires Mineurs": val
                    })
                    st.session_state['last_uploaded_files'][nom] = file_id
                    sauvegarder_donnees(st.session_state['historique_salaires'])
                    st.rerun()

# --- 4. AFFICHAGE ET HISTORIQUE ---
st.divider()
if st.session_state['historique_salaires']:
    df_histo = pd.DataFrame(st.session_state['historique_salaires'])
    
    # Vue Résumé (Dernière valeur pour chaque équipe)
    st.subheader("📊 État Actuel de la Masse Salariale")
    derniers = df_histo.drop_duplicates(subset='Équipe', keep='last')
    m_cols = st.columns(3)
    for i, (_, row) in enumerate(derniers.iterrows()):
        m_cols[i % 3].metric(label=row['Équipe'], value=f"{row['Salaires Mineurs']:,.0f} $", delta=row['Date'])

    # Tableau Historique avec bouton de suppression
    st.subheader("📜 Historique des Calculs")
    df_ed = df_histo.copy()
    df_ed['Supprimer'] = False
    df_ed['Salaires Mineurs'] = df_ed['Salaires Mineurs'].apply(lambda x: f"{x:,.0f} $")

    edited_df = st.data_editor(
        df_ed, 
        column_config={"Supprimer": st.column_config.CheckboxColumn("❌")}, 
        disabled=["Date", "Équipe", "Salaires Mineurs"], 
        hide_index=True, 
        use_container_width=True, 
        key="editor_final"
    )

    # Suppression individuelle
    if edited_df['Supprimer'].any():
        indices_keep = edited_df.index[~edited_df['Supprimer']].tolist()
        st.session_state['historique_salaires'] = [st.session_state['historique_salaires'][i] for i in indices_keep]
        sauvegarder_donnees(st.session_state['historique_salaires'])
        st.rerun()

    if st.sidebar.button("⚠️ Vider toute la base de données"):
        if os.path.exists(SAVE_FILE): os.remove(SAVE_FILE)
        st.session_state['historique_salaires'] = []
        st.rerun()
else:
    st.info("Aucune donnée enregistrée dans l'historique permanent.")
