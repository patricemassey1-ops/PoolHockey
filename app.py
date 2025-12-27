import streamlit as st
import pandas as pd
import io

st.set_page_config(page_title="Calculateur Fantrax 2025", layout="wide")

st.title("🏒 Analyseur Fantrax : Correction Finale de l'Erreur Nordiques.csv")

fichiers_telecharges = st.file_uploader("Importez vos fichiers CSV Fantrax", type="csv", accept_multiple_files=True)

if fichiers_telecharges:
    all_players = []

    # Fonction utilitaire pour extraire le nom de colonne correct
    def extract_col_name(col_input):
        if isinstance(col_input, str):
            return col_input
        elif isinstance(col_input, list) and len(col_input) > 0:
            return col_input[0]
        elif isinstance(col_input, pd.Series) or isinstance(col_input, pd.Index):
            return col_input.tolist()[0] if not col_input.empty else None
        return None

    for fichier in fichiers_telecharges:
        try:
            content = fichier.getvalue().decode('utf-8-sig')
            lines = content.splitlines()

            start_line = 0
            for i, line in enumerate(lines):
                if any(kw in line for kw in ["Status", "Salary", "Player"]):
                    start_line = i
                    break
            
            clean_content = "\n".join(lines[start_line:])
            df = pd.read_csv(io.StringIO(clean_content), sep=None, engine='python', on_bad_lines='skip')

            # 2. Identification robuste des colonnes par mots-clés
            def find_col(keywords):
                for k in keywords:
                    found = [c for c in df.columns if k.lower() in c.lower()]
                    if found: return found[0] # On retourne directement la chaîne ici
                return None

            # On appelle find_col qui retourne déjà une chaîne unique
            c_player = find_col(['Player', 'Joueur'])
            c_status = find_col(['Status', 'Statut'])
            c_salary = find_col(['Salary', 'Salaire'])
            c_nhl    = find_col(['Team', 'Équipe'])
            
            # Forçage Colonne E
            col_e_name = df.columns # on prend le nom de la 5eme colonne, peu importe ce qu'il est
            c_pos_name = extract_col_name(col_e_name)

            if not c_status or not c_salary or not c_pos_name:
                st.error(f"❌ Colonnes essentielles manquantes dans {fichier.name}")
                continue

            # 3. Nettoyage Salaire
            df[c_salary] = pd.to_numeric(
                df[c_salary].astype(str).replace(r'[\$,\s]', '', regex=True), 
                errors='coerce'
            ).fillna(0)

            # 4. Scan Forcé de la Colonne E pour 'G'
            def detect_position(val):
                val = str(val).upper().strip()
                if 'G' in val: return 'G'
                if 'D' in val: return 'D'
                return 'F'

            # On utilise le nom de colonne exact dans .apply
            df['P'] = df[c_pos_name].apply(detect_position)

            # 5. Catégorisation Statut
            def categorize_status(val):
                val = str(val).strip()
                if "Min" in val: return "Min"
                if "Act" in val: return "Act"
                return "Autre"

            df['Catégorie'] = df[c_status].apply(categorize_status)
            df_filtered = df[df['Catégorie'].isin(['Act', 'Min'])].copy()

            nom_proprio = fichier.name.replace('.csv', '')
            
            # 6. Construction du résultat (Les noms de colonnes sont maintenant des strings)
            res = pd.DataFrame({
                'P': df_filtered['P'],
                'Joueur': df_filtered[c_player],
                'Salaire': df_filtered[c_salary],
                'Statut': df_filtered['Catégorie'],
                'Propriétaire': nom_proprio,
                'Eligible': df_filtered[c_pos_name] 
            })
            all_players.append(res)

        except Exception as e:
            st.error(f"💥 Erreur avec {fichier.name} : {e}")
            st.exception(e) # Affiche le détail de l'erreur

    if all_players:
        df_final = pd.concat(all_players)

        tab1, tab2 = st.tabs(["📊 Résumé Global", "👤 Détails par Joueur"])
        with tab1:
            st.write("### Masse Salariale par Équipe")
            summary = df_final.pivot_table(index='Propriétaire', columns='Statut', values='Salaire', aggfunc='sum', fill_value=0).reset_index()
            st.dataframe(summary.style.format({'Act': '{:,.0f} $', 'Min': '{:,.0f} $'}), use_container_width=True, hide_index=True)

        with tab2:
            st.write("### Liste des Joueurs (F, D, G)")
            col_act, col_min = st.columns(2)
            def draw_table(df_sub, title):
                st.subheader(title)
                df_sorted = df_sub.sort_values(['Propriétaire', 'P', 'Salaire'], ascending=[True, True, False])
                st.dataframe(
                    df_sorted[['P', 'Joueur', 'Salaire', 'Propriétaire', 'Eligible']],
                    column_config={"Salaire": st.column_config.NumberColumn(format="$%d"), "P": st.column_config.TextColumn("Pos", width="small")},
                    use_container_width=True, hide_index=True
                )
                st.metric(f"Total {title}", f"{df_sub['Salaire'].sum():,.0f} $")
            with col_act:
                draw_table(df_final[df_final['Statut'] == 'Act'], "Joueurs ACTIFS")
            with col_min:
                draw_table(df_final[df_final['Statut'] == 'Min'], "Joueurs MINORS")
