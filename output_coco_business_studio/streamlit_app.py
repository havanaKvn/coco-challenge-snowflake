import os
import pandas as pd
import streamlit as st
import altair as alt

st.set_page_config(page_title="Dashboard COMEX — Qualite & Performance", page_icon=":bar_chart:", layout="wide")
conn = st.connection("snowflake", ttl=os.getenv("SNOWFLAKE_CONNECTION_TTL"))
session = conn.session()

STUDIO = "STUDIO_MARC"
VIEWS = f"{STUDIO}.VIEWS"


@st.cache_data(ttl=300)
def query(view_name):
    return session.sql(f"SELECT * FROM {VIEWS}.{view_name}").to_pandas()


# ── Header ────────────────────────────────────────────────────────────────

st.title(":bar_chart: Dashboard COMEX — Qualite & Performance")
st.caption(f"Studio : `{STUDIO}` | Source : `COCO_BUSINESS_STUDIO.RAW_DATA` | Genere par CoCo Business Studio")
st.divider()

# ── KPIs globaux ──────────────────────────────────────────────────────────

col1, col2, col3, col4 = st.columns(4)

try:
    df_ca = query("V_CA_TOTAL_ANNUEL")
    df_ca_global = df_ca[df_ca["NIVEAU"] == "Global"]
    if not df_ca_global.empty:
        with col1:
            ca = df_ca_global["CA_TOTAL_EUR"].iloc[0]
            st.metric("CA Total", f"{ca:,.0f} EUR")
except Exception:
    with col1:
        st.metric("CA Total", "N/A")

try:
    df_taux_ret = query("V_TAUX_RETARD_LIVRAISON")
    df_ret_global = df_taux_ret[df_taux_ret["NIVEAU"] == "Global"]
    if not df_ret_global.empty:
        with col2:
            taux = df_ret_global["TAUX_RETARD_PCT"].iloc[0]
            st.metric("Taux Retard", f"{taux:.1f}%")
except Exception:
    with col2:
        st.metric("Taux Retard", "N/A")

try:
    df_taux_rec = query("V_TAUX_RECLAMATION")
    df_rec_global = df_taux_rec[df_taux_rec["NIVEAU"] == "Global"]
    if not df_rec_global.empty:
        with col3:
            taux_r = df_rec_global["TAUX_RECLAMATION_PCT"].iloc[0]
            st.metric("Taux Reclamation", f"{taux_r:.1f}%")
except Exception:
    with col3:
        st.metric("Taux Reclamation", "N/A")

try:
    df_panier = query("V_PANIER_MOYEN")
    df_pan_global = df_panier[df_panier["NIVEAU"] == "Global"]
    if not df_pan_global.empty:
        with col4:
            pm = df_pan_global["PANIER_MOYEN_EUR"].iloc[0]
            st.metric("Panier Moyen", f"{pm:,.0f} EUR")
except Exception:
    with col4:
        st.metric("Panier Moyen", "N/A")

st.divider()

# ── Score Sante Region ────────────────────────────────────────────────────

st.subheader(":hospital: Score Sante par Region")
st.caption("Score composite : CA normalise - (taux reclamation x2) - taux retard. Plus c est haut, mieux c est.")
try:
    df_sante = query("V_SCORE_SANTE_REGION")
    if not df_sante.empty:
        c = alt.Chart(df_sante).mark_bar().encode(
            x=alt.X("SCORE_SANTE:Q", title="Score Sante"),
            y=alt.Y("NOM_REGION:N", sort="-x", title=""),
            color=alt.condition(
                alt.datum.SCORE_SANTE < 0,
                alt.value("#e74c3c"),
                alt.value("#2ecc71"),
            ),
            tooltip=["NOM_REGION", "SCORE_SANTE", "CA", "TAUX_RECLAMATION_PCT", "TAUX_RETARD_PCT"],
        ).properties(height=400)
        st.altair_chart(c, width="stretch")
except Exception as e:
    st.warning(f"Erreur Score Sante : {e}")

st.divider()

# ── Tabs : details ────────────────────────────────────────────────────────

tab_corr, tab_seg, tab_evo, tab_alerte, tab_risque = st.tabs([
    "Correlation Retard-Reclam",
    "Taux par Segment",
    "Evolution Mensuelle",
    "Regions en Alerte",
    "Top Clients Risque",
])

with tab_corr:
    st.subheader("Correlation Retard vs Reclamation par Region")
    st.caption("Compare le taux de retard et le taux de reclamation par region pour identifier les correlations.")
    try:
        df_corr = query("V_CORRELATION_RETARD_RECLAM")
        if not df_corr.empty:
            scatter = alt.Chart(df_corr).mark_circle(size=100).encode(
                x=alt.X("TAUX_RETARD_PCT:Q", title="Taux Retard (%)"),
                y=alt.Y("TAUX_RECLAMATION_PCT:Q", title="Taux Reclamation (%)"),
                size=alt.Size("CA_REGION:Q", title="CA Region"),
                color=alt.Color("NOM_REGION:N", legend=None),
                tooltip=["NOM_REGION", "TAUX_RETARD_PCT", "TAUX_RECLAMATION_PCT", "RETARD_MOYEN_JOURS", "CA_REGION"],
            ).properties(height=400)
            text = alt.Chart(df_corr).mark_text(dy=-12, fontSize=11).encode(
                x="TAUX_RETARD_PCT:Q",
                y="TAUX_RECLAMATION_PCT:Q",
                text="NOM_REGION:N",
            )
            st.altair_chart(scatter + text, width="stretch")
            with st.expander("Donnees"):
                st.dataframe(df_corr, width="stretch")
    except Exception as e:
        st.warning(f"Erreur : {e}")

