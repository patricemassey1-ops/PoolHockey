import streamlit as st
import pandas as pd
import io
import os
import re
import csv
from datetime import datetime

# =====================================================
# CONFIG
# =====================================================
st.set_page_config("Fantrax Pool Hockey", layout="wide")

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

# =====================================================
# PLAFONDS (MODIFIABLES)
# =====================================================
if "PLAFOND_GC" not in st.session_state:
    st.session_state["PLAFOND_GC"] = 95_500_000
if "PLAFOND_CE" not in st.session_state:
    st.session_state["PLAFOND_CE"] = 47_750_000

# =====================================================
# LOGOS
# =====================================================
LOGOS = {
    "Nordiques": "Nordiques_Logo.png",
    "Cracheurs": "Cracheurs_Logo.png",
    "Prédateurs": "Prédateurs_Logo.png",
    "Red Wings": "Red_Wings_Logo.png",
    "Whalers": "Whalers_Logo.png",
    "Canadiens": "Canadiens_Logo.png",
}
LOGO_SIZE = 55

# =====================================================
# SAISON AUTO
# =====================================================
def saison_auto():
    now = datetime.now()
    return f"{now.year}-{now.year+1}" if now.month >= 9 else f"{now.year-1}-{now.year}"

def saison_verrouillee(season):
    return int(season[:4]) < int(saison_auto()[:4])

# =====================================================
# FORMAT $
# =====================================================
def money(v):
    return f"{int(v):,}".replace(",", " ") + " $"

# =====================================================
# PARSER FANTRAX (Skaters + Goalies séparés par ligne vide / entêtes multiples)
# - Ajoute Equipe depuis colonne Team
# - Crée Slot: Actif si Grand Club, sinon vide
# =====================================================

