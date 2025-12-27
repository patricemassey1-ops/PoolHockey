import streamlit as st
import pandas as pd
import io

st.set_page_config(page_title="Calculateur Fantrax 2025", layout="wide")

st.title("🏒 Analyseur Fantrax : Scan Intégral & Détection G")

fichiers_telecharges = st.file_uploader("Importez vos fichiers CSV Fantrax", type="csv", accept_multiple_files=True)

if fichiers_telecharges:
    all_players = []

    for fichier in fichiers_telecharges:
        try:
            # 1. Lecture brute du fichier complet
            content = fichier.getvalue().decode('utf-8-sig')
            lines = content.splitlines()

            # 2. Localisation dynamique de l'en-tête
            start_line = 0
            for i, line in enumerate(lines):
                if any(kw in line for kw in ["Status", "Salary", "Player"]):
                    start_line = i
                    break
            
            # On traite tout le contenu à partir de l'en-tête, sans s'arrêter aux lignes vides
            clean_content = "\n".join(lines[start_line:])
            df = pd.read_csv(io.StringIO(clean_content), sep=None, engine='python', on_bad_lines='skip')

            # 3. Identification sécurisée des colonnes (Correction 'arg must be a list')
            def find_col_safe(keywords):
                for k in keywords:
                    found = [c for c in df.columns if k.lower() in c.lower()]
                    if found: return str(found[0]) # Force le retour du nom exact (string)
                return None

            c_player = find_col_safe(['Player', 'Joueur'])
            c_status = find_col_safe(['Status', 'Statut'])
            c_salary = find_col_safe(['Salary', 'Salaire'])
            c_pos    = find_col_safe(['Eligible', 'Pos', 'Position'])

            # Sécurité : Si Pos n'est pas trouvé par nom, on force la Colonne E (index 4)
            if not c_pos and df.shape[1] >= 5:
                c_pos = df.columns[4]

            if not c_status or not c_salary or not c_player:
                st.error(f"❌ Données manquantes dans {fichier.name}")
                continue

            # 4. Nettoyage du Salaire
            df[c_salary] = pd.to_numeric(
                df[c_salary].astype(str).replace(r'[\$,\s]', '', regex=True), 
                errors='coerce'
            ).fillna(0)

            # 5. SCAN CONTINU DE TOUTES LES LIGNES POUR 'G'
            # Cette fonction scanne la cellule même s'il y a des cassures ou du texte complexe
            def scan_for_g(val):
                text = str(val).upper().strip()
                if not text or text == "NAN": return "F" 
                if 'G' in text: return 'G'
                if 'D' in text: return 'D'
                return 'F'

            df['P_Detected'] = df[c_pos].apply(scan_for_g)

            # 6. Catégorisation Statut (Act vs Min)
            def categorize_status(val):
                val = str(val).strip()
                if "Min" in val: return "Min"
                if "Act" in val: return "Act"
                return "Autre"

            df['Catégorie'] = df[c_status].apply(categorize_status)
            
            # Filtrage des joueurs Actifs et Minors (on garde tout le reste du scan)
            df_filtered = df[df['Catégorie'].isin(['Act', 'Min'])].copy()

            nom_proprio = fichier.name.replace('.csv', '')
            
            # 7. Compilation des résultats
            res = pd.DataFrame({
                'P': df_filtered['P_Detected'],
                'Joueur': df_filtered[c_player],
                'Salaire': df_filtered[c_salary],
                'Statut': df_filtered['Catégorie'],
                'Propriétaire': nom_proprio,
                'Info_Pos': df_filtered[c_pos] # Permet de vérifier la source du scan
            })
            all_players.append(res)

        except Exception as e:
            st.error(f"💥 Erreur avec {fichier.name} : {e}")

    if all_players:
        df_final = pd.concat(all_players)

        # Affichage par onglets
        tab1, tab2 = st.tabs(["📊 Masse Salariale", "👤 Détails Joueurs (F, D, G)"])

        with tab1:
            st.write("### Résumé par Équipe")
            summary = df_final.pivot_table(index='Propriétaire', columns='Statut', values='Salaire', aggfunc='sum', fill_value=0).reset_index()
            st.dataframe(summary.style.format({'Act': '{:,.0f} $', 'Min': '{:,.0f} $'}), use_container_width=True, hide_index=True)

        with tab2:
            st.write("### Scan complet des effectifs")
            col_left, col_right = st.columns(2)

            def draw_category_table(df_sub, title):
                st.subheader(title)
                # Tri : Équipe -> Position (F, D, G) -> Salaire
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

            with col_left:
                draw_category_table(df_final[df_final['Statut'] == 'Act'], "ACTIFS")

            with col_right:
                draw_category_table(df_final[df_final['Statut'] == 'Min'], "MINORS")

        st.divider()
        st.success(f"Analyse terminée. {len(df_final)} joueurs traités pour 2025.")
