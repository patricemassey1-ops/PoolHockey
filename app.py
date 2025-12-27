import streamlit as st
import pandas as pd

st.set_page_config(page_title="Calculateur de Salaires Fantrax", layout="wide")

st.title("🏒 Analyse Détaillée des Salaires Fantrax (2025)")

# Configuration des colonnes Fantrax (basé sur l'export standard)
# Index 1: Nom Joueur | Index 2: Équipe NHL | Index 5: Statut (Min) | Index 6: Salaire
COL_PLAYER = 1
COL_NHL_TEAM = 2
COL_STATUS = 5
COL_SALARY = 6

# Liste des équipes de votre ligue
equipes_ligue = ["Canadiens Montréal", "Red Wings Détroit", "Nordiques Québec", 
                 "Prédateurs Nashville", "Sénateurs Ottawa", "Cracheurs Anonymes"]

fichiers_telecharges = st.file_uploader("Importez vos fichiers CSV Fantrax", type="csv", accept_multiple_files=True)

if fichiers_telecharges:
    all_data = []

    for fichier in fichiers_telecharges:
        try:
            df = pd.read_csv(fichier)
            
            # Nettoyage du salaire : retrait du '$' et conversion en nombre
            df.iloc[:, COL_SALARY] = pd.to_numeric(
                df.iloc[:, COL_SALARY].replace(r'[\$,]', '', regex=True), 
                errors='coerce'
            )
            
            # Filtrage des contrats "Min"
            df_min = df[df.iloc[:, COL_STATUS].astype(str).str.strip() == "Min"].copy()
            
            # Ajout du nom du fichier pour identifier l'équipe de la ligue
            df_min['Équipe Ligue'] = fichier.name
            all_data.append(df_min)
            
        except Exception as e:
            st.error(f"Erreur avec le fichier {fichier.name}: {e}")

    if all_data:
        # Fusion de tous les fichiers en un seul DataFrame
        df_total = pd.concat(all_data)
        
        # 1. Somme par Équipe (Tableau Récapitulatif)
        st.write("### 📊 Résumé par Équipe de Ligue")
        summary = df_total.groupby('Équipe Ligue').iloc[:, COL_SALARY].sum().reset_index()
        summary.columns = ['Équipe', 'Total Salaires Min ($)']
        st.dataframe(summary.style.format({'Total Salaires Min ($)': '{:,.2f} $'}))

        st.divider()

        # 2. Détails par Joueur (Tableau Interactif)
        st.write("### 👤 Détails des Joueurs (Contrats Min)")
        
        # Sélection des colonnes spécifiques pour l'affichage
        display_df = df_total.iloc[:, [COL_PLAYER, COL_NHL_TEAM, COL_SALARY]].copy()
        display_df['Équipe Ligue'] = df_total['Équipe Ligue']
        display_df.columns = ['Joueur', 'Équipe NHL', 'Salaire', 'Propriétaire']
        
        # Affichage avec tri et recherche
        st.dataframe(
            display_df,
            column_config={
                "Salaire": st.column_config.NumberColumn("Salaire", format="$%d"),
            },
            hide_index=True,
            use_container_width=True
        )

        # 3. Métrique Globale
        total_global = display_df['Salaire'].sum()
        st.metric("TOTAL GÉNÉRAL CUMULÉ", f"{total_global:,.2f} $")
