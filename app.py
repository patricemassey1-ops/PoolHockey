import streamlit as st
import pandas as pd
import io

st.set_page_config(page_title="Calculateur Fantrax 2025", layout="wide")

st.title("🏒 Analyseur Fantrax : Correction Erreur Ligne 43")

# --- Champs de saisie pour les plafonds ---
col_cap1, col_cap2 = st.columns(2)
with col_cap1:
    CAP_ACTIF = st.number_input("Plafond Salarial Actif ($)", min_value=0, value=95500000, step=1000000)
with col_cap2:
    CAP_MINORS = st.number_input("Plafond Salarial Mineur ($)", min_value=0, value=47750000, step=100000)

fichiers_telecharges = st.file_uploader("Importez vos fichiers CSV Fantrax", type="csv", accept_multiple_files=True)

if fichiers_telecharges:
    all_players = []

    for fichier in fichiers_telecharges:
        try:
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

                # On garde tout à partir de l'en-tête
                raw_data_lines = lines[header_line_index:]
                clean_content = "\n".join(raw_data_lines)
                
                # Le moteur 'python' avec on_bad_lines='skip' règle l'erreur des colonnes inattendues
                df = pd.read_csv(
                    io.StringIO(clean_content), 
                    sep=None, 
                    engine='python', 
                    on_bad_lines='skip'
                )
                
                if 'ID' in df.columns:
                    df = df[df['ID'].astype(str).str.strip().str.startswith(('0', '1', '2', '3', '4', '5', '6', '7', '8', '9', '*'))]

                return df

            df_skaters = extract_table(lines, 'Skaters')
            df_goalies = extract_table(lines, 'Goalies')
            df = pd.concat([df_skaters, df_goalies], ignore_index=True)
            df.dropna(how='all', inplace=True)
            
            def find_col_safe(keywords):
                for k in keywords:
                    found = [c for c in df.columns if k.lower() in c.lower()]
                    if found: return found[0]
                return None

            c_player = find_col_safe(['Player', 'Joueur'])
            c_status = find_col_safe(['Status', 'Statut'])
            c_salary = find_col_safe(['Salary', 'Salaire'])
            c_pos    = find_col_safe(['Eligible', 'Pos', 'Position'])

            if not c_status or not c_salary or not c_player:
                continue

            # Nettoyage et conversion
            df[c_salary] = pd.to_numeric(
                df[c_salary].astype(str).replace(r'[\$,\s]', '', regex=True), 
                errors='coerce'
            ).fillna(0)

            df['Catégorie'] = df[c_status].apply(lambda x: "Min" if "MIN" in str(x).upper() else "Act")
            
            nom_proprio = fichier.name.replace('.csv', '')
            res = pd.DataFrame({
                'Joueur': df[c_player],
                'Salaire': df[c_salary],
                'Statut': df['Catégorie'],
                'Propriétaire': nom_proprio
            })
            all_players.append(res)

        except Exception as e:
            st.error(f"💥 Erreur avec {fichier.name} : {e}")

    if all_players:
        df_final = pd.concat(all_players)

        # --- Fonctions de formatage ---
        def format_currency(val):
            return f"{val:,.0f}".replace(",", " ") + " $"

        def style_negative(v):
            return 'color: red;' if v < 0 else 'color: #00FF00;'

        # --- RÉSUMÉ ---
        st.write("### Résumé par Équipe")
        summary = df_final.groupby(['Propriétaire', 'Statut'])['Salaire'].sum().unstack(fill_value=0).reset_index()
        
        # Sécurité si une colonne manque
        for c in ['Act', 'Min']:
            if c not in summary.columns: summary[c] = 0

        summary['Cap Space Actif'] = CAP_ACTIF - summary['Act']
        summary['Cap Space Mineur'] = CAP_MINORS - summary['Min']

        st.dataframe(
            summary.style.format({
                'Act': format_currency,
                'Min': format_currency,
                'Cap Space Actif': format_currency,
                'Cap Space Mineur': format_currency,
            }).applymap(style_negative, subset=['Cap Space Actif', 'Cap Space Mineur']),
            use_container_width=True, hide_index=True
        )

        # --- DÉTAILS ---
        st.write("### Liste des joueurs")
        st.dataframe(
            df_final.sort_values(['Propriétaire', 'Salaire'], ascending=[True, False]),
            column_config={
                "Salaire": st.column_config.NumberColumn(format="%d $"),
            },
            use_container_width=True, hide_index=True
        )
