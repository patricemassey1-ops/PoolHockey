import streamlit as st
import pandas as pd
import os
import glob
from datetime import datetime
import pytz

# --- CONFIGURATION DE LA PAGE ---
st.set_page_config(page_title="Gestionnaire Masse Salariale - Montréal 2025", layout="wide")

# --- CONFIGURATION DES FICHIERS ---
SAVE_FILE = "historique_masse_salariale.csv"
DOWNLOAD_PATH = os.path.expanduser("~/Downloads")
TIMEZONE = pytz.timezone("America/Toronto") 

# --- 1. CHARGEMENT / SAUVEGARDE ---
def charger_donnees():
    if os.path.exists(SAVE_FILE):
        return pd.read_csv(SAVE_FILE, encoding='utf-8-sig').to_dict('records')
    return []

def sauvegarder_donnees(donnees):
    df = pd.DataFrame(donnees)
    df.to_csv(SAVE_FILE, index=False, encoding='utf-8-sig')

def obtenir_heure_montreal():
    return datetime.now(TIMEZONE).strftime("%d/%m/%Y %H:%M")

if 'historique_salaires' not in st.session_state:
    st.session_state['historique_salaires'] = charger_donnees()

if 'last_uploaded_files' not in st.session_state:
    st.session_state['last_uploaded_files'] = {}

equipes = [
    "Canadiens Montréal", "Cracheurs Anonymes Lima", "Nordiques Québec", 
    "Prédateurs Nashville", "Red Wings Détroit", "Whalers Hartford"
]

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
            df.iloc[:, 5] = df.iloc[:, 5].astype(str).str.strip()
            mask = df.iloc[:, 5].str.contains("Min", case=False, na=False)
            col_h = df.loc[mask].iloc[:, 7].astype(str).str.replace(r'[ \$]', '', regex=True).str.replace(',', '.')
            # Calcul en milliers (ex: 1.55 M$ devient 1550)
            return pd.to_numeric(col_h, errors='coerce').fillna(0).sum() * 1000
    except: return None

# --- INTERFACE ---
st.header("🏒 Gestionnaire de la Masse Salariale du club école")
st.caption(f"Heure de Montréal : {obtenir_heure_montreal()} | Format : 1 550$")

tab1, tab2 = st.tabs(["⚡ Scan Dossier Downloads", "📂 Importation Individuelle"])

with tab1:
    if st.button("🔄 Lancer le Scan Automatique"):
        csv_files = glob.glob(os.path.join(DOWNLOAD_PATH, "*.csv"))
        date_mtl = obtenir_heure_montreal()
        for nom in equipes:
            mot_cle = nom.split()[0].lower() 
            f_trouve = next((f for f in csv_files if mot_cle in os.path.basename(f).lower()), None)
            if f_trouve:
                val = calculer_salaire(f_trouve)
                if val is not None:
                    # On formate déjà pour la sauvegarde (ex: "1 550$")
                    val_formate = f"{int(val):,}".replace(",", " ") + "$"
                    st.session_state['historique_salaires'].append({
                        "Date": date_mtl, 
                        "Équipe": nom, 
                        "Salaire Mineur": val_formate
                    })
        sauvegarder_donnees(st.session_state['historique_salaires'])
        st.rerun()

with tab2:
    for nom in equipes:
        c1, c2 = st.columns(2)
        c1.write(f"**{nom}**")
        up_file = c2.file_uploader(f"Uploader {nom}", type="csv", key=f"up_{nom}", label_visibility="collapsed")
        if up_file:
            file_id = f"{nom}_{up_file.name}_{up_file.size}"
            if st.session_state['last_uploaded_files'].get(nom) != file_id:
                val = calculer_salaire(up_file)
                if val is not None:
                    val_formate = f"{int(val):,}".replace(",", " ") + "$"
                    st.session_state['historique_salaires'].append({
                        "Date": obtenir_heure_montreal(), 
                        "Équipe": nom, 
                        "Salaire Mineur": val_formate
                    })
                    st.session_state['last_uploaded_files'][nom] = file_id
                    sauvegarder_donnees(st.session_state['historique_salaires'])
                    st.rerun()

st.divider()

if st.session_state['historique_salaires']:
    df_histo = pd.DataFrame(st.session_state['historique_salaires'])
    
    st.subheader("📊 État Actuel des Mineurs")
    derniers = df_histo.drop_duplicates(subset='Équipe', keep='last')
    
    m_cols = st.columns(3)
    for i, (_, row) in enumerate(derniers.iterrows()):
        m_cols[i % 3].metric(label=row['Équipe'], value=row['Salaire Mineur'], delta=row['Date'])

    st.divider()

    col_t, col_e = st.columns(2)
    with col_t:
        st.subheader("📜 Historique des Calculs")
    with col_e:
        # Exportation : contiendra exactement le format affiché (ex: 1 550$)
        csv_export = df_histo.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
        st.download_button(
            label="📥 Télécharger l'historique", 
            data=csv_export, 
            file_name=f"masse_salariale_mineurs.csv", 
            mime='text/csv'
        )

    df_ed = df_histo.copy()
    df_ed['Supprimer'] = False

    edited_df = st.data_editor(
        df_ed, 
        column_config={"Supprimer": st.column_config.CheckboxColumn("❌")}, 
        disabled=["Date", "Équipe", "Salaire Mineur"], 
        hide_index=True, 
        use_container_width=True, 
        key="editor_final"
    )

    if edited_df['Supprimer'].any():
        indices_keep = edited_df.index[~edited_df['Supprimer']].tolist()
        st.session_state['historique_salaires'] = [st.session_state['historique_salaires'][i] for i in indices_keep]
        sauvegarder_donnees(st.session_state['historique_salaires'])
        st.rerun()
