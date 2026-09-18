# Pricing

**Purpose:** How customer prices are calculated.  
**Last updated:** 2026-08-14  
**Status:** Populated  
**Source:** Grill session + `plan_item_tier_pricing` / `model_tier_mapping` + eng API path

## Policy (current product)

1. Each vehicle **brand + model** maps to a **tier** (`T1`–`T9`, DB tier IDs `4`–`12`).
2. Smaller cars → lower tiers; larger / premium cars → higher tiers.
3. For a selected **plan**, every included `SERVICE` line item has MRP + **selling / discounted_price** per tier.
4. **The charged price is a round number per tier, and it is *not* the sum of the SERVICE selling prices.** Measured 2026-08-14 for Full Car Spa Premium:

   | Tier | Sum of `plan_item_tier_pricing` | **Actually charged** |
   |------|-------------------------------:|---------------------:|
   | T1 | 436 | **379** |
   | T2 | 461 | **399** |
   | T3 | 529 | **459** |
   | T4 | 576 | **499** |
   | T5 | 673 | **589** |
   | T6 | 794 | **702** |
   | T7 | 970 | **869** |
   | T8 | 1,068 | **959** |
   | T9 | 1,140 | **1,021** |

   The component sum runs **~11–13% above** what the customer pays. Treat `plan_item_tier_pricing` as the **MRP / component-breakdown source for display**, not as the checkout total. Where the round price is set is **not in this repo** — open as P-13 in [../questions.md](../questions.md).
5. **Actual one-time plan price** for answers: prefer whatever the **plans/cart API returns** for that plan + model. Wiki arithmetic is illustrative.
6. Vehicle-type pricing may exist in schema/code — **not** product source of truth.
7. `ADDON` rows may exist in DB — **addons are disabled** in the customer app.
8. Displayed / charged package prices are **GST-inclusive**. GST rate = **18%** (embedded).
9. Handbook ASP ~₹500 is a **portfolio average**, not a fixed menu price.
10. **Promo codes** (OMS / Park+): typically **cashback to Park+ wallet** on top of the tier price.
11. **Instant (ASAP) bookings** add a **₹200 service fee** as a separate OMS order line — it is *not* part of the catalog package price, and it is waived for subscription-pack holders. See [instant.md](instant.md).

## How a one-time spa price is resolved

```text
model_id → model_tier_mapping → tier (T1–T9)
         → plan_item_tier_pricing for plan_id + SERVICE rows
         → API returns the plan’s tier price (source of truth = DB + controllers)
```

## Tiers

| tier_id | Code | Example |
|---------|------|---------|
| 4 | T1 | Datsun GO |
| 5 | T2 | VW Polo |
| 6 | T3 | Ford Aspire |
| 7 | T4 | Hyundai Creta |
| 8 | T5 | Maruti Kizashi |
| 9 | T6 | Mahindra XEV 9e |
| 10 | T7 | Hyundai IONIQ 6 |
| 11 | T8 | BMW X4 |
| 12 | T9 | Nissan GT-R |

## Row shape (`plan_item_tier_pricing`)

| Field | Meaning |
|-------|---------|
| `plan_id` | 1 Premium / 2 Basic / 3 Exterior |
| `entity_type` | `SERVICE` (ADDON rows exist but product-disabled) |
| `entity_id` | `plan_services.id` |
| `tier_id` | `tier.id` |
| `price` | Component original / MRP |
| `discounted_price` | Component sell unit |
| `upload_priority` / `min_images_required` | Cleaner media rules |

## Observed amount patterns

Booking `order_amount` decodes cleanly, which is useful when reading raw data:

| Pattern | Meaning |
|---------|---------|
| Round tier price (379 / 399 / 459 / 499 / 589 / 702 / 869 / 959 / 1021) | Normal single booking |
| ~50% of that (200 / 230 / 250 / 295 / 351) | 50% promo or refer-and-earn cashback booking |
| **4 ×** round price | Retired **4+1** multipack purchase |
| **5 ×** round price | Live **5+1** multipack purchase |
| **0** | Multipack redemption |

## Worked example (Premium / T1 / tier_id 4)

Illustrative sum from component selling prices (names from [service-catalog.md](service-catalog.md)):

| item_id | Service | Selling (₹) |
|---------|---------|-------------|
| 1 | Foam Wash | 77 |
| 2 | Tyre Cleaning & Polish | 39 |
| 3 | Tyre Polish | 41 |
| 4 | Exterior Wax | 124 |
| 5 | Glass Cleaning | 39 |
| 6 | Vacuum Cleaning | 15 |
| 7 | Dashboard & Interior Wipe | 16 |
| 8 | Seat Cleaning | 19 |
| 9 | Dashboard Interior Polish & Wipe | 22 |
| 10 | Cladding Cleaning & Polish | 26 |
| 11 | Interior Deep Cleaning | 18 |
| **Sum** | | **436** |

GST component at 18% inclusive ≈ `436 × 18/118` ≈ **₹66.5** (illustrative; checkout may round).

## Foam Wash component by tier (illustrative)

| Tier | Foam Wash discounted |
|------|----------------------|
| T1–T9 | 77, 81, 93, 102, 120, 143, 177, 195, 208 |

## Multipack / subscription pricing

See [subscriptions.md](subscriptions.md):

- **5 ×** Premium for last booking car’s tier (or **T5** if none) → **6** any-plan / any-tier redemptions / 1 year. SKU `full_spa_premium_6_multipack`.
- Recompute pack price as 5 × the tier price (e.g. Creta T4 Premium ≈ ₹576 → pack ≈ **₹2,880**). The older ~₹2,000 / ₹2,304 shorthand was the retired 4+1 pack.
- The retired **4+1** pack still prices and redeems on its original 4× terms for anyone who bought one.
- Unused washes expire — **no refund**.

## Engineering

- Tier resolve + cart: `apps/car_care/controllers` + `db_manager/tier_catalog_helper.go`
- Model: `models.PlanItemTierPricing`

## Related

- [plans.md](plans.md) · [service-catalog.md](service-catalog.md) · [subscriptions.md](subscriptions.md) · [instant.md](instant.md) · [../GLOSSARY.md](../GLOSSARY.md)
