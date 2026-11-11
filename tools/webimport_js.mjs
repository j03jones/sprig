// Companion to tests/test_webimport.py: prints what web/js/webimport.js makes of a schema.org Recipe (JSON on stdin).
import { readFileSync } from 'node:fs';
import { recipeFromSchema } from '../web/js/webimport.js';
import { formatIngredient, formatYield } from '../web/js/units.js';

const { node, url, site } = JSON.parse(readFileSync(0, 'utf8'));
const r = recipeFromSchema(node, url, site);
process.stdout.write(JSON.stringify({
  title: r.title, ings: r.ings.map(formatIngredient), dir: r.dir, yield: formatYield(r),
  tags: r.tags, author: r.src.author, site: r.src.name, url: r.src.url, vegan: r.categories.includes('Vegetarian & Vegan'),
}));
