import streamlit as st
import pandas as pd
import io
import os
from datetime import datetime
from streamlit_sortables import sort_items

st.set_page_config(page_title="Calculateur Fantrax 2025", layout="wide")

DB_FILE = "historique_fantrax_v2.csv"
PLAYERS_DB_FILE = "Hockey_Players.csv" # Nouveau fichier de base de données des joueurs

# --- FONCTIONS ---
def charger_historique():
    if os.path.exists(DB_FILE):
        return pd.read_csv(DB_FILE)
    return pd.DataFrame()

def charger_base_joueurs():
    if os.path.exists(PLAYERS_DB_FILE):
        df_base = pd.read_csv(PLAYERS_DB_FILE)
        # Assurer la cohérence des noms de colonnes pour la recherche
        df_base.rename(columns={'Player': 'Joueur', 'Salary': 'Salaire', 'Position': 'Pos'}, inplace=True)
        return df_base[['Joueur', 'Salaire', 'Pos']].copy()
    return pd.DataFrame(columns=['Joueur', 'Salaire', 'Pos'])

def sauvegarder_historique(df):
    df = df.drop_duplicates(subset=['Joueur', 'Propriétaire'], keep='last')
    df.to_csv(DB_FILE, index=False)
    return df

def format_currency(val):
    if pd.isna(val): return "0 $"
    return f"{int(val):,}".replace(",", " ") + "$"

def pos_sort_order(pos_text):
    pos = str(pos_text).upper()
    if 'G' in pos: return 2
    if 'D' in pos: return 1
    return 0 

# Initialisation des états
if 'historique' not in st.session_state:
    st.session_state['historique'] = charger_historique()

if 'base_joueurs' not in st.session_state:
    st.session_state['base_joueurs'] = charger_base_joueurs()

if 'buyouts' not in st.session_state:
    st.session_state['buyouts'] = {}

st.title("🏒 Analyseur Fantrax 2025")

# --- BARRE LATÉRALE (inchangée) ---
st.sidebar.header("⚙️ Configuration Globale")
CAP_GRAND_CLUB = st.sidebar.number_input("Plafond Grand Club ($)", value=95500000, step=500000)
CAP_CLUB_ECOLE = st.sidebar.number_input("Plafond Club École ($)", value=47750000, step=100000)

# --- LOGIQUE D'IMPORTATION FANTRAX (inchangée) ---
fichiers_telecharges = st.file_uploader("Importer des CSV Fantrax (Rosters)", type="csv", accept_multiple_files=True)
if fichiers_telecharges:
    dfs_a_ajouter = []
    horodatage = datetime.now().strftime("%d-%m %H:%M")
    for fichier in fichiers_telecharges:
        try:
            content = fichier.getvalue().decode('utf-8-sig')
            lines = content.splitlines()
            def extract_table(lines, keyword):
                idx = next((i for i, l in enumerate(lines) if keyword in l), -1)
                if idx == -1: return pd.DataFrame()
                h_idx = next((i for i in range(idx + 1, len(lines)) if any(kw in lines[i] for kw in ["ID", "Player", "Salary"])), -1)
                if h_idx == -1: return pd.DataFrame()
                df_raw = pd.read_csv(io.StringIO("\n".join(lines[h_idx:])), sep=None, engine='python', on_bad_lines='skip')
                if 'ID' in df_raw.columns:
                    df_raw = df_raw[df_raw['ID'].astype(str).str.strip().str.startswith(('0','1','2','3','4','5','6','7','8','9','*'))]
                return df_raw
            
            df_merged = pd.concat([extract_table(lines, 'Skaters'), extract_table(lines, 'Goalies')], ignore_index=True)
            c_player = next((c for c in df_merged.columns if 'player' in c.lower() or 'joueur' in c.lower()), None)
            c_status = next((c for c in df_merged.columns if 'status' in c.lower() or 'statut' in c.lower()), None)
            c_salary = next((c for c in df_merged.columns if 'salary' in c.lower() or 'salaire' in c.lower()), None)
            c_pos = next((c for c in df_merged.columns if 'pos' in c.lower() or 'eligible' in c.lower()), None)
            
            if c_status and c_salary and c_player:
                df_merged[c_salary] = pd.to_numeric(df_merged[c_salary].astype(str).replace(r'[\$,\s]', '', regex=True), errors='coerce').fillna(0) * 1000
                df_merged['Catégorie'] = df_merged[c_status].apply(lambda x: "Club École" if "MIN" in str(x).upper() else "Grand Club")
                nom_equipe = fichier.name.replace('.csv', '')
                
                temp_df = pd.DataFrame({
                    'Joueur': df_merged[c_player], 'Salaire': df_merged[c_salary], 'Statut': df_merged['Catégorie'],
                    'Pos': df_merged[c_pos] if c_pos else "N/A", 'Propriétaire': nom_equipe,
                    'pos_order': df_merged[c_pos].apply(pos_sort_order) if c_pos else 0
                })
                dfs_a_ajouter.append(temp_df)
        except Exception as e:
            st.error(f"Erreur sur {fichier.name}: {e}")

    if dfs_a_ajouter:
        nouveau_df = pd.concat([st.session_state['historique'], pd.concat(dfs_a_ajouter)], ignore_index=True)
        st.session_state['historique'] = sauvegarder_historique(nouveau_df)
        st.success("Importation terminée.")

