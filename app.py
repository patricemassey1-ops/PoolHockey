import streamlit as st
import pandas as pd
import io

st.set_page_config(page_title="Calculateur Fantrax 2025", layout="wide")

st.title("🏒 Analyseur de Salaires Fantrax")

# On définit les noms de colonnes standards de Fantrax pour plus de sécurité
# Si les index (0,1,2...) échouent, on peut essayer par noms
TARGET_COLUMNS = ['Player', 'Team', 'Status', 'Salary']

fichiers_telecharges = st.file_uploader("Importez vos CSV", type="csv", accept_multiple_files=True)

if fichiers_telecharges:
    all_data = []

    for fichier in fichiers_telecharges:
        try:
            # ÉTAPE 1 : Détection du séparateur et lecture robuste
            # On lit d'abord une petite partie pour tester
            content = fichier.getvalue().decode('utf-8-sig') # gère aussi le format UTF-8 avec BOM
            
            # On essaie de lire avec détection automatique du séparateur (sep=None)
            df = pd.read_csv(
                io.StringIO(content), 
                sep=None, 
                engine='python', 
                on_bad_lines='skip' # Saute la ligne 45 si elle est corrompue
            )

            # ÉTAPE 2 : Vérification du nombre de colonnes
            if df.shape[1] < 5:
                st.error(f"❌ {fichier.name} semble mal formaté (seulement {df.shape[1]} colonne détectée).")
                continue

            # ÉTAPE 3 : Extraction dynamique des colonnes
            # On cherche les colonnes Salaire et Statut par index ou par nom
            # Fantrax standard: Index 1=Joueur, 2=Équipe, 5=Statut, 6=Salaire
            idx_status = 5 if df.shape[1] > 5 else -1
            idx_salary = 6 if df.shape[1] > 6 else -1
            
            if idx_status == -1 or idx_salary == -1:
                st.warning(f"⚠️ Colonnes manquantes dans {fichier.name}")
                continue

            # Nettoyage du Salaire
            df.iloc[:, idx_salary] = pd.to_numeric(
                df.iloc[:, idx_salary].astype(str).replace(r'[\$,\s]', '', regex=True), 
                errors='coerce'
            ).fillna(0)

            # Filtrage "Min"
            mask_min = df.iloc[:, idx_status].astype(str).str.contains("Min", na=False, case=False)
            df_min = df[mask_min].copy()
            
            # Nettoyage des noms (enlever les positions comme 'LW, RW')
            df_min['Équipe Ligue'] = fichier.name.replace('.csv', '')
            
            # On ne garde que les colonnes essentielles pour éviter les erreurs d'index
            res = pd.DataFrame({
                'Joueur': df_min.iloc[:, 1],
                'Équipe NHL': df_min.iloc[:, 2],
                'Salaire': df_min.iloc[:, idx_salary],
                'Équipe Ligue': df_min['Équipe Ligue']
            })
            
            all_data.append(res)
            
        except Exception as e:
            st.error(f"💥 Erreur critique avec {fichier.name} : {e}")

    if all_data:
        df_final = pd.concat(all_data)
        
        # Affichage des totaux par équipe
        st.write("### 💰 Totaux par Équipe (Contrats Min)")
        total_par_equipe = df_final.groupby('Équipe Ligue')['Salaire'].sum().reset_index()
        
        m_cols = st.columns(len(total_par_equipe))
        for i, row in total_par_equipe.iterrows():
            m_cols[i].metric(row['Équipe Ligue'], f"{row['Salaire']:,.0f} $")

        st.divider()

        # Tableau détaillé
        st.write("### 📋 Détail des joueurs")
        st.dataframe(
            df_final,
            column_config={"Salaire": st.column_config.NumberColumn(format="$%d")},
            use_container_width=True,
            hide_index=True
        )
