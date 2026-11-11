// Companion to tests/test_js_twins.py: runs web/js conversion, range scaling and shopping-list code
// on recipes given as JSON on stdin (the compact row shape of data/recipes.json) and prints the results.
import { readFileSync } from 'node:fs';
import { Frac, convertRecipe, formatIngredient, scaleRecipe } from '../web/js/units.js';
import { fromRow } from '../web/js/model.js';
import { aisleFor, combine, shoppingList, toText, toTextByAisle } from '../web/js/shopping.js';
import * as planner from '../web/js/planner.js';
import * as pantry from '../web/js/pantry.js';
import * as collections from '../web/js/collections.js';
import * as cooklog from '../web/js/cooklog.js';

const { rows, factors, picks, names = [], plan = null, have = null, colls = null, log = null } = JSON.parse(readFileSync(0, 'utf8'));
const recipes = rows.map(fromRow);
const out = { convert: {}, scale: {}, shop: [] };
for (const r of recipes) {
  for (const system of ['metric', 'us']) out.convert[`${r.id}|${system}`] = convertRecipe(r, system).ings.map(formatIngredient);
  for (const f of factors) out.scale[`${r.id}|${f}`] = scaleRecipe(r, Frac.parse(f)).recipe.ings.map(formatIngredient);
}
out.shop.push(toText(combine(recipes)));
out.shop.push(toText(shoppingList(picks.map(([n, f]) => [recipes[n], Frac.parse(f)]))));
out.shop.push(toTextByAisle(combine(recipes)));
out.aisles = names.map(aisleFor);
if (plan) {
  // meal-plan storage rules (no browser needed: clean/merge/recipesOn are pure)
  const cleaned = planner.clean(plan.raw, plan.today);
  out.plan = {
    cleaned,
    week: planner.weekDates(planner.weekStart(plan.today)),
    recipes: planner.recipesOn(cleaned, planner.weekDates(planner.weekStart(plan.today))).map(([id, f]) => [id, String(f)]),
    merged: planner.merge(cleaned, plan.other),
  };
}
if (have) {
  out.pantry = have.map(([list, maxMissing, assumeStaples]) =>
    pantry.match(recipes, list, { maxMissing, assumeStaples }).map((m) => [m.recipe.id, m.missing, m.used]));
}
if (colls) out.colls = { cleaned: collections.clean(colls.raw), merged: collections.merge(colls.raw, colls.other) };
if (log) {
  const cleaned = cooklog.clean(log.raw);
  out.log = { cleaned, merged: cooklog.merge(log.raw, log.other), recent: cooklog.recent(cleaned).map(([id]) => id),
    summary: cooklog.summary(cleaned.a) };
}
process.stdout.write(JSON.stringify(out));
