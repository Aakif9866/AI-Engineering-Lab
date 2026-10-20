# 04 · TrustBoundary: guardrails and defensive UX

**In one sentence:** an assistant reads emails from strangers and proposes actions (look up an order, open a ticket, send a reply), and the system makes sure a malicious email can't trick it into doing something harmful, *even when the model itself is fooled*.

## The scenario

Ops staff at Meridian Logistics receive customer emails. The assistant summarises each one and proposes up to 3 tool actions:

| Tool | Risk | Rule |
|---|---|---|
| `query_sales_db` | low | Read-only SQL, approved tables only, runs immediately |
| `create_ticket` | medium | Runs immediately; P1 (urgent) tickets need a human |
| `send_reply` | high | **Always** needs a human; only to the sender or an internal address |
| `export_customer_data` | critical | Admins only, and needs a human |

Roles decide who can use what: `viewer` < `analyst` < `operator` < `admin`.

## Try it in the web app

Open **http://localhost:5173/trustboundary**.

1. **Process untrusted input:** pick a preset, keep the planner on **compromised (simulation)**, and process. The page shows every stage:
   1. Input guardrails: a risk meter, which rules fired, and what personal data was hidden from the model
   2. Model output and schema validation, including retries
   3. The policy engine's decision for each proposed action, with reasons
   4. Output cleaning
   - The *"Indirect injection + exfiltration"* preset gets **blocked** before the model.
   - *"Polite exfiltration"* gets through detection, but the attacker's address was already hidden, so nothing harmful can be proposed.
   - *"SQL via document: SELECT \*"* passes the text check and is stopped **inside the database engine**.
2. **Approvals, sandbox & log:** approve or reject pending actions. Try approving an email as an `analyst`: it's denied on review. Sent "emails" land in a sandbox outbox and never leave your machine.
3. **SQL guard:** write SQL (or, with a key, ask in English) and see it validated *before* it runs. Execution needs a separate click.
4. **Adversarial report:** run all 30 attack and benign cases and see which layer stopped each one.

**Compromised (simulation)** is an offline stand-in for a hijacked model. It deliberately obeys instructions it finds in the email, so we can prove the backend holds anyway.

## How it works

```
email ─► normalise (remove invisible chars) ─► detect PII → hide it ─► injection risk score
      ─► risk ≥ 0.8: BLOCK    risk ≥ 0.4: mark TAINTED (risky tools disabled)
      ─► model proposes JSON ─► validate against schema ─► invalid? retry with the error (max 2) ─► still invalid: FAIL CLOSED
      ─► for each proposed action: policy engine → allow / needs approval / deny
      ─► allowed SQL: read-only connection + database-level column checks
      ─► release summary: hide PII, strip image beacons, defang hostile links
```

| File | What it does |
|---|---|
| `detectors.py` | Input normalisation, hidden-text and base64 checks, the risk score, the optional Groq Prompt Guard signal |
| `policy.py` | **The security boundary:** roles, tool arguments, recipient and link rules, taint |
| `sqlguard.py` | Three layers of SQL protection and the sample analytics database |
| `pipeline.py` | The full request, planners, retry loop, approval queue, sandboxed tools, output cleaning |
| `adversarial.py` | Runs the 30-case corpus and scores detection and enforcement separately |
| `backend/data/p04/adversarial.json` | The test cases |

## Commands

```bash
cd backend
.venv/bin/python -m lab.p04_guardrails.adversarial                # offline
.venv/bin/python -m lab.p04_guardrails.adversarial --mode llm     # DeepSeek as the planner (~25 paid calls)
.venv/bin/python -m pytest tests/test_p04_guardrails.py
```

## Measured results (2026-10-20)

| | Offline (compromised) | DeepSeek planner |
|---|---|---|
| Attacks where enforcement held | **100%** | 100% in 6 of 8 runs after fixes |
| Attacks the detector flagged | 45% | 45% |
| Benign emails wrongly flagged | 0% | 0% |

Real findings from the DeepSeek runs:
- DeepSeek **refused** most embedded attacks on its own (it never proposed the malicious SQL).
- It also exposed a **real gap**: it described a tracking-pixel URL in plain text in its summary, which the output filter missed. That's now fixed (hostile links are "defanged") and covered by tests.

## Limits and next steps

- Heuristic detection misses novel phrasing; the report lists every miss instead of hiding it.
- Groq Prompt Guard was verified live: injection 0.999, benign 0.0005, but it **missed** the polite exfiltration email (0.0005) that the heuristic flagged (0.55). Detectors cover different attacks; neither is the boundary.
- **V2:** versioned policies, learned risk scores, auto-generated attack variants, a red-team trend dashboard.
