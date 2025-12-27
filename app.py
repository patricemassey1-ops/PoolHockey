import streamlit as st
import pandas as pd
import os
import glob
from datetime import datetime

st.set_page_config(page_title="Fantrax 2025 - Vue Complète", layout="wide")

st.header("🏒 Suivi des Salaires Mineurs (2025)")

# --- 1. INITIALISATION ---
if 'historique_salaires' not in st.session_state:
    st.session_state['historique_salaires'] = []

download_path = os.path.expanduser("~/Downloads")

equipes = [
    "Canadiens Montréal", "Red Wings Détroit", "Nordiques Québec", 
    "Prédateurs Nashville", "Sénateurs Ottawa", "Cracheurs Anonymes Lima"
]

def calculer_salaire(file_path):
    try:
        df = None
        for sep in [',', ';']:
            for enc in ['utf-8', 'latin1']:
                try:
                    # Début à la ligne 2 (skiprows=1)
                    temp_df = pd.read_csv(file_path, sep=sep, skiprows=1, on_bad_lines='skip', engine='python', encoding=enc)
                    if temp_df.shape[1] >= 8:
                        df = temp_df
                        break
                except:
                    continue
            if df is not None: break

        if df is not None:
            df.iloc[:, 5] = df.iloc[:, 5].astype(str).str.strip()
            mask = df.iloc[:, 5].str.contains("Min", case=False, na=False)
            col_h = df.loc[mask].iloc[:, 7].astype(str)
            col_h = col_h.str.replace(r'[ \$]', '', regex=True).str.replace(',', '.')
            return pd.to_numeric(col_h, errors='coerce').fillna(0).sum() * 1_000_000
    except:
        return None
    return None

# --- 2. ACTIONS (BOUTONS) ---
col_btn1, col_btn2 = st.columns(2)

with col_btn1:
    if st.button("🔄 Scanner le dossier & Ajouter"):
        csv_files = glob.glob(os.path.join(download_path, "*.csv"))
        import_date = datetime.now().strftime("%d/%m/%Y %H:%M")
        trouve = False
        
        for nom_equipe in equipes:
            # Recherche flexible (premier mot du nom de l'équipe)
            mot_cle = nom_equipe.split()[0].lower()
            fichier_trouve = next((f for f in csv_files if mot_cle in os.path.basename(f).lower()), None)
            
            if fichier_trouve:
                somme = calculer_salaire(fichier_trouve)
                if somme is not None:
                    st.session_state['historique_salaires'].append({
                        "Date": import_date,
                        "Équipe": nom_equipe,
                        "Salaires Mineurs": somme
                    })
                    trouve = True
        if trouve: st.rerun()
        else: st.warning("Aucun fichier correspondant trouvé dans Downloads.")

with col_btn2:
    if st.button("🗑️ Effacer tout l'historique"):
        st.session_state['historique_salaires'] = []
        st.rerun()

st.divider()

# --- 3. VUE : DERNIERS SALAIRES CALCULÉS ---
if st.session_state['historique_salaires']:
    st.subheader("📊 Derniers Salaires Mineurs Calculés")
    df_histo = pd.DataFrame(st.session_state['historique_salaires'])
    
    # On garde seulement la dernière entrée pour chaque équipe
    derniers_salaires = df_histo.drop_duplicates(subset='Équipe', keep='last')
    
    # Affichage en 3 colonnes de cartes (métriques)
    cols = st.columns(3)
    for i, (_, row) in enumerate(derniers_salaires.iterrows()):
        cols[i % 3].metric(
            label=row['Équipe'], 
            value=f"{row['Salaires Mineurs']:,.0f} $",
            delta=f"Importé le {row['Date']}",
            delta_color="off"
        )

    st.divider()

    # --- 4. VUE : HISTORIQUE COMPLET ET SUPPRESSION ---
    st.subheader("📜 Historique et Gestion")
    
    # Préparation pour le tableau éditable
    df_editor = df_histo.copy()
    df_editor['Supprimer'] = False
    # Formatage pour l'affichage (le calcul reste sur les chiffres bruts en session_state)
    df_editor['Salaires Mineurs'] = df_editor['Salaires Mineurs'].apply(lambda x: f"{x:,.0f} $")

    edited_df = st.data_editor(
        df_editor,
        column_config={
            "Supprimer": st.column_config.CheckboxColumn("❌", help="Cochez pour supprimer cette ligne"),
            "Date": st.column_config.TextColumn("Date d'import"),
            "Équipe": st.column_config.TextColumn("Équipe"),
            "Salaires Mineurs": st.column_config.TextColumn("Montant")
        },
        disabled=["Date", "Équipe", "Salaires Mineurs"],
        hide_index=True,
        use_container_width=True,
        key="data_editor_key"
    )

    # Logique de suppression si une case est cochée
    if edited_df['Supprimer'].any():
        # On identifie les lignes à garder
        indices_a_garder = edited_df.index[~edited_df['Supprimer']].tolist()
        # On met à jour la session_state avec uniquement ces lignes
        st.session_state['historique_salaires'] = [st.session_state['historique_salaires'][i] for i in indices_a_garder]
        st.rerun()

else:
    st.info("L'historique est vide. Assurez-vous d'avoir vos fichiers CSV dans votre dossier Téléchargements.")
