import os
from dash import Dash, dcc, html, Input, Output, State
from flask import Flask

from qa_app.db import Database
from qa_app.specs import SpecsRepository
from qa_app.auth import AuthService
from qa_app.rag import RAGAssistant


def initialize_services():
    data_dir = os.path.join(os.path.dirname(__file__), "qa_app", "data")
    uploads_dir = os.path.join(os.path.dirname(__file__), "qa_app", "uploads")
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(uploads_dir, exist_ok=True)

    db_path = os.path.join(os.path.dirname(__file__), "qa_app", "qa_qc.db")
    database = Database(db_path=db_path)
    database.initialize()

    specs = SpecsRepository(data_dir=data_dir)
    specs.load()

    auth = AuthService(database=database)
    auth.ensure_seed_users(os.path.join(data_dir, "seed_users.json"))

    rag = RAGAssistant(corpus_dir=os.path.join(data_dir, "sop_corpus"))
    rag.build_index()

    return database, specs, auth, rag


server = Flask(__name__)
app = Dash(__name__, server=server, suppress_callback_exceptions=True)

database, specs, auth, rag = initialize_services()


def navbar(user):
    return html.Div([
        html.Div([
            html.Span("Pharma QA/QC Workflow", style={"fontWeight": "bold", "fontSize": "20px"}),
        ], style={"display": "inline-block", "width": "40%"}),
        html.Div([
            dcc.Link("Dashboard", href="/dashboard", style={"marginRight": "12px"}),
            dcc.Link("Request", href="/request", style={"marginRight": "12px"}),
            dcc.Link("QC", href="/qc", style={"marginRight": "12px"}),
            dcc.Link("Reports", href="/reports"),
        ], style={"display": "inline-block", "width": "40%"}),
        html.Div([
            html.Span(f"{user['full_name']} ({user['role']})" if user else "Not logged in"),
            html.Button("Logout", id="logout-btn", n_clicks=0, style={"marginLeft": "12px"}),
        ], style={"display": "inline-block", "width": "20%", "textAlign": "right"}),
    ], style={"padding": "10px", "borderBottom": "1px solid #ddd"})


def sop_sidebar():
    return html.Div([
        html.H4("Ask SOP"),
        dcc.Textarea(id="sop-question", style={"width": "100%", "height": "100px"}),
        html.Button("Ask", id="ask-btn"),
        html.Div(id="sop-answer", style={"whiteSpace": "pre-wrap", "marginTop": "8px"}),
    ], style={"width": "25%", "display": "inline-block", "verticalAlign": "top", "paddingRight": "16px", "borderRight": "1px solid #eee"})


def page_dashboard():
    rows = database.get_all_samples()
    header = html.Tr([html.Th(c) for c in ["sample_id", "material", "stage", "status", "created_at"]])
    body = [html.Tr([
        html.Td(dcc.Link(r["sample_id"], href=f"/sample/{r['sample_id']}")),
        html.Td(r["material"]),
        html.Td(r["stage"]),
        html.Td(r["status"]),
        html.Td(r["created_at"]),
    ]) for r in rows]
    return html.Div([
        html.H3("Real-time Dashboard"),
        html.Table([header] + body, style={"width": "100%"}),
    ], style={"width": "73%", "display": "inline-block", "paddingLeft": "16px"})


def page_request(user):
    materials = specs.materials()
    return html.Div([
        html.H3("Request Initiation"),
        html.Label("Material"),
        dcc.Dropdown(id="req-material", options=[{"label": m, "value": m} for m in materials]),
        html.Label("Stage"),
        dcc.Dropdown(id="req-stage"),
        html.Button("Submit - Sample Ready for Analysis", id="req-submit", n_clicks=0),
        html.Div(id="req-msg", style={"marginTop": "8px"}),
    ], style={"width": "73%", "display": "inline-block", "paddingLeft": "16px"})


