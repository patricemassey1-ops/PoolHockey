import streamlit as st
import pandas as pd
import io
import os
from streamlit_sortables import sort_items

# 1. CONFIGURATION & CACHE
st.set_page_config(page_title="Simulateur Fantrax 2025", layout="wide")

DB_FILE = "historique_fantrax_v2.csv"
BUYOUT_FILE = "rachats_v2.csv"

@st.cache_data
def load_data(file, columns):
    if os.path.exists(file):
        try: return pd.read_csv(file)
        except: return pd.DataFrame(columns=columns)
    return pd.DataFrame(columns=columns)

if 'historique' not in st.session_state:
    st.session_state.historique = load_data(DB_FILE, ['Joueur', 'Salaire', 'Statut', 'Pos', 'Equipe_NHL', 'Propriétaire'])
if 'rachats' not in st.session_state:
    st.session_state.rachats = load_data(BUYOUT_FILE, ['Propriétaire', 'Joueur', 'Impact'])

def format_currency(val):
    return f"{int(val):,}".replace(",", " ") + "$" if val else "0$"

def save_all():
    st.session_state.historique.to_csv(DB_FILE, index=False)
    st.session_state.rachats.to_csv(BUYOUT_FILE, index=False)

# 2. IMPORTATION (BARRE LATÉRALE)
with st.sidebar:
    st.header("⚙️ Paramètres 2025")
    cap_gc = st.number_input("Plafond Grand Club", value=95500000, step=500000)
    cap_ce = st.number_input("Plafond Club École", value=47750000, step=100000)
    
    files = st.sidebar.file_uploader("Importer CSV Fantrax", accept_multiple_files=True)
    if files and st.sidebar.button("Lancer l'importation"):
        all_new = []
        for f in files:
            content = f.getvalue().decode('utf-8-sig').splitlines()
            idx = next((i for i, l in enumerate(content) if any(x in l for x in ['Skaters', 'Goalies', 'Player'])), -1)
            if idx != -1:
                df = pd.read_csv(io.StringIO("\n".join(content[idx+1:])), sep=None, engine='python', on_bad_lines='skip')
                col_p = next((c for c in df.columns if 'player' in c.lower()), "Player")
                col_s = next((c for c in df.columns if 'salary' in c.lower()), "Salary")
                col_st = next((c for c in df.columns if 'status' in c.lower()), "Status")
                col_tm = next((c for c in df.columns if 'team' in c.lower()), "Team")
                
                df['Sal_Clean'] = pd.to_numeric(df[col_s].astype(str).str.replace(r'[^\d]', '', regex=True), errors='coerce').fillna(0)
                df.loc[df['Sal_Clean'] < 100000, 'Sal_Clean'] *= 1000
                
                temp = pd.DataFrame({
                    'Joueur': df[col_p],
                    'Salaire': df['Sal_Clean'],
                    'Statut': df[col_st].apply(lambda x: "Club École" if "MIN" in str(x).upper() else "Grand Club") if col_st in df.columns else "Grand Club",
                    'Pos': df['Pos'] if 'Pos' in df.columns else "N/A",
                    'Equipe_NHL': df[col_tm] if col_tm in df.columns else "N/A",
                    'Propriétaire': f.name.replace('.csv', '')
                })
                all_new.append(temp)
        if all_new:
            st.session_state.historique = pd.concat([st.session_state.historique] + all_new).drop_duplicates(subset=['Joueur', 'Propriétaire'], keep='last')
            save_all()
            st.rerun()

# 3. ONGLETS
tab1, tab2, tab3 = st.tabs(["📊 Dashboard", "⚖️ Simulateur", "🛠️ Gestion"])

# --- DASHBOARD ---
with tab1:
    if not st.session_state.historique.empty:
        df = st.session_state.historique
        stats = df.groupby(['Propriétaire', 'Statut'])['Salaire'].sum().unstack(fill_value=0).reset_index()
        r_sum = st.session_state.rachats.groupby('Propriétaire')['Impact'].sum().reset_index()
        stats = stats.merge(r_sum, on='Propriétaire', how='left').fillna(0)
        for c in ['Grand Club', 'Club École', 'Impact']: 
            if c not in stats.columns: stats[c] = 0
        stats['Total GC'] = stats['Grand Club'] + stats['Impact']
        stats['Espace GC'] = cap_gc - stats['Total GC']
        st.dataframe(stats.style.format(format_currency, subset=['Grand Club', 'Club École', 'Impact', 'Total GC', 'Espace GC']), use_container_width=True)

