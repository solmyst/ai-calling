# Product overview — Park+ Car Care (Car Spa)

**Purpose:** What Park+ Car Spa is and how the product fits the business.  
**Last updated:** 2026-07-14  
**Status:** Populated  
**Source:** Handbook + grill session + eng product pass

## One-liner

Park+ Car Care is an **at-home / at-parking car spa**: a verified cleaner visits the customer’s parked car with equipment; the customer provides water and space. Hyperlocal doorstep fulfilment inside a serviceable geo boundary.

**Live geo:** Gurugram, Haryana — **one cluster** covering the city; booking requires lat/lon **inside the cluster polygon**.

## Current state snapshot

| Metric | Current |
|--------|---------|
| Bookings/day | ~20 |
| Organic/day | ~10 (informal; attribution not tracked) |
| Subscriptions/day | 0 |
| Cleaners | 11 |
| Capacity/day | ~44 |
| Average price | ~₹500 |
| Live rating signal | Post-job 1–5 stars in Metabase (high; sample ~4.89) |
| Live city | Gurgaon only |

## What customers buy

Three spa plans (addons **off**):

1. **Full Car Spa Premium** (110 min) — SKU `car_care_full_spa_premium` (DB `plan_code` may still say `interior_only`; treat as Premium)
2. **Full Car Spa Basic** (80 min) — `car_care_full_spa_basic`
3. **Exterior Only** (40 min) — `car_care_exterior_only`
4. **Multipack / subscription** — 5 washes for price of 4 — see [subscriptions.md](subscriptions.md)

Pricing: **tier-based** (T1–T9). Promos usually → **Park+ wallet cashback**. See [pricing.md](pricing.md), [plans.md](plans.md).

## Cancel / reschedule / refund

- Customer: **no self-serve cancel**; **one** reschedule if **>2h** before slot
- Help & Support may grant cancel exceptions (Ops Manager; e.g. unserviceable address)
- Dashboard: **multiple** reschedules (independent of customer flag)
- Refund: **full**, **manual via OMS** when OMS raises
- Multipack: **4×** Premium (tier from last booking’s car, else T5) → **5** washes / 1 year

## Assignment

- 08:00 & 10:30 tomorrow → assigned **day before** (~10 PM IST)
- Other slots → every ~15 min into the window
- No customer↔cleaner preference (no "my usual cleaner"); assignment balances load — fewest jobs that day among free cleaners
- Assign WhatsApp to customer; ops ensures assignment

## Personas / acquisition (current)

- Personas: apartment residents, corporate employees, premium vehicle owners, busy professionals, existing Park+ users
- Channels: society carnivals, corporate activations, organic, WhatsApp, offline branding, referrals (₹200 live — see [../business/partner-management.md](../business/partner-management.md))
- Market: weekend demand > weekdays; society activations strong; hyperlocal density helps productivity

## Surfaces

| Surface | Role |
|---------|------|
| Customer app | Plans, cart, slots, **Instant (ASAP)**, track, up to 3 reschedules, rating/tip entry points |
| Cleaner app | Attendance, schedule, cleaning FSM |
| Dashboard | Assign, multi reschedule, manual cancel |

## Product principles

- Verified professionals, bring equipment; customer provides water + space.
- Cleaners do not start/drive/move the vehicle.
- Price depends on vehicle model tier + selected plan.

## Further reading

- Journey: [customer-journey.md](customer-journey.md)
- Lifecycle: [../operations/booking-lifecycle.md](../operations/booking-lifecycle.md)
- Rating/tip: [rating-and-tipping.md](rating-and-tipping.md)
- Subscriptions: [subscriptions.md](subscriptions.md)
- Engineering: [../engineering/architecture.md](../engineering/architecture.md)

## Related

- [customer-journey.md](customer-journey.md) · [../operations/booking-lifecycle.md](../operations/booking-lifecycle.md) · [state-machines.md](state-machines.md) · [notifications.md](notifications.md) · [error-states.md](error-states.md)
