import streamlit as st
import pandas as pd
import io
import os
from datetime import datetime
from zoneinfo import ZoneInfo

# --- CONFIGURATION ---
st.set_page_config(page_title="Calculateur Fantrax 2025", layout="wide")

DB_FILE = "historique_fantrax_v2.csv"
BUYOUT_FILE = "rachats_v2.csv"
PLAYERS_DB_FILE = "Hockey_Players.csv"
EQUIPE_FILE = "equipes_joueurs.csv"  # Fichier pour stocker les équipes

# PLAFONDS SALARIAUX (par défaut)
DEFAULT_PLAFOND_GRAND_CLUB = 95_500_000
DEFAULT_PLAFOND_CLUB_ECOLE = 47_750_000

# --- FONCTIONS DE CHARGEMENT / SAUVEGARDE ---
@st.cache_data(ttl=3600, show_spinner=False)
def charger_donnees(file, columns):
    if os.path.exists(file):
        df = pd.read_csv(file, dtype={'Salaire': 'float64'}).fillna(0)
        return df.drop_duplicates()
    return pd.DataFrame(columns=columns)

def sauvegarder_donnees(df, file):
    df.drop_duplicates().to_csv(file, index=False)
    charger_donnees.clear()

def format_currency(val):
    if pd.isna(val) or val == "": 
        return "0 $"
    try:
        return f"{int(float(val)):,}".replace(",", " ") + " $"
    except:
        return "0 $"

@st.cache_data(ttl=3600, show_spinner=False)
def charger_db_joueurs():
    """Charge la base de données des joueurs avec cache"""
    if os.path.exists(PLAYERS_DB_FILE):
        df_players = pd.read_csv(PLAYERS_DB_FILE, dtype={'Salaire': 'float64'})
        df_players.rename(columns={'Player': 'Joueur', 'Salary': 'Salaire', 'Position': 'Pos', 'Team': 'Equipe_NHL'}, inplace=True, errors='ignore')
        
        df_players['Salaire'] = pd.to_numeric(df_players['Salaire'], errors='coerce').fillna(0)
        df_players = df_players.drop_duplicates(subset=['Joueur', 'Equipe_NHL'])
        
        df_players['search_label'] = (
            df_players['Joueur'].astype(str) + 
            " (" + df_players['Equipe_NHL'].astype(str).fillna("N/A") + ") - " + 
            df_players['Salaire'].apply(format_currency)
        )
        return df_players
    return pd.DataFrame()

# Initialisation de la session (optimisée)
if 'historique' not in st.session_state:
    st.session_state['historique'] = charger_donnees(DB_FILE, ['Joueur', 'Salaire', 'Statut', 'Pos', 'Equipe', 'Propriétaire', 'pos_order'])
    # Nettoyer les données invalides au chargement
    if not st.session_state['historique'].empty:
        st.session_state['historique'] = st.session_state['historique'][
            (st.session_state['historique']['Joueur'].notna()) & 
            (st.session_state['historique']['Joueur'].astype(str).str.strip() != '') &
            (st.session_state['historique']['Joueur'].astype(str).str.strip() != '0') &
            (st.session_state['historique']['Joueur'].astype(str) != 'nan')
        ]
        # Ajouter colonne Equipe si elle n'existe pas
        if 'Equipe' not in st.session_state['historique'].columns:
            st.session_state['historique']['Equipe'] = 'N/A'

if 'rachats' not in st.session_state:
    st.session_state['rachats'] = charger_donnees(BUYOUT_FILE, ['Propriétaire', 'Joueur', 'Impact'])

if 'db_joueurs' not in st.session_state:
    st.session_state['db_joueurs'] = charger_db_joueurs()

# --- LOGIQUE D'IMPORTATION ---
st.sidebar.header("⚙️ Configuration")

# Formater l'affichage des plafonds dans les inputs
plafond_gc_display = st.sidebar.text_input(
    "💰 Plafond Grand Club", 
    value=f"{DEFAULT_PLAFOND_GRAND_CLUB:,}".replace(",", " ") + " $",
    key="plafond_gc_input"
)
plafond_ce_display = st.sidebar.text_input(
    "🎓 Plafond Club École", 
    value=f"{DEFAULT_PLAFOND_CLUB_ECOLE:,}".replace(",", " ") + " $",
    key="plafond_ce_input"
)