def parse_fantrax(upload):
    import re
    import io
    import pandas as pd

    # -------------------------------------------------
    # Lecture brute + nettoyage caractères invisibles
    # -------------------------------------------------
    raw_lines = upload.read().decode("utf-8", errors="ignore").splitlines()
    raw_lines = [re.sub(r"[\x00-\x1f\x7f]", "", l) for l in raw_lines]

    # -------------------------------------------------
    # Détection automatique du séparateur
    # -------------------------------------------------
    def detect_sep(lines):
        for l in lines:
            low = l.lower()
            if "player" in low and "salary" in low:
                for d in [",", ";", "\t", "|"]:
                    if d in l:
                        return d
        return ","

    sep = detect_sep(raw_lines)

    # -------------------------------------------------
    # Détection des headers Fantrax (Skaters / Goalies)
    # -------------------------------------------------
    header_idxs = [
        i for i, l in enumerate(raw_lines)
        if ("player" in l.lower() and "salary" in l.lower() and sep in l)
    ]

    if not header_idxs:
        raise ValueError("Aucune section Fantrax valide détectée (Player / Salary).")

    # -------------------------------------------------
    # Lecture sécurisée d’une section Fantrax
    # -------------------------------------------------
    def read_section(start, end):
        lines = raw_lines[start:end]
        lines = [l for l in lines if l.strip() != ""]
        if len(lines) < 2:
            return None

        dfp = pd.read_csv(
            io.StringIO("\n".join(lines)),
            sep=sep,
            engine="python",
            on_bad_lines="skip"
        )
        dfp.columns = [c.strip().replace('"', "") for c in dfp.columns]
        return dfp

    # -------------------------------------------------
    # Lecture de toutes les sections
    # -------------------------------------------------
    parts = []
    for i, h in enumerate(header_idxs):
        end = header_idxs[i + 1] if i + 1 < len(header_idxs) else len(raw_lines)
        dfp = read_section(h, end)
        if dfp is not None and not dfp.empty:
            parts.append(dfp)

    if not parts:
        raise ValueError("Sections Fantrax détectées mais aucune donnée exploitable.")

    df = pd.concat(parts, ignore_index=True)

    # -------------------------------------------------
    # Normalisation des colonnes (tolérance Fantrax)
    # -------------------------------------------------
    def find_col(possibles):
        for p in possibles:
            for c in df.columns:
                if p in c.lower():
                    return c
        return None

    player_col = find_col(["player"])
    salary_col = find_col(["salary"])
    team_col   = find_col(["team"])
    pos_col    = find_col(["pos"])
    status_col = find_col(["status"])

    if not player_col or not salary_col:
        raise ValueError(
            f"Colonnes Player/Salary introuvables. Colonnes trouvées: {list(df.columns)}"
        )

    # -------------------------------------------------
    # Construction du DataFrame final
    # -------------------------------------------------
    out = pd.DataFrame()
    out["Joueur"] = df[player_col].astype(str).str.strip()
    out["Equipe"] = df[team_col].astype(str).str.strip() if team_col else "N/A"
    out["Pos"] = df[pos_col].astype(str).str.strip() if pos_col else "N/A"

    sal = (
        df[salary_col]
        .astype(str)
        .str.replace(",", "", regex=False)
        .str.replace(" ", "", regex=False)
        .replace(["None", "nan", "NaN", ""], "0")
    )

    # Fantrax = salaires en milliers → on stocke en $
    out["Salaire"] = pd.to_numeric(sal, errors="coerce").fillna(0) * 1000

    # Statut Fantrax
    if status_col:
        out["Statut"] = df[status_col].apply(
            lambda x: "Club École" if "min" in str(x).lower() else "Grand Club"
        )
    else:
        out["Statut"] = "Grand Club"

    # Slot par défaut
    out["Slot"] = out["Statut"].apply(lambda s: "Actif" if s == "Grand Club" else "")

    # -------------------------------------------------
    # NETTOYAGE FINAL (ANTI LIGNES FANTÔMES)
    # -------------------------------------------------
    out["Joueur"] = out["Joueur"].astype(str).str.strip()
    out["Pos"] = out["Pos"].astype(str).str.strip()
    out["Equipe"] = out["Equipe"].astype(str).str.strip()

    forbidden = {"none", "skaters", "goalies", "player"}

    out = out[
        ~out["Joueur"].str.lower().isin(forbidden)
        & ~out["Pos"].str.lower().isin(forbidden)
    ]

    # Joueur valide
    out = out[out["Joueur"].str.len() > 2]

    # Ligne fantôme classique Fantrax
    out = out[
        ~(
            (out["Salaire"] <= 0)
            & (out["Equipe"].str.lower().isin(["none", "nan", "", "n/a"]))
        )
    ]

    return out.reset_index(drop=True)


# =====================================================
# SIDEBAR
# =====================================================
st.sidebar.header("📅 Saison")

saisons = ["2024-2025", "2025-2026", "2026-2027"]
auto = saison_auto()
if auto not in saisons:
    saisons.append(auto)
    saisons.sort()

season = st.sidebar.selectbox("Saison", saisons, index=saisons.index(auto))
LOCKED = saison_verrouillee(season)
DATA_FILE = f"{DATA_DIR}/fantrax_{season}.csv"

st.sidebar.divider()
st.sidebar.header("💰 Plafonds")

if st.sidebar.button("✏️ Modifier les plafonds"):
    st.session_state["edit_plafond"] = True

if st.session_state.get("edit_plafond"):
    st.session_state["PLAFOND_GC"] = st.sidebar.number_input(
        "Plafond Grand Club", value=st.session_state["PLAFOND_GC"], step=500_000
    )
    st.session_state["PLAFOND_CE"] = st.sidebar.number_input(
        "Plafond Club École", value=st.session_state["PLAFOND_CE"], step=250_000
    )

st.sidebar.metric("🏒 Grand Club", money(st.session_state["PLAFOND_GC"]))
st.sidebar.metric("🏫 Club École", money(st.session_state["PLAFOND_CE"]))

