# Instant (ASAP) booking

**Purpose:** The on-demand booking mode — book now instead of picking a slot.
**Last updated:** 2026-08-13
**Status:** Populated from code (`master`)
**Source:** `config/constants/instant_slots.go`, `spec/instant-slots.md`, `spec/oms-instant-service-fee.md`, `spec/subscriber-free-instant-booking.md`, `spec/instant-cleaner-open-work-guard.md`

Instant is a **second booking path**, not a plan and not an addon. The customer buys the same spa plan; what differs is *when* it is served and that a service fee applies.

## Rules

| Rule | Value |
|------|-------|
| Sell window | **08:00 – 16:00 IST**, every day including weekends. Half-open: open at exactly 08:00, closed **at** 16:00 |
| Arrival | **now + 45 minutes** |
| Job length | The plan's duration; **120 minutes** if the plan has none |
| Service fee | **₹200** (SKU `INSTANT_SERVICE_FEE`) |
| Who serves it | Only cleaners flagged as **instant servers**, and only if free |
| Availability check | `instant_details` on the slots API tells the app whether Instant can be offered right now |

The 16:00 cut-off is deliberate even though it overruns: with the 45-minute buffer and a 120-minute default job, a purchase at the cutoff can finish after the last scheduled afternoon window. That is accepted.

## Who pays the fee

| Customer | Instant fee |
|----------|-------------|
| One-time booking | **₹200** |
| Active subscription (multipack) holder | **Waived** |
| Buying a pack **in the same order** as the instant wash | **Waived** |
| Anything the fee service cannot read | **No fee** — it fails open rather than blocking checkout |

The pack-purchase waiver exists because the subscription does not exist yet at fee time — the order is recognised from its own item SKUs. Fee resolution happens in a **blocking** call from OMS while building the order summary, so it is designed to never break checkout: on any doubt, no fee.

## Why a cleaner may be unavailable

A cleaner counts as **busy** — and so cannot take an Instant job — if they have any live booking on the **same IST day** as the slot, or any booking overlapping it on any date. This is stricter than a pure time overlap on purpose: slot timestamps are never extended when a job runs long, so overlap alone would hand a second job to a cleaner who is still working the first.

So "no Instant available" usually means *every instant cleaner already has work today*, not that the feature is off.

### The live constraint: one cleaner

**Measured 2026-08-14: exactly one cleaner has `is_instant_server = 1`** (cleaner id 7), and **15 of
the 16** Instant bookings ever created were served by him. Automatic Instant assignment can only pick
instant-flagged cleaners, and the busy rule above is per-IST-day — so whenever that one cleaner has
any live booking, **Instant goes dark for the whole of Gurgaon**.

That, not customer demand, is the most likely explanation for Instant sitting at 0.9% of bookings.
Flagging more cleaners is a data change (`POST /cleaners/update` sets `is_instant_server`), not a
deploy. Nothing in the product decides how many instant servers there should be — open as **P-11**
in [../questions.md](../questions.md).

## Assignment

Instant bookings are **eager-assigned at fulfilment** — there is no waiting for the 15-minute cron. They bypass the slot timetable and do not consume slot inventory.

Automatic assignment picks only instant-flagged cleaners. Ops reassignment from the dashboard is looser — see [../operations/assignment.md](../operations/assignment.md).

## What ops sees

A Slack reconciliation alert fires **after** the booking is created when the fee and the service disagree: charged for Instant but given a scheduled slot, or served instant without being charged. It is **alert-only** and never blocks or cancels a paid booking, so an alert means "check this", not "the customer has no booking".

## Commercials

The **₹200 is revenue — Park+ keeps it.** No share is passed to the cleaner who serves the job
(confirmed by Business, 2026-08-13). It is charged as a separate OMS order line, so it does not move
the catalog package price and it is not part of the tier price.

Measured to 2026-08-13: Instant went live **2026-07-31**; **15** fee-bearing successful orders,
**₹3,000** of fee revenue booked, **3.9%** of August's successful orders. Instant ASP ₹707 against a
₹507 base. Orders with the fee **waived** (pack holders, pack purchases) do not show the fee line, so
15 is a floor rather than the total — see [../business/metrics.md](../business/metrics.md#instant).

## Not documented

- Customer-facing copy and placement of the Instant entry point in the app
- **Target** Instant mix (the current 3.9% has nothing to be measured against)
- Whether cleaners serving Instant get any incentive, given the fee is retained in full
- Whether the 08:00–16:00 window is final (it has already moved once — see [../CHANGELOG.md](../CHANGELOG.md))

## Related

[pricing.md](pricing.md) · [subscriptions.md](subscriptions.md) · [plans.md](plans.md) · [../operations/assignment.md](../operations/assignment.md) · [../operations/slot-configuration.md](../operations/slot-configuration.md) · [../engineering/system-design.md](../engineering/system-design.md#instant-booking-asap)
