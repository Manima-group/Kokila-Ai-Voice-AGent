# Master Specification — index

The full authoritative texts live in the Claude Project "Kokila-Ai-Agent":

1. **KOKILA — MASTER ENGINEERING PROMPT v1.0** — original Voice SaaS scope (implemented in commits up to `71089f6`).
2. **Kokila Master Project Specification v5.0 (frozen, 25 Nov 2026)** — unified Voice + Assistant + Connect + Pro modules.
3. **Unified Platform Implementation Instructions (27 Nov 2026)** — owner amendments that override v5.0 where they conflict.

## Amendments applied (27 Nov 2026)
- Theme orange/white/grey; product-selection dashboard after login (reference image).
- Two products: **Calling Agent**, **Business Assistant** (with Personal mode). Connect is shared infrastructure.
- Locked products are visible with Upgrade / Request access; locked URLs and APIs are denied server-side.
- Connectors: v5.0 list + **ERPNext** + **Manima Hub** (first-party priority).
- One authentication, one entitlement system, one organization model, one Super Admin console.
- Platform sidebar: Overview, Calling Agent, Business Assistant, Integrations, Billing, Settings, Help & Support.
- No autonomous model retraining; improvement via prompts, templates, RAG, user-approved memory and human-approved knowledge.

## Conflicts resolved
| Source A | Source B | Resolution |
|---|---|---|
| v5.0 §26.2 yellow/cream, no orange | Amendment: orange | Orange (amendment) |
| v5.0 three experiences (Voice, Assistant, Connect) | Amendment: two products | Two products; Connect is infrastructure |
| Project instructions: 8 phases | v5.0: no phases | Work proceeds as one scope with recorded progress; phases are not stopping points |

Progress against every requirement is tracked in `REQUIREMENTS_TRACEABILITY.csv` (root) and summarised in `IMPLEMENTATION_PROGRESS.md`.
