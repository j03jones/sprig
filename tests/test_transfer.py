"""Import and export formats: Paprika, Mealie, Tandoor, Cooklang, schema.org, pasted text (the web app's JS, run in Node)."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SCRIPT = r"""
import { importFile, toPaprika, toSchemaJson, toMarkdown, fromCooklang, fromPlainText, writeZip, readZip, crc32 } from './web/js/transfer.js';
import { formatIngredient, formatYield } from './web/js/units.js';
const bytes = (o) => new TextEncoder().encode(typeof o === 'string' ? o : JSON.stringify(o));
const shape = (r) => ({ title: r.title, yield: formatYield(r), ings: r.ings.map((i) => (i.group ? `${i.group}: ` : '') + formatIngredient(i)),
  steps: r.dir ? r.dir.split('\n').length : 0, cats: r.categories, tags: r.tags, src: r.src });
const out = {};

const ck = fromCooklang(`>> servings: 4\n>> tags: dinner, quick\n-- a comment\nCrack @eggs{3} into a #bowl{} and add @milk{1%cup}. Cook ~{5%minutes}.\n\nAdd @salt and @flour{2%cups}.\n[- block comment -]`, 'my-eggs.cook');
out.cook = shape(ck); out.cookDir = ck.dir;
const txt = fromPlainText(`Banana Bread\nServes 8\nIngredients\n2 cups flour\n3 ripe bananas\nTopping:\n1/4 cup sugar\nDirections\n1. Mix.\n2. Bake 50 minutes.`);
out.text = shape(txt);
const loose = fromPlainText(`Toast\n2 slices bread\n1 tbsp butter\nToast the bread and butter it.`);
out.loose = shape(loose);

const pk = await toPaprika([ck, txt]);
const back = await importFile('x.paprikarecipes', pk);
out.paprika = { kind: back.kind, titles: back.recipes.map((r) => r.title), ings: back.recipes.map((r) => shape(r).ings) };
const names = readZip(pk).map((e) => e.name);
out.paprikaNames = names;
out.zipCrc = readZip(writeZip([{ name: 'a.txt', data: bytes('hello') }])).length;
out.crc = crc32(bytes('123456789'));

const sj = await importFile('a.json', bytes(toSchemaJson([ck, txt])));
out.schema = { kind: sj.kind, n: sj.recipes.length, ings: sj.recipes.map((r) => shape(r).ings) };
out.md = toMarkdown([txt]);

const mealie = { name: 'Soup', recipeYield: '4 servings', recipeIngredient: [{ quantity: 2, unit: { name: 'cup' }, food: { name: 'broth' }, note: '' }, { originalText: '1 onion, diced' }],
  recipeInstructions: [{ text: 'Boil.' }, { text: 'Serve.' }], tags: [{ name: 'easy' }], recipeCategory: [{ name: 'Soup' }], orgURL: 'https://x.com/soup' };
out.mealie = shape((await importFile('m.json', bytes(mealie))).recipes[0]);
const tandoor = { name: 'Pie', servings: 6, steps: [{ name: 'Crust', instruction: 'Roll.', ingredients: [{ amount: 2, unit: { name: 'cup' }, food: { name: 'flour' } }] },
  { name: 'Filling', instruction: 'Fill.\nBake.', ingredients: [{ amount: 3, unit: null, food: { name: 'apples' }, note: 'sliced' }] }], keywords: [{ name: 'dessert' }] };
