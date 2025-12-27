import streamlit as st
import pandas as pd
import os
import glob
from datetime import datetime

st.set_page_config(page_title="Fantrax 2025 - Import Instantané", layout="wide")

st.header("🏒 Gestionnaire de Salaires Fantrax")

# --- 1. INITIALISATION ---
if 'historique_salaires' not in st.session_state:
    st.session_state['historique_salaires'] = []

# Pour éviter les doublons lors du chargement automatique des fichiers uploadés
if 'last_uploaded_files' not in st.session_state:
    st.session_state['last_uploaded_files'] = {}

download_path = os.path.expanduser("~/Downloads")
equipes = [
    "Canadiens Montréal", "Red Wings Détroit", "Nordiques Québec", 
    "Prédateurs Nashville", "Sénateurs Ottawa", "Cracheurs Anonymes Lima"
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
            col_h = df.loc[mask].iloc[:, 7].astype(str)
            col_h = col_h.str.replace(r'[ \$]', '', regex=True).str.replace(',', '.')
            return pd.to_numeric(col_h, errors='coerce').fillna(0).sum() * 1_000_000
    except: return None
    return None

# --- 2. SECTION IMPORTATION ---
tab1, tab2 = st.tabs(["⚡ Scan Automatique", "📂 Upload Manuel (Instantané)"])

with tab1:
    if st.button("🔄 Scanner le dossier Téléchargements"):
        csv_files = glob.glob(os.path.join(download_path, "*.csv"))
        date_now = datetime.now().strftime("%d/%m/%Y %H:%M")
        for nom in equipes:
            mot_cle = nom.split()[0].lower()
            f_trouve = next((f for f in csv_files if mot_cle in os.path.basename(f).lower()), None)
            if f_trouve:
                val = calculer_salaire(f_trouve)
                if val is not None:
                    st.session_state['historique_salaires'].append({"Date": date_now, "Équipe": nom, "Salaires Mineurs": val})
        st.rerun()

with tab2:
    for nom in equipes:
        c1, c2 = st.columns([2, 3])
        c1.markdown(f"**{nom}**")
        up_file = c2.file_uploader(f"Upload {nom}", type="csv", key=f"up_{nom}", label_visibility="collapsed")
        
        # AJOUT AUTOMATIQUE SANS BOUTON DE CONFIRMATION
        if up_file:
            # On vérifie si ce fichier a déjà été traité pour cette session pour éviter les boucles
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
                    st.rerun()

# --- 3. VUES ET HISTORIQUE ---
st.divider()
if st.session_state['historique_salaires']:
    # MÉTRIQUES
    df_histo = pd.DataFrame(st.session_state['historique_salaires'])
    derniers = df_histo.drop_duplicates(subset='Équipe', keep='last')
    st.subheader("📊 Derniers Salaires Mineurs Calculés")
    m_cols = st.columns(3)
    for i, (_, row) in enumerate(derniers.iterrows()):
        m_cols[i % 3].metric(label=row['Équipe'], value=f"{row['Salaires Mineurs']:,.0f} $", delta=row['Date'])

    # TABLEAU ÉDITABLE
    st.divider()
    st.subheader("📜 Historique (Cochez ❌ pour supprimer)")
    df_ed = df_histo.copy()
    df_ed['Supprimer'] = False
    df_ed['Salaires Mineurs'] = df_ed['Salaires Mineurs'].apply(lambda x: f"{x:,.0f} $")

    edited_df = st.data_editor(
        df_ed,
        column_config={"Supprimer": st.column_config.CheckboxColumn("❌")},
        disabled=["Date", "Équipe", "Salaires Mineurs"],
        hide_index=True, use_container_width=True, key="main_editor"
    )

    if edited_df['Supprimer'].any():
        indices_keep = edited_df.index[~edited_df['Supprimer']].tolist()
        st.session_state['historique_salaires'] = [st.session_state['historique_salaires'][i] for i in indices_keep]
        st.rerun()
else:
    st.info("Prêt pour l'importation. Déposez un fichier ou lancez un scan.")
