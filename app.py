"""
app.py
------
Streamlit prototype UI for the Incoming Request Processing Workflow.

Five tabs:
  1. Process a Request   — intake (simulated inbox / manual / file upload)
  2. Batch Processing    — one-click run of the full sample dataset
  3. Review Queue        — human-in-the-loop: approve or reclassify held cases
  4. Dashboard & Audit   — volumes, deflection rate, full case log
  5. Admin               — stakeholder directory (routing targets) + outbox

Run with:  streamlit run app.py
Optional env vars:
  ANTHROPIC_API_KEY          live Claude classification & drafting
  SMTP_USER / SMTP_PASSWORD  real email notifications (Gmail App Password)
Without these the app falls back to the offline engine and a simulated
outbox respectively, so it is always demoable.
"""

import os
import uuid

import pandas as pd
import streamlit as st

from classifier import classify_request
from workflows import run_workflow, BRANCH_MAP
from storage import (
    log_case, fetch_all_cases, fetch_review_queue, fetch_stakeholders,
    replace_stakeholders, summary_counts, update_case_status,
    update_case_after_reclassify, init_db,
)
from notifier import fetch_outbox
from sample_data import SAMPLE_REQUESTS

st.set_page_config(page_title="Incoming Request Processing Workflow", layout="wide")
init_db()


def new_request_id():
    return f"REQ-{uuid.uuid4().hex[:8].upper()}"


def render_case_trace(request_id: str, text: str, classification: dict, result: dict):
    badge_color = {
        "Low": "🟢", "Medium": "🟡", "High": "🟠", "Critical": "🔴",
    }.get(classification.get("urgency"), "⚪")

    st.markdown(f"### Case `{request_id}` — {badge_color} {classification.get('urgency')} urgency")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Request Type", classification.get("request_type"))
    c2.metric("Urgency", classification.get("urgency"))
    c3.metric("Confidence", classification.get("confidence"))
    c4.metric("Engine", classification.get("engine", "").split(":")[0])

    if result.get("override_applied"):
        st.warning(f"⚠️ **Escalation override applied.** {result['override_reason']}")

    st.markdown(f"**Sub-topic:** {classification.get('sub_topic')}  \n**Key details:** {classification.get('key_details')}")

    st.markdown(f"#### Branch executed: `{result['branch']}`")
    for i, step in enumerate(result["steps"], 1):
        st.markdown(f"**{i}. {step['step']}** — ✅ {step['status']}  \n*{step['detail']}*")

    st.markdown("#### Generated Outputs")
    for k, v in result["outputs"].items():
        with st.expander(k.replace("_", " ").title()):
            if isinstance(v, dict):
                st.json(v)
            else:
                st.write(v)


def process_and_log(request_id: str, text: str):
    with st.spinner("Classifying request..."):
        classification = classify_request(text)
    with st.spinner(f"Executing {classification['request_type']} remediation workflow..."):
        result = run_workflow(request_id, text, classification)
    log_case(request_id, text, classification, result)
    return classification, result


STATUS_BADGE = {
    "RESOLVED": "🟢 RESOLVED",
    "IN_PROGRESS": "🟡 IN PROGRESS",
    "HELD_FOR_REVIEW": "🔴 HELD FOR REVIEW",
    "APPROVED": "✅ APPROVED",
}

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("⚙️ Incoming Request Workflow")
    st.caption("AI classification + branch-specific remediation prototype")
    if os.environ.get("ANTHROPIC_API_KEY"):
        st.success("Claude API key detected — live classification & drafting enabled.")
    else:
        st.info("No `ANTHROPIC_API_KEY` set — running on the offline fallback engine.")
    if os.environ.get("SMTP_USER") and os.environ.get("SMTP_PASSWORD"):
        st.success("SMTP configured — stakeholder notifications sent as real emails.")
    else:
        st.info("No SMTP configured — notifications go to the simulated Outbox (Admin tab).")
    st.divider()
    st.markdown("**Branches implemented:**")
    st.markdown("- 🔴 Complaint (High)\n- 🟢 General Enquiry (Low)\n- 🟡 Service Request (Medium)\n- 🚨 Escalation (Critical)")
    st.divider()
    st.caption("Low-confidence classifications are held for human review (Review Queue tab).")

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📥 Process a Request", "📦 Batch Processing", "🧑‍⚖️ Review Queue",
    "📊 Dashboard & Audit Log", "🛠️ Admin",
])