# Convertir les valeurs formatées en nombres
try:
    PLAFOND_GRAND_CLUB = int(plafond_gc_display.replace(" ", "").replace("$", "").replace(",", ""))
except:
    PLAFOND_GRAND_CLUB = DEFAULT_PLAFOND_GRAND_CLUB
    
try:
    PLAFOND_CLUB_ECOLE = int(plafond_ce_display.replace(" ", "").replace("$", "").replace(",", ""))
except:
    PLAFOND_CLUB_ECOLE = DEFAULT_PLAFOND_CLUB_ECOLE

st.sidebar.divider()

fichiers_telecharges = st.sidebar.file_uploader("📥 Importer CSV Fantrax", type="csv", accept_multiple_files=True)

if fichiers_telecharges:
    # Barre de progression
    progress_bar = st.sidebar.progress(0)
    status_text = st.sidebar.empty()
    
    status_text.text("⏳ Début de l'import...")
    progress_bar.progress(10)
    
    dfs_a_ajouter = []
    # Utiliser le fuseau horaire de Montréal
    montreal_tz = ZoneInfo("America/Montreal")
    horodatage = datetime.now(montreal_tz).strftime("%d-%m %H:%M")
    
    status_text.text("📂 Lecture des fichiers...")
    progress_bar.progress(30)
    
    for idx, fichier in enumerate(fichiers_telecharges):
        try:
            content = fichier.getvalue().decode('utf-8-sig')
            lines = content.splitlines()

            def extract_table(lines, keyword):
                idx = next((i for i, l in enumerate(lines) if keyword in l), -1)
                if idx == -1: return pd.DataFrame()
                h_idx = next((i for i in range(idx + 1, len(lines)) if any(kw in lines[i] for kw in ["ID", "Player", "Salary"])), -1)
                if h_idx == -1: return pd.DataFrame()
                return pd.read_csv(io.StringIO("\n".join(lines[h_idx:])), sep=None, engine='python', on_bad_lines='skip')

            df_merged = pd.concat([extract_table(lines, 'Skaters'), extract_table(lines, 'Goalies')], ignore_index=True)
            
            if not df_merged.empty:
                c_player = next((c for c in df_merged.columns if 'player' in c.lower()), "Player")
                c_status = next((c for c in df_merged.columns if 'status' in c.lower()), "Status")
                c_salary = next((c for c in df_merged.columns if 'salary' in c.lower()), "Salary")
                c_pos = next((c for c in df_merged.columns if 'pos' in c.lower()), "Pos")
                c_team = next((c for c in df_merged.columns if 'team' in c.lower()), None)

                df_merged[c_salary] = pd.to_numeric(df_merged[c_salary].astype(str).replace(r'[\$,\s]', '', regex=True), errors='coerce').fillna(0)
                df_merged[c_salary] = df_merged[c_salary].apply(lambda x: x*1000 if x < 100000 else x)
                
                temp_df = pd.DataFrame({
                    'Joueur': df_merged[c_player].astype(str), 
                    'Salaire': df_merged[c_salary], 
                    'Statut': df_merged[c_status].apply(lambda x: "Club École" if "MIN" in str(x).upper() else "Grand Club"),
                    'Pos': df_merged[c_pos].fillna("N/A").astype(str),
                    'Equipe': df_merged[c_team].astype(str) if c_team else "N/A",
                    'Propriétaire': f"{fichier.name.replace('.csv', '')} ({horodatage})"
                })
                
                # Nettoyer les joueurs invalides
                temp_df = temp_df[
                    (temp_df['Joueur'].notna()) & 
                    (temp_df['Joueur'] != '') &
                    (temp_df['Joueur'] != '0') &
                    (temp_df['Joueur'].str.strip() != '0') &
                    (temp_df['Joueur'].str.strip() != '')
                ]
                
                dfs_a_ajouter.append(temp_df)
                
            # Mettre à jour la progression par fichier
            file_progress = 30 + int((idx + 1) / len(fichiers_telecharges) * 40)
            progress_bar.progress(file_progress)
            status_text.text(f"📄 Traitement: {idx + 1}/{len(fichiers_telecharges)} fichiers")
            
        except Exception as e: 
            st.error(f"Erreur import {fichier.name}: {e}")

    if dfs_a_ajouter:
        status_text.text("💾 Sauvegarde des données...")
        progress_bar.progress(80)
        
        new_data = pd.concat(dfs_a_ajouter, ignore_index=True)
        st.session_state['historique'] = pd.concat([st.session_state['historique'], new_data], ignore_index=True).drop_duplicates(subset=['Joueur', 'Propriétaire'], keep='last')
        sauvegarder_donnees(st.session_state['historique'], DB_FILE)
        
        status_text.text("✅ Import terminé!")
        progress_bar.progress(100)
        
        status_text.empty()
        progress_bar.empty()
        
        st.rerun()

