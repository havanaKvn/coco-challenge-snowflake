import os
import json
import re
import pandas as pd
import streamlit as st
import altair as alt

st.set_page_config(page_title="CoCo Business Studio", page_icon=":bar_chart:", layout="wide")

PHASES = [
    ("cadrage", "Cadrage du besoin"),
    ("discovery", "Exploration des données"),
    ("kpi_design", "Conception des indicateurs"),
    ("dashboard", "Tableau de bord"),
    ("export", "Livraison"),
]
PHASE_ICONS = {"cadrage": ":speech_balloon:", "discovery": ":mag:", "kpi_design": ":hammer_and_wrench:", "dashboard": ":bar_chart:", "export": ":rocket:"}

conn = st.connection("snowflake", ttl=os.getenv("SNOWFLAKE_CONNECTION_TTL"))
session = conn.session()

INFRA_DB = "COCO_BUSINESS_STUDIO"
INFRA_SCHEMA = "RAW_DATA"
PROJECTS_TABLE = f"{INFRA_DB}.{INFRA_SCHEMA}.STUDIO_PROJECTS"

TABLE_CATALOG = {
    "REGIONS": {"desc": "12 regions commerciales France", "cols": "REGION_ID, NOM_REGION, CODE_REGION, ZONE_GEOGRAPHIQUE"},
    "CLIENTS": {"desc": "200 clients rattaches aux regions", "cols": "CLIENT_ID, NOM_CLIENT, REGION_ID, SEGMENT, DATE_CREATION"},
    "COMMANDES": {"desc": "2000 commandes sur 6 mois", "cols": "COMMANDE_ID, CLIENT_ID, DATE_COMMANDE, DATE_LIVRAISON_PREVUE, DATE_LIVRAISON_REELLE, RETARD_JOURS, MONTANT_EUR, STATUT"},
    "RECLAMATIONS": {"desc": "400 reclamations liees aux commandes", "cols": "RECLAMATION_ID, COMMANDE_ID, DATE_RECLAMATION, TYPE_RECLAMATION, SEVERITE, STATUT_RECLAMATION"},
}
RELATIONS = "CLIENTS.REGION_ID -> REGIONS.REGION_ID, COMMANDES.CLIENT_ID -> CLIENTS.CLIENT_ID, RECLAMATIONS.COMMANDE_ID -> COMMANDES.COMMANDE_ID"

SKILLS_DOC = ""
try:
    with open(os.path.join(os.path.dirname(__file__), "SKILLS.md"), "r") as f:
        SKILLS_DOC = f.read()
except Exception:
    pass


# ── Studio DB management ──────────────────────────────────────────────────

def list_studio_databases():
    try:
        rows = session.sql("SHOW DATABASES LIKE 'STUDIO\\_%'").collect()
        return sorted([str(r[1]) for r in rows])
    except Exception:
        return []

def create_studio_database(name):
    try:
        role = session.sql("SELECT CURRENT_ROLE()").collect()[0][0]
        session.sql(f'CREATE DATABASE IF NOT EXISTS "{name}"').collect()
        session.sql(f'CREATE SCHEMA IF NOT EXISTS "{name}".VIEWS').collect()
        session.sql(f'CREATE SCHEMA IF NOT EXISTS "{name}".DASHBOARDS').collect()
        for s in ["VIEWS", "DASHBOARDS", "PUBLIC"]:
            try:
                session.sql(f'GRANT ALL PRIVILEGES ON SCHEMA "{name}".{s} TO ROLE {role}').collect()
            except Exception:
                pass
        try:
            session.sql(f'GRANT ALL PRIVILEGES ON DATABASE "{name}" TO ROLE {role}').collect()
        except Exception:
            pass
        return True, None
    except Exception as e:
        return False, str(e)

def get_studio_db():
    return st.session_state.get("studio_db", None)

# ── Studio selector ───────────────────────────────────────────────────────

if "studio_db" not in st.session_state:
    st.title(":bar_chart: CoCo Business Studio")
    st.markdown("### Choisissez ou créez votre Studio")
    existing = list_studio_databases()
    tab_sel, tab_new = st.tabs(["Ouvrir un Studio", "Creer un Studio"])
    with tab_sel:
        if existing:
            chosen = st.selectbox("Studios :", existing, index=None, placeholder="Selectionnez...")
            if chosen and st.button("Ouvrir", key="open_studio", width="stretch"):
                st.session_state["studio_db"] = chosen
                st.rerun()
        else:
            st.info("Aucun studio. Creez-en un.")
    with tab_new:
        user = session.sql("SELECT CURRENT_USER()").collect()[0][0]
        new_name = st.text_input("Nom :", value=f"STUDIO_{user}")
        new_name = new_name.strip().upper().replace(" ", "_")
        if not new_name.startswith("STUDIO_"):
            new_name = f"STUDIO_{new_name}"
        if st.button(f"Creer **{new_name}**", key="create_studio", width="stretch"):
            ok, err = create_studio_database(new_name)
            if ok:
                st.session_state["studio_db"] = new_name
                st.rerun()
            else:
                st.error(f"Erreur: {err}")
    st.stop()

STUDIO_DB = get_studio_db()


# ── Persistence ───────────────────────────────────────────────────────────

