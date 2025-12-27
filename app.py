import streamlit as st
import pandas as pd
import io

# Définition des plafonds salariaux
CAP_ACTIF = 95500000
CAP_MINORS = 47750000

st.set_page_config(page_title="Calculateur Fantrax 2025", layout="wide")

st.title("🏒 Analyseur Fantrax : Plafonds Salariaux Appliqués")

st.markdown(f"Plafond Actif défini à **{CAP_ACTIF:,.0f} $** et Mineur à **{CAP_MINORS:,.0f} $**.")

fichiers_telecharges = st.file_uploader("Importez vos fichiers CSV Fantrax", type="csv", accept_multiple_files=True)

if fichiers_telecharges:
    all_players = []

    for fichier in fichiers_telecharges:
        try:
            # 1. Lecture brute du fichier
            content = fichier.getvalue().decode('utf-8-sig')
            lines = content.splitlines()

            def extract_table(lines, section_keyword):
                start_line_index = -1
                for i, line in enumerate(lines):
                    if section_keyword in line:
                        start_line_index = i
                        break
                
                if start_line_index == -1: return pd.DataFrame()

                header_line_index = -1
                for i in range(start_line_index + 1, len(lines)):
                    if any(kw in lines[i] for kw in ["ID", "Player", "Status", "Salary"]):
                        header_line_index = i
                        break
                
                if header_line_index == -1: return pd.DataFrame()

                raw_data_lines = lines[header_line_index:]
                
                filtered_lines = [
                    line for line in raw_data_lines 
                    if line.strip() and any(cell.strip() for cell in line.split(','))
                ]
                
                clean_content = "\n".join(filtered_lines)
                df = pd.read_csv(io.StringIO(clean_content), sep=None, engine='python', on_bad_lines='skip')
                
                if 'ID' in df.columns:
                    df = df[df['ID'].astype(str).str.strip().str.startswith(('0', '1', '2', '3', '4', '5', '6', '7', '8', '9', '*'))]

                return df.head(70)

            df_skaters = extract_table(lines, 'Skaters')
            df_goalies = extract_table(lines, 'Goalies')
            df = pd.concat([df_skaters, df_goalies], ignore_index=True)
            df.dropna(how='all', inplace=True)
            
            # 4. Identification sécurisée des colonnes (CORRECTION DÉFINITIVE APPLIQUÉE)
            def find_col_safe(keywords):
                for k in keywords:
                    found = [c for c in df.columns if k.lower() in c.lower()]
                    # On retourne UNIQUEMENT la première chaîne de caractères trouvée, pas une liste.
                    if found: 
                        return found[0] # <-- FIX CRITIQUE
                return None

            c_player = find_col_safe(['Player', 'Joueur'])
            c_status = find_col_safe(['Status', 'Statut'])
            c_salary = find_col_safe(['Salary', 'Salaire'])
            c_pos    = find_col_safe(['Eligible', 'Pos', 'Position'])

            if not c_status or not c_salary or not c_player:
                st.error(f"❌ Colonnes essentielles manquantes dans {fichier.name}.")
                continue

            # 5. Nettoyage et conversion des salaires (Utilise maintenant une chaîne unique)
            df[c_salary] = pd.to_numeric(
                df[c_salary].astype(str).replace(r'[\$,\s]', '', regex=True), 
                errors='coerce'
            ).fillna(0)

            def scan_pos(val):
                text = str(val).upper().strip()
                if 'G' in text: return 'G'
                if 'D' in text: return 'D'
                return 'F'

            # 6. Utilise maintenant une chaîne unique
            df['P'] = df[c_pos].apply(scan_pos)

            def categorize_status(val):
                val = str(val).strip()
                if "Min" in val: return "Min"
                if "Act" in val: return "Act"
                return "Autre"

            # 7. Utilise maintenant une chaîne unique
            df['Catégorie'] = df[c_status].apply(categorize_status)
            df_filtered = df[df['Catégorie'].isin(['Act', 'Min'])].copy()

            nom_proprio = fichier.name.replace('.csv', '')
            
            # 8. Utilise maintenant une chaîne unique
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

        tab1, tab2 = st.tabs(["📊 Masse Salariale & Cap Space", "👤 Détails Joueurs"])

        with tab1:
            st.write("### Résumé par Équipe")
            summary = df_final.pivot_table(index='Propriétaire', columns='Statut', values='Salaire', aggfunc='sum', fill_value=0).reset_index()
            
            if 'Act' in summary.columns:
                summary['Total Actif'] = summary['Act']
                summary['Cap Space Actif'] = CAP_ACTIF - summary['Total Actif']
                del summary['Act']
            
            if 'Min' in summary.columns:
                summary['Total Mineur'] = summary['Min']
                summary['Cap Space Mineur'] = CAP_MINORS - summary['Total Mineur']
                del summary['Min']

            if 'Total Actif' in summary.columns and 'Total Mineur' in summary.columns:
                 summary['Total Global'] = summary['Total Actif'] + summary['Total Mineur']
                 summary['Cap Space Global'] = (CAP_ACTIF + CAP_MINORS) - summary['Total Global']

            st.dataframe(
                summary.style.format({
                    'Total Actif': '{:,.0f} $', 
                    'Cap Space Actif': '{:,.0f} $',
                    'Total Mineur': '{:,.0f} $',
                    'Cap Space Mineur': '{:,.0f} $',
                    'Total Global': '{:,.0f} $',
                    'Cap Space Global': '{:,.0f} $'
                }), 
                use_container_width=True, 
                hide_index=True
            )

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
        st.success(f"Analyse terminée. Les totaux et l'espace salarial restant sont affichés.")