def _progress_badges(status: str):
    stages = [
        ("Sample Ready for Analysis", "Requested"),
        ("Under Analysis", "Under Analysis"),
        ("Analysis Complete", "Analyzed"),
        ("Decision Complete", "Decided"),
    ]
    mapping = {
        "Sample Ready for Analysis": 1,
        "Under Analysis": 2,
        "Analysis Complete": 3,
        "Decision Complete": 4,
    }
    done = mapping.get(status, 0)
    items = []
    for idx, (_, label) in enumerate(stages, start=1):
        style = {"padding": "4px 8px", "borderRadius": "6px", "marginRight": "8px"}
        style.update({"backgroundColor": "#28a745", "color": "#fff"} if idx <= done else {"backgroundColor": "#e9ecef"})
        items.append(html.Span(label, style=style))
    return html.Div(items, style={"marginBottom": "10px"})


def page_qc():
    pending = database.get_samples_by_status("Sample Ready for Analysis")
    analyzing = database.get_samples_by_status("Under Analysis")
    def table(rows):
        header = html.Tr([html.Th(c) for c in ["sample_id", "material", "stage", "created_at"]])
        body = [html.Tr([
            html.Td(dcc.Link(r["sample_id"], href=f"/sample/{r['sample_id']}")),
            html.Td(r["material"]),
            html.Td(r["stage"]),
            html.Td(r["created_at"]),
        ]) for r in rows]
        return html.Table([header] + body, style={"width": "100%"})
    return html.Div([
        html.H3("QC Dashboard"),
        html.H4("Pending Samples"),
        table(pending),
        html.H4("Under Analysis"),
        table(analyzing),
    ], style={"width": "73%", "display": "inline-block", "paddingLeft": "16px"})


def page_sample(sample_id: str, user):
    row = database.get_sample(sample_id)
    if not row:
        return html.Div([html.H4("Sample not found")], style={"width": "73%", "display": "inline-block", "paddingLeft": "16px"})
    sop_code = specs.sop_code(row["material"], row["stage"]) or "N/A"
    tests = specs.test_fields(row["material"], row["stage"]) or []

    # analysis inputs dynamic
    inputs = []
    for i, (name, limits) in enumerate(tests):
        limits_txt = ", ".join([f">= {limits['min']}" if 'min' in limits else None, f"<= {limits['max']}" if 'max' in limits else None])
        limits_txt = ", ".join([x for x in limits_txt.split(", ") if x]) if limits_txt else ""
        inputs.append(html.Div([
            html.Label(f"{name} ({limits_txt})"),
            dcc.Input(id={"type": "test-input", "index": i}, type="number", step="any")
        ], style={"marginBottom": "6px"}))

    return html.Div([
        html.H3(f"Sample {sample_id}"),
        _progress_badges(row["status"]),
        html.Div([f"Material: {row['material']} | Stage: {row['stage']} | SOP: {sop_code}"]),
        html.Br(),
        html.Div([
            html.Button("Assign - Under Analysis", id="assign-btn", n_clicks=0, disabled=row["status"] != "Sample Ready for Analysis"),
            html.Span(id="assign-msg", style={"marginLeft": "8px"})
        ]),
        html.Hr(),
        html.H4("Analysis Entry"),
        html.Div(inputs),
        dcc.Upload(id="upload", children=html.Div(["Drag and Drop or ", html.A("Select Files")]), multiple=True, style={"padding": "10px", "border": "1px dashed #999", "margin": "8px 0"}),
        html.Button("Submit Analysis - Complete", id="analysis-submit", n_clicks=0, disabled=row["status"] not in ("Under Analysis", "Analysis Complete", "Decision Complete")),
        html.Div(id="analysis-msg", style={"marginTop": "8px"}),
        html.Hr(),
        html.H4("Automated Decision (QA/Admin)"),
        html.Div(id="decision-proposed"),
        html.Div([
            html.Label("E-sign Username"), dcc.Input(id="esign-user", type="text"),
            html.Label("E-sign Password", style={"marginLeft": "8px"}), dcc.Input(id="esign-pwd", type="password"),
            html.Button("Approve Decision", id="decision-approve", n_clicks=0),
            html.Div(id="decision-msg", style={"marginTop": "8px"}),
        ]),
    ], style={"width": "73%", "display": "inline-block", "paddingLeft": "16px"})


