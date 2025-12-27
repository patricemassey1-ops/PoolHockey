import streamlit as st
import pandas as pd
import io

st.set_page_config(page_title="Calculateur Fantrax 2025", layout="wide")
st.title("🏒 Analyseur Fantrax : Scan Complet Gardiens (F, D, G)")

fichiers_telecharges = st.file_uploader("Importez vos fichiers CSV Fantrax", type="csv", accept_multiple_files=True)

if fichiers_telecharges:
    all_players = []

    for fichier in fichiers_telecharges:
        try:
            content = fichier.getvalue().decode('utf-8-sig')
            lines = content.splitlines()

            # 1. Identification de la ligne d'en-tête réelle
            start_line = 0
            for i, line in enumerate(lines):
                if any(kw in line for kw in ["Status", "Salary", "Player"]):
                    start_line = i
                    break
            
            clean_content = "\n".join(lines[start_line:])
            df = pd.read_csv(io.StringIO(clean_content), sep=None, engine='python', on_bad_lines='skip')

            # 2. Identification des colonnes (Correction finale de l'erreur 'arg must be a list')
            def get_col_safe(keywords):
                for k in keywords:
                    found = [c for c in df.columns if k.lower() in c.lower()]
                    if found: return found[0] # Renvoie uniquement le premier String trouvé
                return None

            c_player = get_col_safe(['Player', 'Joueur'])
            c_status = get_col_safe(['Status', 'Statut'])
            c_salary = get_col_safe(['Salary', 'Salaire'])
            c_nhl    = get_col_safe(['Team', 'Équipe'])
            c_pos    = get_col_safe(['Eligible', 'Pos', 'Position'])

            # Sécurité si Pos (Col E) n'a pas de nom mais existe physiquement
            if not c_pos and df.shape[1] >= 5:
                c_pos = df.columns[4]

            if not c_status or not c_salary or not c_player:
                st.error(f"❌ Données critiques manquantes dans {fichier.name}")
                continue

            # 3. Nettoyage Salaire
            df[c_salary] = pd.to_numeric(
                df[c_salary].astype(str).replace(r'[\$,\s]', '', regex=True), 
                errors='coerce'
            ).fillna(0)

            # 4. Scan exhaustif des positions (G, D, F)
            def scan_pos(val):
                text = str(val).upper().strip()
                if 'G' in text: return 'G'
                if 'D' in text: return 'D'
                return 'F'

            df['P'] = df[c_pos].apply(scan_pos)

            # 5. Catégorisation Statut
            def categorize(val):
                val = str(val).strip()
                if "Min" in val: return "Min"
                if "Act" in val: return "Act"
                return "Autre"

            df['Cat'] = df[c_status].apply(categorize)
            df_filtered = df[df['Cat'].isin(['Act', 'Min'])].copy()

            nom_proprio = fichier.name.replace('.csv', '')
            
            # 6. Assemblage
            res = pd.DataFrame({
                'P': df_filtered['P'],
                'Joueur': df_filtered[c_player],
                'Salaire': df_filtered[c_salary],
                'Statut': df_filtered['Cat'],
                'Propriétaire': nom_proprio,
                'Position Éligible': df_filtered[c_pos] # Garde la colonne pour vérification
            })
            all_players.append(res)

        except Exception as e:
            st.error(f"💥 Erreur avec {fichier.name} : {e}")

    if all_players:
        df_final = pd.concat(all_players)

        tab1, tab2 = st.tabs(["📊 Résumé Global", "👤 Détails par Joueur"])

        with tab1:
            st.write("### Masse Salariale par Équipe")
            summary = df_final.pivot_table(index='Propriétaire', columns='Statut', values='Salaire', aggfunc='sum', fill_value=0).reset_index()
            st.dataframe(summary.style.format({'Act': '{:,.0f} $', 'Min': '{:,.0f} $'}), use_container_width=True, hide_index=True)

        with tab2:
            st.write("### Liste des Joueurs (Tri par Position F, D, G)")
            col_act, col_min = st.columns(2)

            def draw_table(df_sub, title):
                st.subheader(title)
                # Tri : Équipe -> Position (F, D, G) -> Salaire décroissant
                df_sorted = df_sub.sort_values(['Propriétaire', 'P', 'Salaire'], ascending=[True, True, False])
                st.dataframe(
                    df_sorted[['P', 'Joueur', 'Salaire', 'Propriétaire', 'Position Éligible']],
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
        st.success(f"Analyse terminée pour la saison 2025. Tous les gardiens (G) sont détectés.")
