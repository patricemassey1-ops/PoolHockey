# --- GESTION (EMBAUCHE AVEC PÉNALITÉ DE 50% SUR LE CAP) ---
with tab3:
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("🆕 Embaucher un Agent Libre")
        available = st.session_state.db_joueurs.copy()
        
        if not available.empty:
            # Affichage du salaire COMPLET dans la liste
            available['label'] = available.apply(lambda r: f"{r['Joueur']} ({r['Pos']} - {r['Equipe_NHL']}) | Salaire: {format_currency(r['Salaire'])}", axis=1)
            
            with st.form("fa_form_2025"):
                f_prop = st.selectbox("Équipe Acquéreuse", teams if teams else ["Ma Ligue"])
                sel_label = st.selectbox("Sélectionner le joueur", available['label'].tolist())
                
                # Récupération des données originales
                player_row = available[available['label'] == sel_label].iloc[0]
                original_sal = player_row['Salaire']
                penalite_cap = int(original_sal * 0.5) 
                
                f_stat = st.radio("Assignation", ["Grand Club", "Club École"], horizontal=True)
                
                st.info(f"Note : Le joueur sera ajouté avec son salaire complet ({format_currency(original_sal)}). "
                        f"Une pénalité de cap de {format_currency(penalite_cap)} (50%) sera ajoutée automatiquement.")

                if st.form_submit_button("Confirmer l'embauche"):
                    # 1. Ajouter le joueur avec son salaire 100%
                    new_player = pd.DataFrame([{
                        'Joueur': player_row['Joueur'], 
                        'Salaire': original_sal, 
                        'Statut': f_stat,
                        'Pos': player_row['Pos'], 
                        'Equipe_NHL': player_row['Equipe_NHL'], 
                        'Propriétaire': f_prop
                    }])
                    st.session_state.historique = pd.concat([st.session_state.historique, new_player], ignore_index=True)
                    
                    # 2. Ajouter la pénalité de 50% dans la table des rachats/impacts
                    new_penalty = pd.DataFrame([{
                        'Propriétaire': f_prop, 
                        'Joueur': f"Pénalité JA: {player_row['Joueur']}", 
                        'Impact': penalite_cap
                    }])
                    st.session_state.rachats = pd.concat([st.session_state.rachats, new_penalty], ignore_index=True)
                    
                    save_all()
                    st.success(f"Embauche réussie pour {player_row['Joueur']}.")
                    st.rerun()
