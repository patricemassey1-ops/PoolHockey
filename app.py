import streamlit as st
import pandas as pd
import io

st.set_page_config(page_title="Calculateur Fantrax 2025", layout="wide")

st.title("🏒 Analyseur de Salaires Fantrax (Act/Min + Positions)")

# Liste officielle des équipes 2025
EQUIPES_OFFICIELLES = [
    "Canadiens Montréal", "Cracheurs Anonymes Lima", "Red Wings Détroit", 
    "Prédateurs Nashville", "Whalers Hartford"
]

fichiers_telecharges = st.file_uploader("Importez vos fichiers CSV Fantrax", type="csv", accept_multiple_files=True)

if fichiers_telecharges:
    all_players = []

    for fichier in fichiers_telecharges:
        try:
            # 1. Lecture robuste du fichier
            content = fichier.getvalue().decode('utf-8-sig')
            lines = content.splitlines()

            # 2. Détection de la ligne d'en-tête dynamique
            start_line = 0
            for i, line in enumerate(lines):
                if any(kw in line for kw in ["Status", "Salary", "Player", "Pos"]):
                    start_line = i
                    break
            
            clean_content = "\n".join(lines[start_line:])
            df = pd.read_csv(io.StringIO(clean_content), sep=None, engine='python', on_bad_lines='skip')

            # 3. Identification des colonnes par mots-clés
            def get_col_name(keywords):
                for k in keywords:
                    found = [c for c in df.columns if k.lower() in c.lower()]
                    if found: return found[0] # Renvoie le premier nom exact trouvé
                return None

            c_player = get_col_name(['Player', 'Joueur'])
            c_pos    = get_col_name(['Pos', 'Position']) # Nouvelle colonne ajoutée
            c_status = get_col_name(['Status', 'Statut'])
            c_salary = get_col_name(['Salary', 'Salaire'])
            c_nhl    = get_col_name(['Team', 'Équipe'])

            if not c_status or not c_salary:
                st.error(f"❌ Colonnes critiques (Statut/Salaire) manquantes dans {fichier.name}")
                continue

            # 4. Nettoyage et conversion des données
            df[c_salary] = pd.to_numeric(
                df[c_salary].astype(str).replace(r'[\$,\s]', '', regex=True), 
                errors='coerce'
            ).fillna(0)

            # Normalisation des statuts (Act ou Min)
            def clean_status(val):
                val = str(val).strip()
                if "Min" in val: return "Min"
                if "Act" in val: return "Act"
                return "Autre"

            df['Status_Clean'] = df[c_status].apply(clean_status)
            df_filtered = df[df['Status_Clean'].isin(['Act', 'Min'])].copy()

            # 5. Création du DataFrame consolidé
            nom_proprio = fichier.name.replace('.csv', '')
            res = pd.DataFrame({
                'Joueur': df_filtered[c_player] if c_player else "Inconnu",
                'Pos': df_filtered[c_pos] if c_pos else "N/A", # Inclusion de la position
                'Équipe NHL': df_filtered[c_nhl] if c_nhl else "N/A",
                'Salaire': df_filtered[c_salary],
                'Statut': df_filtered['Status_Clean'],
                'Propriétaire': nom_proprio
            })
            all_players.append(res)

        except Exception as e:
            st.error(f"💥 Erreur avec {fichier.name}")
            st.exception(e)

    if all_players:
        df_final = pd.concat(all_players)

        # --- INTERFACE UTILISATEUR ---
        tab1, tab2 = st.tabs(["📊 Résumé par Équipe", "👤 Détails par Joueur"])

        with tab1:
            st.write("### Masse Salariale Totale ($)")
            summary_pivot = df_final.pivot_table(
                index='Propriétaire', 
                columns='Statut', 
                values='Salaire', 
                aggfunc='sum', 
                fill_value=0
            ).reset_index()
            
            st.dataframe(
                summary_pivot.style.format({'Act': '{:,.0f} $', 'Min': '{:,.0f} $'}),
                use_container_width=True, hide_index=True
            )

        with tab2:
            st.write("### Liste des Joueurs avec Positions")
            
            c_filter1, c_filter2 = st.columns(2)
            with c_filter1:
                choix_statut = st.multiselect("Filtrer par Statut", ["Act", "Min"], default=["Act", "Min"])
            with c_filter2:
                choix_equipe = st.multiselect("Filtrer par Propriétaire", df_final['Propriétaire'].unique())

            filtered_df = df_final[df_final['Statut'].isin(choix_statut)]
            if choix_equipe:
                filtered_df = filtered_df[filtered_df['Propriétaire'].isin(choix_equipe)]

            # Affichage du tableau final incluant Pos
            st.dataframe(
                filtered_df.sort_values(by=['Propriétaire', 'Statut', 'Salaire'], ascending=[True, True, False]),
                column_config={
                    "Salaire": st.column_config.NumberColumn("Salaire", format="$%d"),
                    "Pos": "Position"
                },
                use_container_width=True,
                hide_index=True
            )

        # Totaux en bas de page
        st.divider()
        m1, m2 = st.columns(2)
        m1.metric("TOTAL ACTIFS (ACT)", f"{df_final[df_final['Statut'] == 'Act']['Salaire'].sum():,.0f} $")
        m2.metric("TOTAL MINORS (MIN)", f"{df_final[df_final['Statut'] == 'Min']['Salaire'].sum():,.0f} $")