# ---------------------------------------------------------------------------
# TAB 1 — Single request intake
# ---------------------------------------------------------------------------
with tab1:
    st.subheader("Simulated Inbox Intake")
    intake_mode = st.radio("Choose intake source:", ["Pick from simulated inbox", "Type/paste a request", "Upload a .txt file"], horizontal=True)

    request_text = ""
    if intake_mode == "Pick from simulated inbox":
        options = {f"{r['id']} — {r['text'][:70]}...": r for r in SAMPLE_REQUESTS}
        choice = st.selectbox("Simulated inbox (sample requests):", list(options.keys()))
        request_text = options[choice]["text"]
        st.text_area("Request preview", request_text, height=100, disabled=True)
    elif intake_mode == "Type/paste a request":
        request_text = st.text_area("Paste or type the incoming request text:", height=150,
                                     placeholder="e.g. I was charged twice for my subscription this month...")
    else:
        uploaded = st.file_uploader("Upload a .txt file containing the request", type=["txt"])
        if uploaded is not None:
            request_text = uploaded.read().decode("utf-8")
            st.text_area("File contents", request_text, height=100, disabled=True)

    if st.button("▶️ Process Request", type="primary", disabled=not request_text.strip()):
        request_id = new_request_id()
        classification, result = process_and_log(request_id, request_text)
        render_case_trace(request_id, request_text, classification, result)

# ---------------------------------------------------------------------------
# TAB 2 — Batch processing
# ---------------------------------------------------------------------------
with tab2:
    st.subheader("Batch Processing — Full Sample Dataset")
    st.caption(f"Processes all {len(SAMPLE_REQUESTS)} sample requests end-to-end in one click, "
               "demonstrating every branch type.")
    if st.button("▶️ Run Batch Demo", type="primary"):
        progress = st.progress(0, text="Starting batch run...")
        for i, req in enumerate(SAMPLE_REQUESTS):
            progress.progress((i + 1) / len(SAMPLE_REQUESTS), text=f"Processing {req['id']}...")
            classification, result = process_and_log(req["id"], req["text"])
            with st.expander(f"{req['id']} → {result['branch']} ({classification['urgency']})", expanded=False):
                render_case_trace(req["id"], req["text"], classification, result)
        st.success(f"Batch complete — {len(SAMPLE_REQUESTS)} requests processed. "
                   "Check the Review Queue for held cases and the Dashboard for the summary.")

# ---------------------------------------------------------------------------
# TAB 3 — Review Queue (human-in-the-loop)
# ---------------------------------------------------------------------------
with tab3:
    st.subheader("Human Review Queue")
    st.caption("Escalations and low-confidence overrides land here. A human approves the "
               "AI's handling or reclassifies the case down a different branch.")
    queue = fetch_review_queue()
    if not queue:
        st.info("Nothing awaiting review. Process an escalation (e.g. REQ-1004 or REQ-1010) to populate this queue.")
    else:
        st.markdown(f"**{len(queue)} case(s) awaiting review**")
        branch_options = list(BRANCH_MAP.keys())
        for case in queue:
            header = f"{case['request_id']} — {case['request_type']} ({case['urgency']})"
            if case["override_applied"]:
                header += " ⚠️ override"
            with st.expander(header, expanded=True):
                st.markdown(f"**Received:** {case['timestamp']}")
                st.markdown(f"**Message:** {case['raw_text']}")
                if case["override_applied"]:
                    st.warning(case["override_reason"])
                col_a, col_b, col_c = st.columns([1, 1.6, 1])
                with col_a:
                    if st.button("✅ Approve handling", key=f"approve_{case['request_id']}"):
                        update_case_status(case["request_id"], "APPROVED")
                        st.success(f"{case['request_id']} approved.")
                        st.rerun()
                with col_b:
                    new_type = st.selectbox("Reclassify as:", branch_options,
                                            key=f"type_{case['request_id']}")
                with col_c:
                    if st.button("🔁 Reclassify & re-run", key=f"reclass_{case['request_id']}"):
                        new_classification = {
                            "request_type": new_type,
                            "urgency": {"Complaint": "High", "General Enquiry": "Low",
                                        "Service Request": "Medium", "Escalation": "Critical"}[new_type],
                            "sub_topic": case["sub_topic"],
                            "confidence": "High",
                            "key_details": case["raw_text"][:160],
                            "engine": "human-reclassified",
                        }
                        new_result = BRANCH_MAP[new_type](case["request_id"], case["raw_text"], new_classification)
                        new_result["override_applied"] = False
                        update_case_after_reclassify(case["request_id"], new_classification, new_result)
                        st.success(f"{case['request_id']} reclassified as {new_type} and re-run.")
                        st.rerun()

