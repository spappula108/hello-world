"""Streamlit UI for the Pharma QA/QC workflow."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional
import json

import pandas as pd
import streamlit as st

from ..db import Database
from ..specs import SpecsRepository
from ..auth import AuthService, SessionUser, verify_password, hash_password
from ..rag import RAGAssistant


# --- helpers ---
def _progress_steps(status: str) -> None:
    steps = [
        ("Requested", "Sample Ready for Analysis"),
        ("Under Analysis", "Under Analysis"),
        ("Analyzed", "Analysis Complete"),
        ("Decided", "Decision Complete"),
    ]
    mapping = {
        "Sample Ready for Analysis": 1,
        "Under Analysis": 2,
        "Analysis Complete": 3,
        "Decision Complete": 4,
    }
    done = mapping.get(status, 0)
    cols = st.columns(4)
    for idx, (label, _) in enumerate(steps, start=1):
        with cols[idx - 1]:
            if idx <= done:
                st.success(label)
            else:
                st.info(label)


def _render_sidebar(rag: RAGAssistant, specs: SpecsRepository) -> None:
    st.sidebar.header("Ask SOP")
    question = st.sidebar.text_area("Question", placeholder="e.g., What is the assay acceptance criterion?", height=100)
    use_ollama = st.sidebar.checkbox("Use local LLM (Ollama)", value=False)
    if st.sidebar.button("Ask") and question.strip():
        answer = rag.ask(question.strip(), use_ollama=use_ollama)
        st.sidebar.write(answer)

    st.sidebar.divider()
    st.sidebar.header("Security & Best Practices")
    st.sidebar.markdown(
        "- Use strong passwords and role-based access\n"
        "- Record immutable audit logs with e-signatures\n"
        "- Validate inputs and restrict uploads\n"
        "- SOP/specs version control under change management\n"
        "- Time sync and unique Sample IDs\n"
        "- Regular backups and restricted DB access\n"
    )


# --- pages ---
def _page_login(auth: AuthService, db: Database) -> Optional[SessionUser]:
    st.title("Pharma QA/QC Workflow")
    st.caption("Login to continue")
    with st.form("login_form", clear_on_submit=False):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login")
        if submitted:
            user = auth.authenticate(username, password)
            if user:
                st.session_state["user"] = user
                db.log_audit(action="login", user_id=user.id, details={"username": user.username})
                st.experimental_rerun()
            else:
                st.error("Invalid credentials")
    return None


def _page_request_initiation(db: Database, specs: SpecsRepository, user: SessionUser) -> None:
    st.subheader("Request Initiation")
    materials = specs.materials()
    material = st.selectbox("Material", materials)
    stages = specs.stages_for_material(material) if material else []
    stage = st.selectbox("Stage", stages)
    if st.button("Submit - Sample Ready for Analysis") and material and stage:
        sample_id = _generate_sample_id(material, stage)
        db.create_sample(sample_id=sample_id, material=material, stage=stage, requester_id=user.id, status="Sample Ready for Analysis")
        db.log_audit("request_initiated", user_id=user.id, entity_type="sample", entity_id=sample_id, details={"material": material, "stage": stage})
        st.success(f"Created sample {sample_id}")


def _generate_sample_id(material: str, stage: str) -> str:
    base = f"{material[:3].upper()}-{stage[:3].upper()}"
    from datetime import datetime
    ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    return f"{base}-{ts}"


def _page_qc_dashboard(db: Database, specs: SpecsRepository, user: SessionUser) -> None:
    st.subheader("QC Dashboard")
    pending = db.get_samples_by_status("Sample Ready for Analysis")
    analyzing = db.get_samples_by_status("Under Analysis")
    st.write("Pending Samples")
    st.table(pd.DataFrame(pending))
    st.write("Under Analysis")
    st.table(pd.DataFrame(analyzing))

    sample_id = st.text_input("Enter Sample ID to open")
    if st.button("Open Sample") and sample_id:
        st.session_state["selected_sample"] = sample_id
        st.experimental_rerun()

    if st.session_state.get("selected_sample"):
        _page_sample_details(db, specs, user, st.session_state["selected_sample"]) 


def _page_sample_details(db: Database, specs: SpecsRepository, user: SessionUser, sample_id: str) -> None:
    st.markdown(f"### Sample {sample_id}")
    sample = db.get_sample(sample_id)
    if not sample:
        st.error("Sample not found")
        return
    _progress_steps(sample["status"])
    st.info(f"Material: {sample['material']} | Stage: {sample['stage']}")

    sop_code = specs.sop_code(sample["material"], sample["stage"]) or "N/A"
    st.write(f"SOP: {sop_code}")

    if sample["status"] == "Sample Ready for Analysis":
        if st.button("Assign - Under Analysis"):
            db.update_sample_status(sample_id, "Under Analysis")
            db.log_audit("sample_assigned", user_id=user.id, entity_type="sample", entity_id=sample_id)
            st.experimental_rerun()

    if sample["status"] in ("Under Analysis", "Analysis Complete", "Decision Complete"):
        _analysis_entry_form(db, specs, user, sample)

    if sample["status"] in ("Analysis Complete", "Decision Complete") and user.role in ("QA", "Admin"):
        _automated_decision(db, specs, user, sample)

    st.markdown("#### History")
    analyses = db.get_analyses_for_sample(sample_id)
    if analyses:
        records: List[Dict[str, Any]] = []
        for a in analyses:
            try:
                res = json.loads(a["results_json"]) if a["results_json"] else {}
            except Exception:
                res = {"_parse_error": True}
            records.append({"created_at": a["created_at"], **res})
        st.write(pd.DataFrame(records))
    decisions = db.get_decisions_for_sample(sample_id)
    if decisions:
        st.write(pd.DataFrame(decisions))


def _analysis_entry_form(db: Database, specs: SpecsRepository, user: SessionUser, sample_row) -> None:
    st.markdown("#### Analysis Entry")
    tests = specs.test_fields(sample_row["material"], sample_row["stage"]) or []
    if not tests:
        st.warning("No tests defined for this spec.")
        return

    with st.form("analysis_form", clear_on_submit=True):
        entries: Dict[str, Any] = {}
        for test_name, limits in tests:
            default_val = 0.0 if ("min" in limits or "max" in limits) else ""
            value = st.text_input(f"{test_name} ({_fmt_limits(limits)})", value=str(default_val))
            entries[test_name] = value

        uploaded_files = st.file_uploader("Attachments (optional)", accept_multiple_files=True)
        submitted = st.form_submit_button("Submit Analysis - Complete")
        if submitted:
            # Validate numeric fields
            validated: Dict[str, float] = {}
            errors: List[str] = []
            for test_name, limits in tests:
                raw = entries.get(test_name, "").strip()
                try:
                    val = float(raw)
                    validated[test_name] = val
                except ValueError:
                    errors.append(f"{test_name} must be numeric.")
            if errors:
                st.error("\n".join(errors))
                return

            # Save attachments
            save_list: List[Dict[str, Any]] = []
            if uploaded_files:
                updir = os.path.join(os.path.dirname(__file__), "..", "uploads")
                updir = os.path.abspath(updir)
                os.makedirs(updir, exist_ok=True)
                for f in uploaded_files:
                    filename = f"{sample_row['sample_id']}_{f.name}"
                    path = os.path.join(updir, filename)
                    with open(path, "wb") as out:
                        out.write(f.getbuffer())
                    save_list.append({"filename": filename, "path": path})

            db.create_analysis(sample_id=sample_row["sample_id"], analyst_id=user.id, results=validated, attachments=save_list)
            db.update_sample_status(sample_row["sample_id"], "Analysis Complete")
            db.log_audit("analysis_submitted", user_id=user.id, entity_type="sample", entity_id=sample_row["sample_id"], details={"results": validated, "attachments": [x["filename"] for x in save_list]})
            st.success("Analysis submitted and marked complete. QA has been notified.")
            st.experimental_rerun()


def _fmt_limits(limits: Dict[str, Any]) -> str:
    parts: List[str] = []
    if "min" in limits:
        parts.append(f">= {limits['min']}")
    if "max" in limits:
        parts.append(f"<= {limits['max']}")
    return ", ".join(parts)


def _automated_decision(db: Database, specs: SpecsRepository, user: SessionUser, sample_row) -> None:
    st.markdown("#### Automated Decision")
    tests = specs.test_fields(sample_row["material"], sample_row["stage"]) or []
    analyses = db.get_analyses_for_sample(sample_row["sample_id"]) or []
    if not analyses:
        st.info("No analysis entries yet.")
        return
    # Use the latest analysis
    latest = analyses[0]
    import json as _json
    results = _json.loads(latest["results_json"]) if latest else {}

    outcome, rationale_lines = _compare_to_spec(results, tests)
    st.write("Proposed decision:")
    st.code("\n".join(rationale_lines))

    with st.form("decision_form"):
        st.write(f"Outcome: {outcome}")
        esign_user = st.text_input("E-sign Username")
        esign_pwd = st.text_input("E-sign Password", type="password")
        approve = st.form_submit_button("Approve Decision")
        if approve:
            # Validate e-sign against current user credentials
            user_row = db.get_user_by_username(esign_user)
            if not user_row or not verify_password(esign_pwd, user_row.password_hash) or user_row.username != user.username:
                st.error("E-sign invalid. Must match your credentials.")
                return
            # Store decision and audit with e-sign hash
            signature_hash = hash_password(f"{esign_user}|{sample_row['sample_id']}|decision")
            db.create_decision(sample_id=sample_row["sample_id"], status="Decision Complete", pass_fail=outcome, rationale="; ".join(rationale_lines), decided_by=user.id)
            db.update_sample_status(sample_row["sample_id"], "Decision Complete")
            db.log_audit(
                "decision_recorded",
                user_id=user.id,
                entity_type="sample",
                entity_id=sample_row["sample_id"],
                details={"outcome": outcome, "rationale": rationale_lines},
                esign_username=esign_user,
                esign_signature_hash=signature_hash,
            )
            st.success("Decision recorded. Production notified.")
            st.experimental_rerun()


def _compare_to_spec(results: Dict[str, float], tests: List) -> tuple[str, List[str]]:
    rationale: List[str] = []
    all_pass = True
    for test_name, limits in tests:
        val = results.get(test_name)
        this_pass = True
        if val is None:
            this_pass = False
            rationale.append(f"{test_name}: missing result")
        if this_pass and "min" in limits and val < float(limits["min"]):
            this_pass = False
            rationale.append(f"{test_name}: {val} below min {limits['min']}")
        if this_pass and "max" in limits and val > float(limits["max"]):
            this_pass = False
            rationale.append(f"{test_name}: {val} above max {limits['max']}")
        if this_pass:
            rationale.append(f"{test_name}: {val} within spec")
        all_pass = all_pass and this_pass
    return ("Pass" if all_pass else "Fail", rationale)


def _page_reporting(db: Database) -> None:
    st.subheader("Audit & Reporting")
    rows = db.export_audit_rows()
    df = pd.DataFrame(rows)
    st.dataframe(df)
    if not df.empty:
        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button("Download Audit CSV", data=csv, file_name="audit_log.csv", mime="text/csv")


def render_application(database: Database, specs: SpecsRepository, auth: AuthService, rag: RAGAssistant) -> None:
    _render_sidebar(rag, specs)

    user: Optional[SessionUser] = st.session_state.get("user")
    if not user:
        _page_login(auth, database)
        return

    st.sidebar.write(f"Logged in as: {user.full_name} ({user.role})")
    if st.sidebar.button("Logout"):
        st.session_state.pop("user", None)
        database.log_audit(action="logout", user_id=user.id)
        st.experimental_rerun()

    tabs = ["Dashboard", "Request", "QC", "Reports"]
    selected = st.sidebar.radio("Navigate", tabs)

    if selected == "Dashboard":
        st.header("Real-time Dashboard")
        all_samples = database.get_all_samples()
        st.dataframe(pd.DataFrame(all_samples))
    elif selected == "Request" and auth.can_access_role(user, ["Requester", "Admin"]):
        _page_request_initiation(database, specs, user)
    elif selected == "QC" and auth.can_access_role(user, ["QC", "Admin", "QA"]):
        _page_qc_dashboard(database, specs, user)
    elif selected == "Reports" and auth.can_access_role(user, ["QA", "Admin"]):
        _page_reporting(database)
    else:
        st.warning("You do not have access to this section.")

