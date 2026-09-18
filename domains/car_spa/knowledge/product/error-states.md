# Error states & edge cases (documented)

**Purpose:** Expected product behaviour when things go wrong — grounded in code + grill; no invented SLAs.  
**Last updated:** 2026-07-15  
**Status:** PARTIAL  
**Owner:** Product · Support  
**Related:** [../operations/cancellations.md](../operations/cancellations.md) · [../playbooks/](../playbooks/) · [../questions.md](../questions.md)

| Scenario | Documented behaviour | Gaps |
|----------|---------------------|------|
| **Customer cancel** | No self-serve; Help & Support → Ops Manager (e.g. unserviceable address) | Response SLA ❌ |
| **Ops cancel** | Manual (e.g. no water/space) | — |
| **Reschedule (customer UI)** | Button if >2h before slot and not yet customer-rescheduled | Support post-cut-off path ❌ |
| **Reschedule (dashboard)** | Multiple; no 2h / one-shot limit | — |
| **Reschedule (customer API)** | No 2h gate in API (status / future slot / already-rescheduled checks) | Confirm product intent |
| **Refund** | Full, manual via OMS when OMS raises | Turnaround ❌ |
| **Subscription expiry** | Unused washes expire; no refund | — |
| **Payment not SUCCESS** | Fulfilment consumer skips booking create; OMS status `FAIL` | App retry UX (OMS) ❌ |
| **Cleaner late (>30m)** | Customer notify + Slack ops; only if already **ASSIGNED**; no cleaner penalty | Customer compensation ❌ |
| **Assign cron skip** (no free cleaner) | Booking stays unassigned; log skip; **no auto customer notify** | Ops playbook / SLA ❌ |
| **OTP_VERIFIED** | Legacy status; live start uses **StartPin**, not OTP verify step | — |
| **Vendor unavailable** | N/A — in-house cleaners only | — |
| **Weather abort** | ❌ not documented | O-06 |
| **Quality complaint** | Escalation matrix only | Defect SOP ❌ |

## Playbooks (stubs)

- [../playbooks/payment-failed.md](../playbooks/payment-failed.md)
- [../playbooks/cleaner-not-assigned.md](../playbooks/cleaner-not-assigned.md)
- [../playbooks/customer-complaint.md](../playbooks/customer-complaint.md)