# --- TABS (Dashboard & Sim) ---
tab1, tab2, tab3 = st.tabs(["📊 Dashboard", "⚖️ Simulateur", "🛠️ Gestion"])

with tab1:
    if not st.session_state['historique'].empty:
        st.header("📊 Masse Salariale par Propriétaire")
        
        # Nettoyer les données avant traitement
        df_f = st.session_state['historique'][
            (st.session_state['historique']['Joueur'].notna()) & 
            (st.session_state['historique']['Joueur'].astype(str).str.strip() != '') &
            (st.session_state['historique']['Joueur'].astype(str).str.strip() != '0') &
            (st.session_state['historique']['Joueur'].astype(str) != 'nan')
        ].copy()
        
        # Conversion efficace des salaires
        salaires = pd.to_numeric(df_f['Salaire'], errors='coerce').fillna(0)
        
        # Extraction rapide propriétaire/date
        split_data = df_f['Propriétaire'].str.extract(r'(.+?)\s*\((.+)\)', expand=True)
        proprio_nom = split_data[0].fillna(df_f['Propriétaire']).values
        date_time = split_data[1].fillna('').values
        
        # Créer un DataFrame optimisé pour le groupement
        temp_df = pd.DataFrame({
            'Propriétaire': df_f['Propriétaire'].values,
            'Propriétaire_nom': proprio_nom,
            'DateTime': date_time,
            'Statut': df_f['Statut'].values,
            'Salaire': salaires.values
        })
        
        # Groupement et pivot optimisés
        summary = temp_df.groupby(['Propriétaire', 'Propriétaire_nom', 'DateTime', 'Statut'], observed=True)['Salaire'].sum().reset_index()
        summary = summary.pivot_table(
            index=['Propriétaire', 'Propriétaire_nom', 'DateTime'], 
            columns='Statut', 
            values='Salaire', 
            fill_value=0,
            observed=True
        ).reset_index()
        
        # Colonnes garanties
        if 'Grand Club' not in summary.columns:
            summary['Grand Club'] = 0
        if 'Club École' not in summary.columns:
            summary['Club École'] = 0
            
        # Calculs vectorisés
        summary['Restant Grand Club'] = PLAFOND_GRAND_CLUB - summary['Grand Club']
        summary['Restant Club École'] = PLAFOND_CLUB_ECOLE - summary['Club École']
        
        # Métriques en haut
        col1, col2 = st.columns(2)
        with col1:
            st.metric("🏒 Plafond Grand Club", format_currency(PLAFOND_GRAND_CLUB))
        with col2:
            st.metric("🎓 Plafond Club École", format_currency(PLAFOND_CLUB_ECOLE))
        
        st.divider()
        
        # Formatage optimisé avec couleurs
        display_data = {
            'Propriétaire': summary['Propriétaire_nom'].values,
            'Date/Heure': summary['DateTime'].values,
            'Grand Club': [],
            'Restant Grand Club': [],
            'Club École': [],
            'Restant Club École': []
        }
        
        for idx, row in summary.iterrows():
            display_data['Grand Club'].append(format_currency(row['Grand Club']))
            display_data['Restant Grand Club'].append(format_currency(row['Restant Grand Club']))
            display_data['Club École'].append(format_currency(row['Club École']))
            display_data['Restant Club École'].append(format_currency(row['Restant Club École']))
        
        display_df = pd.DataFrame(display_data)
        
        # Fonction pour colorer selon les dépassements de plafond
        def color_by_plafond(row):
            styles = [''] * len(row)
            
            try:
                # Extraire les valeurs numériques
                gc_val = float(row['Grand Club'].replace(" ", "").replace("$", ""))
                ce_val = float(row['Club École'].replace(" ", "").replace("$", ""))
                
                # Vérifier les dépassements
                gc_depasse = gc_val > PLAFOND_GRAND_CLUB
                ce_depasse = ce_val > PLAFOND_CLUB_ECOLE
                
                for i, col_name in enumerate(row.index):
                    if col_name in ['Grand Club', 'Restant Grand Club']:
                        if gc_depasse:
                            styles[i] = 'color: #ff0000; font-weight: bold'
                        else:
                            styles[i] = 'color: #00cc00; font-weight: bold'
                    elif col_name in ['Club École', 'Restant Club École']:
                        if ce_depasse:
                            styles[i] = 'color: #ff0000; font-weight: bold'
                        else:
                            styles[i] = 'color: #00cc00; font-weight: bold'
            except:
                pass
            
            return styles
        
        # Appliquer le style
        styled_df = display_df.style.apply(color_by_plafond, axis=1)
        
        st.dataframe(styled_df, use_container_width=True, hide_index=True)
        
        st.divider()
        
        # Section suppression
        st.subheader("🗑️ Supprimer une importation")
        
        proprietaires_list = summary['Propriétaire'].tolist()
        proprietaires_display = [f"{row['Propriétaire_nom']} ({row['DateTime']})" for _, row in summary.iterrows()]
        
        if proprietaires_list:
            col_select, col_btn = st.columns([3, 1])
            with col_select:
                selected_proprio = st.selectbox(
                    "Sélectionner une importation à supprimer",
                    options=range(len(proprietaires_list)),
                    format_func=lambda x: proprietaires_display[x],
                    key="delete_select"
                )
            with col_btn:
                st.write("")
                st.write("")
                if st.button("🗑️ Supprimer", type="primary", use_container_width=True):
                    proprio_to_delete = proprietaires_list[selected_proprio]
                    st.session_state['historique'] = st.session_state['historique'][
                        st.session_state['historique']['Propriétaire'] != proprio_to_delete
                    ].copy()
                    sauvegarder_donnees(st.session_state['historique'], DB_FILE)
                    st.success(f"✅ Importation supprimée: {proprietaires_display[selected_proprio]}")
                    st.rerun()
        
        st.divider()
        
        # Alertes optimisées
        st.subheader("⚠️ Alertes")
        alertes = []
        for idx, row in summary.iterrows():
            proprio_display = f"{row['Propriétaire_nom']} ({row['DateTime']})"
            if row['Restant Grand Club'] < 0:
                alertes.append(('error', f"🚨 **{proprio_display}** dépasse le plafond du Grand Club de **{format_currency(abs(row['Restant Grand Club']))}**"))
            if row['Restant Club École'] < 0:
                alertes.append(('error', f"🚨 **{proprio_display}** dépasse le plafond du Club École de **{format_currency(abs(row['Restant Club École']))}**"))
        
        if alertes:
            for alert_type, msg in alertes:
                st.error(msg)
        else:
            st.success("✅ Aucun dépassement de plafond salarial")
    else:
        st.info("Aucune donnée disponible. Importez un fichier CSV via la barre latérale.")

