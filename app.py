# --- AFFICHAGE PRINCIPAL ---
if not st.session_state['historique'].empty:
    df_f = st.session_state['historique']
    
    # CORRECTION APPLIQUÉE ICI :
    tab1, tab2 = st.tabs(["📊 Tableau de Bord", "⚖️ Simulateur Avancé"]) # Unpack en tab1 et tab2

    with tab1:
        st.header("Résumé des Masses Salariales")
        summary = df_f.groupby(['Propriétaire', 'Statut'])['Salaire'].sum().unstack(fill_value=0).reset_index()
        for col in ['Grand Club', 'Club École']:
            if col not in summary.columns: summary[col] = 0
        st.dataframe(summary.style.format({'Grand Club': format_currency, 'Club École': format_currency}), use_container_width=True)

        st.header("Détails des Effectifs")
        for eq in sorted(df_f['Propriétaire'].unique(), reverse=True):
            with st.expander(f"📂 {eq}"):
                col_a, col_b = st.columns(2)
                df_e = df_f[df_f['Propriétaire'] == eq]
                with col_a:
                    st.write("**Grand Club**")
                    st.table(df_e[df_e['Statut'] == "Grand Club"][['Joueur', 'Salaire']].assign(Salaire=lambda x: x['Salaire'].apply(format_currency)))
                with col_b:
                    st.write("**Club École**")
                    st.table(df_e[df_e['Statut'] == "Club École"][['Joueur', 'Salaire']].assign(Salaire=lambda x: x['Salaire'].apply(format_currency)))


    with tab2:
        st.header("🔄 Outil de Transfert Interactif")
        st.markdown("Utilisez le menu déroulant dans la colonne **`Statut`** pour changer l'affectation d'un joueur et voir l'impact sur le cap.")

        # 1. Sélection de l'équipe
        equipe_sim_choisie = st.selectbox("Sélectionner l'équipe à simuler", options=df_f['Propriétaire'].unique(), key='simulateur_equipe')
        
        df_sim = df_f[df_f['Propriétaire'] == equipe_sim_choisie].copy()
        
        # 2. Utilisation de st.data_editor pour permettre l'édition du statut
        df_sim = df_sim.sort_values(['pos_order', 'Statut', 'Salaire'], ascending=[True, False, False])
        
        edited_data = st.data_editor(
            df_sim[['Joueur', 'Pos', 'Salaire', 'Statut']],
            column_config={
                "Statut": st.column_config.SelectboxColumn(
                    "Statut",
                    help="Déplacer le joueur entre les clubs",
                    width="medium",
                    options=["Grand Club", "Club École"],
                    required=True,
                ),
                "Salaire": st.column_config.Column(format="%.0f $"),
            },
            hide_index=True,
            use_container_width=True,
            key=f'editor_{equipe_sim_choisie}'
        )

        # 3. Calculer les totaux simulés à partir des données éditées
        sim_g = edited_data[edited_data['Statut'] == "Grand Club"]['Salaire'].sum()
        sim_c = edited_data[edited_data['Statut'] == "Club École"]['Salaire'].sum()

        st.markdown("---")
        c1, c2 = st.columns(2)
        
        # Affichage des métriques de plafond simulées
        c1.metric(
            "Simulé: Grand Club", 
            format_currency(sim_g), 
            delta=format_currency(CAP_GRAND_CLUB - sim_g), 
            delta_color="normal" if sim_g <= CAP_GRAND_CLUB else "inverse"
        )
        c2.metric(
            "Simulé: Club École", 
            format_currency(sim_c), 
            delta=format_currency(CAP_CLUB_ECOLE - sim_c),
            delta_color="normal" if sim_c <= CAP_CLUB_ECOLE else "inverse"
        )

else:
    st.info("Importez un fichier CSV pour activer les fonctionnalités.")

