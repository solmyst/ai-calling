# Plans

**Purpose:** Bookable packages and subscription / multipack definition.  
**Last updated:** 2026-07-14  
**Status:** Populated  
**Source:** Live `plans` rows + grill session + eng catalog dump

Source dump: `plans` table (active Car Spa packages). All durations IST field time estimates.

## Active plans

| id | plan_code (DB) | SKU | Display name | Duration | display_order | Tag |
|----|----------------|-----|--------------|----------|---------------|-----|
| 1 | `interior_only` ⚠️ | `car_care_full_spa_premium` | Full Car Spa Premium | 110 | 1 | INTRODUCTORY OFFER |
| 2 | `full_spa_ie` | `car_care_full_spa_basic` | Full Car Spa Basic | 80 | 2 | — |
| 3 | `exterior_only` | `car_care_exterior_only` | Exterior Only | 40 | 3 | — |

`plan_code = interior_only` **is** Full Car Spa Premium in product terms (legacy code string only). Always use display name / SKU for humans.

## Inclusions (from plan meta `services_included`)

### Exterior Only (id 3) — ~40 min

| Step | Typical mins |
|------|----------------|
| Foam Wash | 20 |
| Tyre Cleaning | 5 |
| Tyre Polish | 5 |
| Exterior Wax | 10 |
| Glass Cleaning | 5 |

### Full Car Spa Basic (id 2) — ~80 min

Everything in Exterior Only, plus:

| Step | Typical mins |
|------|----------------|
| Vacuum Cleaning | 10 |
| Dashboard & Interior Wipe | 10 |
| Seat Cleaning (Leather/Leatherite) | 5 |
| Dashboard & Interior Polish | 10 |

### Full Car Spa Premium (id 1) — ~110 min

Everything in Basic, plus:

| Step | Typical mins |
|------|----------------|
| Plastic Cladding Cleaning & Polish | 20 |
| Deep Interior Detailing | 10 |

Maps to `plan_services` ids — see [service-catalog.md](service-catalog.md).

## Multipack / subscription

Canonical rules: [subscriptions.md](subscriptions.md).

| Field | Value |
|-------|-------|
| Offer | **6 washes for price of 5 (5+1)** — SKU `full_spa_premium_6_multipack` |
| Base pricing plan | Full Car Spa Premium × 5 (last booking tier, else T5) |
| Redeem | Any spa plan, any car tier, 6 times |
| Validity | 365 days / 1 year |
| Expiry | Unused washes expire — **no refund** |
| Concurrent packs | Max one active |
| Current sales volume | ~0/day |

The retired **4+1** pack (`full_spa_premium_5_multipack`, 5 washes at 4× price) is no longer sold but is still honoured for everyone who bought one — see [subscriptions.md](subscriptions.md).

Price is 5 × the Full Spa Premium price for the tier, so recompute from [pricing.md](pricing.md) rather than reusing the old 4× round number.

## Shared customer guidelines (all plans)

- Cleaner brings equipment; customer provides **water** (often “≥2 buckets”) and **space**.
- Customer need not stay the whole time; phone reachability recommended; inspect car before taking keys.
- Cleaners **will not start, drive, or move** the vehicle.
- Remove valuables; park at final spot.
- Exclusions: engine bay/bonnet, underbody, pet hair, biohazard, surrounding floor water cleanup; interior limits as listed per plan.

## Cancel / reschedule / refund

Plan FAQs may say cancel & reschedule are not allowed. **Operative rules:** see [../operations/cancellations.md](../operations/cancellations.md).

- No customer self-serve cancel; Help & Support / Ops Manager exceptions; ops may cancel manually
- Customer: **one** reschedule if **>2h** before slot
- Dashboard: **multiple** reschedules; does not consume the customer one-shot
- Refund via OMS when cleaning could not be processed / after approved cancel

## Engineering touchpoints

- List / home: `apps/car_care/controllers/plan_controller.go`
- Models: `models/car_care_catalog_models.go` → `plans`
- Pricing overlay: `plan_item_tier_pricing` + [pricing.md](pricing.md)

## Related

- [pricing.md](pricing.md) · [service-catalog.md](service-catalog.md) · [subscriptions.md](subscriptions.md) · [faq.md](faq.md)
