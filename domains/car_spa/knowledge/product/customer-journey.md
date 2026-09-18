# Customer journey (Car Spa)

**Purpose:** End-to-end customer path from discover → book → service → repeat.  
**Last updated:** 2026-07-14  
**Status:** Populated  
**Source:** Live FAQs + grill policies + eng product pass

Happy path and product rules for Gurugram spa bookings.

## Happy path

```text
Serviceability (lat/lon inside Gurugram cluster polygon)
  → Pick vehicle (model → tier)
  → Choose plan + slot
  → Cart / pay (OMS; promo codes → typically Park+ wallet cashback)
  → Kafka fulfilment creates booking (CREATED)
  → Cleaner assigned (ASSIGNED) + WhatsApp “expert assigned / will arrive”
  → Job (REACHED → STARTED → INTERIOR_COMPLETED → EXTERIOR_COMPLETED
         → CLEANED | DELIVERY_ITEMS_ACKNOWLEDGED | COMPLETED — equivalent “done”)
  → Rating nudge (+ live tip options) → multipack / subscription upsell (~day 3)
```

## Stages (narrative)

1. **Discover** — In-app Car Spa, society/corporate activations, WhatsApp, referrals, organic Park+ traffic.
2. **Select vehicle & package** — Model → tier; Premium / Basic / Exterior Only; “Add Car to see Prices”.
3. **Review inclusions & guidelines** — Services, exclusions, water/space.
4. **Choose slot & address** — Inside Gurgaon polygon; slots 08:00, 10:30, 13:00, 15:30.
5. **Pay** — Park+ / OMS checkout.
6. **Pre-service prep** — Final parking spot, valuables out, water (≥2 buckets preferred), space, phone reachable.
7. **Service delivery** — Cleaner arrives with tools; executes plan; no driving/moving the car.
8. **Completion & feedback** — Inspect before taking keys; rating / tip.
9. **Reschedule / support** — Reschedule **up to 3 times** if **>2h** before slot; cancel not self-serve (Help & Support / Ops).
10. **Repeat / subscription** — Day-3 upsell / multipack; day-30 WhatsApp repeat theme.

## Product rules (authoritative)

| Topic | Rule |
|-------|------|
| Geography | **Gurugram only**; entire city = **one cluster**; must be **inside polygon** |
| Pricing | Tier-based only; **addons off**; GST-inclusive @ 18% |
| Promos | Codes usually grant **wallet cashback** (not catalog row edits) |
| Cancel (customer) | **No self-serve**; Help & Support exceptions via **Ops Manager** |
| Cancel (ops) | Manual (e.g. no water/space; unserviceable address) |
| Refund | **Full**, **manual via OMS** when OMS raises; subscription unused washes expire **no refund** |
| Multipack | Pay **4×** Full Spa Premium (last booking car’s tier, or **T5** if none) → **5** bookings of **any** plan on **any** tier car / 1 year; **one** active pack max |
| Reschedule (customer) | **Up to 3 times**, if **>2h** before slot start |
| Instant (ASAP) | Sold **08:00–16:00 IST**; cleaner arrives **now + 45 min**; **₹200** fee (waived for pack holders) — [instant.md](instant.md) |
| Reschedule (dashboard) | **Multiple**; **independent** of customer one-shot |
| Morning assign | Tomorrow **08:00** & **10:30** assigned **day before** (~**10 PM IST** cron) |
| Other slots | `assign-jobs` every **~15 min** |
| Assignment preference | **None** today |
| Late / no-show | Customer got assign WhatsApp; ops still expected to assign; >30 mins after slot start → ops alert |

## Cleaning status FSM (field)

```text
CREATED → ASSIGNED → REACHED → STARTED → INTERIOR_COMPLETED → EXTERIOR_COMPLETED
  → CLEANED | DELIVERY_ITEMS_ACKNOWLEDGED | COMPLETED  (equivalent terminals)
```

See [booking-lifecycle.md](../operations/booking-lifecycle.md).

## Post-job

| Moment | What |
|--------|------|
| After done | Rating WhatsApp (~**45 min** after slot end); status terminal set by **cleaner app** |
| Tip | Live OMS options ₹30 / ₹50 / ₹100 |
| Multipack / upsell | **5+1**; redeem any plan/any tier car; WhatsApp ~day 3 if no active sub |

Details: [rating-and-tipping.md](rating-and-tipping.md), [subscriptions.md](subscriptions.md).

## Engineering links

- Reschedule: `booking_controller.go` (`shouldShowReschedule` — 2h cut-off)
- Morning assign: `cronjobs/assign_morning_slots.go`
- Rolling assign: `cronjobs/assign_jobs.go`
- Slots: `slotconfig/config.go` (08:00, 10:30, 13:00, 15:30)
