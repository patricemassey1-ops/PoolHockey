import streamlit as st
import pandas as pd

st.set_page_config(page_title="Calculateur de Salaires Fantrax", layout="wide")

st.title("🏒 Analyse des Salaires Fantrax (Version Corrective)")

# Configuration des index de colonnes
COL_PLAYER = 1
COL_NHL_TEAM = 2
COL_STATUS = 5
COL_SALARY = 6

fichiers_telecharges = st.file_uploader("Importez vos fichiers CSV Fantrax", type="csv", accept_multiple_files=True)

if fichiers_telecharges:
    all_data = []

    for fichier in fichiers_telecharges:
        try:
            # SOLUTION AUTOMATIQUE : 
            # engine='python' gère mieux les irrégularités
            # on_bad_lines='warn' permet de sauter la ligne 45 au lieu de planter
            df = pd.read_csv(
                fichier, 
                sep=',', 
                engine='python', 
                on_bad_lines='warn'
            )
            
            # Nettoyage et conversion des salaires
            df.iloc[:, COL_SALARY] = pd.to_numeric(
                df.iloc[:, COL_SALARY].astype(str).replace(r'[\$,]', '', regex=True), 
                errors='coerce'
            ).fillna(0)
            
            # Filtrage des contrats "Min"
            mask_min = df.iloc[:, COL_STATUS].astype(str).str.contains("Min", na=False, case=False)
            df_min = df[mask_min].copy()
            
            # Identification de l'équipe par le nom du fichier
            df_min['Équipe Ligue'] = fichier.name
            all_data.append(df_min)
            
        except Exception as e:
            st.error(f"⚠️ Impossible de lire {fichier.name}. Erreur : {e}")

    if all_data:
        df_total = pd.concat(all_data)
        
        # 1. Résumé par Équipe
        st.write("### 📊 Masse Salariale (Contrats Min) par Équipe")
        # On s'assure que la colonne salaire est bien traitée comme nombre avant le groupby
        summary = df_total.groupby('Équipe Ligue').apply(lambda x: x.iloc[:, COL_SALARY].sum()).reset_index()
        summary.columns = ['Équipe', 'Total ($)']
        
        cols_summary = st.columns(len(summary))
        for idx, row in summary.iterrows():
            cols_summary[idx].metric(row['Équipe'], f"{row['Total']:,.0f} $")

        st.divider()

        # 2. Détails par Joueur
        st.write("### 👤 Liste Complète des Joueurs 'Min'")
        
        display_df = df_total.iloc[:, [COL_PLAYER, COL_NHL_TEAM, COL_SALARY]].copy()
        display_df['Équipe Ligue'] = df_total['Équipe Ligue']
        display_df.columns = ['Joueur', 'Équipe NHL', 'Salaire', 'Propriétaire']
        
        st.dataframe(
            display_df.sort_values(by="Salaire", ascending=False),
            column_config={
                "Salaire": st.column_config.NumberColumn("Salaire", format="$%d"),
            },
            hide_index=True,
            use_container_width=True
        )
        
        st.success(f"Analyse terminée. Total global : {display_df['Salaire'].sum():,.2f} $")