with tab_seg:
    st.subheader("Taux de Reclamation par Segment Client")
    st.caption("Identifie si les Grands Comptes sont mieux ou moins bien servis que les PME/TPE.")
    try:
        df_seg = query("V_TAUX_RECLAM_SEGMENT")
        if not df_seg.empty:
            c = alt.Chart(df_seg).mark_bar().encode(
                x=alt.X("SEGMENT:N", title="Segment"),
                y=alt.Y("TAUX_RECLAMATION_PCT:Q", title="Taux Reclamation (%)"),
                color=alt.Color("SEGMENT:N"),
                tooltip=["SEGMENT", "NB_COMMANDES", "NB_RECLAMATIONS", "TAUX_RECLAMATION_PCT", "CA_MOYEN_PAR_CLIENT"],
            ).properties(height=350)
            st.altair_chart(c, width="stretch")
    except Exception as e:
        st.warning(f"Erreur : {e}")

    st.subheader("Performance par Segment")
    try:
        df_perf_seg = query("V_PERFORMANCE_SEGMENT")
        if not df_perf_seg.empty:
            st.dataframe(df_perf_seg, width="stretch")
    except Exception as e:
        st.warning(f"Erreur : {e}")

with tab_evo:
    st.subheader("Evolution Mensuelle")
    st.caption("Tendances CA, taux de retard et taux de reclamation mois par mois.")
    try:
        df_evo = query("V_EVOLUTION_MENSUELLE")
        if not df_evo.empty:
            df_evo = df_evo.sort_values("MOIS")
            col_a, col_b = st.columns(2)
            with col_a:
                st.markdown("**CA Total par mois**")
                st.bar_chart(df_evo.set_index("MOIS")["CA_TOTAL"])
            with col_b:
                st.markdown("**Taux Retard & Reclamation**")
                st.line_chart(df_evo.set_index("MOIS")[["TAUX_RETARD_PCT", "TAUX_RECLAMATION_PCT"]])
    except Exception as e:
        st.warning(f"Erreur : {e}")

with tab_alerte:
    st.subheader("Regions en Alerte (taux reclamation > 20%)")
    st.caption("Regions depassant le seuil critique. CRITIQUE = > 25%, ALERTE = > 20%.")
    try:
        df_alerte = query("V_ALERTE_REGIONS")
        if not df_alerte.empty:
            st.dataframe(
                df_alerte.style.apply(
                    lambda row: ["background-color: #ffcccc" if row["STATUT"] == "CRITIQUE" else "background-color: #fff3cd"] * len(row),
                    axis=1,
                ),
                width="stretch",
            )
        else:
            st.success("Aucune region en alerte !")
    except Exception as e:
        st.warning(f"Erreur : {e}")

with tab_risque:
    st.subheader("Top 10 Clients a Risque")
    st.caption("Clients avec le plus de jours de retard cumules.")
    try:
        df_top = query("V_TOP_CLIENTS_RISQUE")
        if not df_top.empty:
            st.dataframe(df_top, width="stretch")
    except Exception as e:
        st.warning(f"Erreur : {e}")

st.divider()

# ── Details supplementaires ───────────────────────────────────────────────

with st.expander(":mag: CA & Retards par Region"):
    col_a, col_b = st.columns(2)
    try:
        with col_a:
            df_ca_reg = query("V_CA_TOTAL_REGION")
            if not df_ca_reg.empty:
                st.bar_chart(df_ca_reg.set_index("NOM_REGION")["CA_TOTAL_EUR"])
        with col_b:
            df_ret_reg = query("V_MONTANT_RETARDS_REGION")
            if not df_ret_reg.empty:
                st.bar_chart(df_ret_reg.set_index("NOM_REGION")["MONTANT_TOTAL_RETARDS_EUR"])
    except Exception as e:
        st.warning(f"Erreur : {e}")

with st.expander(":mag: Repartition Reclamations par Type & Region"):
    try:
        df_rep = query("V_REPARTITION_RECLAMATIONS_REGION")
        if not df_rep.empty:
            c = alt.Chart(df_rep).mark_rect().encode(
                x=alt.X("TYPE_RECLAMATION:N", title="Type"),
                y=alt.Y("NOM_REGION:N", title=""),
                color=alt.Color("NB_RECLAMATIONS:Q", scale=alt.Scale(scheme="orangered")),
                tooltip=["NOM_REGION", "TYPE_RECLAMATION", "NB_RECLAMATIONS", "PCT_TYPE_REGION"],
            ).properties(height=400)
            st.altair_chart(c, width="stretch")
    except Exception as e:
        st.warning(f"Erreur : {e}")

with st.expander(":mag: Score Risque par Region"):
    try:
        df_risque = query("V_SCORE_RISQUE_REGION")
        if not df_risque.empty:
            st.dataframe(df_risque, width="stretch")
    except Exception as e:
        st.warning(f"Erreur : {e}")

# ── Sidebar ───────────────────────────────────────────────────────────────

st.sidebar.markdown("### Actualiser")
if st.sidebar.button("Rafraichir les donnees"):
    query.clear()
    st.rerun()

st.sidebar.caption("Genere par CoCo Business Studio")