def page_reports():
    return html.Div([
        html.H3("Audit & Reporting"),
        html.Button("Download Audit CSV", id="download-audit"),
        dcc.Download(id="audit-csv"),
    ], style={"width": "73%", "display": "inline-block", "paddingLeft": "16px"})


app.layout = html.Div([
    dcc.Location(id="url"),
    dcc.Store(id="session-user", storage_type="session"),
    navbar(user=None),
    html.Div(id="content", children=[html.Div("Loading...")]),
    html.Div(id="sop-pane", children=sop_sidebar()),
])


@app.callback(
    Output("req-stage", "options"),
    Input("req-material", "value"),
)
def update_stage(material):
    if not material:
        return []
    return [{"label": s, "value": s} for s in specs.stages_for_material(material)]


@app.callback(
    Output("session-user", "data"),
    Output("login-status", "children", allow_duplicate=True),
    Input("login-btn", "n_clicks"),
    State("username", "value"),
    State("password", "value"),
    prevent_initial_call=True,
)
def do_login(n, username, password):
    user = auth.authenticate(username or "", password or "")
    if user:
        database.log_audit(action="login", user_id=user.id, details={"username": user.username})
        return ({"id": user.id, "username": user.username, "role": user.role, "full_name": user.full_name}, f"Logged in as {user.full_name} ({user.role})")
    return (None, "Invalid credentials")


@app.callback(
    Output("session-user", "clear_data"),
    Input("logout-btn", "n_clicks"),
    State("session-user", "data"),
    prevent_initial_call=True,
)
def do_logout(n, data):
    try:
        if data:
            database.log_audit(action="logout", user_id=int(data.get("id")))
    except Exception:
        pass
    return True


@app.callback(
    Output("content", "children"),
    Output("sop-pane", "children"),
    Output("logout-btn", "disabled"),
    Output("logout-btn", "n_clicks"),
    Output("url", "pathname", allow_duplicate=True),
    Input("url", "pathname"),
    Input("session-user", "data"),
    State("url", "pathname"),
    prevent_initial_call=False,
)
def route(pathname, user, current):
    # Header refresh
    app.layout.children[2] = navbar(user)
    # Not logged in: show login page only
    if not user:
        return (
            html.Div([
                html.H3("Login"),
                html.Label("Username"), dcc.Input(id="username", type="text"),
                html.Label("Password", style={"marginLeft": "8px"}), dcc.Input(id="password", type="password"),
                html.Button("Login", id="login-btn"),
                html.Div(id="login-status", style={"marginTop": "8px"}),
            ]),
            sop_sidebar(),
            True,
            0,
            "/login",
        )

    # Logged in: route pages
    page = pathname or "/dashboard"
    if page.startswith("/sample/"):
        sample_id = page.split("/sample/")[-1]
        return (page_sample(sample_id, user), sop_sidebar(), False, 0, page)
    if page == "/request":
        return (page_request(user), sop_sidebar(), False, 0, page)
    if page == "/qc":
        return (page_qc(), sop_sidebar(), False, 0, page)
    if page == "/reports":
        return (page_reports(), sop_sidebar(), False, 0, page)
    return (page_dashboard(), sop_sidebar(), False, 0, "/dashboard")


@app.callback(
    Output("req-msg", "children"),
    Input("req-submit", "n_clicks"),
    State("req-material", "value"),
    State("req-stage", "value"),
    State("session-user", "data"),
    prevent_initial_call=True,
)
def submit_request(n, material, stage, user):
    if not (material and stage and user):
        return "Missing material, stage, or user"
    # Generate sample id
    from datetime import datetime
    base = f"{material[:3].upper()}-{stage[:3].upper()}"
    ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    sample_id = f"{base}-{ts}"
    database.create_sample(sample_id, material, stage, int(user["id"]), "Sample Ready for Analysis")
    database.log_audit("request_initiated", user_id=int(user["id"]), entity_type="sample", entity_id=sample_id, details={"material": material, "stage": stage})
    return f"Created sample {sample_id}"


