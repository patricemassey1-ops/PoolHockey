import streamlit as st
import pandas as pd
import io

st.set_page_config(page_title="Calculateur Fantrax 2025", layout="wide")

st.title("🏒 Analyseur Fantrax : Groupé par Positions (F, D, G)")

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

            start_line = 0
            for i, line in enumerate(lines):
                if any(kw in line for kw in ["Status", "Salary", "Player", "Pos"]):
                    start_line = i
                    break
            
            clean_content = "\n".join(lines[start_line:])
            df = pd.read_csv(io.StringIO(clean_content), sep=None, engine='python', on_bad_lines='skip')

            # 2. Identification des colonnes
            def get_col_name(keywords):
                for k in keywords:
                    found = [c for c in df.columns if k.lower() in c.lower()]
                    if found: return found[0] # Renvoie le premier nom trouvé
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

            # Normalisation simplifié des positions pour le tri (F, D, G)
            def simplify_pos(val):
                val = str(val).upper()
                if 'G' in val: return 'G'
                if 'D' in val: return 'D'
                return 'F' # Par défaut Attaquant (C, LW, RW, etc.)

            df['Pos_Group'] = df[c_pos].apply(simplify_pos)

            # Catégorisation Act/Min
            def categorize_status(val):
                val = str(val).strip()
                if "Min" in val: return "Min"
                if "Act" in val: return "Act"
                return "Autre"

            df['Catégorie'] = df[c_status].apply(categorize_status)
            df_filtered = df[df['Catégorie'].isin(['Act', 'Min'])].copy()

            nom_proprio = fichier.name.replace('.csv', '')
            
            res = pd.DataFrame({
                'Joueur': df_filtered[c_player] if c_player else "Inconnu",
                'Pos': df_filtered['Pos_Group'],
                'Détail Pos': df_filtered[c_pos],
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
        st.write("### 📊 Résumé des Salaires")
        summary_pivot = df_final.pivot_table(
            index='Propriétaire', 
            columns='Statut', 
            values='Salaire', 
            aggfunc='sum', 
            fill_value=0
        ).reset_index()
        st.dataframe(summary_pivot.style.format({'Act': '{:,.0f} $', 'Min': '{:,.0f} $'}), use_container_width=True, hide_index=True)

        st.divider()

        # --- SECTION DÉTAILS GROUPÉS ---
        col_act, col_min = st.columns(2)

        # Fonction d'affichage pour éviter la répétition
        def display_category(df_cat, title):
            st.subheader(title)
            # Tri par Propriétaire, puis par Position (F, D, G), puis par Salaire
            df_sorted = df_cat.sort_values(['Propriétaire', 'Pos', 'Salaire'], ascending=[True, True, False])
            
            st.dataframe(
                df_sorted[['Pos', 'Joueur', 'Salaire', 'Propriétaire', 'Détail Pos']],
                column_config={
                    "Salaire": st.column_config.NumberColumn(format="$%d"),
                    "Pos": st.column_config.TextColumn("P", width="small")
                },
                use_container_width=True, hide_index=True
            )
            st.metric(f"Total {title}", f"{df_cat['Salaire'].sum():,.0f} $")

        with col_act:
            display_category(df_final[df_final['Statut'] == 'Act'], "Joueurs ACTIFS")

        with col_min:
            display_category(df_final[df_final['Statut'] == 'Min'], "Joueurs MINORS")