with tab2:
    st.header("⚖️ Simulateur de Transactions")
    
    if not st.session_state['historique'].empty:
        df_hist = st.session_state['historique']
        
        # Nettoyer les données
        df_hist = df_hist[
            (df_hist['Joueur'].notna()) & 
            (df_hist['Joueur'].astype(str).str.strip() != '') &
            (df_hist['Joueur'].astype(str).str.strip() != '0') &
            (df_hist['Joueur'].astype(str) != 'nan')
        ].copy()
        
        proprietaires_uniques = df_hist['Propriétaire'].unique().tolist()
        
        if not proprietaires_uniques:
            st.warning("Aucun propriétaire trouvé dans les données.")
        else:
            proprio_display = {}
            for p in proprietaires_uniques:
                try:
                    parts = p.split('(')
                    if len(parts) >= 2:
                        nom = parts[0].strip()
                        date = parts[1].replace(')', '').strip()
                        proprio_display[p] = f"{nom} ({date})"
                    else:
                        proprio_display[p] = p
                except:
                    proprio_display[p] = p
            
            selected_proprio_full = st.selectbox(
                "Sélectionner un propriétaire",
                options=proprietaires_uniques,
                format_func=lambda x: proprio_display.get(x, x),
                key="sim_proprio_select"
            )
            
            if selected_proprio_full:
                joueurs_proprio = df_hist[df_hist['Propriétaire'] == selected_proprio_full].copy()
                joueurs_proprio = joueurs_proprio[
                    (joueurs_proprio['Joueur'].notna()) & 
                    (joueurs_proprio['Joueur'] != '') &
                    (joueurs_proprio['Joueur'] != '0')
                ].copy()
                
                joueurs_proprio['Salaire'] = pd.to_numeric(joueurs_proprio['Salaire'], errors='coerce').fillna(0)
                
                sim_key = f"sim_{selected_proprio_full}"
                
                if f'{sim_key}_grand_club' not in st.session_state:
                    gc_joueurs = joueurs_proprio[joueurs_proprio['Statut'] == 'Grand Club']['Joueur'].tolist()
                    st.session_state[f'{sim_key}_grand_club'] = [j for j in gc_joueurs if j and str(j).strip() != '' and str(j) != '0']
                if f'{sim_key}_club_ecole' not in st.session_state:
                    ce_joueurs = joueurs_proprio[joueurs_proprio['Statut'] == 'Club École']['Joueur'].tolist()
                    st.session_state[f'{sim_key}_club_ecole'] = [j for j in ce_joueurs if j and str(j).strip() != '' and str(j) != '0']
                
                if st.button("🔄 Réinitialiser", key="reset_sim"):
                    gc_joueurs = joueurs_proprio[joueurs_proprio['Statut'] == 'Grand Club']['Joueur'].tolist()
                    st.session_state[f'{sim_key}_grand_club'] = [j for j in gc_joueurs if j and str(j).strip() != '' and str(j) != '0']
                    ce_joueurs = joueurs_proprio[joueurs_proprio['Statut'] == 'Club École']['Joueur'].tolist()
                    st.session_state[f'{sim_key}_club_ecole'] = [j for j in ce_joueurs if j and str(j).strip() != '' and str(j) != '0']
                    st.rerun()
                
                st.divider()
                
                col1, col2 = st.columns(2)
                
                with col1:
                    st.subheader("🏒 Grand Club (Act)")
                    
                    total_gc = 0
                    joueurs_gc_data = []
                    
                    for joueur_nom in st.session_state[f'{sim_key}_grand_club']:
                        if not joueur_nom or joueur_nom == '0' or str(joueur_nom).strip() == '':
                            continue
                            
                        joueur_info = joueurs_proprio[joueurs_proprio['Joueur'] == joueur_nom]
                        if not joueur_info.empty:
                            j = joueur_info.iloc[0]
                            salaire = float(j['Salaire'])
                            equipe = j.get('Equipe', 'N/A') if 'Equipe' in joueur_info.columns else 'N/A'
                            total_gc += salaire
                            joueurs_gc_data.append({
                                'Joueur': joueur_nom,
                                'Équipe': equipe,
                                'Pos': j['Pos'],
                                'Salaire': format_currency(salaire)
                            })
                    
                    restant_gc = PLAFOND_GRAND_CLUB - total_gc
                    color_gc = "🟢" if total_gc <= PLAFOND_GRAND_CLUB else "🔴"
                    
                    st.metric("Total Masse Salariale", format_currency(total_gc))
                    st.metric(f"{color_gc} Restant", format_currency(restant_gc))
                    
                    if joueurs_gc_data:
                        df_gc = pd.DataFrame(joueurs_gc_data)
                        st.dataframe(df_gc, use_container_width=True, hide_index=True)
                        
                        st.write("**Déplacer vers Club École:**")
                        if st.session_state[f'{sim_key}_grand_club']:
                            joueur_to_move = st.selectbox(
                                "Sélectionner un joueur",
                                options=st.session_state[f'{sim_key}_grand_club'],
                                key="move_to_ce"
                            )
                            if st.button("➡️ Déplacer", key="btn_move_ce"):
                                if joueur_to_move in st.session_state[f'{sim_key}_grand_club']:
                                    st.session_state[f'{sim_key}_grand_club'].remove(joueur_to_move)
                                    st.session_state[f'{sim_key}_club_ecole'].append(joueur_to_move)
                                    st.rerun()
                    else:
                        st.info("Aucun joueur dans le Grand Club")
                
                with col2:
                    st.subheader("🎓 Club École (Min)")
                    
                    total_ce = 0
                    joueurs_ce_data = []
                    
                    for joueur_nom in st.session_state[f'{sim_key}_club_ecole']:
                        if not joueur_nom or joueur_nom == '0' or str(joueur_nom).strip() == '':
                            continue
                            
                        joueur_info = joueurs_proprio[joueurs_proprio['Joueur'] == joueur_nom]
                        if not joueur_info.empty:
                            j = joueur_info.iloc[0]
                            salaire = float(j['Salaire'])
                            equipe = j.get('Equipe', 'N/A') if 'Equipe' in joueur_info.columns else 'N/A'
                            total_ce += salaire
                            joueurs_ce_data.append({
                                'Joueur': joueur_nom,
                                'Équipe': equipe,
                                'Pos': j['Pos'],
                                'Salaire': format_currency(salaire)
                            })
                    
                    restant_ce = PLAFOND_CLUB_ECOLE - total_ce
                    color_ce = "🟢" if total_ce <= PLAFOND_CLUB_ECOLE else "🔴"
                    
                    st.metric("Total Masse Salariale", format_currency(total_ce))
                    st.metric(f"{color_ce} Restant", format_currency(restant_ce))
                    
                    if joueurs_ce_data:
                        df_ce = pd.DataFrame(joueurs_ce_data)
                        st.dataframe(df_ce, use_container_width=True, hide_index=True)
                        
                        st.write("**Déplacer vers Grand Club:**")
                        if st.session_state[f'{sim_key}_club_ecole']:
                            joueur_to_move_gc = st.selectbox(
                                "Sélectionner un joueur",
                                options=st.session_state[f'{sim_key}_club_ecole'],
                                key="move_to_gc"
                            )
                            if st.button("⬅️ Déplacer", key="btn_move_gc"):
                                if joueur_to_move_gc in st.session_state[f'{sim_key}_club_ecole']:
                                    st.session_state[f'{sim_key}_club_ecole'].remove(joueur_to_move_gc)
                                    st.session_state[f'{sim_key}_grand_club'].append(joueur_to_move_gc)
                                    st.rerun()
                    else:
                        st.info("Aucun joueur dans le Club École")
                
                st.divider()
                
                st.subheader("📊 Résumé")
                col_sum1, col_sum2 = st.columns(2)
                with col_sum1:
                    st.write("**Grand Club:**")
                    st.write(f"- Total: {format_currency(total_gc)}")
                    st.write(f"- Plafond: {format_currency(PLAFOND_GRAND_CLUB)}")
                    st.write(f"- Restant: {format_currency(restant_gc)}")
                with col_sum2:
                    st.write("**Club École:**")
                    st.write(f"- Total: {format_currency(total_ce)}")
                    st.write(f"- Plafond: {format_currency(PLAFOND_CLUB_ECOLE)}")
                    st.write(f"- Restant: {format_currency(restant_ce)}")
    else:
        st.info("Aucune donnée disponible. Importez un fichier CSV via la barre latérale.")

with tab3:
    st.header("🛠️ Gestion des Données")
    st.info("Fonctionnalité à venir")
