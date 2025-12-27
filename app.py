import streamlit as st
import pandas as pd
import io

st.set_page_config(page_title="Calculateur Fantrax 2025", layout="wide")

st.title("🏒 Analyseur Fantrax : Scan exhaustif (Skaters + Goalies)")

fichiers_telecharges = st.file_uploader("Importez vos fichiers CSV Fantrax", type="csv", accept_multiple_files=True)

if fichiers_telecharges:
    all_players = []

    for fichier in fichiers_telecharges:
        try:
            # 1. Lecture brute du fichier
            content = fichier.getvalue().decode('utf-8-sig')
            lines = content.splitlines()

            # Function to extract a data frame by finding the *actual* header line after a keyword
            def extract_table(lines, section_keyword):
                start_line_index = -1
                for i, line in enumerate(lines):
                    if section_keyword in line:
                        start_line_index = i
                        break
                
                if start_line_index == -1:
                    return pd.DataFrame() # Section non trouvée, retourne un DataFrame vide

                # 2. Recherche de la ligne d'en-tête réelle (celle avec ID, Player, etc.) après le titre de section
                header_line_index = -1
                for i in range(start_line_index + 1, len(lines)):
                    if any(kw in lines[i] for kw in ["ID", "Player", "Status", "Salary"]):
                        header_line_index = i
                        break
                
                if header_line_index == -1:
                    # Ne devrait pas arriver si le format Fantrax est respecté
                    return pd.DataFrame()

                # On prend les lignes à partir de l'en-tête réel trouvé
                raw_data_lines = lines[header_line_index:]
                
                # Filtrage des lignes vides/comma-only
                filtered_lines = [
                    line for line in raw_data_lines 
                    if line.strip() and any(cell.strip() for cell in line.split(','))
                ]
                
                clean_content = "\n".join(filtered_lines)
                df = pd.read_csv(io.StringIO(clean_content), sep=None, engine='python', on_bad_lines='skip')
                
                # Si la colonne ID existe, on filtre les lignes de données non valides
                if 'ID' in df.columns:
                    df = df[df['ID'].astype(str).str.strip().str.startswith(('0', '1', '2', '3', '4', '5', '6', '7', '8', '9', '*'))]

                # Cap at 70 entries to avoid weird summary totals at the very end of files
                return df.head(70)

            # --- Process Skaters ---
            df_skaters = extract_table(lines, 'Skaters')
            
            # --- Process Goalies (Look for the second header) ---
            df_goalies = extract_table(lines, 'Goalies')

            # Combine them.
            df = pd.concat([df_skaters, df_goalies], ignore_index=True)
            
            # Remove any totally empty rows that might remain
            df.dropna(how='all', inplace=True)
            
            # 4. Identification sécurisée des colonnes (Fonction corrigée)
            def find_col_safe(keywords):
                for k in keywords:
                    found = [c for c in df.columns if k.lower() in c.lower()]
                    # On retourne le nom exact de la première colonne trouvée
                    if found: return found 
                return None

            c_player = find_col_safe(['Player', 'Joueur'])
            c_status = find_col_safe(['Status', 'Statut'])
            c_salary = find_col_safe(['Salary', 'Salaire'])
            c_pos    = find_col_safe(['Eligible', 'Pos', 'Position'])

            if not c_status or not c_salary or not c_player:
                st.error(f"❌ Colonnes essentielles manquantes dans {fichier.name}. Impossible de trouver 'Player', 'Status' ou 'Salary'.")
                st.write("Colonnes trouvées dans le DataFrame final :", list(df.columns))
                continue

            # 5. Nettoyage et conversion des salaires
            df[c_salary] = pd.to_numeric(
                df[c_salary].astype(str).replace(r'[\$,\s]', '', regex=True), 
                errors='coerce'
            ).fillna(0)

            # 6. Scan de la position (F, D, G)
            def scan_pos(val):
                text = str(val).upper().strip()
                if 'G' in text: return 'G'
                if 'D' in text: return 'D'
                return 'F'

            df['P'] = df[c_pos].apply(scan_pos)

            # 7. Catégorisation Statut (Act vs Min)
            def categorize_status(val):
                val = str(val).strip()
                if "Min" in val: return "Min"
                if "Act" in val: return "Act"
                return "Autre"

            df['Catégorie'] = df[c_status].apply(categorize_status)
            
            # Filtrage des lignes valides (Act ou Min uniquement)
            df_filtered = df[df['Catégorie'].isin(['Act', 'Min'])].copy()

            nom_proprio = fichier.name.replace('.csv', '')
            
            # 8. Compilation du DataFrame résultat
            res = pd.DataFrame({
                'P': df_filtered['P'],
                'Joueur': df_filtered[c_player],
                'Salaire': df_filtered[c_salary],
                'Statut': df_filtered['Catégorie'],
                'Propriétaire': nom_proprio,
                'Info_Pos': df_filtered[c_pos]
            })
            all_players.append(res)

        except Exception as e:
            st.error(f"💥 Erreur inattendue avec {fichier.name} : {e}")

    if all_players:
        df_final = pd.concat(all_players)

        # Affichage de l'interface
        tab1, tab2 = st.tabs(["📊 Masse Salariale", "👤 Détails Joueurs"])

        with tab1:
            st.write("### Résumé par Équipe")
            summary = df_final.pivot_table(index='Propriétaire', columns='Statut', values='Salaire', aggfunc='sum', fill_value=0).reset_index()
            st.dataframe(summary.style.format({'Act': '{:,.0f} $', 'Min': '{:,.0f} $'}), use_container_width=True, hide_index=True)

        with tab2:
            st.write("### Liste des joueurs (Tri par Position)")
            col_act, col_min = st.columns(2)

            def draw_table(df_sub, title):
                st.subheader(title)
                df_sorted = df_sub.sort_values(['Propriétaire', 'P', 'Salaire'], ascending=[True, True, False])
                st.dataframe(
                    df_sorted[['P', 'Joueur', 'Salaire', 'Propriétaire', 'Info_Pos']],
                    column_config={
                        "Salaire": st.column_config.NumberColumn(format="$%d"),
                        "P": st.column_config.TextColumn("Pos", width="small")
                    },
                    use_container_width=True, hide_index=True
                )
                st.metric(f"Total {title}", f"{df_sub['Salaire'].sum():,.0f} $")

            with col_act:
                draw_table(df_final[df_final['Statut'] == 'Act'], "ACTIFS")

            with col_min:
                draw_table(df_final[df_final['Statut'] == 'Min'], "MINORS")

        st.divider()
        st.success(f"Analyse terminée. Les sections Skaters et Goalies ont été combinées.")
