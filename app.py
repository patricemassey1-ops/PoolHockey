import streamlit as st
import pandas as pd

# =====================================================
# CONFIG SAFE
# =====================================================
st.set_page_config(page_title="PMS – Joueurs autonomes", layout="wide")

# =====================================================
# AUTH SIMPLE (ANTI BLACK SCREEN)
# =====================================================
if "auth_ok" not in st.session_state:
    st.session_state.auth_ok = False

if not st.session_state.auth_ok:
    st.title("🔐 Accès sécurisé")
    pwd = st.text_input("Mot de passe", type="password")
    if st.button("Entrer"):
        if pwd == "pms":  # change plus tard
            st.session_state.auth_ok = True
            st.experimental_rerun()
        else:
            st.error("Mot de passe invalide")
    st.stop()

# =====================================================
# SESSION STATE SAFE
# =====================================================
if "selected_players" not in st.session_state:
    st.session_state.selected_players = []

# =====================================================
# DATA (EXEMPLE)
# =====================================================
PLAYERS = pd.DataFrame([
    {"Player": "Leon Draisaitl", "Team": "EDM", "NHL GP": 830, "Level": "STD"},
    {"Player": "Ryan McLeod", "Team": "BUF", "NHL GP": 336, "Level": "STD"},
    {"Player": "Kaiden Guhle", "Team": "MTL", "NHL GP": 174, "Level": "STD"},
    {"Player": "Leo Carlsson", "Team": "ANA", "NHL GP": 169, "Level": "ELC"},
])

# =====================================================
# HELPERS
# =====================================================
def is_jouable(r):
    return r["NHL GP"] >= 84 and r["Level"] != "ELC"

def reason(r):
    if r["NHL GP"] < 84 and r["Level"] == "ELC":
        return "NHL GP < 84 et ELC"
    if r["NHL GP"] < 84:
        return "NHL GP < 84"
    if r["Level"] == "ELC":
        return "Contrat ELC"
    return ""

# =====================================================
# UI
# =====================================================
st.title("👤 Joueurs autonomes")
st.caption("Recherche → sélection (max 5) → confirmer. La sélection reste même si tu recherches autre chose.")

query = st.text_input("Nom / Prénom")

if not query.strip():
    st.info("Commence à taper un nom pour afficher des résultats.")
    st.stop()

results = PLAYERS[PLAYERS["Player"].str.lower().str.contains(query.lower())].copy()
results["Jouable"] = results.apply(is_jouable, axis=1)
results["Raison"] = results.apply(reason, axis=1)

# =====================================================
# RESULTS TABLE (IDIOTPROOF)
# =====================================================
st.subheader("📋 Résultats")

for _, r in results.iterrows():
    cols = st.columns([4, 2, 2, 2, 2, 3])

    cols[0].write(r["Player"])
    cols[1].write(r["Team"])
    cols[2].write(r["NHL GP"])
    cols[3].write("✅" if r["Jouable"] else "❌")

    if r["Player"] in st.session_state.selected_players:
        cols[4].success("Ajouté")
    else:
        cols[4].button(
            "➕ Ajouter",
            key=f"add_{r['Player']}",
            disabled=(
                not r["Jouable"]
                or len(st.session_state.selected_players) >= 5
            ),
            on_click=lambda p=r["Player"]: st.session_state.selected_players.append(p),
        )

    if not r["Jouable"]:
        cols[5].error(r["Raison"])

# =====================================================
# SELECTION
# =====================================================
st.divider()
st.subheader(f"✅ Sélection ({len(st.session_state.selected_players)} / 5)")

if not st.session_state.selected_players:
    st.caption("Aucun joueur sélectionné.")
else:
    for p in st.session_state.selected_players:
        c1, c2 = st.columns([6, 1])
        c1.write(p)
        if c2.button("❌", key=f"rm_{p}"):
            st.session_state.selected_players.remove(p)
            st.experimental_rerun()

# =====================================================
# CONFIRM
# =====================================================
if st.button(
    "🚨 Confirmer l’embauche",
    disabled=not st.session_state.selected_players,
    type="primary",
):
    st.success("Embauche confirmée : " + ", ".join(st.session_state.selected_players))
    st.session_state.selected_players = []
    st.experimental_rerun()