def save_project():
    p = st.session_state.product
    pid = st.session_state.get("project_id")
    msgs = [{"role": m["role"], "content": m["content"]} for m in st.session_state.messages]
    state_j = json.dumps({**p, "studio_db": STUDIO_DB}, ensure_ascii=False).replace("'", "''")
    msgs_j = json.dumps(msgs, ensure_ascii=False).replace("'", "''")
    name = (p.get("brief", {}).get("objectif", "") or "Sans titre")[:120].replace("'", "''")
    try:
        if pid:
            session.sql(f"UPDATE {PROJECTS_TABLE} SET STATE=PARSE_JSON('{state_j}'), MESSAGES=PARSE_JSON('{msgs_j}'), PROJECT_NAME='{name}', UPDATED_AT=CURRENT_TIMESTAMP() WHERE PROJECT_ID='{pid}'").collect()
        else:
            r = session.sql(f"INSERT INTO {PROJECTS_TABLE} (PROJECT_NAME,STATE,MESSAGES) SELECT '{name}',PARSE_JSON('{state_j}'),PARSE_JSON('{msgs_j}') RETURNING PROJECT_ID").collect()
            if r:
                st.session_state["project_id"] = str(r[0][0])
    except Exception:
        pass

def load_project(pid):
    try:
        rows = session.sql(f"SELECT STATE, MESSAGES FROM {PROJECTS_TABLE} WHERE PROJECT_ID='{pid}'").collect()
        if rows:
            state = json.loads(str(rows[0][0]))
            st.session_state["studio_db"] = state.pop("studio_db", STUDIO_DB)
            st.session_state.product = state
            st.session_state.messages = json.loads(str(rows[0][1]))
            st.session_state["project_id"] = pid
            st.session_state.created_views = [k["view_name"] for k in state.get("kpis", []) if k.get("created")]
            st.session_state.pop("pending_question", None)
            return True
    except Exception:
        pass
    return False

def list_projects():
    try:
        rows = session.sql(f"SELECT PROJECT_ID, PROJECT_NAME, UPDATED_AT FROM {PROJECTS_TABLE} WHERE OWNER=CURRENT_USER() ORDER BY UPDATED_AT DESC LIMIT 20").collect()
        return [(str(r[0]), str(r[1]), r[2]) for r in rows]
    except Exception:
        return []

def delete_project(pid):
    try:
        session.sql(f"DELETE FROM {PROJECTS_TABLE} WHERE PROJECT_ID='{pid}'").collect()
    except Exception:
        pass


# ── Session state ─────────────────────────────────────────────────────────

def _default_product():
    return {"phase": "cadrage", "brief": {}, "tables": [], "kpis": [], "dashboard": []}

def _init():
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "product" not in st.session_state:
        st.session_state.product = _default_product()
    if "created_views" not in st.session_state:
        st.session_state.created_views = []

_init()
product = st.session_state.product


# ── Helpers ───────────────────────────────────────────────────────────────

def fq(name):
    return f"{STUDIO_DB}.VIEWS.{name}"

def fq_source(table):
    return f"{INFRA_DB}.{INFRA_SCHEMA}.{table}"

def run_query_safe(sql):
    try:
        return session.sql(sql).to_pandas()
    except Exception:
        return None

def create_view(name, sql):
    try:
        session.sql(f"CREATE SCHEMA IF NOT EXISTS {STUDIO_DB}.VIEWS").collect()
    except Exception:
        pass
    # Strip any DDL prefix the LLM may have included
    # Handles: CREATE [OR REPLACE] VIEW name [COMMENT='...'] AS SELECT ...
    sql_clean = re.sub(
        r"^\s*CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+\S+\s*(?:COMMENT\s*=\s*'[^']*'\s*)?\s*AS\s+",
        "",
        sql.strip(),
        flags=re.IGNORECASE,
    )
    view_sql = f"CREATE OR REPLACE VIEW {fq(name)} AS {sql_clean}"
    try:
        session.sql(view_sql).collect()
        if name not in st.session_state.created_views:
            st.session_state.created_views.append(name)
        return True, view_sql
    except Exception as e:
        return False, f"{e}\nSQL: {view_sql}"

def table_context_block():
    lines = [f"- {fq_source(t)} ({info['desc']}): {info['cols']}" for t, info in TABLE_CATALOG.items()]
    lines.append(f"Relations: {RELATIONS}")
    lines.append("RETARD_JOURS = jours de retard (0 si pas de retard).")
    return "\n".join(lines)

def find_kpi_by_name(name):
    # Normalize: strip FQ prefix if present
    short = name.split(".")[-1] if "." in name else name
    for k in product["kpis"]:
        kn = k["name"].split(".")[-1] if "." in k["name"] else k["name"]
        kv = k.get("view_name", "").split(".")[-1] if "." in k.get("view_name", "") else k.get("view_name", "")
        if kn == short or kv == short or k["name"] == name or k.get("view_name") == name:
            return k
    return None


# ── Dashboard file generator ──────────────────────────────────────────────