@app.callback(
    Output("assign-msg", "children"),
    Input("assign-btn", "n_clicks"),
    State("url", "pathname"),
    State("session-user", "data"),
    prevent_initial_call=True,
)
def assign_under_analysis(n, pathname, user):
    if not pathname or not pathname.startswith("/sample/"):
        return ""
    sample_id = pathname.split("/sample/")[-1]
    database.update_sample_status(sample_id, "Under Analysis")
    database.log_audit("sample_assigned", user_id=int(user["id"]), entity_type="sample", entity_id=sample_id)
    return "Assigned and set to Under Analysis (refresh to see progress)"


def _save_uploads(sample_id: str, contents_list, filenames):
    saved = []
    if not contents_list:
        return saved
    updir = os.path.abspath(os.path.join(os.path.dirname(__file__), "qa_app", "uploads"))
    os.makedirs(updir, exist_ok=True)
    import base64
    for content, name in zip(contents_list, filenames):
        if content is None:
            continue
        header, data = content.split(',') if ',' in content else ("", content)
        raw = base64.b64decode(data)
        fname = f"{sample_id}_{name}"
        fpath = os.path.join(updir, fname)
        with open(fpath, 'wb') as f:
            f.write(raw)
        saved.append({"filename": fname, "path": fpath})
    return saved


@app.callback(
    Output("analysis-msg", "children"),
    Input("analysis-submit", "n_clicks"),
    State({"type": "test-input", "index": ALL}, "value"),
    State("url", "pathname"),
    State("session-user", "data"),
    State("upload", "contents"),
    State("upload", "filename"),
    prevent_initial_call=True,
)
def submit_analysis(n, values, pathname, user, contents, filenames):
    if not pathname or not pathname.startswith("/sample/"):
        return ""
    sample_id = pathname.split("/sample/")[-1]
    # Build results map against current tests order
    row = database.get_sample(sample_id)
    test_list = specs.test_fields(row["material"], row["stage"]) or []
    results = {}
    errors = []
    values = values or []
    for idx, pair in enumerate(test_list):
        name, _ = pair
        try:
            val = float(values[idx]) if idx < len(values) and values[idx] is not None else None
        except Exception:
            val = None
        if val is None:
            errors.append(f"{name} must be numeric")
        else:
            results[name] = val
    if errors:
        return "; ".join(errors)
    attachments = _save_uploads(sample_id, contents, filenames) if contents else []
    database.create_analysis(sample_id, int(user["id"]), results, attachments)
    database.update_sample_status(sample_id, "Analysis Complete")
    database.log_audit("analysis_submitted", user_id=int(user["id"]), entity_type="sample", entity_id=sample_id, details={"results": results, "attachments": [a['filename'] for a in attachments]})
    return "Analysis submitted and marked complete. QA has been notified."


@app.callback(
    Output("decision-proposed", "children"),
    Input("url", "pathname"),
)
def show_proposed_decision(pathname):
    if not pathname or not pathname.startswith("/sample/"):
        return ""
    sample_id = pathname.split("/sample/")[-1]
    row = database.get_sample(sample_id)
    if not row or row["status"] not in ("Analysis Complete", "Decision Complete"):
        return ""
    tests = specs.test_fields(row["material"], row["stage"]) or []
    analyses = database.get_analyses_for_sample(sample_id)
    if not analyses:
        return "No analysis entries yet."
    import json as _json
    latest = analyses[0]
    results = _json.loads(latest["results_json"]) if latest else {}
    rationale = []
    all_pass = True
    for test_name, limits in tests:
        val = results.get(test_name)
        ok = True
        if val is None:
            ok = False
            rationale.append(f"{test_name}: missing result")
        if ok and 'min' in limits and val < float(limits['min']):
            ok = False
            rationale.append(f"{test_name}: {val} below min {limits['min']}")
        if ok and 'max' in limits and val > float(limits['max']):
            ok = False
            rationale.append(f"{test_name}: {val} above max {limits['max']}")
        if ok:
            rationale.append(f"{test_name}: {val} within spec")
        all_pass = all_pass and ok
    outcome = "Pass" if all_pass else "Fail"
    return html.Div([
        html.Div(f"Outcome: {outcome}"),
        html.Pre("\n".join(rationale), style={"whiteSpace": "pre-wrap"}),
    ])


