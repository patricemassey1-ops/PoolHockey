
import streamlit as st
import os
import traceback

# ============================
# BOOT DIAGNOSTIC (ALWAYS)
# ============================
st.markdown("## ✅ BOOT: app.py chargé")

# ============================
# SAFE IMAGE (ANTI-CRASH)
# ============================
def safe_image(path: str, width=None, use_container_width=False, caption=None):
    p = str(path or "").strip()
    if not p:
        return
    if not os.path.exists(p):
        st.caption(f"🖼️ Image introuvable: {os.path.basename(p)}")
        return
    try:
        st.image(p, width=width, use_container_width=use_container_width, caption=caption)
    except Exception:
        st.caption(f"⚠️ Image non affichable: {os.path.basename(p)}")

# ============================
# PASSWORD GATE (SAFE)
# ============================
def require_password():
    if st.session_state.get("authed"):
        return True
    st.markdown("### 🔐 Accès sécurisé")
    pwd = st.text_input("Mot de passe", type="password")
    if st.button("Entrer"):
        # ⚠️ change 'secret' to your real password check
        if pwd == "secret":
            st.session_state["authed"] = True
            st.success("Connecté")
            st.stop()  # next rerun will be authed
        else:
            st.error("Mot de passe invalide")
            st.stop()
    st.stop()

require_password()

# ============================
# ANTI BLACK SCREEN WRAPPER
# ============================
try:
    st.markdown("## 🧊 PMS — Application chargée après login")
    st.caption("Si tu vois ceci, le problème n'est PAS le login ni les images.")

    # ----------------------------
    # SIDEBAR
    # ----------------------------
    st.sidebar.markdown("### Navigation")
    tab = st.sidebar.radio(
        "Onglet",
        ["🏠 Home", "👤 Joueurs autonomes", "🛠️ Admin"],
        key="nav_tab"
    )

    # ----------------------------
    # ROUTING
    # ----------------------------
    if tab == "🏠 Home":
        st.subheader("🏠 Home")
        st.write("Home fonctionne.")

    elif tab == "👤 Joueurs autonomes":
        st.subheader("👤 Joueurs autonomes")
        st.info("Cette page sert à valider que le rendu fonctionne.")
        st.write("Si tu vois ceci, le rendu d'onglet est OK.")

    elif tab == "🛠️ Admin":
        st.subheader("🛠️ Admin")
        st.write("Section admin OK.")

    else:
        st.warning("Onglet inconnu.")

    st.markdown("---")
    st.success("🎉 Aucun écran noir. Le rendu Streamlit fonctionne.")

except Exception:
    st.error("💥 CRASH DÉTECTÉ APRÈS LOGIN")
    st.code(traceback.format_exc())
    st.stop()
