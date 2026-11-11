// Companion to parity_check.py: prints JS output for every recipe/factor as JSON.
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { Frac, formatIngredient, formatYield, recipeToText, scaleRecipe } from '../web/js/units.js';
import { fromRow } from '../web/js/model.js';

const here = dirname(fileURLToPath(import.meta.url));
const data = JSON.parse(readFileSync(join(here, '..', 'web', 'data', 'recipes.json'), 'utf8'));
const FACTORS = ['1/2', '2', '3/2', '3', '1/3', '4', '5/4', '7/3'];
const out = {};
for (const row of data.recipes) {
  const r = fromRow(row);
  out[`${r.id}|text`] = recipeToText(r);
  for (const f of FACTORS) {
    for (const smart of [true, false]) {
      const s = scaleRecipe(r, Frac.parse(f), smart);
      out[`${r.id}|${f}|${+smart}`] = [formatYield(s.recipe), ...s.recipe.ings.map(formatIngredient), ...s.warnings].join('\n');
    }
  }
}
process.stdout.write(JSON.stringify(out));