@app.callback(
    Output("decision-msg", "children"),
    Input("decision-approve", "n_clicks"),
    State("esign-user", "value"),
    State("esign-pwd", "value"),
    State("session-user", "data"),
    State("url", "pathname"),
    prevent_initial_call=True,
)
def approve_decision(n, esign_user, esign_pwd, user, pathname):
    if not pathname or not pathname.startswith("/sample/"):
        return ""
    if not user or user.get("role") not in ("QA", "Admin"):
        return "Access denied"
    sample_id = pathname.split("/sample/")[-1]
    # validate e-sign
    user_row = database.get_user_by_username(esign_user or "")
    from qa_app.auth import verify_password, hash_password
    if not user_row or not verify_password(esign_pwd or "", user_row.password_hash) or user_row.username != user.get("username"):
        return "E-sign invalid. Must match your credentials."
    # Compute outcome again
    tests = specs.test_fields(database.get_sample(sample_id)["material"], database.get_sample(sample_id)["stage"]) or []
    analyses = database.get_analyses_for_sample(sample_id)
    import json as _json
    latest = analyses[0]
    results = _json.loads(latest["results_json"]) if latest else {}
    rationale = []
    all_pass = True
    for test_name, limits in tests:
        val = results.get(test_name)
        ok = True
        if val is None:
            ok = False
            rationale.append(f"{test_name}: missing result")
        if ok and 'min' in limits and val < float(limits['min']):
            ok = False
            rationale.append(f"{test_name}: {val} below min {limits['min']}")
        if ok and 'max' in limits and val > float(limits['max']):
            ok = False
            rationale.append(f"{test_name}: {val} above max {limits['max']}")
        if ok:
            rationale.append(f"{test_name}: {val} within spec")
        all_pass = all_pass and ok
    outcome = "Pass" if all_pass else "Fail"
    sig_hash = hash_password(f"{esign_user}|{sample_id}|decision")
    database.create_decision(sample_id, "Decision Complete", outcome, "; ".join(rationale), int(user["id"]))
    database.update_sample_status(sample_id, "Decision Complete")
    database.log_audit("decision_recorded", user_id=int(user["id"]), entity_type="sample", entity_id=sample_id, details={"outcome": outcome, "rationale": rationale}, esign_username=esign_user, esign_signature_hash=sig_hash)
    return "Decision recorded. Production notified."


@app.callback(
    Output("audit-csv", "data"),
    Input("download-audit", "n_clicks"),
    prevent_initial_call=True,
)
def download_audit(n):
    rows = database.export_audit_rows()
    import csv
    import io
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "timestamp", "user_id", "action", "entity_type", "entity_id", "details_json", "esign_username", "esign_signature_hash"])
    for r in rows:
        writer.writerow([r["id"], r["timestamp"], r["user_id"], r["action"], r["entity_type"], r["entity_id"], r["details_json"], r["esign_username"], r["esign_signature_hash"]])
    return dict(content=output.getvalue(), filename="audit_log.csv")


@app.callback(
    Output("sop-answer", "children"),
    Input("ask-btn", "n_clicks"),
    State("sop-question", "value"),
    prevent_initial_call=True,
)
def do_ask(n, question):
    if not question or not question.strip():
        return "Enter a question"
    answer = rag.ask(question.strip(), use_ollama=False)
    return answer


if __name__ == "__main__":
    app.run_server(host="0.0.0.0", port=8501, debug=False)

