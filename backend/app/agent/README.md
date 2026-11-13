# Agent (planned)

Agentic escalation and transfer planning is **postponed** after the initial
prototype. The intended shape:

- A Claude agent with tools (`get_inventory`, `get_alerts`, `propose_transfer`,
  `notify_contact`, `check_acknowledgement`) runs the escalation ladder:
  who to call next, when to retry, and when to move on to transfer planning.
- It may *suggest* and *explain* transfer plans, but every plan is validated by
  the deterministic planner in `app/domain/planner.py`, which is authoritative.
- A human still approves every transfer.
- A rule-based fallback runs when no API key is configured.
