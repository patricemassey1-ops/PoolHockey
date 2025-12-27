import streamlit as st
import pandas as pd
import io

st.set_page_config(page_title="Calculateur Fantrax 2025", layout="wide")
st.title("🏒 Analyseur de Salaires Fantrax (Mode Ultra-Compatible)")

fichiers_telecharges = st.file_uploader("Importez vos CSV", type="csv", accept_multiple_files=True)

if fichiers_telecharges:
    all_data = []

    for fichier in fichiers_telecharges:
        try:
            # 1. Lire le contenu brut
            bytes_data = fichier.getvalue()
            content = bytes_data.decode('utf-8-sig')
            lines = content.splitlines()

            # 2. Trouver la ligne d'en-tête (Header)
            # Fantrax contient souvent "Player" ou "Status" dans ses en-têtes
            skip_rows = 0
            for i, line in enumerate(lines):
                if "Status" in line or "Salary" in line or "Player" in line:
                    skip_rows = i
                    break
            
            # 3. Essayer la lecture avec détection de séparateur
            # On utilise le contenu à partir de la ligne d'en-tête trouvée
            clean_content = "\n".join(lines[skip_rows:])
            
            df = pd.read_csv(
                io.StringIO(clean_content),
                sep=None, # Détection automatique (virgule, point-virgule, etc.)
                engine='python',
                on_bad_lines='skip'
            )

            # 4. Identification dynamique des colonnes par nom
            # Car les index changent si le fichier est mal lu
            def find_col(possible_names):
                for name in possible_names:
                    match = [c for c in df.columns if name.lower() in c.lower()]
                    if match: return match[0]
                return None

            col_status = find_col(['Status', 'Statut'])
            col_salary = find_col(['Salary', 'Salaire'])
            col_player = find_col(['Player', 'Joueur'])
            col_nhl = find_col(['Team', 'Équipe'])

            if not col_status or not col_salary:
                st.error(f"❌ Impossible de trouver les colonnes 'Status' ou 'Salary' dans {fichier.name}")
                continue

            # 5. Nettoyage et Filtrage
            df[col_salary] = pd.to_numeric(
                df[col_salary].astype(str).replace(r'[\$,\s]', '', regex=True), 
                errors='coerce'
            ).fillna(0)

            mask_min = df[col_status].astype(str).str.contains("Min", na=False, case=False)
            df_min = df[mask_min].copy()
            
            # 6. Consolidation
            res = pd.DataFrame({
                'Joueur': df_min[col_player] if col_player else "Inconnu",
                'Équipe NHL': df_min[col_nhl] if col_nhl else "N/A",
                'Salaire': df_min[col_salary],
                'Propriétaire': fichier.name.replace('.csv', '')
            })
            
            all_data.append(res)
            
        except Exception as e:
            st.error(f"💥 Erreur avec {fichier.name} : {e}")

    if all_data:
        df_final = pd.concat(all_data)
        
        # Totaux
        st.write("### 💰 Totaux par Équipe (Contrats Min)")
        total_par_equipe = df_final.groupby('Propriétaire')['Salaire'].sum().reset_index()
        
        m_cols = st.columns(len(total_par_equipe))
        for i, row in total_par_equipe.iterrows():
            m_cols[i].metric(row['Propriétaire'], f"{row['Salaire']:,.0f} $")

        st.divider()

        # Tableau
        st.write("### 📋 Détail des joueurs")
        st.dataframe(
            df_final.sort_values(['Propriétaire', 'Salaire'], ascending=[True, False]),
            column_config={"Salaire": st.column_config.NumberColumn(format="$%d")},
            use_container_width=True,
            hide_index=True
        )
