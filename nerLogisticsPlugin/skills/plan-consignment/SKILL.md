---
name: plan-consignment
description: Plan and explain freight movements across India's North Eastern Region using the NER Smart Logistics engine. Use whenever someone asks how to move goods, cargo, relief supplies, medicine or a consignment between places in Assam, Arunachal Pradesh, Manipur, Meghalaya, Mizoram, Nagaland, Sikkim, Tripura or the Siliguri corridor; asks which roads or corridors are open, blocked, risky or accessible; asks where to drop off or collect a parcel in the region; or reports a landslide, flood, washout or road blockage there. Also use for questions about NER logistics feasibility, ETAs, freight cost or disaster-affected supply routes.
---

# Planning a consignment in the North East

Route across this region using the `ner-logistics` tools rather than general road knowledge.
The terrain makes intuition unreliable: two towns 60 km apart can be a two-hour drive or
unreachable depending on one landslide, and the engine holds live corridor state that no
amount of background knowledge substitutes for.

## The normal sequence

1. **Turn place names into ids.** `plan_route` takes location ids (`LOC002`), not names. Run
   `search_places` on whatever the user said. Results marked *routable corridor node* can be
   used directly; anything marked *off-network* is a real place the road graph does not reach,
   so call `nearby_handover_points` on its coordinates and use the nearest node it returns.

2. **Choose the cargo profile deliberately.** `cargo_type` and `urgency` are not labels — they
   reweight the five objectives and genuinely change which corridor is chosen. Relief and
   medicine weight risk and reliability; perishables weight time; construction weights cost.
   If the user's intent is clear, set it. If not, ask rather than defaulting to `general`,
   because a wrong profile produces a confident answer to the wrong question.

3. **Pass the real weight.** `weight_kg` sizes the fleet and steps the cost as vehicle
   capacity is crossed. A 9,500 kg consignment can cost markedly more than 9,000 kg because
   it needs a second vehicle. Do not leave it at the default when the user has told you.

4. **Give them somewhere to actually go.** A route between two towns is not yet actionable.
   Call `nearby_handover_points` at the origin and destination so the answer ends with a
   counter, a distance and a phone number.

## Reading the results honestly

- **Accessibility is 0–100, higher is better.** The *worst link* matters more than the
  average: a route is only as passable as its weakest stretch, which is exactly how the
  engine scores it.
- **Disruption risk is a predicted probability, not an observation.** It comes from a model
  trained on synthetic data. Never present it as a forecast from IMD, GSI, CWC, NDMA or any
  state agency.
- **An alternative that is faster and cheaper is not automatically better.** It usually
  carries a worse weakest link. Say which trade-off the recommendation is making — the
  `explanation.reasons` on each route are there to be quoted, not summarised away.
- **No route returned means the graph is genuinely disconnected** under current conditions,
  not that the tool failed. Report which corridors were excluded and why.

## Reporting a blockage

When someone describes an obstruction they have seen, offer `report_incident`. Be accurate
about what it does: the report raises the corridor's risk immediately, and **never closes a
road on its own**. Closure requires two different human verifiers to agree, and severity 5
means "impassable" — do not inflate it to make a report seem more urgent.

Never claim a report has closed a road, and never state or imply that a road is open or
closed on your own judgement. Report what the engine returns.

## Standing caveat

The road network is sample data with real town names and real corridor names, and the risk
figures are model estimates from synthetic training data. Every answer that carries a number
from this engine should make that clear once, plainly, without burying it. Someone may be
deciding whether to send a truck.
