import streamlit as st
import pandas as pd
import io

st.set_page_config(page_title="Calculateur Fantrax 2025", layout="wide")

st.title("🏒 Analyseur Fantrax : Détection Forcée des Gardiens (Col E)")

fichiers_telecharges = st.file_uploader("Importez vos fichiers CSV Fantrax", type="csv", accept_multiple_files=True)

if fichiers_telecharges:
    all_players = []

    for fichier in fichiers_telecharges:
        try:
            # 1. Lecture brute avec gestion des lignes vides
            content = fichier.getvalue().decode('utf-8-sig')
            lines = content.splitlines()

            # 2. Identification de la ligne d'en-tête
            start_line = 0
            for i, line in enumerate(lines):
                if any(kw in line for kw in ["Status", "Salary", "Player"]):
                    start_line = i
                    break
            
            clean_content = "\n".join(lines[start_line:])
            
            # Lecture flexible du CSV
            df = pd.read_csv(
                io.StringIO(clean_content), 
                sep=None, 
                engine='python', 
                on_bad_lines='skip'
            )

            # 3. Mappage des colonnes par mots-clés
            def find_col(keywords):
                for k in keywords:
                    match = [c for c in df.columns if k.lower() in c.lower()]
                    if match: return match # Retourne le premier nom exact
                return None

            c_player = find_col(['Player', 'Joueur'])
            c_status = find_col(['Status', 'Statut'])
            c_salary = find_col(['Salary', 'Salaire'])
            c_nhl    = find_col(['Team', 'Équipe'])

            # --- FORÇAGE DE LA DÉTECTION DES GARDIENS DANS LA COLONNE E ---
            # On force l'accès à la colonne à l'index 4 (Colonne E)
            # même si l'en-tête est vide ou mal nommé
            try:
                col_e_data = df.iloc[:, 4].astype(str).fillna("N/A")
            except IndexError:
                st.error(f"❌ Le fichier {fichier.name} n'a pas de colonne E (index 4).")
                continue

            # 4. Nettoyage du Salaire
            df[c_salary] = pd.to_numeric(
                df[c_salary].astype(str).replace(r'[\$,\s]', '', regex=True), 
                errors='coerce'
            ).fillna(0)

            # 5. Scan Forcé de la Colonne E pour 'G'
            def force_scan_g(val):
                val = str(val).upper().strip()
                if 'G' in val: return 'G'
                if 'D' in val: return 'D'
                return 'F'

            df['P_Detected'] = col_e_data.apply(force_scan_g)

            # 6. Catégorisation Statut
            def categorize_status(val):
                val = str(val).strip()
                if "Min" in val: return "Min"
                if "Act" in val: return "Act"
                return "Autre"

            df['Catégorie'] = df[c_status].apply(categorize_status)
            
            # Filtrage des catégories valides
            df_filtered = df[df['Catégorie'].isin(['Act', 'Min'])].copy()

            nom_proprio = fichier.name.replace('.csv', '')
            
            # 7. Construction du résultat
            res = pd.DataFrame({
                'P': df_filtered['P_Detected'],
                'Joueur': df_filtered[c_player],
                'Salaire': df_filtered[c_salary],
                'Statut': df_filtered['Catégorie'],
                'Propriétaire': nom_proprio,
                'Col_E_Brut': col_e_data.loc[df_filtered.index] # Pour vérification visuelle
            })
            all_players.append(res)

        except Exception as e:
            st.error(f"💥 Erreur avec {fichier.name} : {e}")

    if all_players:
        df_final = pd.concat(all_players)

        tab1, tab2 = st.tabs(["📊 Résumé Global", "👤 Détails par Joueur"])

        with tab1:
            st.write("### Masse Salariale par Équipe")
            summary = df_final.pivot_table(
                index='Propriétaire', 
                columns='Statut', 
                values='Salaire', 
                aggfunc='sum', 
                fill_value=0
            ).reset_index()
            st.dataframe(summary.style.format({'Act': '{:,.0f} $', 'Min': '{:,.0f} $'}), use_container_width=True, hide_index=True)

        with tab2:
            st.write("### Liste des Joueurs (F, D, G forcés via Col E)")
            col_act, col_min = st.columns(2)

            def draw_table(df_sub, title):
                st.subheader(title)
                # Tri : Équipe -> Position (F, D, G) -> Salaire
                df_sorted = df_sub.sort_values(['Propriétaire', 'P', 'Salaire'], ascending=[True, True, False])
                st.dataframe(
                    df_sorted[['P', 'Joueur', 'Salaire', 'Propriétaire', 'Col_E_Brut']],
                    column_config={
                        "Salaire": st.column_config.NumberColumn(format="$%d"),
                        "P": st.column_config.TextColumn("Pos", width="small")
                    },
                    use_container_width=True, hide_index=True
                )
                st.metric(f"Total {title}", f"{df_sub['Salaire'].sum():,.0f} $")

            with col_act:
                draw_table(df_final[df_final['Statut'] == 'Act'], "Joueurs ACTIFS")

            with col_min:
                draw_table(df_final[df_final['Statut'] == 'Min'], "Joueurs MINORS")

        st.divider()
        st.info("Note : La colonne 'Col_E_Brut' est affichée pour confirmer que la détection 'G' scanne bien la 5ème colonne du fichier.")