# =====================================================
# DATA
# =====================================================
if "season" not in st.session_state or st.session_state["season"] != season:
    if os.path.exists(DATA_FILE):
        st.session_state["data"] = pd.read_csv(DATA_FILE)
    else:
        st.session_state["data"] = pd.DataFrame(
            columns=["Propriétaire", "Joueur", "Salaire", "Statut", "Slot", "Pos", "Equipe"]
        )

    # Compatibilité si anciens fichiers sans Slot
    if "Slot" not in st.session_state["data"].columns:
        st.session_state["data"]["Slot"] = ""

    # Default: GC + Slot vide => Actif
    mask_gc = (st.session_state["data"]["Statut"] == "Grand Club") & (st.session_state["data"]["Slot"].fillna("").eq(""))
    st.session_state["data"].loc[mask_gc, "Slot"] = "Actif"

    st.session_state["season"] = season

# =====================================================
# IMPORT FANTRAX (uploader toujours visible)
# =====================================================
st.sidebar.header("📥 Import Fantrax")

uploaded = st.sidebar.file_uploader(
    "CSV Fantrax",
    type=["csv", "txt"],
    help="Import autorisé seulement pour la saison courante ou future"
)

if uploaded:
    if LOCKED:
        st.sidebar.warning("🔒 Saison verrouillée : import désactivé.")
    else:
        try:
            df_import = parse_fantrax(uploaded)

            if df_import is None or not isinstance(df_import, pd.DataFrame):
                st.sidebar.error("❌ Erreur: données invalides (parse_fantrax).")
                st.stop()

            if df_import.empty:
                st.sidebar.error("❌ Aucune donnée valide trouvée dans le fichier Fantrax.")
                st.stop()

            owner = os.path.splitext(uploaded.name)[0]
            df_import["Propriétaire"] = owner

            st.session_state["data"] = (
                pd.concat([st.session_state["data"], df_import], ignore_index=True)
                .drop_duplicates(subset=["Propriétaire", "Joueur"])
            )

            st.session_state["data"].to_csv(DATA_FILE, index=False)
            st.sidebar.success("✅ Import réussi")

        except Exception as e:
            st.sidebar.error(f"❌ Import échoué : {e}")
            st.stop()

# =====================================================
# HEADER
# =====================================================
st.image("Logo_Pool.png", use_container_width=True)
st.title("🏒 Fantrax – Gestion Salariale")

df = st.session_state["data"]
if df.empty:
    st.info("Aucune donnée")
    st.stop()

# =====================================================
# CALCULS (plafonds par propriétaire)
# =====================================================
resume = []
for p in df["Propriétaire"].unique():
    d = df[df["Propriétaire"] == p]
    gc_sum = d[d["Statut"] == "Grand Club"]["Salaire"].sum()
    ce_sum = d[d["Statut"] == "Club École"]["Salaire"].sum()

    logo = ""
    for k, v in LOGOS.items():
        if k.lower() in p.lower():
            logo = v

    resume.append(
        {
            "Propriétaire": p,
            "Logo": logo,
            "GC": gc_sum,
            "CE": ce_sum,
            "Restant GC": st.session_state["PLAFOND_GC"] - gc_sum,
            "Restant CE": st.session_state["PLAFOND_CE"] - ce_sum,
        }
    )

plafonds = pd.DataFrame(resume)

# =====================================================
# ONGLETs (Alignement juste après Tableau)
# =====================================================
tab1, tab4, tab2, tab3 = st.tabs(
    ["📊 Tableau", "🧾 Alignement", "⚖️ Transactions", "🧠 Recommandations"]
)