out.tandoor = shape((await importFile('recipe.json', bytes(tandoor))).recipes[0]);
const nested = writeZip([{ name: 'Pie.zip', data: writeZip([{ name: 'recipe.json', data: bytes(tandoor) }]) }]);
const nz = await importFile('export.zip', nested);
out.nested = { kind: nz.kind, titles: nz.recipes.map((r) => r.title) };
const html = '<html><script type="application/ld+json">{"@graph":[{"@type":"Recipe","name":"Toast","recipeIngredient":["2 slices bread"],"recipeInstructions":"Toast it."}]}</script></html>';
out.html = shape((await importFile('p.html', bytes(html))).recipes[0]);
const errs = {};
for (const [k, n, b] of [['empty', 'e.txt', bytes('')], ['backup', 'b.json', bytes({ app: 'recipelib', records: [] })], ['badzip', 'z.zip', new Uint8Array([0x50, 0x4b, 3, 4, 1, 2, 3])]]) {
  try { await importFile(n, b); errs[k] = 'no error'; } catch (e) { errs[k] = e.message; }
}
out.errs = errs;
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class TransferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        run = subprocess.run(["node", "--input-type=module", "-e", SCRIPT], cwd=ROOT, capture_output=True, text=True, timeout=60)
        if run.returncode:
            raise RuntimeError(run.stderr)
        cls.o = json.loads(run.stdout)

    def test_cooklang(self):
        c = self.o["cook"]
        self.assertEqual(c["title"], "my eggs")
        self.assertEqual(c["yield"], "4 servings")
        self.assertEqual(c["ings"], ["3 eggs", "1 cup milk", "salt", "2 cups flour"])
        self.assertEqual(c["steps"], 2)
        self.assertEqual(c["tags"], ["dinner", "quick"])
        self.assertNotIn("@", self.o["cookDir"])
        self.assertIn("bowl", self.o["cookDir"])
        self.assertIn("5 minutes", self.o["cookDir"])

    def test_plain_text(self):
        t = self.o["text"]
        self.assertEqual((t["title"], t["yield"]), ("Banana Bread", "8 servings"))
        self.assertEqual(t["ings"], ["2 cups flour", "3 ripe bananas", "Topping: 1/4 cup sugar"])
        self.assertEqual(t["steps"], 2)
        self.assertEqual(self.o["loose"]["ings"], ["2 slices bread", "1 Tbsp butter"])
        self.assertEqual(self.o["loose"]["steps"], 1)

    def test_paprika_round_trip(self):
        p = self.o["paprika"]
        self.assertEqual(p["kind"], "Paprika")
        self.assertEqual(p["titles"], ["my eggs", "Banana Bread"])
        self.assertEqual(p["ings"][1], ["2 cups flour", "3 ripe bananas", "Topping: 1/4 cup sugar"])
        self.assertTrue(all(n.endswith(".paprikarecipe") for n in self.o["paprikaNames"]))

    def test_zip_and_crc(self):
        self.assertEqual(self.o["zipCrc"], 1)
        self.assertEqual(self.o["crc"], 0xCBF43926)

    def test_schema_org_round_trip_and_markdown(self):
        self.assertEqual(self.o["schema"]["n"], 2)
        self.assertEqual(self.o["schema"]["ings"][1], ["2 cups flour", "3 ripe bananas", "1/4 cup sugar"])
        self.assertIn("## Ingredients", self.o["md"])
        self.assertIn("1. Mix.", self.o["md"])
        self.assertEqual(self.o["html"]["ings"], ["2 slices bread"])

    def test_mealie_and_tandoor(self):
        m = self.o["mealie"]
        self.assertEqual(m["ings"], ["2 cups broth", "1 onion, diced"])
        self.assertEqual((m["yield"], m["cats"], m["tags"]), ("4 servings", ["Soup"], ["easy"]))
        self.assertEqual(m["src"]["url"], "https://x.com/soup")
        t = self.o["tandoor"]
        self.assertEqual(t["ings"], ["Crust: 2 cups flour", "Filling: 3 apples, sliced"])
        self.assertEqual((t["steps"], t["yield"], t["tags"]), (3, "6 servings", ["dessert"]))
        self.assertEqual(self.o["nested"], {"kind": "Tandoor", "titles": ["Pie"]})

    def test_problems_are_explained(self):
        e = self.o["errs"]
        self.assertIn("No recipe", e["empty"])
        self.assertIn("backup", e["backup"])
        self.assertNotEqual(e["badzip"], "no error")


if __name__ == "__main__":
    unittest.main()
