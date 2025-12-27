import streamlit as st
import pandas as pd
import io

st.set_page_config(page_title="Calculateur Fantrax 2025", layout="wide")

st.title("🏒 Analyse Détaillée des Salaires Fantrax")

# Official Team List 2025
EQUIPES_OFFICIELLES = [
    "Canadiens Montréal", "Cracheurs Anonymes Lima", "Red Wings Détroit", 
    "Prédateurs Nashville", "Whalers Hartford"
]

st.write("### 📂 Importez vos fichiers CSV")
fichiers_telecharges = st.file_uploader("Choisir les exports Fantrax", type="csv", accept_multiple_files=True)

if fichiers_telecharges:
    all_players = []

    for fichier in fichiers_telecharges:
        try:
            # 1. Robust Reading (Handling UTF-8 and bad lines)
            content = fichier.getvalue().decode('utf-8-sig')
            lines = content.splitlines()

            # 2. Find Header Row automatically
            start_line = 0
            for i, line in enumerate(lines):
                if any(kw in line for kw in ["Status", "Salary", "Player"]):
                    start_line = i
                    break
            
            clean_content = "\n".join(lines[start_line:])
            df = pd.read_csv(io.StringIO(clean_content), sep=None, engine='python', on_bad_lines='skip')

            # 3. Dynamic Column Identification
            def get_col(keywords):
                for k in keywords:
                    found = [c for c in df.columns if k.lower() in c.lower()]
                    if found: return found[0]
                return None

            c_player = get_col(['Player', 'Joueur'])
            c_status = get_col(['Status', 'Statut'])
            c_salary = get_col(['Salary', 'Salaire'])
            c_nhl    = get_col(['Team', 'Équipe'])

            if not c_status or not c_salary:
                continue

            # 4. Data Cleaning
            df[c_salary] = pd.to_numeric(
                df[c_salary].astype(str).replace(r'[\$,\s]', '', regex=True), 
                errors='coerce'
            ).fillna(0)

            # Filter for "Min" contracts only
            df_min = df[df[c_status].astype(str).str.contains("Min", na=False, case=False)].copy()

            # Create clean dataframe for this file
            team_name = fichier.name.replace('.csv', '')
            res = pd.DataFrame({
                'Joueur': df_min[c_player] if c_player else "Inconnu",
                'Équipe NHL': df_min[c_nhl] if c_nhl else "N/A",
                'Salaire': df_min[c_salary],
                'Propriétaire': team_name
            })
            all_players.append(res)

        except Exception as e:
            st.error(f"Erreur avec {fichier.name} : {e}")

    if all_players:
        df_final = pd.concat(all_players)
        
        st.divider()
        
        # --- SECTION 1: TOTALS BY TEAM ---
        st.write("### 💰 Résumé des Totaux")
        summary = df_final.groupby('Propriétaire')['Salaire'].sum().reset_index()
        
        m_cols = st.columns(len(summary))
        for i, row in summary.iterrows():
            m_cols[i].metric(row['Propriétaire'], f"{row['Salaire']:,.0f} $")

        st.divider()

        # --- SECTION 2: PLAYER DETAILS BY TEAM ---
        st.write("### 🔍 Détails des Joueurs par Équipe")
        
        # We iterate through each unique owner to create a dedicated section
        for team in sorted(df_final['Propriétaire'].unique()):
            with st.expander(f"Voir les joueurs de : {team}"):
                team_data = df_final[df_final['Propriétaire'] == team].sort_values(by='Salaire', ascending=False)
                
                # Table for this specific team
                st.table(team_data[['Joueur', 'Équipe NHL', 'Salaire']].style.format({'Salaire': '{:,.0f} $'}))
                
                # Small sub-total for the expander
                st.write(f"**Sous-total pour {team} : {team_data['Salaire'].sum():,.0f} $**")

        st.divider()

        # --- SECTION 3: SEARCHABLE GLOBAL LIST ---
        st.write("### 📋 Liste Globale de la Ligue (Recherche possible)")
        st.dataframe(
            df_final.sort_values(by='Salaire', ascending=False),
            column_config={"Salaire": st.column_config.NumberColumn(format="$%d")},
            use_container_width=True,
            hide_index=True
        )

        st.success(f"**Analyse terminée. Total des salaires 'Min' : {df_final['Salaire'].sum():,.2f} $**")
