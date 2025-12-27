import streamlit as st
import pandas as pd
import io

st.set_page_config(page_title="Calculateur Fantrax 2025", layout="wide")

st.title("🏒 Analyseur Fantrax : Détails par Équipe")

# --- Configuration des plafonds ---
col_cap1, col_cap2 = st.columns(2)
with col_cap1:
    CAP_ACTIF = st.number_input("Plafond Salarial Actif ($)", min_value=0, value=95500000, step=1000000)
with col_cap2:
    CAP_MINORS = st.number_input("Plafond Salarial Mineur ($)", min_value=0, value=47750000, step=100000)

fichiers_telecharges = st.file_uploader("Importez vos fichiers CSV Fantrax", type="csv", accept_multiple_files=True)

def format_currency(val):
    return f"{val:,.0f}".replace(",", " ") + " $"

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

                raw_data_lines = lines[header_line_index:]
                df = pd.read_csv(io.StringIO("\n".join(raw_data_lines)), sep=None, engine='python', on_bad_lines='skip')
                
                if 'ID' in df.columns:
                    df = df[df['ID'].astype(str).str.strip().str.startswith(('0', '1', '2', '3', '4', '5', '6', '7', '8', '9', '*'))]
                return df

            df_skaters = extract_table(lines, 'Skaters')
            df_goalies = extract_table(lines, 'Goalies')
            df = pd.concat([df_skaters, df_goalies], ignore_index=True)
            
            def find_col_safe(keywords):
                for k in keywords:
                    found = [c for c in df.columns if k.lower() in c.lower()]
                    if found: return found[0]
                return None

            c_player = find_col_safe(['Player', 'Joueur'])
            c_status = find_col_safe(['Status', 'Statut'])
            c_salary = find_col_safe(['Salary', 'Salaire'])
            c_pos    = find_col_safe(['Eligible', 'Pos'])

            if c_status and c_salary and c_player:
                df[c_salary] = pd.to_numeric(df[c_salary].astype(str).replace(r'[\$,\s]', '', regex=True), errors='coerce').fillna(0)
                df['Catégorie'] = df[c_status].apply(lambda x: "Min" if "MIN" in str(x).upper() else "Act")
                
                res = pd.DataFrame({
                    'Joueur': df[c_player],
                    'Salaire': df[c_salary],
                    'Statut': df['Catégorie'],
                    'Pos': df[c_pos] if c_pos else "N/A",
                    'Propriétaire': fichier.name.replace('.csv', '')
                })
                all_players.append(res)
        except Exception as e:
            st.error(f"Erreur avec {fichier.name}: {e}")

    if all_players:
        df_final = pd.concat(all_players)

        # --- TABLEAU RÉSUMÉ GLOBAL ---
        st.write("### 📊 Résumé des Masses Salariales")
        summary = df_final.groupby(['Propriétaire', 'Statut'])['Salaire'].sum().unstack(fill_value=0).reset_index()
        for c in ['Act', 'Min']:
            if c not in summary.columns: summary[c] = 0

        summary['Space Actif'] = CAP_ACTIF - summary['Act']
        summary['Space Mineur'] = CAP_MINORS - summary['Min']

        st.dataframe(
            summary.style.format({
                'Act': format_currency, 'Min': format_currency,
                'Space Actif': format_currency, 'Space Mineur': format_currency,
            }).applymap(lambda v: 'color: red;' if v < 0 else 'color: #00FF00;', 
                        subset=['Space Actif', 'Space Mineur']),
            use_container_width=True, hide_index=True
        )

        st.divider()

        # --- DÉTAILS PAR ÉQUIPE ---
        st.write("### 👤 Détails des Effectifs par Équipe")
        
        # On boucle sur chaque équipe unique
        equipes = sorted(df_final['Propriétaire'].unique())
        
        for eq in equipes:
            with st.expander(f"📂 Équipe : {eq}"):
                col_act, col_min = st.columns(2)
                
                df_equipe = df_final[df_final['Propriétaire'] == eq]
                
                with col_act:
                    st.markdown("**🏒 Joueurs Actifs**")
                    df_act = df_equipe[df_equipe['Statut'] == 'Act'].sort_values('Salaire', ascending=False)
                    # Affichage avec formatage
                    st.table(df_act[['Joueur', 'Pos', 'Salaire']].assign(
                        Salaire=df_act['Salaire'].apply(format_currency)
                    ))
                    st.metric("Sous-total Actif", format_currency(df_act['Salaire'].sum()))

                with col_min:
                    st.markdown("**👶 Joueurs Mineurs**")
                    df_min = df_equipe[df_equipe['Statut'] == 'Min'].sort_values('Salaire', ascending=False)
                    st.table(df_min[['Joueur', 'Pos', 'Salaire']].assign(
                        Salaire=df_min['Salaire'].apply(format_currency)
                    ))
                    st.metric("Sous-total Mineur", format_currency(df_min['Salaire'].sum()))

        st.success("Analyse terminée. Les totaux par équipe sont calculés séparément.")
