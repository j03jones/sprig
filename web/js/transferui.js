// The "Import and export" page. The file reading and writing is in transfer.js; this shows it.
import { creditLine, formatIngredient, formatYield } from './units.js';
import { fileNameFor, importFile, toMarkdown, toPaprika, toSchemaJson } from './transfer.js';

const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`;

function download(h, blob, name) {
  const a = h('a', { href: URL.createObjectURL(blob), download: name });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}

/**
 * h, fill, toast: the app's helpers. add(recipes) saves them and resolves to how many were saved.
 * mine() and starred() return recipes in the working shape for export.
 */
export function transferPage({ h, fill, toast, add, mine, starred, signedIn }) {
  const root = h('div', { class: 'transfer stack' });
  let found = [];                       // [{ r, on }]
  const files = h('input', { type: 'file', multiple: true, hidden: true,
    accept: '.paprikarecipes,.zip,.json,.jsonld,.cook,.html,.htm,.txt,.md,text/plain,application/json,application/zip' });
  const paste = h('textarea', { class: 'full', rows: 6, placeholder: 'Or paste a recipe here: the title on the first line, then Ingredients and Directions.', 'aria-label': 'Paste a recipe' });
  const status = h('p', { class: 'muted small', role: 'status' });
  const found$ = h('div', { class: 'stack' });

  function showFound() {
    if (!found.length) { fill(found$); return; }
    const chosen = () => found.filter((f) => f.on);
    const go = h('button', { class: 'primary', type: 'button', onclick: async () => {
      const recs = chosen().map((f) => f.r);
      if (!recs.length) return;
      go.disabled = true;
      try {
        const n = await add(recs);
        toast(`Added ${plural(n, 'recipe')}`);
        found = []; status.textContent = `Added ${plural(n, 'recipe')} to your recipes.`; showFound();
      } catch (err) { status.textContent = `Stopped: ${err.message}`; go.disabled = false; }
    } });
    const label = () => { go.textContent = `Add ${plural(chosen().length, 'recipe')}`; go.disabled = !chosen().length; };
    fill(found$,
      h('p', { class: 'muted small' }, `Found ${plural(found.length, 'recipe')}. Untick any you do not want. They go into your own recipes${signedIn ? ', saved to your account' : ' on this device'}.`),
      go,
      h('ul', { class: 'costlines foundlist' }, found.map((f) => {
        const box = h('input', { type: 'checkbox', checked: true, 'aria-label': `Add ${f.r.title}` });
        box.addEventListener('change', () => { f.on = box.checked; label(); });
        return h('li', { class: 'costline' }, h('label', { class: 'cl-what' }, box, ' ', h('strong', null, f.r.title),
          h('span', { class: 'muted small' }, ` ${plural(f.r.ings.length, 'ingredient')}`)));
      })));
    label();
  }

  async function readFiles(list) {
    const got = []; const notes = [];
    for (const f of list) {
      try {
        const res = await importFile(f.name, new Uint8Array(await f.arrayBuffer()));
        got.push(...res.recipes);
        notes.push(`${f.name}: ${plural(res.recipes.length, 'recipe')} (${res.kind})${res.skipped ? `, ${res.skipped} skipped` : ''}`);
      } catch (err) { notes.push(`${f.name}: ${err.message}`); }
    }
    found = got.map((r) => ({ r, on: true }));
    status.textContent = notes.join('. ');
    showFound();
  }
  files.addEventListener('change', async () => { const l = [...files.files]; files.value = ''; if (l.length) await readFiles(l); });
  const readPaste = h('button', { type: 'button', onclick: async () => {
    const t = paste.value.trim();
    if (!t) { paste.focus(); return; }
    await readFiles([new File([t], 'pasted.txt', { type: 'text/plain' })]);
    if (found.length) paste.value = '';
  } }, 'Read pasted text');

  // ---- going out
  const which = h('select', { 'aria-label': 'Which recipes' },
    h('option', { value: 'mine' }, 'My recipes (added, imported or edited)'),
    h('option', { value: 'starred' }, 'Starred recipes'));
  const pick = () => (which.value === 'starred' ? starred() : mine());
  const out = (fn) => async () => {
    const recs = pick();
    if (!recs.length) { toast('No recipes in that set yet'); return; }
    try { await fn(recs); } catch (err) { toast(`Could not export: ${err.message}`); }
  };
  const bookBtn = h('button', { type: 'button', onclick: out((recs) => printBook(h, recs)) }, 'Print as a book (PDF)');

  fill(root,
    h('section', { class: 'card stack' },
      h('h2', null, 'Bring recipes in'),
      h('p', { class: 'muted' }, 'Choose a file you exported from Paprika (.paprikarecipes), Mealie or Tandoor (.json or .zip), a Cooklang file (.cook), a saved web page, or any text file. You see what was found before anything is added.'),
      h('div', { class: 'row grow' }, h('button', { class: 'primary', type: 'button', onclick: () => files.click() }, 'Choose files'), files),
      paste, h('div', { class: 'row grow' }, readPaste),
      status, found$),
    h('section', { class: 'card stack' },
      h('h2', null, 'Take recipes out'),
      h('p', { class: 'muted' }, 'Your recipes are yours. Download them in a format other apps read, or print a book. Built-in library recipes are not included.'),
      h('label', { class: 'field' }, h('span', null, 'Which recipes'), which),
      h('div', { class: 'row grow' },
        h('button', { type: 'button', onclick: out(async (r) => download(h, new Blob([await toPaprika(r)], { type: 'application/zip' }), fileNameFor('recipes', 'paprikarecipes'))) }, 'Paprika file'),
        h('button', { type: 'button', onclick: out((r) => download(h, new Blob([toSchemaJson(r)], { type: 'application/json' }), fileNameFor('recipes', 'json'))) }, 'JSON (schema.org)'),
        h('button', { type: 'button', onclick: out((r) => download(h, new Blob([toMarkdown(r)], { type: 'text/markdown' }), fileNameFor('recipes', 'md'))) }, 'Markdown'),
        bookBtn),
      h('p', { class: 'muted small' }, 'JSON with schema.org recipe data opens in Mealie, Tandoor and most recipe tools. For a full copy of everything for this app, use Export backup in Settings.')));
  return root;
}

/** A printable book of recipes: drawn into the page, the print dialog is opened, then it is removed. */
export function printBook(h, recipes) {
  const sorted = [...recipes].sort((a, b) => a.title.localeCompare(b.title, undefined, { sensitivity: 'base' }));
  const book = h('div', { class: 'printbook', 'aria-hidden': 'true' },
    h('section', { class: 'bookcover' }, h('h1', null, 'Recipes'), h('p', null, plural(sorted.length, 'recipe'))),
    h('section', { class: 'bookindex' }, h('h2', null, 'Contents'), h('ol', null, sorted.map((r) => h('li', null, r.title)))),
    sorted.map((r) => {
      const credit = creditLine(r);
      let group = null;
      return h('section', { class: 'bookrecipe' },
        h('h2', null, r.title),
        h('p', { class: 'bookmeta' }, [formatYield(r) && `Yield: ${formatYield(r)}`, r.categories?.length && r.categories.join(', '), credit].filter(Boolean).join('  ·  ')),
        h('ul', null, r.ings.map((i) => {
          const head = i.group && i.group !== group ? h('li', { class: 'bookgroup' }, i.group) : null;
          group = i.group;
          return [head, h('li', null, formatIngredient(i))];
        })),
        h('ol', null, String(r.dir || '').split(/\r?\n/).map((s) => s.trim()).filter(Boolean).map((s) => h('li', null, s))));
    }));
  document.body.append(book);
  document.body.classList.add('bookprinting');
  const done = () => { book.remove(); document.body.classList.remove('bookprinting'); window.removeEventListener('afterprint', done); };
  window.addEventListener('afterprint', done);
  setTimeout(() => { window.print(); if (!/Android|iPhone|iPad/i.test(navigator.userAgent)) setTimeout(done, 400); }, 50);
}