def generate_dashboard_file():
    created_kpis = [k for k in product["kpis"] if k.get("created")]
    components = product["dashboard"]
    brief = product["brief"]
    title = brief.get("objectif", "Dashboard")[:60]

    lines = [
        'import os', 'import pandas as pd', 'import streamlit as st', 'import altair as alt', '',
        f'st.set_page_config(page_title="{title}", layout="wide")',
        'conn = st.connection("snowflake", ttl=os.getenv("SNOWFLAKE_CONNECTION_TTL"))',
        'session = conn.session()', '',
        f'st.title("{title}")',
        f'st.caption("Studio: {STUDIO_DB} | Genere par CoCo Business Studio")',
        'st.divider()', '',
    ]

    metric_comps = [c for c in components if c["type"] == "metric"]
    if metric_comps:
        lines.append(f'cols = st.columns({len(metric_comps)})')
        for i, comp in enumerate(metric_comps):
            kpi = find_kpi_by_name(comp["kpi_name"])
            if kpi:
                desc = kpi.get("description", "")
                lines.append(f'with cols[{i}]:')
                lines.append(f'    df = session.sql("SELECT * FROM {fq(kpi["view_name"])}").to_pandas()')
                lines.append(f'    ncols = df.select_dtypes(include=["number"]).columns.tolist()')
                lines.append(f'    if ncols:')
                lines.append(f'        val = df[ncols[0]].iloc[0]')
                lines.append(f'        st.metric("{comp["title"]}", f"{{val:,.2f}}" if isinstance(val, float) else str(val))')
                if desc:
                    lines.append(f'        st.caption("{desc}")')
        lines.append('')

    for comp in [c for c in components if c["type"] in ("bar", "line", "pie", "table")]:
        kpi = find_kpi_by_name(comp["kpi_name"])
        if kpi:
            desc = kpi.get("description", "")
            lines.append(f'st.subheader("{comp["title"]}")')
            if desc:
                lines.append(f'st.caption("{desc}")')
            lines.append(f'df = session.sql("SELECT * FROM {fq(kpi["view_name"])}").to_pandas()')
            lines.append('for col in df.columns:')
            lines.append("    df[col] = pd.to_numeric(df[col], errors='coerce')")
            lines.append('numeric = df.select_dtypes(include=["number"]).columns.tolist()')
            lines.append('non_numeric = df.select_dtypes(exclude=["number"]).columns.tolist()')
            lines.append('if numeric and non_numeric:')
            if comp["type"] == "bar":
                lines.append('    st.bar_chart(df.set_index(non_numeric[0])[numeric[:3]])')
            elif comp["type"] == "line":
                lines.append('    st.line_chart(df.set_index(non_numeric[0])[numeric[:3]])')
            elif comp["type"] == "pie":
                lines.append('    c = alt.Chart(df).mark_arc(innerRadius=50).encode(theta=alt.Theta(field=numeric[0], type="quantitative"), color=alt.Color(field=non_numeric[0], type="nominal"), tooltip=[non_numeric[0], numeric[0]]).properties(height=400)')
                lines.append('    st.altair_chart(c, width="stretch")')
            elif comp["type"] == "table":
                lines.append('    st.dataframe(df, width="stretch")')
            lines.append('')

    return "\n".join(lines)


# ── LLM ───────────────────────────────────────────────────────────────────

def llm_call(system_msg, user_msg):
    s = system_msg.replace("'", "''")
    u = user_msg.replace("'", "''")
    try:
        r = session.sql(f"SELECT SNOWFLAKE.CORTEX.COMPLETE('claude-sonnet-4-5',[{{'role':'system','content':'{s}'}},{{'role':'user','content':'{u}'}}],{{'temperature':0.3,'max_tokens':4000}})").collect()
        if r:
            raw = str(r[0][0])
            try:
                parsed = json.loads(raw)
                msg = parsed.get("choices", [{}])[0].get("messages", "")
                if isinstance(msg, str) and msg:
                    return msg
                msg = parsed.get("choices", [{}])[0].get("message", {})
                if isinstance(msg, dict):
                    return msg.get("content", raw)
                return raw
            except (json.JSONDecodeError, TypeError, IndexError):
                return raw
    except Exception as e:
        return f"[Erreur LLM: {e}]"