# --- AFFICHAGE PRINCIPAL ---
if not st.session_state['historique'].empty:
    df_f = st.session_state['historique']
    tab1, tab2 = st.tabs(["📊 Tableau de Bord", "⚖️ Simulateur Avancé"]) 

    with tab1:
        summary = df_f.groupby(['Propriétaire', 'Statut'])['Salaire'].sum().unstack(fill_value=0).reset_index()
        st.dataframe(summary, use_container_width=True)

    with tab2:
        st.header("🔄 Outil de Transfert & Simulateur")
        equipe_choisie = st.selectbox("Équipe à simuler", options=sorted(df_f['Propriétaire'].unique()))
        
        # --- FORMULAIRE D'AJOUT DE JOUEUR AUTONOME ---
        st.subheader("➕ Ajouter un joueur autonome")
        if not st.session_state['base_joueurs'].empty:
            
            col_add1, col_add2 = st.columns([0.6, 0.4])
            with col_add1:
                joueur_selectionne = st.selectbox("Sélectionner le joueur", options=[None] + st.session_state['base_joueurs']['Joueur'].tolist(), key=f"sel_auto_player_{equipe_choisie}")
            
            if joueur_selectionne:
                data_joueur = st.session_state['base_joueurs'][st.session_state['base_joueurs']['Joueur'] == joueur_selectionne].iloc[0]
                
                with col_add2:
                    destination = st.selectbox("Assigner à", options=["Grand Club", "Club École"], key=f"sel_auto_dest_{equipe_choisie}")

                st.write(f"**Pos:** {data_joueur['Pos']} | **Salaire:** {format_currency(data_joueur['Salaire'])}")

                if st.button(f"Ajouter {joueur_selectionne} à {equipe_choisie}"):
                    nouvelle_entree = pd.DataFrame([{
                        'Joueur': data_joueur['Joueur'],
                        'Salaire': data_joueur['Salaire'],
                        'Statut': destination,
                        'Pos': data_joueur['Pos'],
                        'Propriétaire': equipe_choisie,
                        'pos_order': pos_sort_order(data_joueur['Pos']),
                        'Dernière Mise à jour': datetime.now().strftime("%d-%m %H:%M")
                    }])
                    # Ajout et sauvegarde immédiate pour mise à jour
                    st.session_state['historique'] = pd.concat([st.session_state['historique'], nouvelle_entree], ignore_index=True)
                    st.session_state['historique'] = sauvegarder_historique(st.session_state['historique'])
                    st.success(f"{joueur_selectionne} ajouté!")
                    st.rerun()
            
        else:
            st.warning("Le fichier Hockey_Players.csv est manquant ou vide.")

        st.markdown("---")
        
        # ... (Rachats et Drag and Drop inchangés) ...
        # --- SECTION DES RACHATS MULTIPLES (DÉDUCTION 50%) ---
        st.subheader(f"💰 Rachats de contrats (Multiples autorisés)")
        col_r1, col_r2 = st.columns(2)
        
        with col_r1:
            joueurs_gc_df = df_sim[df_sim['Statut'] == "Grand Club"]
            choix_gc_multi = st.multiselect("Joueurs à racheter (Grand Club)", options=joueurs_gc_df['Joueur'].tolist(), key=f"multi_gc_{equipe_choisie}")
            total_deduction_gc = joueurs_gc_df[joueurs_gc_df['Joueur'].isin(choix_gc_multi)]['Salaire'].sum() / 2
            if total_deduction_gc > 0: st.warning(f"Total déduit (GC) : -{format_currency(total_deduction_gc)}")
        with col_r2:
            joueurs_ce_df = df_sim[df_sim['Statut'] == "Club École"]
            choix_ce_multi = st.multiselect("Joueurs à racheter (Club École)", options=joueurs_ce_df['Joueur'].tolist(), key=f"multi_ce_{equipe_choisie}")
            total_deduction_ce = joueurs_ce_df[joueurs_ce_df['Joueur'].isin(choix_ce_multi)]['Salaire'].sum() / 2
            if total_deduction_ce > 0: st.warning(f"Total déduit (CE) : -{format_currency(total_deduction_ce)}")

        st.markdown("---")

        # --- DRAG AND DROP ---
        list_gc = [f"{r['Joueur']} ({r['Pos']}) - {format_currency(r['Salaire'])}" for _, r in df_sim[df_sim['Statut'] == "Grand Club"].iterrows()]
        list_ce = [f"{r['Joueur']} ({r['Pos']}) - {format_currency(r['Salaire'])}" for _, r in df_sim[df_sim['Statut'] == "Club École"].iterrows()]

        updated_sort = sort_items([{'header': '🏙️ GRAND CLUB', 'items': list_gc}, {'header': '🏫 CLUB ÉCOLE', 'items': list_ce}], multi_containers=True, direction='horizontal')
        
        col_gc_final = updated_sort['items'] if updated_sort else list_gc
        col_ce_final = updated_sort['items'] if updated_sort else list_ce

        def extract_salary(player_list):
            total = 0
            for item in player_list:
                try:
                    s_str = item.split('-')[-1].replace('$', '').replace(' ', '').replace(',', '').strip()
                    total += int(s_str)
                except: continue
            return total

        masse_gc_pure = extract_salary(col_gc_final)
        masse_ce_pure = extract_salary(col_ce_final)
        
        sim_g = masse_gc_pure - total_deduction_gc
        sim_c = masse_ce_pure - total_deduction_ce

        res1, res2 = st.columns(2)
        res1.metric("Masse Grand Club (Net)", format_currency(sim_g), delta=format_currency(CAP_GRAND_CLUB - sim_g), delta_color="normal" if sim_g <= CAP_GRAND_CLUB else "inverse")
        res2.metric("Masse Club École (Net)", format_currency(sim_c), delta=format_currency(CAP_CLUB_ECOLE - sim_c), delta_color="normal" if sim_c <= CAP_CLUB_ECOLE else "inverse")

        st.markdown("""<style>.stSortablesItem { background-color: #1E3A8A !important; color: white !important; border-radius: 5px !important; padding: 8px !important; margin-bottom: 5px !important; }</style>""", unsafe_allow_html=True)
else:
    st.info("Veuillez importer un fichier CSV Fantrax.")
