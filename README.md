# Incoming Request Processing Workflow — Prototype

An AI-powered prototype that classifies incoming customer requests and executes a
distinct, multi-step remediation workflow for each classification — built for a
general BPO / customer operations context.

## 1. Setup

```bash
pip install -r requirements.txt

# Optional — enables live Claude-powered classification & drafting.
# Without this the app runs on a deterministic offline fallback so it's
# always demoable, e.g. in an environment with no network access.
export ANTHROPIC_API_KEY=sk-ant-...

streamlit run app.py
```

The app opens five tabs: **Process a Request** (simulated inbox / manual text /
file upload), **Batch Processing** (runs the full sample dataset in one click),
**Review Queue** (human-in-the-loop: approve or reclassify held cases),
**Dashboard & Audit Log** (volumes, deflection rate, estimated time and cost
saved, full case log with status filter and CSV export), and **Admin**
(editable stakeholder directory that controls notification routing, plus a
notification outbox).

Optional: set `SMTP_USER` and `SMTP_PASSWORD` (a Gmail App Password) to send
stakeholder notifications as real emails. Without them, notifications are
logged to a simulated outbox instead, so the workflow always completes.

For a quick terminal-only smoke test (no UI):

```bash
python3 run_batch_demo.py
```

## 2. Workflow Design

```
Incoming request (form / upload / simulated inbox)
        │
        ▼
 Claude classifies: request_type, urgency, sub_topic, confidence, key_details
        │
        ├── confidence == "Low"? ──► SAFETY-NET OVERRIDE ──► Escalation branch
        │                                                    (human review, regardless
        │                                                     of predicted type)
        ▼
 Branch on request_type
        │
        ├── Complaint          (High)     → acknowledge → escalate to senior handler
        │                                   → log w/ priority flag → 2h follow-up
        ├── General Enquiry    (Low)      → classify sub-topic → generate KB response
        │                                   → send → log resolved
        ├── Service Request    (Medium)   → extract details → route to department
        │                                   → confirm → SLA timer
        └── Escalation         (Critical) → flag for human review → draft urgent ack
                                             → notify supervisor → pause automation
        │
        ▼
 Every case logged to SQLite audit trail (data/case_log.db) → feeds dashboard
```

## 3. Classification Logic

`classifier.py` sends the request text to Claude (model `claude-sonnet-4-5`) with a
system prompt that defines the four categories and their urgency bands, and asks
for strict JSON output: `request_type`, `urgency`, `sub_topic`, `confidence`,
`key_details`.

**Why a `confidence` field matters:** rather than forcing every request into one
of four buckets even when the model is unsure, the classifier also self-reports
its confidence. `workflows.run_workflow()` checks this before branching — any
`confidence == "Low"` result is force-routed to the **Escalation** branch
regardless of the predicted type, holding the case for human review instead of
letting a shaky auto-classification drive an unsupervised action. This is the
"escalation override mechanism for edge cases the AI is uncertain about"
enhancement called out in the brief.

**Offline fallback:** if no `ANTHROPIC_API_KEY` is set (or the API call fails for
any reason), `classifier.py` transparently falls back to a keyword/regex-based
classifier so the prototype never goes down and stays demoable in constrained
environments. The `engine` field on every classification result records which
path was used (`claude-api:<model>` vs `offline-keyword-fallback`), and this is
visible in both the UI and the audit log — nothing is hidden from the ops team.

## 4. Remediation Strategy per Branch

| Branch | Urgency | Steps | Outputs |
|---|---|---|---|
| **Complaint** | High | Acknowledge receipt → escalate to senior handler → log with priority flag → set 2h follow-up | Draft acknowledgement, escalation notification, case log entry |
| **General Enquiry** | Low | Classify sub-topic → generate AI response from KB → send → log resolved | Auto-generated response, resolved status log |
| **Service Request** | Medium | Extract details → route to department (billing / technical / account / shipping / general, inferred by keyword) → generate confirmation → set 24h SLA timer | Routing notification, confirmation message, SLA flag |
| **Escalation** | Critical | Flag for human review → draft urgent acknowledgement → notify supervisor → pause auto-resolution | Supervisor alert, draft acknowledgement (held, not sent), human-in-the-loop flag |

Draft customer-facing messages (acknowledgements, confirmations, KB answers) are
generated per-case by Claude with a short, warm, professional tone constraint;
offline mode uses a generic template so the flow still produces a full artifact
set without a live model.

## 5. Tools Used

- **Python 3** — orchestration logic (`classifier.py`, `workflows.py`, `storage.py`)
- **Anthropic Claude API** (`claude-sonnet-4-5`) — classification + draft generation
- **Streamlit** — 5-tab UI (intake, batch, review queue, dashboard, admin)
- **smtplib (Gmail SMTP)** — optional real email notifications to stakeholders, with a simulated-outbox fallback
- **SQLite** — case log / audit trail (`data/case_log.db`)
- **Pandas** — dashboard aggregation, CSV export

## 6. One End-to-End Example per Branch

