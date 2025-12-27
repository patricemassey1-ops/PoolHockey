import streamlit as st
import pandas as pd
import io

st.set_page_config(page_title="Calculateur Fantrax 2025", layout="wide")

st.title("🏒 Analyseur Fantrax : Groupé par Positions (Version Corrigée)")

EQUIPES_OFFICIELLES = [
    "Canadiens Montréal", "Cracheurs Anonymes Lima", "Red Wings Détroit", 
    "Prédateurs Nashville", "Whalers Hartford"
]

fichiers_telecharges = st.file_uploader("Importez vos fichiers CSV Fantrax", type="csv", accept_multiple_files=True)

if fichiers_telecharges:
    all_players = []

    for fichier in fichiers_telecharges:
        try:
            content = fichier.getvalue().decode('utf-8-sig')
            lines = content.splitlines()

            start_line = 0
            for i, line in enumerate(lines):
                if any(kw in line for kw in ["Status", "Salary", "Player", "Pos"]):
                    start_line = i
                    break
            
            clean_content = "\n".join(lines[start_line:])
            df = pd.read_csv(io.StringIO(clean_content), sep=None, engine='python', on_bad_lines='skip')

            # 2. Identification des colonnes - CORRECTION APPLIQUÉE
            def get_col_name(keywords):
                """Renvoie le nom de la colonne exact sous forme de chaîne de caractères, ou None."""
                for k in keywords:
                    found = [c for c in df.columns if k.lower() in c.lower()]
                    if found: 
                        # On retourne UNIQUEMENT le premier nom de colonne exact trouvé (chaîne de caractères)
                        return found[0] 
                return None

            c_player = get_col_name(['Player', 'Joueur'])
            c_pos    = get_col_name(['Pos', 'Position'])
            c_status = get_col_name(['Status', 'Statut'])
            c_salary = get_col_name(['Salary', 'Salaire'])
            c_nhl    = get_col_name(['Team', 'Équipe'])

            if not c_status or not c_salary:
                st.error(f"❌ Colonnes critiques (Statut/Salaire) manquantes dans {fichier.name}")
                continue

            # 3. Nettoyage des données
            # Utilisation des noms de colonnes exacts retournés par get_col_name
            df[c_salary] = pd.to_numeric(
                df[c_salary].astype(str).replace(r'[\$,\s]', '', regex=True), 
                errors='coerce'
            ).fillna(0)

            # Simplification des positions (F, D, G)
            def simplify_pos(val):
                val = str(val).upper()
                if 'G' in val: return 'G'
                if 'D' in val: return 'D'
                return 'F' 

            # Utilisation du nom de colonne exact pour .apply()
            df['Pos_Group'] = df[c_pos].apply(simplify_pos)

            # Catégorisation Act/Min
            def categorize_status(val):
                val = str(val).strip()
                if "Min" in val: return "Min"
                if "Act" in val: return "Act"
                return "Autre"

            # Utilisation du nom de colonne exact pour .apply()
            df['Catégorie'] = df[c_status].apply(categorize_status)
            df_filtered = df[df['Catégorie'].isin(['Act', 'Min'])].copy()

            nom_proprio = fichier.name.replace('.csv', '')
            
            # 5. Création du DataFrame consolidé (qui utilise des noms de colonne uniques)
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
            st.error(f"💥 Erreur avec {fichier.name}")
            st.exception(e) # Affiche le détail complet de l'erreur pour débogage

    if all_players:
        df_final = pd.concat(all_players)

        # ... (Le reste de l'affichage avec les onglets et les colonnes reste inchangé) ...
        tab1, tab2 = st.tabs(["📊 Résumé par Équipe", "👤 Détails par Joueur"])
        with tab1:
            st.write("### Résumé des Salaires")
            summary_pivot = df_final.pivot_table(index='Propriétaire', columns='Statut', values='Salaire', aggfunc='sum', fill_value=0).reset_index()
            st.dataframe(summary_pivot.style.format({'Act': '{:,.0f} $', 'Min': '{:,.0f} $'}), use_container_width=True, hide_index=True)
        with tab2:
            st.write("### Détails des Joueurs")
            col_act, col_min = st.columns(2)
            def display_category(df_cat, title):
                st.subheader(title)
                df_sorted = df_cat.sort_values(['Propriétaire', 'Pos', 'Salaire'], ascending=[True, True, False])
                st.dataframe(
                    df_sorted[['Pos', 'Joueur', 'Salaire', 'Propriétaire', 'Détail Pos']],
                    column_config={"Salaire": st.column_config.NumberColumn(format="$%d"), "Pos": st.column_config.TextColumn("P", width="small")},
                    use_container_width=True, hide_index=True
                )
                st.metric(f"Total {title}", f"{df_cat['Salaire'].sum():,.0f} $")
            with col_act:
                display_category(df_final[df_final['Statut'] == 'Act'], "Joueurs ACTIFS")
            with col_min:
                display_category(df_final[df_final['Statut'] == 'Min'], "Joueurs MINORS")
