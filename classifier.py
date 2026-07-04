"""
classifier.py
--------------
Uses the Anthropic Claude API to classify an incoming request into:
  - request_type: "Complaint" | "General Enquiry" | "Service Request" | "Escalation"
  - urgency: "Low" | "Medium" | "High" | "Critical"
  - sub_topic: short free-text topic (e.g. "billing", "password reset")
  - confidence: "High" | "Medium" | "Low"  (used for the human-override safety net)
  - key_details: short extracted summary of what the customer actually needs

If no ANTHROPIC_API_KEY is available in the environment, the module falls back
to a deterministic keyword-based classifier so the prototype can still be
demoed/graded end-to-end offline. This mirrors a realistic production pattern:
never let an unavailable third-party API take the whole pipeline down.
"""

import json
import os
import re

SYSTEM_PROMPT = """You are a request triage assistant for a customer operations team.
Classify the incoming request and respond with ONLY a JSON object, no other text,
no markdown fences. The JSON object must have exactly these keys:

{
  "request_type": one of ["Complaint", "General Enquiry", "Service Request", "Escalation"],
  "urgency": one of ["Low", "Medium", "High", "Critical"],
  "sub_topic": a short 2-4 word topic label, e.g. "billing dispute", "password reset",
  "confidence": one of ["High", "Medium", "Low"] reflecting how confident you are in this classification,
  "key_details": a one-sentence summary of what the customer is asking for, written for an ops agent
}

Guidance on request types:
- "Complaint": the customer is unhappy about something that already happened (billing error, poor service, broken product) and wants it fixed or acknowledged.
- "General Enquiry": the customer is asking a question or wants information; nothing is broken and nothing urgent is being requested.
- "Service Request": the customer wants an action performed (change plan, update address, cancel, install, reset something).
- "Escalation": the customer is explicitly threatening to leave, demanding a manager, using highly charged/urgent language, mentions legal action, or has already complained before without resolution.

Guidance on urgency:
- "Critical": explicit escalation language, legal/regulatory threats, safety issues, repeated unresolved complaints.
- "High": clear complaint with financial or service impact.
- "Medium": standard service request with a reasonable expectation of timely action.
- "Low": general questions with no time pressure.

If you are unsure between two categories, choose the more cautious (higher urgency / more
human-oversight-requiring) option and set confidence to "Low".
"""

# ---- Offline fallback classifier -----------------------------------------

_ESCALATION_SIGNALS = [
    r"\blawyer\b", r"\blegal action\b", r"\bsue\b", r"\bregulator\b",
    r"\bmanager\b.*\bnow\b", r"\bthird time\b", r"\bunacceptable\b",
    r"\bcancel my account immediately\b", r"\bnever again\b", r"\bdemand\b",
    r"\bcompensation\b", r"\bmedia\b", r"\bsocial media\b", r"\breport (you|this)\b",
]
_COMPLAINT_SIGNALS = [
    r"\boverchar", r"\bwrong(ly)? charged\b", r"\brefund\b", r"\bnot working\b",
    r"\bbroken\b", r"\bpoor service\b", r"\bdisappoint", r"\bmistake\b",
    r"\bcomplain", r"\bissue with\b", r"\berror on my\b",
]
_SERVICE_SIGNALS = [
    r"\bplease (update|change|reset|cancel|install|upgrade|downgrade)\b",
    r"\bcan you (update|change|reset|cancel|install|activate)\b",
    r"\bneed to (update|change|reset|cancel)\b", r"\bnew address\b",
    r"\bupgrade my\b", r"\breset my password\b",
]

def _offline_classify(text: str) -> dict:
    t = text.lower()

    def hits(patterns):
        return sum(1 for p in patterns if re.search(p, t))

    esc = hits(_ESCALATION_SIGNALS)
    comp = hits(_COMPLAINT_SIGNALS)
    serv = hits(_SERVICE_SIGNALS)

    if esc > 0:
        request_type, urgency = "Escalation", "Critical"
        confidence = "High" if esc >= 2 else "Medium"
    elif comp > 0:
        request_type, urgency = "Complaint", "High"
        confidence = "High" if comp >= 2 else "Medium"
    elif serv > 0:
        request_type, urgency = "Service Request", "Medium"
        confidence = "Medium"
    else:
        request_type, urgency = "General Enquiry", "Low"
        # A well-formed question (has "?") or a reasonably long message is a
        # confident "nothing urgent going on here" read. Only very short,
        # vague, signal-free messages should trip the low-confidence override.
        word_count = len(t.split())
        if "?" in text or word_count >= 8:
            confidence = "Medium"
        else:
            confidence = "Low"

    return {
        "request_type": request_type,
        "urgency": urgency,
        "sub_topic": "general" if request_type == "General Enquiry" else request_type.lower(),
        "confidence": confidence,
        "key_details": text.strip()[:160],
        "engine": "offline-keyword-fallback",
    }


# ---- Claude API classifier -------------------------------------------------

def _extract_json(raw: str) -> dict:
    raw = raw.strip()
    raw = re.sub(r"^```(json)?", "", raw).strip()
    raw = re.sub(r"```$", "", raw).strip()
    return json.loads(raw)


def classify_request(text: str, model: str = "claude-sonnet-4-5") -> dict:
    """
    Classify a single incoming request. Tries the Claude API first; falls back
    to a local keyword classifier if no API key is configured or the call fails.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")

    if not api_key:
        return _offline_classify(text)

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=model,
            max_tokens=300,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Incoming request:\n\n{text}"}],
        )
        raw_text = "".join(
            block.text for block in resp.content if getattr(block, "type", None) == "text"
        )
        result = _extract_json(raw_text)
        result["engine"] = f"claude-api:{model}"
        return result
    except Exception as e:
        fallback = _offline_classify(text)
        fallback["engine"] = f"offline-fallback (API error: {type(e).__name__})"
        return fallback