def build_system_prompt():
    phase = product["phase"]
    brief = product["brief"]
    tables = product["tables"]
    kpis = product["kpis"]

    base = ""
    if SKILLS_DOC:
        base += f"REFERENCE:\n{SKILLS_DOC}\n\n"

    base += (
        "Tu es CoCo, assistant concepteur de produits data expert et proactif.\n"
        f"STUDIO: {STUDIO_DB}.VIEWS | SOURCE: {INFRA_DB}.{INFRA_SCHEMA}\n\n"
        "STYLE: Concis (3-5 phrases). Proactif. Challenge l utilisateur avec des idees.\n\n"
        "ACTIONS: termine CHAQUE reponse par @@ACTIONS@@ [...] @@END_ACTIONS@@.\n"
        "Le contenu DOIT etre un TABLEAU JSON valide avec virgules: [{...}, {...}]\n"
        "Types:\n"
        '  {"type":"set_brief","field":"role|domaine|objectif|audience","value":"..."}\n'
        '  {"type":"select_tables","tables":["T1"]}\n'
        '  {"type":"propose_kpi","name":"V_...","description":"...","sql":"SELECT ..."}\n'
        '  {"type":"create_view","view_name":"V_...","sql":"SELECT ..."}\n'
        '  {"type":"add_dashboard_component","component_type":"metric|bar|line|pie|table|heatmap","title":"...","kpi_name":"..."}\n'
        '  {"type":"advance_phase"}\n'
        '  {"type":"ask","question":"...","options":["a","b","c"]}\n'
        '  {"type":"none"}\n\n'
        "REGLES:\n"
        "1. create_view EXECUTE REELLEMENT le DDL dans Snowflake.\n"
        "2. propose_kpi = proposition en attente. create_view = creation reelle.\n"
        "3. Flux KPI: propose_kpi -> user valide -> create_view pour chacun + advance_phase.\n"
        "4. Pour Discovery: agis directement.\n"
        "5. Pour Dashboard: CHALLENGE l utilisateur avec ask sur le style/type de chaque visualisation.\n"
        "6. Chaque KPI description doit expliquer: ce que ca mesure, comment c est calcule, pourquoi c est utile.\n"
        f"7. SQL: {INFRA_DB}.{INFRA_SCHEMA}.TABLE. Vues: V_ prefix.\n\n"
        "QUALITE DES KPIs:\n"
        "- Propose des KPIs AVANCES, pas juste des aggregations simples.\n"
        "- Utilise des ratios, taux, comparaisons, rankings, moyennes mobiles, ecarts.\n"
        "- Exemples: taux de reclamation croise avec retard, CA moyen par client actif, "
        "score de performance region (composite), evolution MoM, concentration Pareto.\n"
        "- Chaque KPI doit apporter un INSIGHT actionnable, pas juste un chiffre brut.\n\n"
    )

    if phase == "cadrage":
        filled = list(brief.keys())
        missing = [f for f in ["role", "domaine", "objectif", "audience"] if f not in brief]
        base += f"PHASE: CADRAGE | Rempli: {filled} | Manquant: {missing}\n"
        if len(missing) <= 1:
            base += (
                "Recapitule le brief en 2-3 lignes. NE PROPOSE PAS de KPIs.\n"
                "Puis utilise ask pour demander validation: "
                '["C\'est exact, on y va", "Je veux modifier quelque chose"].\n'
                "Si l utilisateur valide, ALORS advance_phase.\n"
            )
        else:
            base += "Pose UNE question couvrant plusieurs champs.\n"
    elif phase == "discovery":
        base += f"PHASE: DISCOVERY\nBrief: {json.dumps(brief, ensure_ascii=False)}\nTables:\n{table_context_block()}\n"
        base += "Selectionne les tables (select_tables) + advance_phase directement.\n"
    elif phase == "kpi_design":
        pending = [k for k in kpis if not k.get("created")]
        created = [k for k in kpis if k.get("created")]
        base += f"PHASE: DESIGN KPI\nBrief: {json.dumps(brief, ensure_ascii=False)}\nTables: {tables}\nSchema:\n{table_context_block()}\n"
        base += f"Proposes: {json.dumps([k['name'] for k in pending], ensure_ascii=False)}\nCrees: {json.dumps([k['name'] for k in created], ensure_ascii=False)}\n"
        if not pending and not created:
            brief_text = json.dumps(brief, ensure_ascii=False).lower()
            if any(kw in brief_text for kw in ["reclam", "retard", "comex", "qualite", "livraison"]):
                base += (
                    "Le brief correspond au cas Reclamations/Retards/COMEX. "
                    "Utilise les KPIs de reference du SKILLS.md : "
                    "V_TAUX_RECLAM_SEGMENT, V_CORRELATION_RETARD_RECLAM, V_SCORE_SANTE_REGION, "
                    "V_EVOLUTION_MENSUELLE, V_ALERTE_REGIONS. "
                    "Reprends le SQL de reference EXACTEMENT tel quel dans les propose_kpi. "
                    "Propose les 5 KPIs avec leurs descriptions. Puis ask validation.\n"
                )
            else:
                base += "Propose 3-5 KPIs avances (propose_kpi avec description detaillee). Puis ask validation.\n"
        elif pending:
            base += "User a valide. Emet create_view pour CHAQUE KPI propose + advance_phase. Un seul bloc.\n"
        elif created:
            base += "KPIs crees. Si user satisfait, advance_phase.\n"
    elif phase == "dashboard":
        base += f"PHASE: DASHBOARD\nKPIs: {json.dumps([{'name':k['name'],'view':k['view_name'],'desc':k.get('description','')} for k in kpis if k.get('created')], ensure_ascii=False)}\n"
        base += f"Composants actuels: {json.dumps(product['dashboard'], ensure_ascii=False)}\n"
        if not product["dashboard"]:
            base += (
                "Propose un layout de dashboard en CHALLENGEANT l utilisateur.\n"
                "Utilise ask pour demander ses preferences:\n"
                "- Style general (executif minimaliste vs analytique detaille vs operationnel temps-reel)\n"
                "- Pour les KPIs cles, propose 2-3 types de visu possibles et demande lequel il prefere\n"
                "Puis ajoute les composants selon ses choix. Sois force de proposition.\n"
            )
        else:
            base += "Composants ajoutes. Si user satisfait, advance_phase.\n"
    elif phase == "export":
        base += "PHASE: EXPORT\nResume ce qui a ete cree.\n"

    return base