# ---------------------------------------------------------------------------
# TAB 4 — Dashboard & audit log
# ---------------------------------------------------------------------------
with tab4:
    st.subheader("Summary Dashboard")
    summary = summary_counts()

    if summary["total"] == 0:
        st.info("No cases processed yet. Process a request or run the batch demo to populate the dashboard.")
    else:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Cases", summary["total"])
        c2.metric("Auto-Handled (Deflection)", f"{summary['deflection_pct']}%",
                  help="Share of cases fully handled by the workflow without needing a human decision.")
        c3.metric("Needed a Human", summary["human_needed"])
        c4.metric("Awaiting Review Now", summary["by_status"].get("HELD_FOR_REVIEW", 0))

        col_a, col_b, col_c = st.columns(3)
        with col_a:
            st.markdown("**Volume by Request Type**")
            st.bar_chart(pd.Series(summary["by_type"], name="count"))
        with col_b:
            st.markdown("**Volume by Urgency**")
            urgency_order = ["Low", "Medium", "High", "Critical"]
            st.bar_chart(pd.Series(
                {k: summary["by_urgency"].get(k, 0) for k in urgency_order if k in summary["by_urgency"]},
                name="count"))
        with col_c:
            st.markdown("**Cases by Status**")
            st.bar_chart(pd.Series(summary["by_status"], name="count"))

        st.divider()
        st.markdown("### Full Audit Trail / Case Log")
        cases = fetch_all_cases()
        df = pd.DataFrame(cases)[[
            "request_id", "timestamp", "request_type", "urgency", "confidence",
            "engine", "branch", "override_applied", "status", "raw_text",
        ]]
        df["status"] = df["status"].map(lambda s: STATUS_BADGE.get(s, s))
        st.dataframe(df, width="stretch", hide_index=True)

        st.download_button(
            "⬇️ Download audit log as CSV",
            df.to_csv(index=False).encode("utf-8"),
            file_name="case_audit_log.csv",
            mime="text/csv",
        )

# ---------------------------------------------------------------------------
# TAB 5 — Admin: stakeholder directory + outbox
# ---------------------------------------------------------------------------
with tab5:
    st.subheader("Stakeholder Directory")
    st.caption("Who gets notified for each routing target. Edit names, positions, and "
               "emails here — no code changes needed. Positions are matched by keyword: "
               "'Supervisor', 'Senior Handler', 'Department Owner - Billing', etc.")
    stakeholders = fetch_stakeholders()
    df_stake = pd.DataFrame(stakeholders)[["name", "position", "email"]]
    edited = st.data_editor(df_stake, num_rows="dynamic", width="stretch",
                            key="stakeholder_editor")
    if st.button("💾 Save directory"):
        replace_stakeholders(edited.to_dict("records"))
        st.success("Stakeholder directory saved. New notifications will use the updated routing.")
        st.rerun()

    st.divider()
    st.subheader("Notification Outbox")
    st.caption("Every stakeholder notification lands here — 'sent' means a real email went out, "
               "'simulated' means SMTP wasn't configured or failed and the notification was logged instead.")
    outbox = fetch_outbox()
    if not outbox:
        st.info("No notifications yet. Process a Complaint, Service Request, or Escalation to generate one.")
    else:
        df_out = pd.DataFrame(outbox)[["timestamp", "recipient_name", "recipient_email", "subject", "delivery"]]
        st.dataframe(df_out, width="stretch", hide_index=True)
        with st.expander("View latest notification body"):
            st.text(outbox[0]["body"])