*Sub-topic labels below reflect live Claude API output. The offline fallback
engine (used when `ANTHROPIC_API_KEY` is unset) produces coarser generic labels
(e.g. `"complaint"`, `"general"`) — branching and remediation steps are
identical either way; only the richness of the extracted metadata differs.*

### Complaint → `REQ-1001`
> *"I was charged twice for my subscription this month and it's the second time
> this has happened. This is really disappointing and I'd like a refund for the
> duplicate charge."*

- Classified: **Complaint**, urgency **High**, sub-topic "billing dispute"
- Steps executed: acknowledged → escalated to Senior Complaints Handler queue →
  logged with `priority=HIGH` → 2-hour follow-up reminder set
- Outputs: draft acknowledgement, escalation notification, case log entry with
  follow-up due timestamp

### General Enquiry → `REQ-1002`
> *"Hi, just wondering what your customer support hours are on weekends? Also,
> do you offer support in French?"*

- Classified: **General Enquiry**, urgency **Low**, sub-topic "support hours"
- Steps executed: sub-topic classified → KB-grounded response generated → sent →
  logged `RESOLVED`
- Outputs: auto-generated response, resolved status log

### Service Request → `REQ-1003`
> *"Can you please update the delivery address on my last order? I moved house
> last week and the package hasn't shipped yet."*

- Classified: **Service Request**, urgency **Medium**, routed to Account
  Management Team (the "address" keyword matches the account-update routing rule)
- Steps executed: details extracted → routed → confirmation drafted → 24h SLA
  timer set
- Outputs: routing notification, confirmation message, SLA flag

### Escalation → `REQ-1004`
> *"This is the THIRD time I'm contacting you about the same billing error and
> nobody has fixed it. I want to speak to a manager immediately or I will be
> taking this to my bank and reporting you to the regulator."*

- Classified: **Escalation**, urgency **Critical**
- Steps executed: flagged for human review → urgent acknowledgement drafted
  (held for supervisor review, not auto-sent) → supervisor notified →
  auto-resolution paused
- Outputs: supervisor alert, draft acknowledgement, human-in-the-loop flag

### Bonus — Safety-net override → `REQ-1010`
> *"hey. this. still not fixed. do something."*

- Predicted type: General Enquiry, but classifier `confidence = Low` (too short
  and ambiguous to trust). The override rule intercepts this **before**
  branching and force-routes it to the **Escalation** branch for human review
  instead of silently auto-resolving a request that might actually need
  attention.

## 7. Design Decisions & Trade-offs

- **Confidence-gated override over a fixed keyword blocklist** — a threshold on
  the model's own reported confidence generalizes better than trying to
  enumerate every ambiguous phrasing by hand.
- **SQLite over a flat file** — trivial to query for the dashboard, upgradeable
  to Postgres with a one-line connection-string change if this moved to
  production.
- **Draft-then-hold for Escalation** — the acknowledgement is generated but
  explicitly not marked as sent, since critical cases should always pass
  through a human before anything goes out to the customer.
- **Offline fallback as a first-class path, not an afterthought** — a real ops
  team cannot have their whole triage pipeline go down when a third-party API
  has a bad minute; this prototype models that resilience directly.

## 8. Known Gaps & v2 Priorities

Honest limitations of the current build, roughly in the order we would tackle
them next:

- **No accuracy evaluation.** The 10-message sample set demonstrates the
  pipeline but does not measure it. A serious v2 needs a labelled test set
  (~100 messages) with per-category accuracy and a confusion matrix, so
  classification quality is a number rather than a claim.
- **Urgency is displayed, not consumed.** A High-urgency service request gets
  the same 24h SLA as a Medium one. Urgency should scale the SLA window, the
  follow-up timer, and notification priority inside each branch.
- **Keyword department routing.** Fast and fully explainable, but coarser than
  letting the model choose the department directly (with keywords retained as
  the fallback).
- **No few-shot examples in the classifier prompt.** Category definitions only.
  Adding 2-3 worked examples per category would tighten consistency on vague
  messages, which currently skew (deliberately) toward cautious escalation.
- **Multi-intent messages take one branch.** A message containing both a
  complaint and an enquiry rides the complaint path; the enquiry half is not
  split into its own case.
- **Case threading.** Each message is a new case. Linking repeat contacts by a
  customer identifier would enable auto-escalation on repeat contact.
- **Feedback loop.** Human reclassifications are already logged with
  `engine = human-reclassified`, but nothing learns from them yet. Using these
  corrections to refine the prompt or few-shot set is the natural next step,
  since the data collection is already built.

## Project Structure

```
.
├── app.py              # Streamlit UI (5 tabs incl. review queue & admin)
├── notifier.py          # stakeholder email notifications + outbox fallback
├── classifier.py        # Claude-based classification + offline fallback
├── workflows.py         # Branch-specific remediation logic (4 branches)
├── storage.py            # SQLite audit trail / case log
├── sample_data.py        # 10 synthetic sample requests (AI-generated, no real data)
├── run_batch_demo.py     # CLI batch runner (no UI needed)
├── requirements.txt
├── .env.example
└── data/case_log.db      # created on first run
```
