import streamlit as st
import pandas as pd
import io

st.set_page_config(page_title="Calculateur Fantrax 2025", layout="wide")

st.title("🏒 Analyseur Fantrax : Scan Complet Gardiens (Col E)")

fichiers_telecharges = st.file_uploader("Importez vos fichiers CSV Fantrax", type="csv", accept_multiple_files=True)

if fichiers_telecharges:
    all_players = []

    for fichier in fichiers_telecharges:
        try:
            content = fichier.getvalue().decode('utf-8-sig')
            lines = content.splitlines()

            # 1. Détection de la ligne d'en-tête
            start_line = 0
            for i, line in enumerate(lines):
                if any(kw in line for kw in ["Status", "Salary", "Player"]):
                    start_line = i
                    break
            
            clean_content = "\n".join(lines[start_line:])
            df = pd.read_csv(io.StringIO(clean_content), sep=None, engine='python', on_bad_lines='skip')

            # 2. Identification robuste des colonnes
            def get_col_name(keywords):
                for k in keywords:
                    found = [c for c in df.columns if k.lower() in c.lower()]
                    if found: return str(found[0]) # Retourne le premier nom exact trouvé
                return None

            c_player = get_col_name(['Player', 'Joueur'])
            c_status = get_col_name(['Status', 'Statut'])
            c_salary = get_col_name(['Salary', 'Salaire'])
            c_nhl    = get_col_name(['Team', 'Équipe'])
            
            # --- SCAN COLONNE E (INDEX 4) POUR LES GARDIENS ---
            # On définit c_pos comme étant la colonne E (index 4) par défaut si "Pos" n'est pas trouvé
            c_pos_name = get_col_name(['Eligible', 'Pos', 'Position'])
            if not c_pos_name and df.shape[1] >= 5:
                c_pos_name = df.columns[4] # Forçage manuel sur la Colonne E (Index 4)

            if not c_status or not c_salary or not c_pos_name:
                st.error(f"❌ Colonnes essentielles manquantes dans {fichier.name}")
                continue

            # 3. Nettoyage Salaire
            df[c_salary] = pd.to_numeric(
                df[c_salary].astype(str).replace(r'[\$,\s]', '', regex=True), 
                errors='coerce'
            ).fillna(0)

            # 4. SCAN COMPLET DE LA COLONNE E POUR DÉTECTER 'G'
            def detect_position(val):
                val = str(val).upper()
                if 'G' in val: return 'G'
                if 'D' in val: return 'D'
                return 'F' # Défaut pour Attaquants

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
            
            # 6. Assemblage
            res = pd.DataFrame({
                'Joueur': df_filtered[c_player],
                'P': df_filtered['P'],
                'Eligible': df_filtered[c_pos_name], # Affiche le contenu complet de la Col E
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

        tab1, tab2 = st.tabs(["📊 Résumé Global", "👤 Détails par Joueur"])

        with tab1:
            st.write("### Masse Salariale par Équipe")
            summary = df_final.pivot_table(index='Propriétaire', columns='Statut', values='Salaire', aggfunc='sum', fill_value=0).reset_index()
            st.dataframe(summary.style.format({'Act': '{:,.0f} $', 'Min': '{:,.0f} $'}), use_container_width=True, hide_index=True)

        with tab2:
            st.write("### Liste détaillée (F, D, G détectés en Col E)")
            col_act, col_min = st.columns(2)

            def draw_table(df_sub, title):
                st.subheader(title)
                # Tri : Propriétaire -> Position (F, D, G) -> Salaire
                df_sorted = df_sub.sort_values(['Propriétaire', 'P', 'Salaire'], ascending=[True, True, False])
                st.dataframe(
                    df_sorted[['P', 'Joueur', 'Salaire', 'Propriétaire', 'Eligible']],
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
        st.success(f"Analyse terminée le {st.session_state.get('date', '27 décembre 2025')}.")
