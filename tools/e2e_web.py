"""End-to-end check of the phone web app in a real (headless) browser, including offline use.

    python tools/e2e_web.py [screenshot_dir]

Needs Playwright with Chromium. Serves web/ itself on a free port. Expects the real recipe data
(web/data/recipes.json built by tools/export_web.py) because it looks recipes up by name.
"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime
import time
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent.parent
SHOTS = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp())
SHOTS.mkdir(parents=True, exist_ok=True)
PORT = 8791
URL = f"http://127.0.0.1:{PORT}/"
errors, results = [], []
# how many recipes the app should show: the built-in set, plus the on-demand set once its index has loaded
CORE = len(json.loads((ROOT / "web" / "data" / "recipes.json").read_text(encoding="utf-8"))["recipes"])
_more = ROOT / "web" / "data" / "more.json"
MORE = json.loads(_more.read_text(encoding="utf-8")) if _more.exists() else {"v": "", "count": 0}
TOTAL = f"{CORE + MORE['count']:,}"


async def whole_library(page):
    """Wait until the list counts every recipe (the on-demand index loads in the background)."""
    await page.wait_for_function(f"document.querySelector('.count')?.innerText.includes('{TOTAL} recipes')", timeout=30000)


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))


async def search(page, text):
    await page.fill("input[type=search]", text)
    await page.wait_for_timeout(400)


async def main():
    server = subprocess.Popen([sys.executable, "-m", "http.server", str(PORT), "--bind", "127.0.0.1", "--directory", str(ROOT / "web")],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    try:
        return await run()
    finally:
        server.terminate()


async def run():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        if os.environ.get("E2E_NOW"):
            # run as if it were this date (YYYY-MM-DDTHH:MM): the plan and list depend on today's weekday
            real_new_context = b.new_context

            async def new_context(*args, **kwargs):
                c = await real_new_context(*args, **kwargs)
                await c.clock.install(time=datetime.fromisoformat(os.environ["E2E_NOW"]))
                return c
            b.new_context = new_context
        ctx = await b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2,
                                  is_mobile=True, has_touch=True, accept_downloads=True)
        page = await ctx.new_page()
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))

        await page.goto(URL)
        await page.wait_for_selector(".rc")
        await whole_library(page)
        check("library loads with all recipes", f"{TOTAL} recipes" in await page.inner_text(".count"), await page.inner_text(".count"))
        check("rows do not overflow the screen", await page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
        await page.wait_for_function("navigator.serviceWorker.controller !== null", timeout=30000)
        cached = await page.evaluate("caches.keys().then(async ks => { const c = await caches.open(ks.find(k => !['sprig-fonts', 'sprig-more'].includes(k))); return (await c.keys()).length })")
        check("service worker cached app, fonts and data", cached >= 17, cached)
        check("heading font loaded", await page.evaluate("document.fonts.check('700 20px Poppins')"))

        # category chips: section, then group
        await page.click(".chips >> text=Course & type")
        names = await page.locator(".chips.groups .chip").count()
        check("section chip reveals its groups", names >= 8, names)
        await page.click(".chips.groups >> text=Soups & Stews")
        await page.wait_for_timeout(300)
        soups = await page.inner_text(".count")
        check("filter by a group", f" of {TOTAL}" in soups and not soups.startswith(TOTAL), soups)
        await page.click(".chips.groups >> text=Soups & Stews")  # tap again to clear
        await page.wait_for_timeout(300)
        check("tapping the group again clears it", f"{TOTAL} recipes" in await page.inner_text(".count"))
        await page.click(".chips >> text=All")
        await search(page, "penndutch")
        check("old label still searchable", f"of {TOTAL}" in await page.inner_text(".count"), await page.inner_text(".count"))
        await search(page, "zzzzqq")
        check("empty state offers a way out", await page.locator(".empty button:has-text('Clear search and filters')").count() == 1)
        await page.click(".empty button")
        await page.wait_for_timeout(300)
        check("clearing restores the library", f"{TOTAL} recipes" in await page.inner_text(".count"))
        await search(page, "garlic mushroom")
        check("search narrows results", f"of {TOTAL}" in await page.inner_text(".count"))

        # open a known recipe, tick things off, scale it
        await search(page, "Hearty Russian Beet Soup")
        await page.click(".rc >> nth=0")
        await page.wait_for_selector(".dock")
        check("recipe shows labels and original tags", "Original labels:" in await page.inner_text("#app") and await page.locator(".label:has-text('Soups')").count() == 1)
        check("tab bar hidden on recipe, dock shown", not await page.locator("#tabs").is_visible() and await page.locator(".dock").is_visible())
        check("directions become numbered steps", await page.locator("ol.steps li").count() >= 2)
        await page.click("ul.ing .tick >> nth=0")
        await page.click("ol.steps .tick >> nth=0")
        check("ingredients and steps can be ticked off", await page.locator(".tick[aria-pressed=true]").count() == 2)
        before = await page.inner_text("ul.ing")
        await page.click(".seg button:has-text('2×')")
        after = await page.inner_text("ul.ing")
        check("2x doubles amounts", "2 1/2 lb Lean beef" in before and "5 lb Lean beef" in after, after[:80])
        check("2x chip is highlighted", await page.locator(".seg button:has-text('2×')").get_attribute("aria-pressed") == "true")
        await page.click(".seg button:has-text('1×')")
        await page.fill("input[aria-label='Servings to make']", "12")
        await page.wait_for_timeout(150)
        s12 = await page.inner_text("ul.ing")
        check("servings box scales to 12", "3 3/4 lb Lean beef" in s12 and await page.input_value("input[aria-label='Multiplier']") == "1.5", s12[:60])
        await page.click("button[aria-label='More servings']")
        check("+ steps servings by one", await page.input_value("input[aria-label='Servings to make']") == "13")
        await page.click("button[aria-label='Fewer servings']")
        await page.click("button[aria-label='Fewer servings']")
        check("- steps servings by one", await page.input_value("input[aria-label='Servings to make']") == "11")

        # stars
        await page.click(".topbar .star")
        check("recipe can be starred", await page.locator(".topbar .star").get_attribute("aria-pressed") == "true")
        await page.goto(URL + "#/starred")
        await page.wait_for_selector(".rc")
        check("starred tab lists it", "1 starred" in await page.inner_text(".count"))
        await page.screenshot(path=str(SHOTS / "starred.png"))

        # offline from here on
        await ctx.set_offline(True)
        await page.goto(URL)
        await page.wait_for_selector(".rc", timeout=15000)
        await whole_library(page)      # the on-demand index was saved by the service worker too
        check("loads while offline", f"{TOTAL} recipes" in await page.inner_text(".count"))
        await search(page, "biscotti")
        check("search works offline", (await page.locator(".rc").count()) > 0)

        # add a new recipe
        await page.click("a[data-tab=new]")
        await page.wait_for_selector("input[aria-label=Title]")
        await page.fill("input[aria-label=Title]", "Test Chili")
        await page.fill("input[aria-label=Categories]", "Soups, Test")
        await page.fill("input[aria-label=Yield]", "6 servings")
        r0 = page.locator(".ing-row").first
        await r0.locator("input.amt").fill("1½")
        await r0.locator("input.unit").fill("cups")
        await r0.locator("input.item").fill("Kidney beans")
        await page.click("button:has-text('+ Add ingredient')")
        r1 = page.locator(".ing-row").nth(1)
        await r1.locator("input.amt").fill("2")
        await r1.locator("input.unit").fill("Tbsp")
        await r1.locator("input.item").fill("Chili powder")
        await page.fill("textarea", "Simmer everything.\n\nServe hot.")
        await page.screenshot(path=str(SHOTS / "edit.png"), full_page=True)
        await page.click("button:has-text('Save')")
        await page.wait_for_selector("h1:has-text('Test Chili')")
        body = await page.inner_text("ul.ing")
        check("new recipe saved and normalised", "1 1/2 cups Kidney beans" in body and "2 Tbsp Chili powder" in body, body)
        await page.click(".seg button:has-text('2×')")
        body2 = await page.inner_text("ul.ing")
        check("new recipe scales (smart units)", "3 cups Kidney beans" in body2 and "1/4 cup Chili powder" in body2, body2)

        await page.goto(URL + "#/")
        await page.reload()
        await page.wait_for_selector(".rc")
        await search(page, "Test Chili")
        check("new recipe persists after reload", await page.locator(".rc:has-text('Test Chili')").count() == 1)
        check("new recipe is badged", await page.locator(".badge:has-text('Mine')").count() == 1)
        await page.click(".rows .star")   # star it too, so a star survives the removal test below

        # edit a built-in recipe, then revert
        await search(page, "Hearty Russian Beet Soup")
        await page.click(".rc >> nth=0")
        await page.click("a[aria-label='Edit recipe']")
        await page.wait_for_selector("input[aria-label=Title]")
        await page.fill("input[aria-label=Title]", "Hearty Russian Beet Soup EDITED")
        await page.click("button:has-text('Save')")
        await page.wait_for_selector("h1:has-text('EDITED')")
        await page.click("a[aria-label='Edit recipe']")
        await page.click("button:has-text('Revert to original')")
        await page.click("dialog button:has-text('Revert')")
        await page.wait_for_selector("h1:has-text('Hearty Russian Beet Soup')")
        check("edit then revert restores original", "EDITED" not in await page.inner_text("h1"))

        # remove a built-in recipe, restore it in settings
        await page.click("a[aria-label='Edit recipe']")
        await page.click("button:has-text('Remove from library')")
        await page.click("dialog button:has-text('Remove')")
        await page.wait_for_selector("input[type=search]")
        await search(page, "Hearty Russian Beet Soup")
        check("removed recipe disappears", await page.locator(".rc").count() == 0)
        await page.click("a[data-tab=settings]")
        await page.wait_for_selector("button:has-text('Restore removed')")
        await page.screenshot(path=str(SHOTS / "settings.png"), full_page=True)
        async with page.expect_download() as dl:
            await page.click("button:has-text('Export backup')")
        path = await (await dl.value).path()
        backup = json.load(open(path))
        check("backup contains my changes and stars", backup["app"] == "recipelib" and len(backup["records"]) >= 2 and len(backup.get("stars", [])) == 2,
              (len(backup.get("records", [])), backup.get("stars")))
        await page.click("button:has-text('Restore removed')")
        await page.click("a[data-tab=list]")
        await search(page, "Hearty Russian Beet Soup")
        check("restore brings it back", await page.locator(".rc").count() == 1)

        # import the backup into a fresh browser profile
        ctx2 = await b.new_context(viewport={"width": 390, "height": 844}, accept_downloads=True)
        pg2 = await ctx2.new_page()
        await pg2.goto(URL + "#/settings")
        await pg2.wait_for_selector("button:has-text('Import backup')")
        await pg2.set_input_files("input[type=file]", path)
        await pg2.wait_for_timeout(500)
        await pg2.goto(URL + "#/")
        await pg2.wait_for_selector(".rc")
        await pg2.fill("input[type=search]", "Test Chili")
        await pg2.wait_for_timeout(400)
        check("backup imports into a fresh device", await pg2.locator(".rc:has-text('Test Chili')").count() == 1)
        await pg2.goto(URL + "#/starred")
        await pg2.wait_for_selector(".rc")
        check("stars come back with the backup (removed recipe stays hidden)", "1 starred" in await pg2.inner_text(".count"))

        # ---- website look and the new kitchen features
        await page.goto(URL + "#/")
        await page.wait_for_selector(".band.hero .eyebrow")
        check("home page header has the sprig", await page.locator(".band.hero svg.flourish .stem").count() == 1)
        check("signed-out visitors do not see the source chips", not await page.locator(".chips.src").is_visible())
        bg = await page.evaluate("getComputedStyle(document.querySelector('.band.hero')).backgroundColor")
        check("header uses the leaf wash", bg == "rgb(223, 243, 230)", bg)

        await page.click("a[data-tab=new]")
        await page.wait_for_selector("input[aria-label=Title]")
        await page.fill("input[aria-label=Title]", "Timer Soup")
        r0 = page.locator(".ing-row").first
        await r0.locator("input.amt").fill("2")
        await r0.locator("input.unit").fill("cups")
        await r0.locator("input.item").fill("Stock")
        await page.fill("textarea", "Simmer for 10 minutes.\nChill two hours, then 30 seconds more.\nServe hot.")
        await page.click("button:has-text('Save')")
        await page.wait_for_selector("h1:has-text('Timer Soup')")
        check("steps that mention times get timer buttons", await page.locator(".tchip").count() == 3, str(await page.locator(".tchip").count()))
        await page.click(".tchip >> nth=0")
        await page.wait_for_selector("#timers .timer")
        check("tapping starts a countdown", "10 min" in await page.inner_text("#timers .timer") and ":" in await page.inner_text("#timers .tt"))
        await page.reload()
        await page.wait_for_selector("#timers .timer")
        check("a running timer survives a reload", await page.locator("#timers .timer").count() == 1)
        await page.click("#timers .plus")
        await page.click("#timers .x")
        check("timer can be dismissed", await page.locator("#timers .timer").count() == 0)

        await page.click(".cookbtn")
        await page.wait_for_selector(".cook")
        check("cook mode shows step 1 of 3", "step 1 of 3" in (await page.inner_text(".cook-n")).lower())
        await page.click(".cook-foot .primary")
        check("next step advances", "step 2 of 3" in (await page.inner_text(".cook-n")).lower())
        await page.keyboard.press("ArrowLeft")
        check("arrow keys move back", "step 1 of 3" in (await page.inner_text(".cook-n")).lower())
        await page.click(".cook button[aria-label='Show ingredients']")
        check("ingredients sheet lists the recipe", "Stock" in await page.inner_text(".cook-sheet"))
        await page.keyboard.press("Escape")
        check("Escape closes the sheet first", await page.locator(".cook-sheet").count() == 0 and await page.locator(".cook").count() == 1)
        await page.click(".cook-foot .primary"); await page.click(".cook-foot .primary"); await page.click(".cook-foot .primary")
        await page.wait_for_selector(".confetti", state="attached")
        check("finishing cook mode celebrates and closes", await page.locator(".cook").count() == 0 and "Plated" in await page.inner_text("#toast"))
        await page.click("button.tick >> nth=0")
        await page.click("ol.steps .tick >> nth=0"); await page.click("ol.steps .tick >> nth=1"); await page.click("ol.steps .tick >> nth=2")
        await page.wait_for_selector(".confetti", state="attached")
        check("ticking every step also celebrates", True)

        # a newly published version shows an "Update now" banner
        sw = ROOT / "web" / "sw.js"
        original = sw.read_text()
        try:
            await page.goto(URL + "#/")
            await page.wait_for_selector(".rc")
            sw.write_text(original.replace("const VERSION = 'dev'", "const VERSION = 'e2e-new'"))
            await page.evaluate("navigator.serviceWorker.getRegistration().then(r => r.update())")
            await page.wait_for_selector(".updatebar", timeout=15000)
            check("new version shows an update banner", "Update now" in await page.inner_text(".updatebar"))
        finally:
            sw.write_text(original)

        # ---- meal plan, shopping list, What can I make?, collections and the on-demand library (a fresh device)
        ctx4 = await b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2)
        p4 = await ctx4.new_page()
        p4.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        p4.on("pageerror", lambda e: errors.append(str(e)))
        await p4.goto(URL)
        await p4.wait_for_selector(".rc")
        await whole_library(p4)
        await p4.wait_for_function("navigator.serviceWorker.controller !== null", timeout=30000)

        async def plan_on(day, title):
            await p4.click(f".planday >> nth={day} >> .addday")
            await p4.fill("dialog.pickdialog input[type=search]", title)
            await p4.wait_for_timeout(250)
            await p4.click("dialog.pickdialog .picklist button >> nth=0")
            await p4.wait_for_timeout(200)

        await p4.click("a[data-tab=plan]")
        await p4.wait_for_selector(".planday")
        check("meal plan shows a week", await p4.locator(".planday").count() == 7)
        await plan_on(1, "Hearty Russian Beet Soup")
        await plan_on(3, "Hearty Russian Beet Soup")
        check("a planned recipe is listed on its day", "Beet Soup" in await p4.inner_text(".planday >> nth=1"))
        await p4.click(".planday >> nth=4 >> .addday")
        await p4.fill("dialog.pickdialog input[type=text]", "Leftovers")
        await p4.click("dialog.pickdialog form button")
        check("a note can be planned", "Leftovers" in await p4.inner_text(".planday >> nth=4"))
        check("no dialog is left open", await p4.locator("dialog[open]").count() == 0)
        await p4.screenshot(path=str(SHOTS / "plan.png"))

        await p4.click("button:has-text('Add this week to the shopping list')")
        await p4.wait_for_selector(".shoplist")
        check("the week goes to the shopping list, twice-planned counted twice", "×2" in await p4.inner_text(".shoprecipes"))
        check("the list is grouped by aisle", await p4.locator("h3.aisle").count() >= 3, await p4.locator("h3.aisle").count())
        check("the meal-plan button goes once the list matches", await p4.locator("button:has-text('Add my meal plan')").count() == 0)
        await p4.fill(".addextra input", "Paper towels")
        await p4.press(".addextra input", "Enter")
        check("a typed item is added", await p4.locator(".shoplist li.extra:has-text('Paper towels')").count() == 1)
        before = await p4.inner_text("[role=status]")
        await p4.click(".shoplist .tick >> nth=0")
        after = await p4.inner_text("[role=status]")
        check("ticking counts down", "still to get" in after and before != after, after)
        await p4.reload()
        await p4.wait_for_selector(".shoplist")
        check("the list survives a reload", "×2" in await p4.inner_text(".shoprecipes") and "still to get" in await p4.inner_text("[role=status]"))
        await p4.screenshot(path=str(SHOTS / "shopping.png"))

        await p4.goto(URL + "#/pantry")
        await p4.fill(".addextra input", "beets, cabbage, potatoes, onions, carrots, beef")
        await p4.press(".addextra input", "Enter")
        await p4.wait_for_selector("ul.rows li")
        status = await p4.inner_text("[role=status]")
        check("what can I make finds recipes", "make now" in status or "need one or two" in status, status)
        check("each result says what is missing", await p4.locator("ul.rows li .s:has-text('Needs'), ul.rows li .s:has-text('You have everything')").count() > 0)
        await p4.click(".rowacts button:has-text('Plan it') >> nth=0")
        await p4.click("dialog.pickdialog .picklist button >> nth=5")
        check("a result can be planned", "Planned for" in await p4.inner_text("#toast"))
        await p4.screenshot(path=str(SHOTS / "pantry.png"))
        await p4.goto(URL + "#/shop")
        await p4.wait_for_selector(".shoplist")
        check("the list sets aside what is already in the kitchen", await p4.locator(".havebox").count() == 1)
        check("and offers the newly planned recipe", await p4.locator("button:has-text('Add my meal plan')").count() == 1)

        await p4.goto(URL + "#/")
        await search(p4, "Hearty Russian Beet Soup")
        await p4.click(".rc >> nth=0")
        await p4.wait_for_selector(".dock")
        await p4.click("button:has-text('Add to a collection')")
        await p4.fill("dialog.pickdialog input[type=text]", "Soups I like")
        await p4.press("dialog.pickdialog input[type=text]", "Enter")
        await p4.click("dialog.pickdialog button:has-text('Done')")
        check("a recipe can be put in a new collection", await p4.locator("button:has-text('Collections (1)')").count() == 1)
        await p4.goto(URL + "#/starred")
        await p4.click(".collrow .chip:has-text('Soups I like')")
        await p4.wait_for_selector("ul.rows li")
        check("the collection lists it", "Soups I like" in await p4.inner_text("h1") and await p4.locator("ul.rows li").count() == 1)

        # cook log: rate it, mark it made, keep a private note
        await p4.goto(URL + "#/")
        await search(p4, "Hearty Russian Beet Soup")
        await p4.click(".rc >> nth=0")
        await p4.wait_for_selector(".mylog")
        await p4.click(".ratestar >> nth=3")
        check("a recipe can be rated", "4 of 5" in await p4.inner_text(".ratingrow"))
        await p4.click(".mylog button:has-text('I made this')")
        check("and marked as made", "Made once, last today" in await p4.inner_text(".mylog"))
        await p4.fill(".mylog textarea", "Use less salt next time")
        await p4.reload()
        await p4.wait_for_selector(".mylog")
        check("rating, cook log and note survive a reload",
              "4 of 5" in await p4.inner_text(".ratingrow") and "Made once" in await p4.inner_text(".mylog")
              and await p4.input_value(".mylog textarea") == "Use less salt next time")
        await p4.goto(URL + "#/starred")
        await p4.click(".collrow .chip:has-text('Cooked')")
        await p4.wait_for_selector("ul.rows li")
        check("the Cooked page lists it with its rating", "★★★★" in await p4.inner_text("ul.rows") and "Made once" in await p4.inner_text("ul.rows"))

        if MORE["count"]:
            index = json.loads((ROOT / "web" / "data" / "more" / MORE["v"] / "index.json").read_text(encoding="utf-8"))["recipes"]
            first = next(r for r in index if len(r[3]) >= 6)
            other = next(r for r in index if r[0][:2] != first[0][:2])      # in a file that is never fetched here
            await p4.goto(URL + f"#/r/{first[0]}")
            await p4.wait_for_selector(".dock")
            check("an on-demand recipe opens with its ingredients", await p4.locator("ul.ing li").count() >= len(first[3]),
                  await p4.locator("ul.ing li").count())
            await ctx4.set_offline(True)
            await p4.reload()
            await p4.wait_for_selector(".dock", timeout=15000)
            check("an opened on-demand recipe works offline", first[1] in await p4.inner_text("h1"))
            await p4.goto(URL + f"#/r/{other[0]}")
            await p4.wait_for_selector("button:has-text('Try again')", timeout=15000)
            check("an unopened one explains it needs a connection", "needs a connection" in await p4.inner_text("#app"))
            await ctx4.set_offline(False)

        # share a recipe as a link, open it on a device that has never seen it
        await page.goto(URL + "#/")
        await page.wait_for_selector(".rc")
        await search(page, "Hearty Russian Beet Soup")
        await page.click(".rc >> nth=0")
        await page.wait_for_selector("ul.ing li")
        await page.click("button:has-text('Share link')")
        await page.wait_for_selector("dialog.sharedialog input.link")
        link = await page.input_value("dialog.sharedialog input.link")
        check("share dialog gives a self-contained link", "#/s/" in link and link.startswith(URL), link[:60])
        check("QR code only when the link is short enough to scan", await page.locator("dialog.sharedialog .qr svg").count() == (1 if len(link) <= 700 else 0))
        await page.click("dialog.sharedialog button:has-text('Done')")
        ctxS = await b.new_context(viewport={"width": 390, "height": 844})
        pgS = await ctxS.new_page()
        pgS.on("pageerror", lambda e: errors.append(str(e)))
        await pgS.goto(link)
        await pgS.wait_for_selector("ul.ing li", timeout=15000)
        check("a shared link opens the recipe on a fresh device", "Hearty Russian Beet Soup" in await pgS.inner_text("h1"))
        check("shared recipe keeps its ingredients and method", await pgS.locator("ul.ing li").count() > 3 and await pgS.locator("ol.steps li, .dir p").count() >= 1)
        check("shared recipe says it was shared", "Shared with you" in await pgS.inner_text(".sharednote"))
        check("shared recipe has no star, plan or notes", await pgS.locator("button.star, .mylog").count() == 0
              and await pgS.locator("button:has-text('Add to meal plan')").count() == 0)
        await pgS.click("button:has-text('2×')")
        check("shared recipe can be scaled", await pgS.input_value("input[aria-label=Multiplier]") == "2")
        await pgS.emulate_media(media="print")
        check("printed card shows the footer and hides the tools",
              await pgS.locator(".printfoot").is_visible() and not await pgS.locator(".tools").is_visible() and not await pgS.locator(".sharednote").is_visible())
        await pgS.emulate_media(media="screen")
        await pgS.click("button:has-text('Save to my recipes')")
        await pgS.wait_for_selector("input[aria-label=Title], label.field input")
        check("Save to my recipes opens the editor with the recipe", await pgS.locator("input").first.count() >= 1
              and "Hearty Russian Beet Soup" in (await pgS.locator("label.field input").first.input_value()))
        await pgS.goto(URL + "#/s/1AAAA")
        await pgS.reload()
        await pgS.wait_for_selector(".linkbtn")
        check("a damaged link says so and offers the library", "did not work" in await pgS.inner_text("#app"))
        await ctxS.close()

        # nutrition and food cost on a recipe, and the price book
        await page.goto(URL + "#/")
        await page.wait_for_selector(".rc")
        await search(page, "European Sour Cream Apple Pie")
        await page.click(".rc >> nth=0")
        await page.wait_for_selector("ul.ing li")
        nsum = await page.inner_text("details.nutri > summary")
        check("a recipe estimates calories per serving", "calories per serving" in nsum, nsum)
        await page.click("details.nutri > summary")
        check("nutrition shows five figures", await page.locator(".nstats > div").count() == 5)
        check("nutrition says how much it could count", "ingredients" in await page.inner_text("details.nutri") and "not a label" in await page.inner_text("details.nutri"))
        check("food cost starts by asking for prices", "Add prices" in await page.inner_text("details.costcard > summary"))
        await page.click("details.costcard > summary")
        await page.fill("input[aria-label='Price of butter']", "4")
        row = page.locator(".costline:has(input[aria-label='Price of butter']) .cl-cost")
        await page.wait_for_function("document.querySelector(\"input[aria-label='Price of butter']\").closest('.costline').querySelector('.cl-cost').textContent.startsWith('$')")
        check("2/3 cup of butter at $4 a pound costs $1.33", await row.inner_text() == "$1.33", await row.inner_text())
        check("the summary shows cost per serving", "per serving" in await page.inner_text("details.costcard > summary"))
        await page.fill("input[aria-label='Menu price per serving']", "5")
        check("food cost percent follows the menu price", "4.4%" in await page.inner_text(".costtotals"), await page.inner_text(".costtotals"))
        per_before = await page.locator(".costtotals .ctline:has-text('Per serving') strong").first.inner_text()
        await page.click("button:has-text('2×')")
        await page.wait_for_function("document.querySelector('.costtotals').textContent.includes('$2.6')")
        check("scaling doubles the total but not the cost per serving",
              await page.locator(".costtotals .ctline:has-text('Per serving') strong").first.inner_text() == per_before)
        await page.reload()
        await page.wait_for_selector("ul.ing li")
        await page.click("details.costcard > summary")
        check("prices are remembered", await page.input_value("input[aria-label='Price of butter']") == "4")
        check("and so is the menu price", await page.input_value("input[aria-label='Menu price per serving']") == "5")
        await page.goto(URL + "#/settings")
        await page.wait_for_selector("a:has-text('Open the price book')")
        check("Settings links to the price book with its count", "1" in await page.inner_text("section:has(a:has-text('Open the price book'))"))
        await page.click("a:has-text('Open the price book')")
        await page.wait_for_selector(".pricebook .costline")
        check("the price book lists the price", await page.locator(".pricebook .costline:has-text('butter')").count() == 1)
        async with page.expect_download() as dl:
            await page.click("button:has-text('Export CSV')")
        csv_text = Path(await (await dl.value).path()).read_text()
        check("the price book exports a CSV", "butter,4,lb" in csv_text, csv_text)
        csv_in = Path(tempfile.mkdtemp()) / "prices.csv"
        csv_in.write_text("food,price,per\nolive oil,12,gallon\nflour,0.8,lb\nbad row\n")
        await page.set_input_files(".pricebook input[type=file]", str(csv_in))
        await page.wait_for_selector(".pricebook [role=status]:has-text('Added or updated 2')")
        check("a supplier list can be imported, and unreadable rows are reported",
              "1 row could not be read" in await page.inner_text(".pricebook [role=status]")
              and await page.locator(".pricebook .costline:has-text('olive oil')").count() == 1)
        await page.fill(".pricebook input[type=search]", "flour")
        check("the price book can be searched", await page.locator(".pricebook .costline").count() == 1)
        await page.click(".pricebook .costline .icon-btn")
        check("and a price can be removed", await page.locator(".pricebook .costline:has-text('flour')").count() == 0)
        await page.goto(URL + "#/")

        # import and export formats
        await page.goto(URL + "#/settings")
        await page.click("a:has-text('Import and export recipes')")
        await page.wait_for_selector(".transfer")
        await page.fill(".transfer textarea", "Wild Rice Soup\nServes 6\nIngredients\n1 cup wild rice\n2 Tbsp butter\nDirections\n1. Simmer the rice.\n2. Stir in butter.")
        await page.click("button:has-text('Read pasted text')")
        await page.wait_for_selector(".foundlist")
        check("pasted text is read and listed before anything is added", await page.locator(".foundlist li:has-text('Wild Rice Soup')").count() == 1)
        cook = Path(tempfile.mkdtemp()) / "pan-toast.cook"
        cook.write_text(">> servings: 2\nToast @bread{2%slices} with @butter{1%Tbsp}.\n")
        await page.set_input_files(".transfer input[type=file]", str(cook))
        await page.wait_for_selector(".foundlist li:has-text('pan toast')")
        check("a Cooklang file is read", "Cooklang" in await page.inner_text(".transfer [role=status]"))
        await page.locator("button:has-text('Add 1 recipe')").evaluate("e => e.click()")   # a real tap lands (checked by hit test); Playwright's own scrolling trips over the fixed tab bar here
        await page.wait_for_selector(".transfer [role=status]:has-text('Added 1 recipe')")
        await page.goto(URL + "#/")
        await page.fill("input[type=search]", "pan toast")
        await page.wait_for_selector(".rc:has-text('pan toast')")
        check("an imported recipe lands in the library", True)
        await page.goto(URL + "#/transfer")
        await page.wait_for_selector(".transfer")
        async with page.expect_download() as dl:
            await page.locator("button:has-text('Paprika file')").evaluate("e => e.click()")
        pk_path = Path(await (await dl.value).path())
        check("the Paprika export is a zip", pk_path.read_bytes()[:2] == b"PK")
        await page.set_input_files(".transfer input[type=file]", str(pk_path))
        await page.wait_for_selector(".foundlist")
        check("the Paprika export reads back in", await page.locator(".foundlist li:has-text('pan toast')").count() == 1
              and "Paprika" in await page.inner_text(".transfer [role=status]"))
        async with page.expect_download() as dl:
            await page.locator("button:has-text('Markdown')").evaluate("e => e.click()")
        check("Markdown export has the ingredients", "## Ingredients" in Path(await (await dl.value).path()).read_text())
        await page.goto(URL + "#/")

        # dark mode renders
        ctx3 = await b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, color_scheme="dark")
        pg3 = await ctx3.new_page()
        await pg3.goto(URL + "#/")
        await pg3.wait_for_selector(".rc")
        await pg3.screenshot(path=str(SHOTS / "dark.png"))
        await b.close()
    real = [e for e in errors if "Failed to load resource" not in e and "net::ERR" not in e]
    check("no JavaScript errors", not real, real[:3])
    failed = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    return 1 if failed else 0


sys.exit(asyncio.run(main()))
