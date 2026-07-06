# Incoming Request Processing Workflow - Prototype

An AI-powered prototype that classifies incoming customer requests and executes a
distinct, multi-step remediation workflow for each classification - built for a
general BPO / customer operations context.

## 0. Which Document Should You Read?

This submission includes four documents. Each answers a different question:

| Document | Answers | Read this if you are... |
|---|---|---|
| **README** (this file) | How do I install it and click through it? | ...about to run the prototype yourself. |
| **Product Document** | Why does this exist, and who is it for? | ...evaluating the business case, ethics, or market fit, without needing the code. |
| **PRD** | What exactly must it do, and how does the logic work? | ...checking the build against requirements, or want the classification/decision-tree reasoning in full. |
| **Maintenance Document** | How do I run, extend, or fix this after handover? | ...a developer inheriting the codebase, or debugging an issue (see its Troubleshooting table). |

If you only have time for one document beyond this README, the **PRD** carries the most technical substance; the **Product Document** carries the most business framing.

## 1. Setup & Usage Tutorial

### Step 1 - Install

```bash
pip install -r requirements.txt
# On macOS, if pip isn't found: python3 -m pip install -r requirements.txt
```

### Step 2 - Connect the Claude API (recommended)

The prototype works without any keys (it falls back to a deterministic offline
classifier), but live Claude classification and drafting is the full experience.

1. Create a key at [console.anthropic.com](https://console.anthropic.com) →
   API Keys → Create Key (requires a small credit balance under Billing).
2. In your terminal:

```bash
export ANTHROPIC_API_KEY="sk-ant-...your-key..."
```

### Step 3 - Connect email notifications via Gmail SMTP (optional)

With SMTP configured, stakeholder alerts (supervisor, senior handler,
department owners) are sent as real emails. Without it, they are logged to a
simulated Outbox in the Admin tab instead - the workflow completes either way.

1. Enable **2-Step Verification** on your Google account
   (myaccount.google.com → Security).
2. Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords),
   create an App Password, and copy the 16-character code. Note: this is a
   machine-only credential - your normal Gmail password will not work here
   and should never be used in config.
3. In your terminal:

```bash
export SMTP_USER="you@gmail.com"
export SMTP_PASSWORD="your16charapppassword"
```

Environment variables reset when you close the terminal, so re-export all
three in each new session (or keep them in a private file outside the repo
and `source` it).

### Step 4 - Launch

```bash
streamlit run app.py
# On macOS, if streamlit isn't found: python3 -m streamlit run app.py
```

The browser opens at `http://localhost:8501`. The sidebar shows which mode is
active: green badges for live Claude and live SMTP, blue for the fallbacks.

### Step 5 - Use it, end to end

1. **Admin tab** - set who gets notified. Edit the stakeholder directory
   (name, position, email) and click Save. Positions are matched by keyword:
   "Supervisor", "Senior Handler", "Department Owner - Billing", etc.
2. **Process a Request tab** - pick a sample from the simulated inbox, paste
   your own text, or upload a `.txt` file, then click Process. You'll see the
   classification (type, urgency, confidence), the branch that ran, each
   remediation step, and the generated outputs (draft reply, notifications,
   flags).
3. **Batch Processing tab** - one click processes the full 10-message sample
   set, exercising every branch.
4. **Review Queue tab** - escalations and low-confidence cases are held here.
   Approve the AI's handling, or reclassify the case and re-run it down a
   different branch.
5. **Dashboard & Audit Log tab** - volumes by type/urgency/status, the
   deflection rate, estimated time and cost saved (all assumptions editable),
   and the full audit trail with a status filter and CSV export.
6. **Admin tab → Outbox** - every notification sent, marked `sent` (real
   email) or `simulated` (fallback).

For a terminal-only smoke test with no UI:

```bash
python3 run_batch_demo.py
```

Tip: to reset the demo data completely, stop the app and delete
`data/case_log.db` - it is recreated fresh on the next launch.

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
its confidence. `workflows.run_workflow()` checks this before branching - any
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
visible in both the UI and the audit log - nothing is hidden from the ops team.

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

- **Python 3** - orchestration logic (`classifier.py`, `workflows.py`, `storage.py`)
- **Anthropic Claude API** (`claude-sonnet-4-5`) - classification + draft generation
- **Streamlit** - 5-tab UI (intake, batch, review queue, dashboard, admin)
- **smtplib (Gmail SMTP)** - optional real email notifications to stakeholders, with a simulated-outbox fallback
- **SQLite** - case log / audit trail (`data/case_log.db`)
- **Pandas** - dashboard aggregation, CSV export

## 6. One End-to-End Example per Branch

*Sub-topic labels below reflect live Claude API output. The offline fallback
engine (used when `ANTHROPIC_API_KEY` is unset) produces coarser generic labels
(e.g. `"complaint"`, `"general"`) - branching and remediation steps are
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

### Bonus - Safety-net override → `REQ-1010`
> *"hey. this. still not fixed. do something."*

- Predicted type: General Enquiry, but classifier `confidence = Low` (too short
  and ambiguous to trust). The override rule intercepts this **before**
  branching and force-routes it to the **Escalation** branch for human review
  instead of silently auto-resolving a request that might actually need
  attention.

## 7. Design Decisions & Trade-offs

- **Confidence-gated override over a fixed keyword blocklist** - a threshold on
  the model's own reported confidence generalizes better than trying to
  enumerate every ambiguous phrasing by hand.
- **SQLite over a flat file** - trivial to query for the dashboard, upgradeable
  to Postgres with a one-line connection-string change if this moved to
  production.
- **Draft-then-hold for Escalation** - the acknowledgement is generated but
  explicitly not marked as sent, since critical cases should always pass
  through a human before anything goes out to the customer.
- **Offline fallback as a first-class path, not an afterthought** - a real ops
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
