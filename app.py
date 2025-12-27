import streamlit as st
import pandas as pd
import io

st.set_page_config(page_title="Calculateur Fantrax 2025", layout="wide")

st.title("🏒 Analyseur Fantrax : Grand Club & Club École")

# --- Configuration des plafonds salariaux ---
col_cap1, col_cap2 = st.columns(2)
with col_cap1:
    CAP_GRAND_CLUB = st.number_input("Plafond Grand Club ($)", min_value=0, value=95500000, step=1000000)
with col_cap2:
    CAP_CLUB_ECOLE = st.number_input("Plafond Club École ($)", min_value=0, value=47750000, step=100000)

fichiers_telecharges = st.file_uploader("Importez vos fichiers CSV Fantrax", type="csv", accept_multiple_files=True)

# Fonction de formatage : 1 500 000 $
def format_currency(val):
    if pd.isna(val):
        return "0 $"
    return f"{int(val):,}".replace(",", " ") + " $"

# Logique de tri pour les positions (F=0, D=1, G=2)
def pos_sort_order(pos_text):
    pos = str(pos_text).upper()
    if 'G' in pos: return 2
    if 'D' in pos: return 1
    return 0

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
                header_line_index = next((i for i in range(start_line_index + 1, len(lines)) if any(kw in lines[i] for kw in ["ID", "Player", "Status", "Salary"])), -1)
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
                # Nettoyage et multiplication par 1000 pour ajouter "000"
                df[c_salary] = pd.to_numeric(df[c_salary].astype(str).replace(r'[\$,\s]', '', regex=True), errors='coerce').fillna(0) * 1000
                df['Catégorie'] = df[c_status].apply(lambda x: "Club École" if "MIN" in str(x).upper() else "Grand Club")
                
                res = pd.DataFrame({
                    'Joueur': df[c_player], 'Salaire': df[c_salary], 'Statut': df['Catégorie'],
                    'Pos': df[c_pos] if c_pos else "N/A", 'Propriétaire': fichier.name.replace('.csv', '')
                })
                res['pos_order'] = res['Pos'].apply(pos_sort_order)
                all_players.append(res)
        except Exception as e:
            st.error(f"Erreur avec {fichier.name}: {e}")

    if all_players:
        df_final = pd.concat(all_players)

        # --- RÉSUMÉ GLOBAL : AFFICHE SEULEMENT LES TOTAUS BRUTS ---
        st.write("### 📊 Résumé des Masses Salariales Brutes")
        summary = df_final.groupby(['Propriétaire', 'Statut'])['Salaire'].sum().unstack(fill_value=0).reset_index()
        
        for c in ['Grand Club', 'Club École']:
            if c not in summary.columns: summary[c] = 0

        # On renomme simplement les colonnes existantes pour l'affichage final
        summary = summary.rename(columns={
            'Grand Club': 'Masse Salariale Grand Club',
            'Club École': 'Masse Salariale Club École'
        })
        
        st.dataframe(
            summary[['Propriétaire', 'Masse Salariale Grand Club', 'Masse Salariale Club École']].style.format({
                'Masse Salariale Grand Club': format_currency, 
                'Masse Salariale Club École': format_currency,
            }),
            use_container_width=True, hide_index=True
        )

        st.divider()

        # --- DÉTAILS PAR ÉQUIPE ---
        st.write("### 👤 Détails des Effectifs par Propriétaire")
        equipes = sorted(df_final['Propriétaire'].unique())
        
        for eq in equipes:
            with st.expander(f"📂 Équipe : {eq}"):
                col_grand, col_ecole = st.columns(2)
                df_eq = df_final[df_final['Propriétaire'] == eq]
                
                with col_grand:
                    st.subheader("⭐ Grand Club")
                    df_gc = df_eq[df_eq['Statut'] == 'Grand Club'].sort_values(['pos_order', 'Salaire'], ascending=[True, False])
                    st.table(df_gc[['Joueur', 'Pos', 'Salaire']].assign(Salaire=df_gc['Salaire'].apply(format_currency)))
                    st.metric("Masse Grand Club", format_currency(df_gc['Salaire'].sum()))

                with col_ecole:
                    st.subheader("🎓 Club École")
                    df_ce = df_eq[df_eq['Statut'] == 'Club École'].sort_values(['pos_order', 'Salaire'], ascending=[True, False])
                    st.table(df_ce[['Joueur', 'Pos', 'Salaire']].assign(Salaire=df_ce['Salaire'].apply(format_currency)))
                    st.metric("Masse Club École", format_currency(df_ce['Salaire'].sum()))
