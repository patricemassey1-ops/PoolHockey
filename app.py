import streamlit as st
import pandas as pd
import io

st.set_page_config(page_title="Calculateur Fantrax 2025", layout="wide")

st.title("🏒 Analyseur de Salaires Fantrax : Actifs vs Minors")

# Liste officielle des équipes
EQUIPES_OFFICIELLES = [
    "Canadiens Montréal", "Cracheurs Anonymes Lima", "Red Wings Détroit", 
    "Prédateurs Nashville", "Whalers Hartford"
]

fichiers_telecharges = st.file_uploader("Importez vos fichiers CSV Fantrax", type="csv", accept_multiple_files=True)

if fichiers_telecharges:
    all_players = []

    for fichier in fichiers_telecharges:
        try:
            # 1. Lecture robuste (gestion du format et du header)
            content = fichier.getvalue().decode('utf-8-sig')
            lines = content.splitlines()

            start_line = 0
            for i, line in enumerate(lines):
                if any(kw in line for kw in ["Status", "Salary", "Player"]):
                    start_line = i
                    break
            
            clean_content = "\n".join(lines[start_line:])
            df = pd.read_csv(io.StringIO(clean_content), sep=None, engine='python', on_bad_lines='skip')

            # 2. Identification dynamique des colonnes
            def get_col_name(keywords):
                for k in keywords:
                    found = [c for c in df.columns if k.lower() in c.lower()]
                    if found: return found[0]
                return None

            c_player = get_col_name(['Player', 'Joueur'])
            c_pos    = get_col_name(['Pos', 'Position'])
            c_status = get_col_name(['Status', 'Statut'])
            c_salary = get_col_name(['Salary', 'Salaire'])
            c_nhl    = get_col_name(['Team', 'Équipe'])

            if not c_status or not c_salary:
                continue

            # 3. Nettoyage des données
            df[c_salary] = pd.to_numeric(
                df[c_salary].astype(str).replace(r'[\$,\s]', '', regex=True), 
                errors='coerce'
            ).fillna(0)

            # Normalisation du Statut (Act ou Min)
            def categorize_status(val):
                val = str(val).strip()
                if "Min" in val: return "Min"
                if "Act" in val: return "Act"
                return "Autre"

            df['Catégorie'] = df[c_status].apply(categorize_status)
            
            # Filtrage pour ne garder que les catégories voulues
            df_filtered = df[df['Catégorie'].isin(['Act', 'Min'])].copy()

            # Identification du propriétaire (nom du fichier)
            nom_proprio = fichier.name.replace('.csv', '')
            
            res = pd.DataFrame({
                'Joueur': df_filtered[c_player] if c_player else "Inconnu",
                'Pos': df_filtered[c_pos] if c_pos else "N/A",
                'Équipe NHL': df_filtered[c_nhl] if c_nhl else "N/A",
                'Salaire': df_filtered[c_salary],
                'Statut': df_filtered['Catégorie'],
                'Propriétaire': nom_proprio
            })
            all_players.append(res)

        except Exception as e:
            st.error(f"Erreur avec {fichier.name} : {e}")

    if all_players:
        df_final = pd.concat(all_players)

        # --- SECTION RÉSUMÉ ---
        st.write("### 📊 Résumé des Salaires par Équipe")
        
        # Calcul des totaux par équipe et par statut
        summary_pivot = df_final.pivot_table(
            index='Propriétaire', 
            columns='Statut', 
            values='Salaire', 
            aggfunc='sum', 
            fill_value=0
        ).reset_index()

        # Affichage du tableau récapitulatif
        st.dataframe(
            summary_pivot.style.format({'Act': '{:,.0f} $', 'Min': '{:,.0f} $'}),
            use_container_width=True,
            hide_index=True
        )

        st.divider()

        # --- SECTION DÉTAILS ---
        st.write("### 👤 Détails des Joueurs par Catégorie")
        
        col_act, col_min = st.columns(2)

        with col_act:
            st.subheader("📋 Joueurs ACTIFS (Act)")
            df_act = df_final[df_final['Statut'] == 'Act'].sort_values(['Propriétaire', 'Salaire'], ascending=[True, False])
            st.dataframe(
                df_act[['Joueur', 'Pos', 'Salaire', 'Propriétaire']],
                column_config={"Salaire": st.column_config.NumberColumn(format="$%d")},
                use_container_width=True,
                hide_index=True
            )
            st.metric("Total Actifs", f"{df_act['Salaire'].sum():,.0f} $")

        with col_min:
            st.subheader("📋 Joueurs MINORS (Min)")
            df_min = df_final[df_final['Statut'] == 'Min'].sort_values(['Propriétaire', 'Salaire'], ascending=[True, False])
            st.dataframe(
                df_min[['Joueur', 'Pos', 'Salaire', 'Propriétaire']],
                column_config={"Salaire": st.column_config.NumberColumn(format="$%d")},
                use_container_width=True,
                hide_index=True
            )
            st.metric("Total Minors", f"{df_min['Salaire'].sum():,.0f} $")