# --- TAB 2: SIMULATEUR (VERSION CORRIGÉE) ---
with tab2:
    teams = sorted(st.session_state.historique['Propriétaire'].unique()) if not st.session_state.historique.empty else []
    if teams:
        eq = st.selectbox("Sélectionner une équipe", teams, key="sim_selector")
        
        # Nettoyage pour éviter l'erreur JSON NaN
        dff = st.session_state.historique[st.session_state.historique['Propriétaire'] == eq].copy().fillna("N/A")
        
        # Label pour le Drag & Drop
        dff['label'] = dff['Joueur'].astype(str) + " | " + dff['Pos'].astype(str) + " | " + dff['Salaire'].apply(lambda x: f"{int(x/1000)}k")
        
        l_gc = dff[dff['Statut'] == "Grand Club"]['label'].tolist()
        l_ce = dff[dff['Statut'] == "Club École"]['label'].tolist()

        # res renvoie : [ [items_GC], [items_Ecole] ]
        res = sort_items([
            {'header': '🏙️ GRAND CLUB', 'items': l_gc}, 
            {'header': '🏫 CLUB ÉCOLE', 'items': l_ce}
        ], multi_containers=True, key=f"sim_v2025_{eq}")

        def quick_sum(items_list):
            """Calcule la somme des salaires à partir des labels du simulateur"""
            if not items_list or not isinstance(items_list, list): 
                return 0
            total = 0
            for x in items_list:
                if isinstance(x, str) and '|' in x:
                    try:
                        # On récupère la valeur en 'k' à la fin du label
                        val_k = x.split('|')[-1].replace('k','').strip()
                        total += int(val_k) * 1000
                    except:
                        continue
            return total
        
        # CORRECTION DE L'INDEXATION ICI
        # Si res existe, on prend l'index 0 pour GC et 1 pour École
        if res and isinstance(res, list) and len(res) >= 2:
            s_gc_joueurs = quick_sum(res[0]) # Liste du 1er conteneur (GC)
            s_ce_joueurs = quick_sum(res[1]) # Liste du 2e conteneur (École)
        else:
            # Valeurs par défaut si le composant n'a pas encore bougé
            s_gc_joueurs = quick_sum(l_gc)
            s_ce_joueurs = quick_sum(l_ce)
        
        # Récupération des pénalités (Rachats + JA)
        p_imp = st.session_state.rachats[st.session_state.rachats['Propriétaire'] == eq]['Impact'].sum()
        
        st.divider()
        c1, c2, c3 = st.columns(3)
        c1.metric("Masse GC (+ Pénalités)", format_currency(s_gc_joueurs + p_imp), delta=format_currency(cap_gc - (s_gc_joueurs + p_imp)))
        c2.metric("Masse Club École", format_currency(s_ce_joueurs))
        c3.metric("Total Pénalités (50%)", format_currency(p_imp))


# --- GESTION (EMBAUCHE & RACHAT) ---
with tab3:
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("🆕 Embaucher un Joueur Autonome")
        with st.form("fa_form"):
            new_prop = st.selectbox("Équipe Fantrax", teams if teams else ["Ma Ligue"])
            new_nom = st.text_input("Nom du Joueur")
            col_a, col_b = st.columns(2)
            new_pos = col_a.selectbox("Position", ["C", "LW", "RW", "D", "G", "F"])
            new_nhl = col_b.text_input("Équipe NHL (Ex: EDM)")
            new_sal = st.number_input("Salaire ($)", min_value=0, step=100000)
            new_stat = st.radio("Assignation", ["Grand Club", "Club École"], horizontal=True)
            
            if st.form_submit_button("Ajouter à l'effectif"):
                if new_nom:
                    new_row = pd.DataFrame([{
                        'Joueur': new_nom, 'Salaire': new_sal, 'Statut': new_stat,
                        'Pos': new_pos, 'Equipe_NHL': new_nhl.upper(), 'Propriétaire': new_prop
                    }])
                    st.session_state.historique = pd.concat([st.session_state.historique, new_row], ignore_index=True)
                    save_all()
                    st.success(f"{new_nom} a rejoint {new_prop}")
                    st.rerun()

    with col2:
        st.subheader("📉 Rachat de contrat (Pénalité 50%)")
        if teams:
            with st.form("buyout_form"):
                t_sel = st.selectbox("Équipe", teams)
                j_df = st.session_state.historique[st.session_state.historique['Propriétaire'] == t_sel]
                # On affiche le détail dans la liste de rachat aussi
                j_list = {f"{r['Joueur']} ({r['Pos']} - {r['Equipe_NHL']}) | {format_currency(r['Salaire'])}": r['Joueur'] for _, r in j_df.iterrows()}
                j_sel_label = st.selectbox("Sélectionner le joueur", list(j_list.keys()) if j_list else ["Aucun joueur"])
                
                if st.form_submit_button("Confirmer le rachat"):
                    if j_list:
                        j_real_name = j_list[j_sel_label]
                        sal = j_df[j_df['Joueur'] == j_real_name]['Salaire'].values
                        # Ajouter pénalité
                        new_r = pd.DataFrame([{'Propriétaire': t_sel, 'Joueur': j_real_name, 'Impact': int(sal * 0.5)}])
                        st.session_state.rachats = pd.concat([st.session_state.rachats, new_r], ignore_index=True)
                        # Supprimer le joueur
                        st.session_state.historique = st.session_state.historique[~((st.session_state.historique.Joueur == j_real_name) & (st.session_state.historique.Propriétaire == t_sel))]
                        save_all()
                        st.rerun()

st.markdown("""<style>.stSortablesItem { background-color: #1E3A8A !important; color: white !important; font-size: 13px !important; }</style>""", unsafe_allow_html=True)
