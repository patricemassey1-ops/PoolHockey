import streamlit as st
import pandas as pd
import io

st.set_page_config(page_title="Calculateur Fantrax 2025", layout="wide")

st.title("🏒 Analyseur de Salaires Fantrax (Act vs Min)")

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
            # 1. Lecture robuste
            content = fichier.getvalue().decode('utf-8-sig')
            lines = content.splitlines()

            # 2. Détection de la ligne d'en-tête
            start_line = 0
            for i, line in enumerate(lines):
                if any(kw in line for kw in ["Status", "Salary", "Player"]):
                    start_line = i
                    break
            
            clean_content = "\n".join(lines[start_line:])
            df = pd.read_csv(io.StringIO(clean_content), sep=None, engine='python', on_bad_lines='skip')

            # 3. Identification des colonnes
            def get_col(keywords):
                for k in keywords:
                    found = [c for c in df.columns if k.lower() in c.lower()]
                    if found: return found
                return None

            c_player = get_col(['Player', 'Joueur'])
            c_status = get_col(['Status', 'Statut'])
            c_salary = get_col(['Salary', 'Salaire'])
            c_nhl    = get_col(['Team', 'Équipe'])

            if not c_status or not c_salary:
                continue

            # 4. Nettoyage des données
            df[c_salary] = pd.to_numeric(
                df[c_salary].astype(str).replace(r'[\$,\s]', '', regex=True), 
                errors='coerce'
            ).fillna(0)

            # 5. Normalisation du Statut (Act ou Min)
            # On simplifie pour ne garder que "Act" ou "Min"
            def clean_status(val):
                val = str(val).strip()
                if "Min" in val: return "Min"
                if "Act" in val: return "Act"
                return "Autre"

            df['Status_Clean'] = df[c_status].apply(clean_status)
            
            # Filtrage pour ne garder que Act et Min
            df_filtered = df[df['Status_Clean'].isin(['Act', 'Min'])].copy()

            # Identification du propriétaire
            nom_proprio = fichier.name.replace('.csv', '')
            
            res = pd.DataFrame({
                'Joueur': df_filtered[c_player] if c_player else "Inconnu",
                'Équipe NHL': df_filtered[c_nhl] if c_nhl else "N/A",
                'Salaire': df_filtered[c_salary],
                'Statut': df_filtered['Status_Clean'],
                'Propriétaire': nom_proprio
            })
            all_players.append(res)

        except Exception as e:
            st.error(f"Erreur avec {fichier.name} : {e}")

    if all_players:
        df_final = pd.concat(all_players)

        # --- ONGLES POUR NAVIGATION ---
        tab1, tab2 = st.tabs(["📊 Résumé par Équipe", "👤 Détails par Joueur"])

        with tab1:
            st.write("### Masse Salariale par Catégorie")
            # Pivot table pour voir Act et Min côte à côte par équipe
            summary_pivot = df_final.pivot_table(
                index='Propriétaire', 
                columns='Statut', 
                values='Salaire', 
                aggfunc='sum', 
                fill_value=0
            ).reset_index()
            
            # Affichage stylisé
            st.dataframe(
                summary_pivot.style.format({
                    'Act': '{:,.0f} $',
                    'Min': '{:,.0f} $'
                }),
                use_container_width=True,
                hide_index=True
            )

        with tab2:
            st.write("### Liste des Joueurs")
            
            # Filtre interactif
            choix_statut = st.multiselect("Filtrer par Statut", ["Act", "Min"], default=["Act", "Min"])
            choix_equipe = st.multiselect("Filtrer par Propriétaire", df_final['Propriétaire'].unique())

            filtered_df = df_final[df_final['Statut'].isin(choix_statut)]
            if choix_equipe:
                filtered_df = filtered_df[filtered_df['Propriétaire'].isin(choix_equipe)]

            st.dataframe(
                filtered_df.sort_values(by=['Propriétaire', 'Statut', 'Salaire'], ascending=[True, True, False]),
                column_config={"Salaire": st.column_config.NumberColumn(format="$%d")},
                use_container_width=True,
                hide_index=True
            )

        # Totaux Généraux
        st.divider()
        c1, c2 = st.columns(2)
        total_act = df_final[df_final['Statut'] == 'Act']['Salaire'].sum()
        total_min = df_final[df_final['Statut'] == 'Min']['Salaire'].sum()
        
        c1.metric("TOTAL SALAIRES ACTIFS (ACT)", f"{total_act:,.0f} $")
        c2.metric("TOTAL SALAIRES MINIMUM (MIN)", f"{total_min:,.0f} $")
