import streamlit as st
import pandas as pd
import io

st.set_page_config(page_title="Calculateur Fantrax 2025", layout="wide")

st.title("🏒 Analyseur Fantrax : Format 1 500 000 $")

# --- Champs de saisie ---
col_cap1, col_cap2 = st.columns(2)
with col_cap1:
    CAP_ACTIF = st.number_input("Plafond Salarial Actif ($)", min_value=0, value=95500000, step=500000)
with col_cap2:
    CAP_MINORS = st.number_input("Plafond Salarial Mineur ($)", min_value=0, value=47750000, step=100000)

fichiers_telecharges = st.file_uploader("Importez vos fichiers CSV Fantrax", type="csv", accept_multiple_files=True)

if fichiers_telecharges:
    all_players = []

    for fichier in fichiers_telecharges:
        try:
            content = fichier.getvalue().decode('utf-8-sig')
            lines = content.splitlines()

            def extract_table(lines, section_keyword):
                start_idx = next((i for i, line in enumerate(lines) if section_keyword in line), -1)
                if start_idx == -1: return pd.DataFrame()
                header_idx = next((i for i in range(start_idx, len(lines)) if any(k in lines[i] for k in ["Player", "Salary", "Status"])), -1)
                if header_idx == -1: return pd.DataFrame()
                raw_data = [l for l in lines[header_idx:] if "," in l and len(l.strip()) > 0]
                return pd.read_csv(io.StringIO("\n".join(raw_data)))

            df = pd.concat([extract_table(lines, 'Skaters'), extract_table(lines, 'Goalies')], ignore_index=True)
            
            # Identification des colonnes
            cols_found = {k: next((c for c in df.columns if k.lower() in c.lower()), None) 
                          for k in ['Player', 'Status', 'Salary', 'Pos']}

            if cols_found['Player'] and cols_found['Status'] and cols_found['Salary']:
                # Nettoyage et conversion numérique
                df[cols_found['Salary']] = pd.to_numeric(df[cols_found['Salary']].astype(str).replace(r'[\$,\s]', '', regex=True), errors='coerce').fillna(0)
                df['Catégorie'] = df[cols_found['Status']].apply(lambda x: "Min" if "MIN" in str(x).upper() else "Act")
                
                res = pd.DataFrame({
                    'Joueur': df[cols_found['Player']],
                    'Salaire': df[cols_found['Salary']],
                    'Statut': df['Catégorie'],
                    'Équipe': fichier.name.replace('.csv', '')
                })
                all_players.append(res)
        except Exception as e:
            st.error(f"Erreur avec {fichier.name}: {e}")

    if all_players:
        df_final = pd.concat(all_players)
        
        # --- CALCULS ---
        summary = df_final.groupby(['Équipe', 'Statut'])['Salaire'].sum().unstack(fill_value=0).reset_index()
        for col in ['Act', 'Min']:
            if col not in summary.columns: summary[col] = 0

        summary['Space Actif'] = CAP_ACTIF - summary['Act']
        summary['Space Minors'] = CAP_MINORS - summary['Min']

        # Fonction de formatage : 1 500 000 $
        def format_currency(val):
            return f"{val:,.0f}".replace(",", " ") + " $"

        # Style pour le rouge si négatif
        def color_negative(val):
            return 'color: red' if val < 0 else 'color: #00FF00'

        st.subheader("📊 Résumé de la Masse Salariale")
        
        styled_summary = summary.style.format({
            'Act': format_currency,
            'Min': format_currency,
            'Space Actif': format_currency,
            'Space Minors': format_currency
        }).applymap(color_negative, subset=['Space Actif', 'Space Minors'])

        st.dataframe(styled_summary, use_container_width=True, hide_index=True)

        st.divider()
        st.subheader("👤 Détails des Joueurs")
        
        # Formatage de la liste détaillée
        df_details = df_final.copy()
        st.dataframe(
            df_details[['Équipe', 'Joueur', 'Statut', 'Salaire']].sort_values(['Équipe', 'Salaire'], ascending=[True, False]),
            column_config={
                "Salaire": st.column_config.NumberColumn(format="%d $") # Note: Streamlit limite parfois le séparateur selon la locale, le formatage manuel ci-dessus est plus sûr pour le tableau principal.
            },
            use_container_width=True, 
            hide_index=True
        )