# ── Action parsing ────────────────────────────────────────────────────────

def parse_actions(response_text):
    if not isinstance(response_text, str):
        response_text = str(response_text)
    match = re.search(r"@@ACTIONS@@\s*(.*?)\s*@@END_ACTIONS@@", response_text, re.DOTALL)
    if not match:
        match = re.search(r"```json\s*\n?\s*(\[.*?\])\s*\n?\s*```", response_text, re.DOTALL)
    if not match:
        return [], response_text

    actions_str = match.group(1).strip()
    clean_text = response_text[:match.start()].strip()

    # Try valid JSON first
    try:
        actions = json.loads(actions_str)
        if isinstance(actions, dict):
            actions = [actions]
        return actions, clean_text
    except json.JSONDecodeError:
        pass

    # Fallback: extract individual JSON objects (LLM sometimes omits array/commas)
    objects = re.findall(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', actions_str)
    if objects:
        actions = []
        for o in objects:
            try:
                obj = json.loads(o)
                if isinstance(obj, dict) and "type" in obj:
                    actions.append(obj)
            except json.JSONDecodeError:
                continue
        if actions:
            return actions, clean_text

    return [], response_text


def execute_actions(actions):
    results = []
    for action in actions:
        atype = action.get("type", "none")

        if atype == "set_brief":
            f, v = action.get("field", ""), action.get("value", "")
            if f in ("role", "domaine", "objectif", "audience"):
                product["brief"][f] = v

        elif atype == "select_tables":
            product["tables"] = action.get("tables", [])
            results.append(f"Tables : {', '.join(product['tables'])}")

        elif atype == "propose_kpi":
            product["kpis"].append({
                "name": action.get("name", "KPI"),
                "description": action.get("description", ""),
                "sql": action.get("sql", ""),
                "view_name": "", "created": False,
            })

        elif atype == "create_view":
            vname = action.get("view_name", "").strip()
            # Strip any FQ prefix the LLM may have added (STUDIO_X.VIEWS.V_NAME -> V_NAME)
            if "." in vname:
                vname = vname.split(".")[-1]
            sql = action.get("sql", "")
            if vname and sql:
                ok, detail = create_view(vname, sql)
                if ok:
                    linked = False
                    for kpi in product["kpis"]:
                        if not kpi["created"] and (kpi["view_name"] == "" or kpi["view_name"] == vname or kpi["name"] == vname):
                            kpi["view_name"] = vname
                            kpi["created"] = True
                            kpi["sql"] = sql
                            linked = True
                            break
                    if not linked:
                        product["kpis"].append({"name": vname.replace("V_", "").replace("_", " ").title(), "description": "", "sql": sql, "view_name": vname, "created": True})
                    results.append(f":white_check_mark: Vue **{fq(vname)}** creee")
                else:
                    results.append(f":x: Erreur vue {vname}: {detail}")

        elif atype == "add_dashboard_component":
            product["dashboard"].append({"type": action.get("component_type", "metric"), "title": action.get("title", ""), "kpi_name": action.get("kpi_name", "")})

        elif atype == "advance_phase":
            idx = next((i for i, (k, _) in enumerate(PHASES) if k == product["phase"]), 0)
            if idx < len(PHASES) - 1:
                product["phase"] = PHASES[idx + 1][0]
                results.append(f":arrow_forward: Phase : **{PHASES[idx + 1][1]}**")
                st.session_state["auto_continue"] = True

        elif atype == "ask":
            q, opts = action.get("question", ""), action.get("options", [])
            if q and opts:
                st.session_state["pending_question"] = {"question": q, "options": opts}

    return results


# ── Charts ────────────────────────────────────────────────────────────────

def detect_chart_type(df, hint="bar"):
    df2 = df.copy()
    for col in df2.columns:
        try:
            df2[col] = pd.to_numeric(df2[col])
        except (ValueError, TypeError):
            pass
    numeric = df2.select_dtypes(include=["number"]).columns.tolist()
    non_numeric = [c for c in df2.columns if c not in numeric]
    if not numeric or not non_numeric:
        return None, None, None
    return hint, non_numeric[0], numeric[:3]

def render_chart(chart_type, df, label_col, value_cols):
    if chart_type == "pie":
        c = alt.Chart(df).mark_arc(innerRadius=50).encode(theta=alt.Theta(field=value_cols[0], type="quantitative"), color=alt.Color(field=label_col, type="nominal"), tooltip=[label_col, value_cols[0]]).properties(height=400)
        st.altair_chart(c, width="stretch")
    elif chart_type == "line":
        st.line_chart(df.set_index(label_col)[value_cols])
    else:
        st.bar_chart(df.set_index(label_col)[value_cols])

def render_dashboard_preview():
    created_kpis = [k for k in product["kpis"] if k.get("created")]
    components = product["dashboard"]
    if not created_kpis and not components:
        return
    st.divider()
    st.subheader(":bar_chart: Apercu Dashboard")

    metric_comps = [c for c in components if c["type"] == "metric"]
    if metric_comps:
        cols = st.columns(len(metric_comps))
        for i, comp in enumerate(metric_comps):
            kpi = find_kpi_by_name(comp["kpi_name"])
            if kpi:
                df = run_query_safe(f"SELECT * FROM {fq(kpi['view_name'])}")
                if df is not None and not df.empty:
                    ncols = df.select_dtypes(include=["number"]).columns.tolist()
                    if ncols:
                        val = df[ncols[0]].iloc[0]
                        with cols[i]:
                            st.metric(comp["title"], f"{val:,.2f}" if isinstance(val, float) else str(val))
                            if kpi.get("description"):
                                st.caption(kpi["description"])

    for comp in [c for c in components if c["type"] in ("bar", "line", "pie", "table")]:
        kpi = find_kpi_by_name(comp["kpi_name"])
        if kpi:
            df = run_query_safe(f"SELECT * FROM {fq(kpi['view_name'])}")
            if df is not None and not df.empty:
                st.markdown(f"**{comp['title']}**")
                if kpi.get("description"):
                    st.caption(kpi["description"])
                if comp["type"] == "table":
                    st.dataframe(df, width="stretch")
                else:
                    ctype, label, vals = detect_chart_type(df, comp["type"])
                    if ctype:
                        render_chart(ctype, df, label, vals)


# ── LLM processing (shared by all triggers) ──────────────────────────────

def process_llm(prompt_override=None):
    history = ""
    for msg in st.session_state.messages[-10:]:
        history += f"[{msg['role']}]: {msg['content']}\n"

    user_msg = prompt_override or f"Historique:\n{history}\n\nMessage: {st.session_state.messages[-1]['content']}"
    response = llm_call(build_system_prompt(), user_msg if prompt_override else f"Historique:\n{history}\n\nMessage: {st.session_state.messages[-1]['content']}")
    actions, clean_text = parse_actions(response)

    with st.chat_message("assistant"):
        st.markdown(clean_text)

        action_results = []
        sql_preview = None

        if actions:
            action_results = execute_actions(actions)
            for ar in action_results:
                st.info(ar)

            for a in actions:
                if a.get("type") == "create_view" and a.get("sql"):
                    vn = a["view_name"]
                    sql_preview = f"CREATE OR REPLACE VIEW {fq(vn)} AS\n{a['sql']}"
                    df = run_query_safe(f"SELECT * FROM {fq(vn)} LIMIT 10")
                    if df is not None and not df.empty:
                        with st.expander(f":open_file_folder: Aperçu — {vn.replace('V_', '').replace('_', ' ').title()}"):
                            st.dataframe(df, width="stretch")
                        ct, lbl, vals = detect_chart_type(df)
                        if ct and len(df) > 1:
                            render_chart(ct, df, lbl, vals)

        st.session_state.messages.append({
            "role": "assistant", "content": clean_text,
            "action_results": action_results or None, "sql_preview": sql_preview,
        })
        save_project()


# ── Sidebar ───────────────────────────────────────────────────────────────

with st.sidebar:
    st.header(":bar_chart: CoCo Business Studio")
    st.caption(f"Espace de travail : **{STUDIO_DB}**")

    if st.button(":arrows_counterclockwise: Changer d'espace", width="stretch"):
        for k in ["studio_db", "project_id", "pending_question"]:
            st.session_state.pop(k, None)
        st.session_state.messages = []
        st.session_state.product = _default_product()
        st.session_state.created_views = []
        st.rerun()

    projects = list_projects()
    if projects:
        st.markdown("---")
        st.subheader(":open_file_folder: Mes projets")
        for pid, pname, _ in projects:
            is_cur = st.session_state.get("project_id") == pid
            c1, c2, c3 = st.columns([5, 2, 1])
            with c1:
                st.markdown(f":arrow_forward: **{(pname[:35] or 'Sans titre')}**" if is_cur else (pname[:35] or "Sans titre"))
            with c2:
                if not is_cur and st.button(":inbox_tray:", key=f"ld_{pid}", help="Reprendre"):
                    load_project(pid)
                    st.rerun()
            with c3:
                if st.button(":wastebasket:", key=f"dl_{pid}", help="Supprimer"):
                    delete_project(pid)
                    if st.session_state.get("project_id") == pid:
                        st.session_state.pop("project_id", None)
                        st.session_state.messages = []
                        st.session_state.product = _default_product()
                        st.session_state.created_views = []
                    st.rerun()

    st.markdown("---")
    st.subheader("Avancement")
    cur_idx = next((i for i, (k, _) in enumerate(PHASES) if k == product["phase"]), 0)
    for i, (key, label) in enumerate(PHASES):
        if i < cur_idx:
            st.markdown(f":white_check_mark: ~~{label}~~")
        elif i == cur_idx:
            st.markdown(f":arrow_forward: **{label}**")
        else:
            st.markdown(f":white_circle: {label}")

    if product["brief"]:
        st.markdown("---")
        st.subheader(":clipboard: Votre besoin")
        for f, v in product["brief"].items():
            st.markdown(f"**{f.title()}** : {v}")

    if product["kpis"]:
        st.markdown("---")
        st.subheader(":dart: Indicateurs")
        for kpi in product["kpis"]:
            if kpi.get("created"):
                st.markdown(f":white_check_mark: **{kpi['name']}**")
                if kpi.get("description"):
                    st.caption(kpi["description"])
            else:
                st.markdown(f":hourglass_flowing_sand: {kpi['name']} *(en attente)*")

    st.markdown("---")
    c1, c2 = st.columns(2)
    with c1:
        if st.button(":floppy_disk: Enregistrer", width="stretch"):
            save_project()
            st.toast("Projet enregistré ! Vous pourrez le reprendre plus tard.", icon="\u2705")
    with c2:
        if st.button(":sparkles: Nouveau", width="stretch"):
            st.session_state.messages = []
            st.session_state.product = _default_product()
            st.session_state.created_views = []
            for k in ["project_id", "pending_question"]:
                st.session_state.pop(k, None)
            st.rerun()
    st.caption("Vos projets sont sauvegardés automatiquement. Vous pouvez les reprendre à tout moment.")


# ── Header ────────────────────────────────────────────────────────────────

phase_label = next((label for k, label in PHASES if k == product["phase"]), "")
st.title(":bar_chart: CoCo Business Studio")
st.caption(f"{PHASE_ICONS.get(product['phase'], '')} **{phase_label}**")
st.divider()

# ── Welcome ───────────────────────────────────────────────────────────────

if not st.session_state.messages:
    st.session_state.messages.append({
        "role": "assistant",
        "content": (
            "Bienvenue dans le **CoCo Business Studio** !\n\n"
            "Je suis votre assistant pour concevoir des tableaux de bord et des indicateurs sur mesure.\n\n"
            "**Pour commencer, dites-moi : quel est votre rôle, et qu'avez-vous besoin de mesurer ou de suivre ?**"
        ),
    })

# ── Suggestion pills ─────────────────────────────────────────────────────

SUGGESTIONS_BY_PHASE = {
    "cadrage": {},
    "discovery": {":mag: Explorer les données": "Montre-moi les données disponibles.", ":white_check_mark: C'est bon, on continue": "OK, on passe aux indicateurs."},
    "kpi_design": {":bulb: Proposer des indicateurs": "Propose-moi les indicateurs les plus pertinents.", ":arrow_forward: Passer au tableau de bord": "C'est bon, passons au tableau de bord."},
    "dashboard": {":art: Proposer un tableau de bord": "Propose-moi un tableau de bord complet.", ":rocket: Finaliser": "On passe à la livraison."},
    "export": {":page_facing_up: Préparer les livrables": "Prépare les livrables pour l'équipe technique."},
}

if "pending_question" not in st.session_state:
    cur_sugs = SUGGESTIONS_BY_PHASE.get(product["phase"], {})
    if cur_sugs:
        sel = st.pills("Suggestions :", list(cur_sugs.keys()), label_visibility="collapsed")
        if sel and sel in cur_sugs:
            st.session_state.messages.append({"role": "user", "content": cur_sugs[sel]})
            st.session_state["needs_llm"] = True
            st.rerun()

# ── Chat display ──────────────────────────────────────────────────────────

for msg in st.session_state.messages:
    if msg.get("content", "").startswith("[Phase ") and "auto" in msg.get("content", ""):
        continue
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("action_results"):
            for ar in msg["action_results"]:
                st.info(ar)

# ── Interactive question widget ───────────────────────────────────────────

if "pending_question" in st.session_state:
    pq = st.session_state["pending_question"]
    st.info(f":question: **{pq['question']}**")
    chosen = st.pills(pq["question"], pq["options"], label_visibility="collapsed", key="pq_pills")
    if chosen:
        st.session_state.messages.append({"role": "user", "content": chosen})
        st.session_state.pop("pending_question")
        st.session_state["needs_llm"] = True
        st.rerun()

# ── Dashboard preview ─────────────────────────────────────────────────────

if product["phase"] in ("dashboard",) and product["dashboard"]:
    render_dashboard_preview()

# ── Phase Livraison : aperçu + livrables inline ──────────────────────────

if product["phase"] == "export" and product["dashboard"]:
    render_dashboard_preview()

    st.divider()
    st.subheader(":rocket: Vos livrables sont prêts !")

    # Récapitulatif
    created_kpis = [k for k in product["kpis"] if k.get("created")]
    if created_kpis:
        st.markdown("**Indicateurs créés :**")
        for kpi in created_kpis:
            st.markdown(f"- :white_check_mark: **{kpi['name']}** — {kpi.get('description', '')}")

    # Bouton dashboard
    st.markdown("---")
    st.markdown("### :bar_chart: Tableau de bord interactif")
    st.markdown("Votre tableau de bord a été généré et est prêt à être consulté.")
    dash_url = "https://app.snowflake.com/yuakovn/en70248/#/workspaces/ws/COCO_BUSINESS_STUDIO/PUBLIC/Coco%20Business%20Studio/dashboard-studio-marc/streamlit_app.py"
    st.link_button(":bar_chart: Ouvrir le tableau de bord", dash_url, type="primary")
    st.caption("Le tableau de bord s'appuie sur les indicateurs créés pendant cette session.")

    # Transmission équipe Data
    st.markdown("---")
    with st.expander(":outbox_tray: Transmettre à l'équipe Data", expanded=False):
        st.markdown(
            "Transmettez la spécification technique à votre équipe Data pour industrialisation. "
            "La spec contient les requêtes, le dictionnaire de données et les recommandations."
        )

        col_jira, col_nb = st.columns(2)

        with col_jira:
            if st.button(":ticket: Créer un ticket Jira", width="stretch"):
                jira_lines = [f"**Projet** : {product['brief'].get('objectif', 'N/A')}"]
                jira_lines.append(f"**Demandeur** : {product['brief'].get('role', 'N/A')}")
                jira_lines.append(f"**Domaine** : {product['brief'].get('domaine', 'N/A')}")
                jira_lines.append(f"**Audience** : {product['brief'].get('audience', 'N/A')}")
                jira_lines.append("")
                jira_lines.append("**Indicateurs à industrialiser :**")
                for kpi in created_kpis:
                    jira_lines.append(f"- {kpi['name']} : {kpi.get('description', '')}")
                jira_lines.append("")
                jira_lines.append(f"**Espace de travail** : {STUDIO_DB}")
                jira_lines.append("**Statut** : Prototype validé, prêt pour industrialisation")
                st.text_area("Contenu du ticket (copiez-collez dans Jira) :", value="\n".join(jira_lines), height=250)

        with col_nb:
            nb_name = re.sub(r"[^a-z0-9]+", "_", product["brief"].get("objectif", "spec").lower())[:40].strip("_")
            nb_filename = f"spec_{nb_name}.ipynb"
            if st.button(f":notebook: Générer la spec technique", width="stretch"):
                try:
                    cells = []
                    cells.append({"cell_type": "markdown", "metadata": {}, "source": [
                        f"# Spécification technique\n",
                        f"**Projet** : {product['brief'].get('objectif', 'N/A')}\n",
                        f"**Demandeur** : {product['brief'].get('role', 'N/A')}\n",
                        f"**Espace** : {STUDIO_DB}\n",
                    ]})
                    dict_lines = ["## Dictionnaire des indicateurs\n", "| Indicateur | Description |", "|------------|-------------|"]
                    for kpi in created_kpis:
                        dict_lines.append(f"| {kpi['name']} | {kpi.get('description', '')} |")
                    cells.append({"cell_type": "markdown", "metadata": {}, "source": dict_lines})
                    for kpi in created_kpis:
                        desc = kpi.get("description", "").replace("'", "''")
                        sql_lines = [f"-- {kpi['name']}\n", f"-- {kpi.get('description', '')}\n", f"CREATE OR REPLACE VIEW {fq(kpi['view_name'])} AS\n", f"{kpi['sql']};\n"]
                        cells.append({"cell_type": "code", "metadata": {}, "source": sql_lines, "outputs": [], "execution_count": None})
                    notebook = {"metadata": {"kernelspec": {"display_name": "Streamlit Notebook", "name": "streamlit"}, "language_info": {"name": "sql"}}, "nbformat": 4, "nbformat_minor": 5, "cells": cells}
                    workspace_dir = os.path.dirname(os.path.abspath(__file__))
                    with open(os.path.join(workspace_dir, nb_filename), "w") as fp:
                        fp.write(json.dumps(notebook, ensure_ascii=False, indent=1))
                    st.success(f"Spécification technique générée ! Rechargez le workspace pour l'ouvrir.")
                except Exception as e:
                    st.error(f"Erreur : {e}")

# ── Auto-continue after phase advance ─────────────────────────────────────

if st.session_state.pop("auto_continue", False) and "pending_question" not in st.session_state:
    phase_key = product["phase"]
    # Only auto-continue for discovery (no user input needed)
    # KPI design, dashboard, export: wait for user interaction
    if phase_key == "discovery":
        phase_label_auto = next((label for k, label in PHASES if k == product["phase"]), "")
        st.session_state.messages.append({"role": "user", "content": f"[Phase {phase_label_auto} auto]"})

        history = ""
        for msg in st.session_state.messages[-10:]:
            history += f"[{msg['role']}]: {msg['content']}\n"

        ctx = f"Historique:\n{history}\n\nPhase {phase_label_auto}. Sélectionne les tables et avance."

        with st.chat_message("assistant"):
            with st.spinner("CoCo explore les données..."):
                response = llm_call(build_system_prompt(), ctx)
                actions, clean_text = parse_actions(response)
                st.markdown(clean_text)

                action_results = []
                if actions:
                    action_results = execute_actions(actions)
                    for ar in action_results:
                        st.info(ar)

                st.session_state.messages.append({"role": "assistant", "content": clean_text, "action_results": action_results or None})
                save_project()

        st.rerun()

# ── Process pending LLM request (from pills/buttons) ─────────────────────

if st.session_state.pop("needs_llm", False):
    with st.chat_message("user"):
        st.markdown(st.session_state.messages[-1]["content"])

    with st.spinner("CoCo travaille..."):
        process_llm()

    st.rerun()

# ── Chat input ────────────────────────────────────────────────────────────

if prompt := st.chat_input("Décrivez votre besoin ou répondez à la question..."):
    st.session_state.pop("pending_question", None)
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("user"):
        st.markdown(prompt)

    with st.spinner("CoCo travaille..."):
        process_llm()

    st.rerun()
