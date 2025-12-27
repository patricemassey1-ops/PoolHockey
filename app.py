import streamlit as st
import pandas as pd
import io
import os
from datetime import datetime

st.set_page_config(page_title="Analyseur Fantrax 2025", layout="wide")

DB_FILE = "historique_fantrax_2025.csv"

# --- PERSISTENCE ---
def charger_historique():
    if os.path.exists(DB_FILE):
        try: return pd.read_csv(DB_FILE)
        except: return pd.DataFrame()
    return pd.DataFrame()

def sauvegarder_historique(df):
    df.to_csv(DB_FILE, index=False)

if 'historique' not in st.session_state:
    st.session_state['historique'] = charger_historique()

st.title("🏒 Analyseur Fantrax : Grand Club & Club École")

# --- PLAFONDS ---
c1, c2 = st.columns(2)
with c1:
    CAP_GC = st.number_input("Plafond Grand Club ($)", value=95500000, step=1000000)
with c2:
    CAP_CE = st.number_input("Plafond Club École ($)", value=47750000, step=100000)

# --- IMPORT ---
fichiers = st.file_uploader("Importez vos fichiers CSV", type="csv", accept_multiple_files=True)

def format_money(val):
    return f"{int(val):,}".replace(",", " ") + " $"

def get_pos_order(pos):
    p = str(pos).upper()
    if 'G' in p: return 2
    if 'D' in p: return 1
    return 0

if fichiers:
    all_new = []
    now_str = datetime.now().strftime("%d-%m %H:%M")
    ts = datetime.now().timestamp()

    for f in fichiers:
        try:
            content = f.getvalue().decode('utf-8-sig')
            lines = content.splitlines()

            def extract(lines, keyword):
                start = next((i for i, l in enumerate(lines) if keyword in l), -1)
                if start == -1: return pd.DataFrame()
                # Cherche l'entête réelle
                header = next((i for i in range(start, len(lines)) if "Player" in lines[i] or "Salary" in lines[i]), -1)
                if header == -1: return pd.DataFrame()
                
                df = pd.read_csv(io.StringIO("\n".join(lines[header:])), sep=None, engine='python', on_bad_lines='skip')
                # Nettoyage Fantrax : Garder lignes avec ID ou Player
                if 'ID' in df.columns:
                    df = df[df['ID'].astype(str).str.contains(r'\d|\*', na=False)]
                return df

            df_sk = extract(lines, 'Skaters')
            df_go = extract(lines, 'Goalies')
            df_full = pd.concat([df_sk, df_go], ignore_index=True)

            # Identification souple des colonnes
            col_p = next((c for c in df_full.columns if 'player' in c.lower() or 'joueur' in c.lower()), None)
            col_s = next((c for c in df_full.columns if 'salary' in c.lower() or 'salaire' in c.lower()), None)
            col_st = next((c for c in df_full.columns if 'status' in c.lower() or 'statut' in c.lower()), None)
            col_pos = next((c for c in df_full.columns if 'pos' in c.lower() or 'eligible' in c.lower()), None)

            if col_p and col_s and col_st:
                # Calcul Salaire + 000
                sal = pd.to_numeric(df_full[col_s].astype(str).replace(r'[\$,\s]', '', regex=True), errors='coerce').fillna(0) * 1000
                
                # Grand Club vs Club École (Minors)
                def categorize(val):
                    v = str(val).upper()
                    return "Club École" if "MIN" in v else "Grand Club"

                equipe_nom = f.name.replace('.csv', '')
                
                res = pd.DataFrame({
                    'Joueur': df_full[col_p],
                    'Salaire': sal,
                    'Statut': df_full[col_st].apply(categorize),
                    'Pos': df_full[col_pos] if col_pos else "N/A",
                    'Propriétaire_Full': f"{equipe_nom} ({now_str})",
                    'Equipe_Base': equipe_nom,
                    'Timestamp': ts,
                    'pos_order': (df_full[col_pos].apply(get_pos_order) if col_pos else 0)
                })
                all_new.append(res)
        except Exception as e:
            st.error(f"Erreur avec {f.name}: {e}")

    if all_new:
        st.session_state['historique'] = pd.concat([st.session_state['historique'], pd.concat(all_new)], ignore_index=True)
        sauvegarder_historique(st.session_state['historique'])
        st.rerun()

# --- AFFICHAGE ---
if not st.session_state['historique'].empty:
    hist = st.session_state['historique']

    # 1. RÉSUMÉ (Dernier import par équipe)
    st.subheader("📊 Résumé des Dernières Importations")
    last_idx = hist.groupby('Equipe_Base')['Timestamp'].transform(max) == hist['Timestamp']
    df_last = hist[last_idx]
    
    summary = df_last.groupby(['Equipe_Base', 'Statut'])['Salaire'].sum().unstack(fill_value=0).reset_index()
    for c in ['Grand Club', 'Club École']:
        if c not in summary.columns: summary[c] = 0

    st.dataframe(
        summary.style.format({'Grand Club': format_money, 'Club École': format_money})
        .applymap(lambda v: 'color: #00FF00;' if v <= CAP_GC else 'color: red;', subset=['Grand Club'])
        .applymap(lambda v: 'color: #00FF00;' if v <= CAP_CE else 'color: red;', subset=['Club École']),
        use_container_width=True, hide_index=True
    )

    # 2. DÉTAILS AVEC SUPPRESSION
    st.subheader("👤 Détails des Effectifs par Date")
    
    versions = sorted(hist['Propriétaire_Full'].unique(), reverse=True)
    
    for v in versions:
        col_exp, col_del = st.columns([0.9, 0.1])
        with col_exp:
            with st.expander(f"📂 {v}"):
                d1, d2 = st.columns(2)
                df_v = hist[hist['Propriétaire_Full'] == v]
                
                with d1:
                    st.markdown("**⭐ Grand Club**")
                    dg = df_v[df_v['Statut'] == "Grand Club"].sort_values(['pos_order', 'Salaire'], ascending=[True, False])
                    st.dataframe(dg[['Joueur', 'Pos', 'Salaire']].assign(Salaire=dg['Salaire'].apply(format_money)), hide_index=True, use_container_width=True)
                    m_g = dg['Salaire'].sum()
                    st.metric("Masse GC", format_money(m_g), delta=format_money(CAP_GC - m_g), delta_color="normal" if m_g <= CAP_GC else "inverse", key=f"mgc_{v}")

                with d2:
                    st.markdown("**🎓 Club École**")
                    dc = df_v[df_v['Statut'] == "Club École"].sort_values(['pos_order', 'Salaire'], ascending=[True, False])
                    st.dataframe(dc[['Joueur', 'Pos', 'Salaire']].assign(Salaire=dc['Salaire'].apply(format_money)), hide_index=True, use_container_width=True)
                    m_c = dc['Salaire'].sum()
                    st.metric("Masse CÉ", format_money(m_c), delta=format_money(CAP_CE - m_c), delta_color="normal" if m_c <= CAP_CE else "inverse", key=f"mce_{v}")

        with col_del:
            # Petit bouton X pour supprimer cette version précise
            if st.button("❌", key=f"btn_del_{v}"):
                st.session_state['historique'] = hist[hist['Propriétaire_Full'] != v]
                sauvegarder_historique(st.session_state['historique'])
                st.rerun()
else:
    st.info("Aucune donnée. Importez des fichiers CSV Fantrax pour voir la masse salariale.")
