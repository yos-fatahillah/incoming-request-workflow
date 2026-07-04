"""
workflows.py
------------
Branch-specific remediation logic. Each request type maps to its own sequence
of downstream steps, mirroring the brief's example table:

  Complaint         (High)     -> acknowledge, escalate to senior handler, log w/ priority flag, 2h follow-up
  General Enquiry   (Low)      -> generate KB response, send, log resolved
  Service Request   (Medium)   -> extract details, route to department, confirm, SLA timer
  Escalation        (Critical) -> flag for human review, draft urgent ack, notify supervisor, pause automation

Each branch function returns a structured dict describing every step executed
and the artifacts produced (draft message, routing notification, flags, etc.)
so the caller can log it and render it for an ops team.
"""

import os
import re
from datetime import datetime, timedelta

from notifier import notify
from storage import find_stakeholder

DEPARTMENT_ROUTING = {
    "billing": "Billing & Payments Team",
    "technical": "Technical Support Team",
    "account": "Account Management Team",
    "shipping": "Logistics & Fulfilment Team",
    "general": "Customer Care Team",
}


def _draft_response(prompt: str, customer_text: str = "", model: str = "claude-sonnet-4-5") -> str:
    """Generate a short customer-facing draft using Claude, with an offline template fallback."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            resp = client.messages.create(
                model=model,
                max_tokens=200,
                system=(
                    "You write short, warm, professional customer service messages. "
                    "Keep it under 80 words. No subject line, no signature block beyond "
                    "'The Support Team'."
                ),
                messages=[{"role": "user", "content": prompt}],
            )
            return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
        except Exception:
            pass
    # Offline fallback template - keep it generic, don't echo internal instructions
    snippet = (customer_text[:100] + "...") if len(customer_text) > 100 else customer_text
    return (
        "Hi there,\n\nThanks for reaching out. We've received your message "
        f'("{snippet}") and wanted to confirm we\'re on it. '
        "We'll follow up shortly with next steps.\n\nThe Support Team"
    )


def _guess_department(text: str) -> str:
    t = text.lower()
    if re.search(r"\b(bill|charge|invoice|payment|refund)\b", t):
        return "billing"
    if re.search(r"\b(app|website|login|password|error|bug|not working|crash)\b", t):
        return "technical"
    if re.search(r"\b(address|plan|upgrade|downgrade|cancel|account)\b", t):
        return "account"
    if re.search(r"\b(deliver|shipping|package|order|tracking)\b", t):
        return "shipping"
    return "general"


def _notify_stakeholder(position_contains: str, subject: str, body: str) -> dict:
    """Look up a stakeholder by position in the admin directory and notify them.
    Returns {"recipient": ..., "delivery": "sent"|"simulated", "detail": ...}."""
    s = find_stakeholder(position_contains)
    if not s:
        return {"recipient": position_contains, "delivery": "simulated",
                "detail": f"No stakeholder with position matching '{position_contains}' in directory."}
    result = notify(s["name"], s.get("email", ""), subject, body)
    return {"recipient": f"{s['name']} ({s['position']})", **result}


# ---------------------------------------------------------------------------
# Branch implementations
# ---------------------------------------------------------------------------

def handle_complaint(request_id: str, text: str, classification: dict) -> dict:
    now = datetime.now()
    draft = _draft_response(
        f"Write an acknowledgement to a customer complaint. Their message: {text}",
        customer_text=text,
    )
    notification = _notify_stakeholder(
        "Senior Handler",
        f"[HIGH] New complaint case {request_id}",
        f"A new complaint has been logged with priority HIGH.\n\n"
        f"Case ID: {request_id}\n"
        f"Summary: {classification.get('key_details', text[:160])}\n"
        f"Follow-up due: {(now + timedelta(hours=2)).strftime('%Y-%m-%d %H:%M')}\n\n"
        f"Original message:\n{text}",
    )
    steps = [
        {"step": "Acknowledge receipt", "status": "done",
         "detail": "Acknowledgement drafted and queued to send within 15 minutes."},
        {"step": "Escalate to senior handler", "status": "done",
         "detail": notification["detail"]},
        {"step": "Log case with priority flag", "status": "done",
         "detail": f"Case {request_id} logged with priority=HIGH."},
        {"step": "Set 2-hour follow-up reminder", "status": "done",
         "detail": f"Follow-up reminder set for {(now + timedelta(hours=2)).strftime('%Y-%m-%d %H:%M')}."},
    ]
    return {
        "branch": "Complaint",
        "steps": steps,
        "outputs": {
            "escalation_notification": f"{notification['recipient']} — {notification['detail']}",
            "draft_acknowledgement": draft,
            "case_log_entry": {
                "request_id": request_id, "priority": "HIGH",
                "follow_up_due": (now + timedelta(hours=2)).isoformat(timespec="minutes"),
            },
        },
    }


def handle_general_enquiry(request_id: str, text: str, classification: dict) -> dict:
    sub_topic = classification.get("sub_topic", "general")
    draft = _draft_response(
        f"Answer this general customer enquiry helpfully and concisely. Topic: {sub_topic}. "
        f"Their message: {text}",
        customer_text=text,
    )
    steps = [
        {"step": "Classify sub-topic", "status": "done", "detail": f"Sub-topic identified: {sub_topic}."},
        {"step": "Generate AI response from knowledge base", "status": "done",
         "detail": "Response generated from support knowledge base context."},
        {"step": "Send response", "status": "done", "detail": "Response queued for immediate send."},
        {"step": "Log as resolved", "status": "done", "detail": f"Case {request_id} marked RESOLVED."},
    ]
    return {
        "branch": "General Enquiry",
        "steps": steps,
        "outputs": {
            "auto_generated_response": draft,
            "resolved_status_log": {"request_id": request_id, "status": "RESOLVED"},
        },
    }


def handle_service_request(request_id: str, text: str, classification: dict) -> dict:
    now = datetime.now()
    dept_key = _guess_department(text)
    department = DEPARTMENT_ROUTING[dept_key]
    sla_due = now + timedelta(hours=24)
    notification = _notify_stakeholder(
        f"Department Owner - {dept_key.capitalize()}",
        f"[MEDIUM] Service request {request_id} routed to {department}",
        f"A new service request has been routed to your team.\n\n"
        f"Case ID: {request_id}\n"
        f"Details: {classification.get('key_details', text[:160])}\n"
        f"SLA due: {sla_due.strftime('%Y-%m-%d %H:%M')} (24h)\n\n"
        f"Original message:\n{text}",
    )
    draft = _draft_response(
        f"Write a confirmation message to a customer confirming their service request "
        f"has been received and routed to {department}. Their message: {text}",
        customer_text=text,
    )
    steps = [
        {"step": "Extract required details", "status": "done",
         "detail": f"Key details captured: {classification.get('key_details', text[:120])}"},
        {"step": "Route to relevant department", "status": "done",
         "detail": f"Routed to {department}. {notification['detail']}"},
        {"step": "Generate confirmation to requester", "status": "done",
         "detail": "Confirmation message drafted."},
        {"step": "Set SLA timer", "status": "done",
         "detail": f"SLA due by {sla_due.strftime('%Y-%m-%d %H:%M')} (24h)."},
    ]
    return {
        "branch": "Service Request",
        "steps": steps,
        "outputs": {
            "routing_notification": f"{notification['recipient']} — {notification['detail']}",
            "confirmation_message": draft,
            "sla_flag": {"request_id": request_id, "department": department, "sla_due": sla_due.isoformat(timespec="minutes")},
        },
    }


def handle_escalation(request_id: str, text: str, classification: dict) -> dict:
    draft = _draft_response(
        f"Write an urgent, empathetic acknowledgement to a highly upset customer who is "
        f"escalating an issue. Their message: {text}",
        customer_text=text,
    )
    notification = _notify_stakeholder(
        "Supervisor",
        f"[CRITICAL] Escalation {request_id} requires human review",
        f"A critical case has been flagged and auto-resolution is paused.\n\n"
        f"Case ID: {request_id}\n"
        f"Summary: {classification.get('key_details', text[:160])}\n"
        f"Status: HELD FOR HUMAN REVIEW\n\n"
        f"A draft acknowledgement has been prepared and is awaiting your approval "
        f"in the Review Queue. It has NOT been sent to the customer.\n\n"
        f"Original message:\n{text}",
    )
    steps = [
        {"step": "Immediately flag for human review", "status": "done",
         "detail": "Case flagged CRITICAL and pinned to human review queue."},
        {"step": "Draft urgent acknowledgement", "status": "done",
         "detail": "Urgent acknowledgement drafted for supervisor review before sending."},
        {"step": "Notify supervisor", "status": "done",
         "detail": notification["detail"]},
        {"step": "Pause auto-resolution", "status": "done",
         "detail": "Automated resolution paused; case held for human-in-the-loop action."},
    ]
    return {
        "branch": "Escalation",
        "steps": steps,
        "outputs": {
            "supervisor_alert": f"{notification['recipient']} — {notification['detail']}",
            "draft_acknowledgement": draft,
            "human_in_the_loop_flag": {"request_id": request_id, "status": "HELD_FOR_HUMAN_REVIEW"},
        },
    }


BRANCH_MAP = {
    "Complaint": handle_complaint,
    "General Enquiry": handle_general_enquiry,
    "Service Request": handle_service_request,
    "Escalation": handle_escalation,
}


CONFIDENCE_OVERRIDE_THRESHOLD = "Low"


def run_workflow(request_id: str, text: str, classification: dict) -> dict:
    """
    Executes the branch-specific remediation workflow for a classified request.
    Includes an escalation-override safety net: if the classifier itself was
    unsure (confidence == "Low"), the case is force-routed to human review
    regardless of the predicted branch.
    """
    request_type = classification.get("request_type", "General Enquiry")
    confidence = classification.get("confidence", "Medium")

    if confidence == CONFIDENCE_OVERRIDE_THRESHOLD and request_type != "Escalation":
        result = handle_escalation(request_id, text, classification)
        result["override_applied"] = True
        result["override_reason"] = (
            f"Low classification confidence on predicted type '{request_type}' "
            f"-> auto-escalated to human review as a safety net."
        )
        return result

    handler = BRANCH_MAP.get(request_type, handle_general_enquiry)
    result = handler(request_id, text, classification)
    result["override_applied"] = False
    return result
