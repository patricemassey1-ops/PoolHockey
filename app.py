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
    return f"{val:,.0f}".replace(",", " ") + " $"

# Logique de tri pour les positions (F=0, D=1, G=2)
def pos_sort_order(pos_text):
    pos = str(pos_text).upper()
    if 'G' in pos: return 2
    if 'D' in pos: return 1
    return 0  # F ou autres attaquants (LW, RW, C)

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

            # Extraction Skaters + Goalies
            df_skaters = extract_table(lines, 'Skaters')
            df_goalies = extract_table(lines, 'Goalies')
            df = pd.concat([df_skaters, df_goalies], ignore_index=True)

            def find_col_safe(keywords):
                for k in keywords:
                    found = [c for c in df.columns if k.lower() in c.lower()]
                    if found: return found[0] # Correction : retourne l'index 0 directement
                return None

            c_player = find_col_safe(['Player', 'Joueur'])
            c_status = find_col_safe(['Status', 'Statut'])
            c_salary = find_col_safe(['Salary', 'Salaire'])
            c_pos    = find_col_safe(['Eligible', 'Pos'])

            if c_status and c_salary and c_player:
                df[c_salary] = pd.to_numeric(df[c_salary].astype(str).replace(r'[\$,\s]', '', regex=True), errors='coerce').fillna(0)
                df['Catégorie'] = df[c_status].apply(lambda x: "Club École" if "MIN" in str(x).upper() else "Grand Club")
                
                res = pd.DataFrame({
                    'Joueur': df[c_player],
                    'Salaire': df[c_salary],
                    'Statut': df['Catégorie'],
                    'Pos': df[c_pos] if c_pos else "N/A",
                    'Propriétaire': fichier.name.replace('.csv', '')
                })
                # Ajouter l'ordre de tri pour la position
                res['pos_order'] = res['Pos'].apply(pos_sort_order)
                all_players.append(res)
        except Exception as e:
            st.error(f"Erreur avec {fichier.name}: {e}")

    if all_players:
        df_final = pd.concat(all_players)

        # --- RÉSUMÉ GLOBAL ---
        st.write("### 📊 Résumé des Équipes")
        summary = df_final.groupby(['Propriétaire', 'Statut'])['Salaire'].sum().unstack(fill_value=0).reset_index()
        
        for c in ['Grand Club', 'Club École']:
            if c not in summary.columns: summary[c] = 0

        summary['Total Grand Club'] = CAP_GRAND_CLUB - summary['Grand Club']
        summary['Total Club École'] = CAP_CLUB_ECOLE - summary['Club École']

        st.dataframe(
            summary.style.format({
                'Grand Club': format_currency, 
                'Club École': format_currency,
                'Total Grand Club': format_currency, 
                'Total Club École': format_currency,
            }).applymap(lambda v: 'color: red;' if v < 0 else 'color: #00FF00;', 
                        subset=['Total Grand Club', 'Total Club École']),
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
                    # Tri par pos_order (F, D, G) puis par Salaire décroissant
                    df_gc = df_eq[df_eq['Statut'] == 'Grand Club'].sort_values(['pos_order', 'Salaire'], ascending=[True, False])
                    st.table(df_gc[['Joueur', 'Pos', 'Salaire']].assign(
                        Salaire=df_gc['Salaire'].apply(format_currency)
                    ))
                    st.metric("Total Masse Grand Club", format_currency(df_gc['Salaire'].sum()))

                with col_ecole:
                    st.subheader("🎓 Club École")
                    # Tri par pos_order (F, D, G) puis par Salaire décroissant
                    df_ce = df_eq[df_eq['Statut'] == 'Club École'].sort_values(['pos_order', 'Salaire'], ascending=[True, False])
                    st.table(df_ce[['Joueur', 'Pos', 'Salaire']].assign(
                        Salaire=df_ce['Salaire'].apply(format_currency)
                    ))
                    st.metric("Total Masse Club École", format_currency(df_ce['Salaire'].sum()))
