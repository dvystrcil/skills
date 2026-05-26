---
name: "Recipe Units"
description: "Translate recipe ingredient lines (2 tsp X, 1 cup Y) into the right grocery-unit cart entries (1 bottle, 1 bag) and suppress pantry staples the household likely already has."
tags: ["recipe", "grocery", "units", "pantry", "meal-time", "kroger"]
scope: "always"
---

# Recipe Units

When the model is asked to turn one or more recipes into a Kroger cart, it must do two translations the LLM otherwise gets wrong:

1. **Recipe-unit → grocery-unit.** A recipe asking for `2 teaspoons vanilla extract` is consuming a fraction of one bottle. The cart entry is `vanilla extract: 1` (one bottle), not `vanilla extract: 2`. Treating recipe-units as count-units leads to absurd orders.
2. **Pantry-staple suppression.** Salt, pepper, baking soda, etc. are basically free and replaced once a year. Don't put them on the cart for every recipe.

## Pantry staples — assume in stock unless user says otherwise

These are **never** added to the cart by default. If a recipe calls for any of these, omit it. Treat as available.

- salt
- black pepper
- white pepper
- garlic powder
- onion powder
- baking soda
- baking powder
- granulated sugar (for amounts < 1 cup)
- brown sugar (for amounts < 1 cup)
- all-purpose flour (for amounts < 1 cup)
- vegetable oil
- olive oil
- canola oil
- white vinegar
- soy sauce
- ground cinnamon
- dried oregano
- dried basil
- dried thyme
- bay leaves
- cornstarch
- water

**User override:** if the user says "I'm out of salt" or "add baking powder to the list", honor it — they know their pantry better than this list.

## Recipe-unit → grocery-unit translation

| Recipe unit | Grocery-unit rule |
|---|---|
| `1 tsp`, `2 tsp`, ..., `1 tbsp`, `2 tbsp` of a spice / extract / oil / sauce | **1 of the smallest sold container** (bottle, jar). If the ingredient is on the pantry list, skip entirely. |
| `1 cup`, `2 cups` of flour / sugar / oats / rice / dry pasta | **1 standard bag/box** (1-2 lb). Recipe will consume a fraction. If under 1 cup of a pantry staple, skip. |
| `1 cup`, `2 cups` of broth / stock / milk / juice | **1 standard container** (1 quart broth, 1 half-gallon milk, etc.) |
| `1 lb` / `8 oz` / `12 oz` of meat / cheese / fresh produce | **direct mapping** — recipe-unit IS grocery-unit. Buy `1 lb ground beef` to fulfill a `1 lb ground beef` ingredient. |
| `1 onion`, `2 carrots`, `3 cloves garlic` | **count-match or 1 bag/bunch.** Single onion → buy 1. 3 cloves garlic → buy 1 head (which has ~10 cloves). |
| `1 can`, `1 jar`, `1 box`, `1 package` | **direct mapping.** Recipe already uses grocery-unit terms. |
| `to taste`, `for garnish`, `optional` | **skip.** These are pantry-or-omittable. |

## Aggregation across multiple recipes

If two recipes both call for ground beef, add the weights and round up to nearest standard package size. Same rule for any direct-mapping item.

Out of scope for v1: smart fractional aggregation (½ cup + ¾ cup of butter across two recipes should still buy 1 standard package, not 2).

## Worked examples

### Example 1 — Chocolate chip cookies

Recipe asks for:

- 2¼ cups all-purpose flour
- 1 tsp baking soda
- 1 tsp salt
- 1 cup butter
- ¾ cup granulated sugar
- ¾ cup brown sugar
- 2 large eggs
- 2 tsp vanilla extract
- 2 cups chocolate chips

Cart:

- 1 bag all-purpose flour *(only because 2¼ cups exceeds the < 1 cup pantry threshold)*
- 1 (skip — baking soda is pantry)
- 1 (skip — salt is pantry)
- 1 lb butter
- 1 (skip — < 1 cup granulated sugar is pantry)
- 1 (skip — < 1 cup brown sugar is pantry)
- 1 dozen large eggs
- 1 bottle vanilla extract
- 1 bag chocolate chips

**5 items, not 9.**

### Example 2 — Spaghetti bolognese

Recipe asks for:

- 1 lb ground beef
- 1 large onion
- 2 cloves garlic
- 1 (28 oz) can crushed tomatoes
- 1 tbsp tomato paste
- 1 tsp dried oregano
- ½ tsp red pepper flakes
- Salt and pepper to taste
- 1 lb dry spaghetti
- ¼ cup olive oil

Cart:

- 1 lb ground beef
- 1 yellow onion
- 1 head garlic *(2 cloves → 1 head; head has ~10 cloves)*
- 1 (28 oz) can crushed tomatoes
- 1 tube/can tomato paste
- 1 (skip — dried oregano is pantry)
- 1 jar red pepper flakes *(not on pantry list)*
- 1, 1 (skip — salt + pepper are pantry)
- 1 lb dry spaghetti
- 1 (skip — olive oil is pantry; ¼ cup is a fraction of a bottle)

**6 items.**

### Example 3 — Chili (one-pot)

Recipe asks for:

- 1 lb ground beef
- 1 large onion
- 1 green bell pepper
- 3 cloves garlic
- 1 (15 oz) can kidney beans, drained
- 1 (15 oz) can black beans, drained
- 1 (28 oz) can crushed tomatoes
- 2 tbsp chili powder
- 1 tsp ground cumin
- 1 tsp paprika
- Salt and pepper to taste
- Shredded cheddar for garnish

Cart:

- 1 lb ground beef
- 1 yellow onion
- 1 green bell pepper
- 1 head garlic
- 1 (15 oz) can kidney beans
- 1 (15 oz) can black beans
- 1 (28 oz) can crushed tomatoes
- 1 bottle chili powder *(2 tbsp is small; just buy the bottle)*
- 1 bottle ground cumin
- 1 bottle paprika
- 1, 1 (skip — salt + pepper)
- 1 (skip — "for garnish" → optional)

**10 items.**

## When NOT to use this skill

- The user has explicitly said "buy literal quantities" — they want the conversion bypassed.
- The user is shopping for a stocking-up trip, not a per-recipe trip. Use a different prompt for that.
- The user is shopping for a restaurant / catering / large-batch scenario where standard pantry-staple amounts don't cover the recipe.

## Operational notes

- Pantry list and translation table are intentionally short. They cover the 80% case for a typical home kitchen. If a recipe routinely hits the gaps, file a homelab issue with the failing recipe + the suggested rule.
- This skill **assists** the LLM's reasoning; it doesn't replace the model's judgment. If a recipe says "1 cup salt", the model should ask the user "are you sure?" rather than blindly buying a 26 oz canister.
