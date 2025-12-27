import streamlit as st
import pandas as pd
import io

st.set_page_config(page_title="Calculateur Fantrax 2025", layout="wide")

st.title("🏒 Analyseur Fantrax : Nettoyage & Scan Exhaustif")

# --- ÉTAPE 1 : BOUTON D'IMPORTATION ---
st.write("### 1. Importez vos fichiers pour nettoyage et calcul")
fichiers_telecharges = st.file_uploader("Choisir les fichiers CSV Fantrax", type="csv", accept_multiple_files=True)

if fichiers_telecharges:
    all_players = []

    for fichier in fichiers_telecharges:
        try:
            # --- ÉTAPE 2 : SUPPRESSION DES LIGNES VIDES ---
            # Lecture brute du contenu
            content = fichier.getvalue().decode('utf-8-sig')
            lines = content.splitlines()

            # On détecte l'en-tête pour savoir où commencer
            start_line = 0
            for i, line in enumerate(lines):
                if any(kw in line for kw in ["Status", "Salary", "Player"]):
                    start_line = i
                    break
            
            # Filtrage : On garde la ligne SI elle n'est pas vide ET SI elle contient des données
            raw_data_lines = lines[start_line:]
            filtered_lines = [
                line for line in raw_data_lines 
                if line.strip() and any(cell.strip() for cell in line.split(','))
            ]
            
            if not filtered_lines:
                st.warning(f"Le fichier {fichier.name} semble vide après nettoyage.")
                continue

            # Reconstruction pour Pandas
            clean_content = "\n".join(filtered_lines)
            
            # --- ÉTAPE 3 : ANALYSE DES DONNÉES ---
            df = pd.read_csv(io.StringIO(clean_content), sep=None, engine='python', on_bad_lines='skip')
            
            # On prend les 70 premières lignes réelles (sans les trous)
            df = df.head(70)

            # Identification sécurisée des colonnes
            def find_col_safe(keywords):
                for k in keywords:
                    found = [c for c in df.columns if k.lower() in c.lower()]
                    if found: return str(found[0]) # Extraction du nom exact
                return None

            c_player = find_col_safe(['Player', 'Joueur'])
            c_status = find_col_safe(['Status', 'Statut'])
            c_salary = find_col_safe(['Salary', 'Salaire'])
            c_pos    = find_col_safe(['Eligible', 'Pos', 'Position'])

            # Sécurité Colonne E (index 4)
            if not c_pos and df.shape[1] >= 5:
                c_pos = df.columns[4]

            if not c_status or not c_salary or not c_player:
                st.error(f"❌ Colonnes manquantes dans {fichier.name}")
                continue

            # Nettoyage Salaire
            df[c_salary] = pd.to_numeric(
                df[c_salary].astype(str).replace(r'[\$,\s]', '', regex=True), 
                errors='coerce'
            ).fillna(0)

            # Scan Position (F, D, G)
            def scan_pos(val):
                text = str(val).upper().strip()
                if 'G' in text: return 'G'
                if 'D' in text: return 'D'
                return 'F'

            df['P'] = df[c_pos].apply(scan_pos)

            # Catégorisation Statut
            def categorize_status(val):
                val = str(val).strip()
                if "Min" in val: return "Min"
                if "Act" in val: return "Act"
                return "Autre"

            df['Catégorie'] = df[c_status].apply(categorize_status)
            df_filtered = df[df['Catégorie'].isin(['Act', 'Min'])].copy()

            nom_proprio = fichier.name.replace('.csv', '')
            
            # Compilation
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
            st.error(f"💥 Erreur critique avec {fichier.name} : {e}")

    # --- ÉTAPE 4 : AFFICHAGE DES RÉSULTATS ---
    if all_players:
        df_final = pd.concat(all_players)

        tab1, tab2 = st.tabs(["📊 Masse Salariale", "👤 Détails Joueurs"])

        with tab1:
            st.write("### Résumé par Équipe")
            summary = df_final.pivot_table(index='Propriétaire', columns='Statut', values='Salaire', aggfunc='sum', fill_value=0).reset_index()
            st.dataframe(summary.style.format({'Act': '{:,.0f} $', 'Min': '{:,.0f} $'}), use_container_width=True, hide_index=True)

        with tab2:
            st.write("### Liste des joueurs (Positions F, D, G détectées)")
            col_act, col_min = st.columns(2)

            def draw_table(df_sub, title):
                st.subheader(title)
                # Tri : Équipe -> Position -> Salaire
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
        st.success("Nettoyage et analyse terminés. Les lignes vides ont été ignorées.")
