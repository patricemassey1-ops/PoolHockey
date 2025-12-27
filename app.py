import streamlit as st
import pandas as pd
import io

st.set_page_config(page_title="Calculateur Fantrax 2025", layout="wide")

st.title("🏒 Analyseur Fantrax : Act/Min & Gardiens (2025)")

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
            # 1. Lecture robuste (détection du header)
            content = fichier.getvalue().decode('utf-8-sig')
            lines = content.splitlines()

            start_line = 0
            for i, line in enumerate(lines):
                if any(kw in line for kw in ["Status", "Salary", "Player", "Pos"]):
                    start_line = i
                    break
            
            clean_content = "\n".join(lines[start_line:])
            df = pd.read_csv(io.StringIO(clean_content), sep=None, engine='python', on_bad_lines='skip')

            # 2. Identification des colonnes (Correction arg list error)
            def get_col_name(keywords):
                for k in keywords:
                    found = [c for c in df.columns if k.lower() in c.lower()]
                    if found: 
                        return str(found[0]) # Force le retour d'une chaîne de caractères unique
                return None

            c_player = get_col_name(['Player', 'Joueur'])
            c_pos    = get_col_name(['Pos', 'Position'])
            c_status = get_col_name(['Status', 'Statut'])
            c_salary = get_col_name(['Salary', 'Salaire'])
            c_nhl    = get_col_name(['Team', 'Équipe'])

            if not c_status or not c_salary:
                continue

            # 3. Nettoyage et Normalisation
            df[c_salary] = pd.to_numeric(
                df[c_salary].astype(str).replace(r'[\$,\s]', '', regex=True), 
                errors='coerce'
            ).fillna(0)

            # Identification simplifiée des positions (F, D, G)
            def simplify_pos(val):
                val = str(val).upper()
                if 'G' in val: return 'G'
                if 'D' in val: return 'D'
                return 'F'

            df['Pos_Group'] = df[c_pos].apply(simplify_pos)

            # Catégorisation Statut
            def categorize_status(val):
                val = str(val).strip()
                if "Min" in val: return "Min"
                if "Act" in val: return "Act"
                return "Autre"

            df['Catégorie'] = df[c_status].apply(categorize_status)
            
            # Filtrage des joueurs Actifs et Minors (incluant G)
            df_filtered = df[df['Catégorie'].isin(['Act', 'Min'])].copy()

            nom_proprio = fichier.name.replace('.csv', '')
            
            # 4. Création du DataFrame pour compilation
            res = pd.DataFrame({
                'Joueur': df_filtered[c_player],
                'P': df_filtered['Pos_Group'],
                'Position': df_filtered[c_pos],
                'Équipe NHL': df_filtered[c_nhl] if c_nhl else "N/A",
                'Salaire': df_filtered[c_salary],
                'Statut': df_filtered['Catégorie'],
                'Propriétaire': nom_proprio
            })
            all_players.append(res)

        except Exception as e:
            st.error(f"💥 Erreur avec {fichier.name} : {e}")

    if all_players:
        df_final = pd.concat(all_players)

        # --- AFFICHAGE ---
        tab1, tab2 = st.tabs(["📊 Résumé Global", "👤 Détails par Joueur"])

        with tab1:
            st.write("### Masse Salariale par Équipe")
            summary = df_final.pivot_table(index='Propriétaire', columns='Statut', values='Salaire', aggfunc='sum', fill_value=0).reset_index()
            st.dataframe(summary.style.format({'Act': '{:,.0f} $', 'Min': '{:,.0f} $'}), use_container_width=True, hide_index=True)

        with tab2:
            st.write("### Liste détaillée (F, D, G)")
            col_act, col_min = st.columns(2)

            def draw_table(df_sub, title):
                st.subheader(title)
                # Tri : Équipe -> Position (F, D, G) -> Salaire
                df_sorted = df_sub.sort_values(['Propriétaire', 'P', 'Salaire'], ascending=[True, True, False])
                st.dataframe(
                    df_sorted[['P', 'Joueur', 'Salaire', 'Propriétaire', 'Position']],
                    column_config={"Salaire": st.column_config.NumberColumn(format="$%d"), "P": st.column_config.TextColumn("P", width="small")},
                    use_container_width=True, hide_index=True
                )
                st.metric(f"Total {title}", f"{df_sub['Salaire'].sum():,.0f} $")

            with col_act:
                draw_table(df_final[df_final['Statut'] == 'Act'], "Joueurs ACTIFS")

            with col_min:
                draw_table(df_final[df_final['Statut'] == 'Min'], "Joueurs MINORS")

        st.divider()
        st.success(f"**Analyse terminée pour {len(fichiers_telecharges)} fichiers.**")