# =====================================================
# TABLEAU (logo + propriétaire)
# =====================================================
with tab1:
    headers = st.columns([4, 2, 2, 2, 2])
    headers[0].markdown("**Équipe**")
    headers[1].markdown("**Grand Club**")
    headers[2].markdown("**Club École**")
    headers[3].markdown("**Restant GC**")
    headers[4].markdown("**Restant CE**")

    for _, r in plafonds.iterrows():
        cols = st.columns([4, 2, 2, 2, 2])

        owner = str(r["Propriétaire"])
        logo_path = str(r["Logo"]).strip()

        with cols[0]:
            a, b = st.columns([1, 4])
            if logo_path and os.path.exists(logo_path):
                a.image(logo_path, width=LOGO_SIZE)
            else:
                a.markdown("—")
            b.markdown(f"**{owner}**")

        cols[1].markdown(money(r["GC"]))
        cols[2].markdown(money(r["CE"]))
        cols[3].markdown(money(r["Restant GC"]))
        cols[4].markdown(money(r["Restant CE"]))

# =====================================================
# ALIGNEMENT (20 Actifs + Banc(3) + 2 G; pas de gardien sur banc)
# =====================================================
with tab4:
    st.subheader("🧾 Alignement")
    st.caption("Règles : **20 patineurs Actifs**, **max 3 sur le Banc**, **2 Gardiens Actifs** (pas de gardien sur le banc).")

    proprietaire = st.selectbox(
        "Propriétaire",
        sorted(st.session_state["data"]["Propriétaire"].unique()),
        key="align_owner",
    )

    data_all = st.session_state["data"]
    dprop = data_all[data_all["Propriétaire"] == proprietaire].copy()

    def is_goalie_pos(pos):
        return "g" in str(pos).lower()

    def is_goalie_series(s):
        return s.astype(str).str.lower().str.contains("g", na=False)

    # Sécurise Slot
    if "Slot" not in st.session_state["data"].columns:
        st.session_state["data"]["Slot"] = ""

    # Default Slot: GC + Slot vide => Actif
    mask_gc_default = (dprop["Statut"] == "Grand Club") & (dprop["Slot"].fillna("").eq(""))
    if mask_gc_default.any():
        mask_all = (
            (st.session_state["data"]["Propriétaire"] == proprietaire)
            & (st.session_state["data"]["Statut"] == "Grand Club")
            & (st.session_state["data"]["Slot"].fillna("").eq(""))
        )
        st.session_state["data"].loc[mask_all, "Slot"] = "Actif"
        st.session_state["data"].to_csv(DATA_FILE, index=False)
        dprop = st.session_state["data"][st.session_state["data"]["Propriétaire"] == proprietaire].copy()

    gc_all = dprop[dprop["Statut"] == "Grand Club"].copy()
    ce_all = dprop[dprop["Statut"] == "Club École"].copy()

    gc_actif = gc_all[gc_all["Slot"] == "Actif"].copy()
    gc_banc = gc_all[gc_all["Slot"] == "Banc"].copy()

    actif_goalies = gc_actif[is_goalie_series(gc_actif["Pos"])].copy()
    actif_skaters = gc_actif[~is_goalie_series(gc_actif["Pos"])].copy()

    banc_goalies = gc_banc[is_goalie_series(gc_banc["Pos"])].copy()
    banc_skaters = gc_banc[~is_goalie_series(gc_banc["Pos"])].copy()

    nb_actif_skaters = len(actif_skaters)
    nb_actif_goalies = len(actif_goalies)
    nb_banc_skaters = len(banc_skaters)

    total_gc = gc_all["Salaire"].sum()
    total_ce = ce_all["Salaire"].sum()
    restant_gc = st.session_state["PLAFOND_GC"] - total_gc
    restant_ce = st.session_state["PLAFOND_CE"] - total_ce

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("🏒 Total GC", money(total_gc))
    m2.metric("🏫 Total CE", money(total_ce))
    m3.metric("✅ Restant GC", money(restant_gc))
    m4.metric("✅ Restant CE", money(restant_ce))

    cA, cB, cC, cD = st.columns(4)
    cA.metric("Actifs (patineurs)", f"{nb_actif_skaters}/20")
    cB.metric("Gardiens (actifs)", f"{nb_actif_goalies}/2")
    cC.metric("Banc (patineurs)", f"{nb_banc_skaters}/3")
    cD.metric("Gardiens sur banc", f"{len(banc_goalies)}/0")

    if len(banc_goalies) > 0:
        st.error("🚨 Gardien sur le banc interdit. Déplace-le en Actif ou en Club École.")
    if nb_banc_skaters > 3:
        st.error("🚨 Trop de joueurs sur le banc (max 3).")
    if nb_actif_skaters != 20:
        st.warning("⚠️ Il doit y avoir exactement **20 patineurs actifs**.")
    if nb_actif_goalies != 2:
        st.warning("⚠️ Il doit y avoir exactement **2 gardiens actifs**.")

    st.divider()

    def view_df(x):
        if x.empty:
            return x
        y = x.copy()
        y["Salaire"] = y["Salaire"].apply(money)
        return y[["Joueur", "Pos", "Equipe", "Salaire"]].reset_index(drop=True)

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("### 🟢 Actifs")
        st.caption("20 patineurs + 2 gardiens")
        if gc_actif.empty:
            st.info("Aucun joueur actif.")
        else:
            st.dataframe(view_df(gc_actif.sort_values(["Pos", "Joueur"])), use_container_width=True, hide_index=True)

    with col2:
        st.markdown("### 🟡 Banc")
        st.caption("Max 3 (patineurs seulement)")
        if gc_banc.empty:
            st.info("Aucun joueur sur le banc.")
        else:
            st.dataframe(view_df(gc_banc.sort_values(["Pos", "Joueur"])), use_container_width=True, hide_index=True)

    with col3:
        st.markdown("### 🔵 Club École (Min)")
        if ce_all.empty:
            st.info("Aucun joueur au Club École.")
        else:
            st.dataframe(view_df(ce_all.sort_values(["Pos", "Joueur"])), use_container_width=True, hide_index=True)

    st.divider()
    st.markdown("### 🔁 Déplacements")

    if LOCKED:
        st.warning("🔒 Saison verrouillée : aucun changement d’alignement n’est permis.")
        st.stop()

    a1, a2, a3 = st.columns(3)

    # Club École -> Grand Club (Actif ou Banc; gardien => Actif seulement)
    with a1:
        st.markdown("**⬆️ Rappel (Min → GC)**")
        ce_players = ce_all["Joueur"].tolist()
        ce_choice = st.selectbox(
            "Joueur (Club École)",
            ce_players if ce_players else ["—"],
            disabled=(len(ce_players) == 0),
            key="recall_player",
        )

        dest = st.radio(
            "Destination",
            ["Actif", "Banc"],
            horizontal=True,
            key="recall_dest",
            disabled=(len(ce_players) == 0),
        )

        if st.button("Rappeler", disabled=(len(ce_players) == 0), key="btn_recall"):
            row = ce_all[ce_all["Joueur"] == ce_choice].iloc[0]
            goalie = is_goalie_pos(row["Pos"])

            if goalie and dest == "Banc":
                st.error("🚫 Un gardien ne peut pas aller sur le banc.")
            elif goalie and nb_actif_goalies >= 2:
                st.error("🚫 Déjà 2 gardiens actifs.")
            elif (not goalie) and dest == "Actif" and nb_actif_skaters >= 20:
                st.error("🚫 Déjà 20 patineurs actifs.")
            elif (not goalie) and dest == "Banc" and nb_banc_skaters >= 3:
                st.error("🚫 Banc plein (max 3).")
            else:
                mask = (st.session_state["data"]["Propriétaire"] == proprietaire) & (st.session_state["data"]["Joueur"] == ce_choice)
                st.session_state["data"].loc[mask, "Statut"] = "Grand Club"
                st.session_state["data"].loc[mask, "Slot"] = "Actif" if goalie else dest
                st.session_state["data"].to_csv(DATA_FILE, index=False)
                st.success(f"✅ {ce_choice} rappelé au Grand Club ({'Actif' if goalie else dest})")
                st.rerun()

    # Grand Club -> Club École
    with a2:
        st.markdown("**⬇️ Rétrogradation (GC → Min)**")
        gc_players = gc_all["Joueur"].tolist()
        gc_choice = st.selectbox(
            "Joueur (Grand Club)",
            gc_players if gc_players else ["—"],
            disabled=(len(gc_players) == 0),
            key="senddown_player",
        )

        if st.button("Envoyer au Club École", disabled=(len(gc_players) == 0), key="btn_senddown"):
            mask = (st.session_state["data"]["Propriétaire"] == proprietaire) & (st.session_state["data"]["Joueur"] == gc_choice)
            st.session_state["data"].loc[mask, "Statut"] = "Club École"
            st.session_state["data"].loc[mask, "Slot"] = ""
            st.session_state["data"].to_csv(DATA_FILE, index=False)
            st.success(f"✅ {gc_choice} envoyé au Club École (Min)")
            st.rerun()

    # Actif <-> Banc (patineurs seulement)
    with a3:
        st.markdown("**↔️ Actif ⇄ Banc** (patineurs seulement)")

        actifs_list = actif_skaters["Joueur"].tolist()
        banc_list = banc_skaters["Joueur"].tolist()

        sel_actif = st.selectbox(
            "Actif → Banc",
            actifs_list if actifs_list else ["—"],
            disabled=(len(actifs_list) == 0),
            key="actif_to_banc",
        )

        if st.button("Mettre sur le banc", disabled=(len(actifs_list) == 0), key="btn_actif_to_banc"):
            if nb_banc_skaters >= 3:
                st.error("🚫 Banc plein (max 3).")
            else:
                mask = (st.session_state["data"]["Propriétaire"] == proprietaire) & (st.session_state["data"]["Joueur"] == sel_actif)
                st.session_state["data"].loc[mask, "Slot"] = "Banc"
                st.session_state["data"].to_csv(DATA_FILE, index=False)
                st.success(f"✅ {sel_actif} déplacé vers Banc")
                st.rerun()

        st.divider()

        sel_banc = st.selectbox(
            "Banc → Actif",
            banc_list if banc_list else ["—"],
            disabled=(len(banc_list) == 0),
            key="banc_to_actif",
        )

        if st.button("Rendre actif", disabled=(len(banc_list) == 0), key="btn_banc_to_actif"):
            if nb_actif_skaters >= 20:
                st.error("🚫 Déjà 20 patineurs actifs.")
            else:
                mask = (st.session_state["data"]["Propriétaire"] == proprietaire) & (st.session_state["data"]["Joueur"] == sel_banc)
                st.session_state["data"].loc[mask, "Slot"] = "Actif"
                st.session_state["data"].to_csv(DATA_FILE, index=False)
                st.success(f"✅ {sel_banc} déplacé vers Actif")
                st.rerun()

# =====================================================
# TRANSACTIONS (validation simple)
# =====================================================
with tab2:
    p = st.selectbox("Propriétaire", plafonds["Propriétaire"], key="tx_owner")
    salaire = st.number_input("Salaire du joueur", min_value=0, step=100000, key="tx_salary")
    statut = st.radio("Statut", ["Grand Club", "Club École"], key="tx_statut")

    ligne = plafonds[plafonds["Propriétaire"] == p].iloc[0]
    reste = ligne["Restant GC"] if statut == "Grand Club" else ligne["Restant CE"]

    if salaire > reste:
        st.error("🚨 Dépassement du plafond")
    else:
        st.success("✅ Transaction valide")

# =====================================================
# RECOMMANDATIONS (simple)
# =====================================================
with tab3:
    for _, r in plafonds.iterrows():
        if r["Restant GC"] < 2_000_000:
            st.warning(f"{r['Propriétaire']} : rétrogradation recommandée")
        if r["Restant CE"] > 10_000_000:
            st.info(f"{r['Propriétaire']} : rappel possible")
