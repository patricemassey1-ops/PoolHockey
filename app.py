import streamlit as st
import pandas as pd
import io

st.set_page_config(page_title="Calculateur Fantrax 2025", layout="wide")

st.title("🏒 Analyseur de Salaires Fantrax (Forcé sur point-virgule)")

# On définit les noms de colonnes standards de Fantrax pour plus de sécurité
COL_PLAYER = 1
COL_NHL_TEAM = 2
COL_STATUS = 5
COL_SALARY = 6

fichiers_telecharges = st.file_uploader("Importez vos CSV", type="csv", accept_multiple_files=True)

if fichiers_telecharges:
    all_data = []

    for fichier in fichiers_telecharges:
        try:
            content = fichier.getvalue().decode('utf-8-sig') 
            
            # --- MODIFICATION CLÉ ---
            # On force le séparateur à ";" (point-virgule), typique des exports Excel FR
            df = pd.read_csv(
                io.StringIO(content), 
                sep=';',  # Changement ici
                engine='python', 
                on_bad_lines='skip' 
            )

            # ÉTAPE 2 : Vérification du nombre de colonnes
            # Le fichier standard Fantrax a 21 colonnes
            if df.shape[1] < 20: 
                st.error(f"❌ {fichier.name} semble toujours mal formaté ou utilise un autre séparateur. Détecté: {df.shape[1]} colonnes.")
                continue

            # ... (Le reste du code reste identique) ...
            
            # Nettoyage et conversion des salaires
            df.iloc[:, COL_SALARY] = pd.to_numeric(
                df.iloc[:, COL_SALARY].astype(str).replace(r'[\$,\s]', '', regex=True), 
                errors='coerce'
            ).fillna(0)

            # Filtrage "Min"
            mask_min = df.iloc[:, COL_STATUS].astype(str).str.contains("Min", na=False, case=False)
            df_min = df[mask_min].copy()
            
            df_min['Équipe Ligue'] = fichier.name.replace('.csv', '')
            
            res = pd.DataFrame({
                'Joueur': df_min.iloc[:, COL_PLAYER],
                'Équipe NHL': df_min.iloc[:, COL_NHL_TEAM],
                'Salaire': df_min.iloc[:, COL_SALARY],
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
