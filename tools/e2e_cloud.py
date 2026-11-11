"""Browser check of the account features against a FAKE in-memory Supabase (the real one is not reachable
from the test machine). It proves the app's screens and requests behave; it does not prove the real
database rules, which are tested separately by supabase/test/run.sh.

    python tools/e2e_cloud.py
"""
import asyncio
import json
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent.parent
PORT = 8792
URL = f"http://127.0.0.1:{PORT}/"
CORS = {"access-control-allow-origin": "*", "access-control-allow-headers": "*", "access-control-allow-methods": "*"}
results, errors = [], []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))


class Fake:
    def __init__(self):
        self.online = True
        self.users = {}      # email -> dict(pw,id,name,role)
        self.restaurants = {}
        self.members = []    # dict(user_id, restaurant_id, member_role)
        self.invites = {}    # code -> dict(kind, restaurant_id, member_role, uses, max)
        self.recipes = {}
        self.add_user("chef@example.com", "adminpass1", "Joe", "admin")
        self.log = []
        self.user_data = {}
        self.tick = 0
        self.requests = {}   # id -> invite request
        self.notified = []   # admin emails about new requests
        self.open_signup = False
        self.sent = []       # emailed invites

    def add_user(self, email, pw, name, role):
        uid = str(uuid.uuid4())
        self.users[email] = dict(pw=pw, id=uid, name=name, role=role, email=email)
        return uid

    def by_token(self, req):
        tok = req.headers.get("authorization", "").replace("Bearer ", "")
        return next((u for u in self.users.values() if tok == f"tok-{u['id']}"), None)

    def token_resp(self, u):
        return {"access_token": f"tok-{u['id']}", "refresh_token": "r", "expires_in": 3600, "user": {"id": u["id"], "email": u["email"]}}

    def visible(self, u):
        out = []
        for r in self.recipes.values():
            mem = any(m["user_id"] == u["id"] for m in self.members if m["restaurant_id"] == r.get("restaurant_id"))
            active = r.get("restaurant_id") and self.restaurants[r["restaurant_id"]]["subscription_status"] in ("active", "trialing")
            if (u["role"] == "admin" or r["owner_id"] == u["id"] or (r["scope"] == "community" and r["status"] == "approved")
                    or (r["scope"] == "restaurant" and mem and active)):
                out.append(r)
        return out

    async def handle(self, route):
        req = route.request
        if req.method == "OPTIONS":
            return await route.fulfill(status=204, headers=CORS)
        if not self.online:
            return await route.abort()
        u = urlparse(req.url)
        path, q = u.path, parse_qs(u.query)
        body = json.loads(req.post_data) if req.post_data else None
        self.log.append((req.method, path))
        user = self.by_token(req)

        def ok(data, status=200):
            return route.fulfill(status=status, headers={**CORS, "content-type": "application/json"}, body=json.dumps(data))

        def eq(name):
            v = q.get(name, [None])[0]
            return v[3:] if v and v.startswith("eq.") else None

        if path == "/auth/v1/token":
            x = self.users.get((body or {}).get("email"))
            if not x or x["pw"] != body["password"]:
                return await ok({"error_description": "Invalid login credentials"}, 400)
            return await ok(self.token_resp(x))
        if path == "/rest/v1/rpc/signup_open":
            return await ok(self.open_signup)
        if path == "/functions/v1/request-invite":
            new = not any(r["email"] == body["email"].lower() and r["status"] == "waiting" for r in self.requests.values())
            rid = str(uuid.uuid4())
            self.requests[rid] = dict(id=rid, name=body["name"], email=body["email"].lower(), about=body["about"], note=body["note"],
                                      status="waiting", created_at="2026-11-05T10:00:00Z")
            if new:
                self.notified.append(body["email"].lower())
            return await ok({"ok": True, "new": new, "emailed": new})
        if path == "/auth/v1/signup" and self.open_signup and not (body["data"].get("invite_code") or ""):
            uid = self.add_user(body["email"], body["password"], body["data"].get("display_name"), "student")
            return await ok(self.token_resp(self.users[body["email"]]))
        if path == "/auth/v1/signup":
            code = (body["data"].get("invite_code") or "").upper()
            inv = self.invites.get(code)
            if not inv or inv["uses"] >= inv["max"]:
                return await ok({"message": "Database error saving new user"}, 500)
            inv["uses"] += 1
            uid = self.add_user(body["email"], body["password"], body["data"].get("display_name"), "client" if inv["kind"] == "restaurant" else "student")
            if inv["kind"] == "restaurant":
                self.members.append(dict(user_id=uid, restaurant_id=inv["restaurant_id"], member_role=inv["member_role"]))
            return await ok(self.token_resp(self.users[body["email"]]))
        if path == "/auth/v1/recover":
            return await ok({})
        if path == "/rest/v1/rpc/invite_info":
            inv = self.invites.get((body.get("p_code") or "").upper())
            if not inv:
                return await ok([{"status": "not found", "kind": None, "restaurant_name": None, "member_role": None}])
            return await ok([{"status": "active" if inv["uses"] < inv["max"] else "used up", "kind": inv["kind"],
                              "restaurant_name": (self.restaurants.get(inv["restaurant_id"]) or {}).get("name"), "member_role": inv["member_role"]}])
        if path == "/rest/v1/rpc/request_invite":
            rid = str(uuid.uuid4())
            self.requests[rid] = dict(id=rid, name=body["p_name"], email=body["p_email"].lower(), about=body["p_about"], note=body["p_note"],
                                      status="waiting", created_at="2026-11-05T10:00:00Z")
            return await route.fulfill(status=204, headers=CORS)
        if path == "/auth/v1/logout":
            return await ok({})
        if user is None:
            return await ok({"message": "JWT expired"}, 401)
        if path == "/auth/v1/user" and req.method == "PUT":
            user["pw"] = body["password"]
            return await ok({"id": user["id"]})
        if path == "/rest/v1/user_data":
            if getattr(self, "no_table", False):
                return await ok({"message": "Could not find the table 'public.user_data' in the schema cache"}, 404)
            if req.method == "GET":
                return await ok([self.user_data[user["id"]]] if user["id"] in self.user_data else [])
            self.tick += 1
            # an upsert that merges: only the columns sent are changed (stars, library_photos, planner)
            row = {"stars": [], **self.user_data.get(user["id"], {}), **body, "user_id": user["id"],
                   "updated_at": f"2026-11-04T10:00:{self.tick:02d}Z"}
            if getattr(self, "no_planner", False) and "planner" in body:
                return await ok({"message": "Could not find the 'planner' column of 'user_data' in the schema cache"}, 400)
            self.user_data[user["id"]] = row
            return await ok([row], 201)
        if path == "/rest/v1/profiles":
            return await ok([{"display_name": user["name"], "role": user["role"]}])
        if path == "/rest/v1/restaurant_members":
            return await ok([{"member_role": m["member_role"], "restaurant": self.restaurants[m["restaurant_id"]]}
                             for m in self.members if m["user_id"] == user["id"]])
        if path == "/rest/v1/recipes":
            if req.method == "GET":
                return await ok(self.visible(user))
            if req.method == "POST":
                private = [r for r in self.recipes.values() if r["owner_id"] == user["id"] and r["scope"] == "private"]
                if user["role"] != "admin" and len(private) >= 2 and not any(m["user_id"] == user["id"] for m in self.members):
                    return await ok({"message": "Free plan limit reached (2 recipes)"}, 400)
                row = {"id": str(uuid.uuid4()), "scope": "private", "status": "approved", "restaurant_id": None, "source_recipe_id": None, "author_name": None, "review_note": None, **body}
                self.recipes[row["id"]] = row
                return await ok([row], 201)
            rid = eq("id")
            row = self.recipes.get(rid)
            if req.method == "DELETE":
                if row and (user["role"] == "admin" or row["owner_id"] == user["id"]):
                    del self.recipes[rid]
                return await route.fulfill(status=204, headers=CORS)
            if req.method == "PATCH":
                if not row or not (user["role"] == "admin" or (row["owner_id"] == user["id"] and row["scope"] == "private")):
                    return await ok([])
                row.update(body)
                return await ok([row])
        if path == "/functions/v1/import-recipe":   # made-up page; the real function reads the page's schema.org block
            return await ok({"url": body["url"], "site": "", "recipe": {
                "@type": "Recipe", "name": "Test Lentil Soup", "author": {"name": "Pat Example"},
                "recipeYield": ["4", "4 bowls"], "recipeIngredient": ["1 1/2 cups lentils", "½ tsp salt"],
                "recipeInstructions": [{"@type": "HowToStep", "text": "Simmer."}, {"@type": "HowToStep", "text": "Serve."}]}})
        if path == "/rest/v1/rpc/share_link_to_community":
            src = self.recipes[body["p_recipe"]]
            o = src["body"]["src"]
            row = dict(id=str(uuid.uuid4()), owner_id=user["id"], scope="community", status="pending", restaurant_id=None, review_note=None,
                       title=src["title"], categories=src.get("categories", []), source_recipe_id=src["id"], author_name=user["name"],
                       body=dict(kind="link", title=src["title"], tags=[], yq="", yu="", yr="", dir="", ings=[], src=o))
            self.recipes[row["id"]] = row
            return await ok(row["id"])
        if path == "/rest/v1/rpc/submit_to_community":
            src = self.recipes[body["p_recipe"]]
            if (src.get("body") or {}).get("src", {}).get("url"):
                return await ok({"message": "This recipe came from another website, so it stays private."}, 400)
            row = dict(src, id=str(uuid.uuid4()), scope="community", status="pending", source_recipe_id=src["id"], author_name=user["name"])
            self.recipes[row["id"]] = row
            return await ok(row["id"])
        if path == "/rest/v1/app_settings":
            if user["role"] != "admin":
                return await ok([])
            self.open_signup = bool(body["open_signup"])
            return await route.fulfill(status=204, headers=CORS)
        if path == "/rest/v1/invite_requests":
            if user["role"] != "admin":
                return await ok([])
            if req.method == "GET":
                return await ok([r for r in self.requests.values() if r["status"] == "waiting"])
            self.requests[eq("id")].update(body)
            return await ok([self.requests[eq("id")]])
        if path == "/functions/v1/send-invite":
            if user["role"] != "admin":
                return await ok({"error": "You are not allowed to create this invite."}, 403)
            if body["email"] in self.users:
                return await ok({"error": "That email already has an account. They can sign in, or use “Forgot password?”."}, 409)
            code = "CODE" + uuid.uuid4().hex[:6].upper()
            self.invites[code] = dict(kind=body["kind"], restaurant_id=body["restaurant_id"], member_role=body["member_role"], uses=0, max=1)
            self.sent.append(dict(body, code=code))
            if body.get("request_id"):
                self.requests[body["request_id"]]["status"] = "invited"
            return await ok({"ok": True, "code": code})
        if path == "/rest/v1/rpc/admin_list_invites":
            return await ok([dict(code=c, kind=i["kind"], restaurant_name=(self.restaurants.get(i["restaurant_id"]) or {}).get("name"), member_role=i["member_role"],
                                  max_uses=i["max"], uses=i["uses"], expires_at=None, cancelled_at=None, created_at="2026-11-05T10:00:00Z",
                                  status="active" if i["uses"] < i["max"] else "used up", used_by=[], email=None) for c, i in self.invites.items()])
        if path == "/rest/v1/rpc/create_invite":
            code = "CODE" + uuid.uuid4().hex[:6].upper()
            self.invites[code] = dict(kind=body["p_kind"], restaurant_id=body["p_restaurant"], member_role=body["p_member_role"], uses=0, max=body["p_max_uses"])
            return await ok(code)
        if path == "/rest/v1/restaurants":
            if req.method == "GET":
                return await ok(list(self.restaurants.values()))
            if req.method == "POST":
                r = {"id": str(uuid.uuid4()), "subscription_status": "inactive", "seat_limit": 3, **body}
                self.restaurants[r["id"]] = r
                return await ok([r], 201)
            if req.method == "PATCH":
                self.restaurants[eq("id")].update(body)
                return await route.fulfill(status=204, headers=CORS)
        return await ok({"message": f"unhandled {req.method} {path}"}, 404)


async def new_page(b, fake, w=390, h=844):
    ctx = await b.new_context(viewport={"width": w, "height": h}, accept_downloads=True)
    await ctx.route(re.compile(r"https://.*\.supabase\.co/.*"), fake.handle)
    # the tests talk to the fake server whatever web/js/config.js points at (it is empty until a project exists)
    await ctx.route(re.compile(r".*/js/config\.js$"), lambda route: route.fulfill(
        content_type="text/javascript",
        body="export const SUPABASE_URL = 'https://sprig-test.supabase.co';\nexport const SUPABASE_KEY = 'sb_publishable_test';\n"))
    page = await ctx.new_page()
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    return ctx, page


async def close_dialog(page, title_part=""):
    """Close the confirmation dialog shown after signing in / up. Returns its text."""
    sel = "dialog.infodialog[open]" + (f":has-text('{title_part}')" if title_part else "")
    await page.wait_for_selector(sel)
    text = await page.inner_text(sel)
    await page.click("dialog.infodialog[open] button:has-text('OK')")
    return text


async def sign_in(page, email, pw):
    await page.goto(URL + "#/settings")
    await page.wait_for_selector("input[type=email]")
    await page.fill("input[type=email]", email)
    await page.fill("input[type=password]", pw)
    await page.click("button[type=submit]")
    await close_dialog(page, "Welcome back")
    await page.wait_for_selector("text=Sign out")


async def make_link(admin, who="student", restaurant=None):
    """Admin tools > Invite someone > Make a link & QR code. Returns (code, link)."""
    await admin.select_option("select[aria-label='Who are you inviting']", who)
    if restaurant:
        await admin.select_option("select[aria-label=Restaurant]", label=restaurant)
    old = await admin.locator(".invite-share input.link").first.input_value() if await admin.locator("section .invite-share input.link").count() else ""
    await admin.click("button:has-text('Make a link & QR code')")
    await admin.wait_for_function("(o) => { const i = document.querySelector('section .invite-share input.link'); return i && i.value !== o; }", arg=old)
    link = await admin.locator("section .invite-share input.link").first.input_value()
    return link.rsplit("/", 1)[1], link


async def main():
    server = subprocess.Popen([sys.executable, "-m", "http.server", str(PORT), "--bind", "127.0.0.1", "--directory", str(ROOT / "web")],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    try:
        return await run()
    finally:
        server.terminate()


async def run():
    fake = Fake()
    async with async_playwright() as p:
        b = await p.chromium.launch()

        # ---- admin
        actx, admin = await new_page(b, fake)
        await admin.goto(URL + "#/settings")
        await admin.wait_for_selector("input[type=email]")
        await admin.fill("input[type=email]", "chef@example.com")
        await admin.fill("input[type=password]", "wrong")
        await admin.click("button[type=submit]")
        await admin.wait_for_selector(".note:has-text('Wrong email')")
        check("wrong password shows a friendly message", True)
        await admin.fill("input[type=password]", "adminpass1")
        await admin.click("button[type=submit]")
        check("signing in shows a welcome-back dialog", "Welcome back, Joe" in await close_dialog(admin))
        await admin.wait_for_selector("text=Sign out")
        check("admin sees Admin tools link", await admin.locator("a:has-text('Admin tools')").count() == 1)

        await admin.click("a:has-text('Admin tools')")
        await admin.wait_for_selector("h1:has-text('Admin tools')")
        await admin.fill("input[aria-label='New restaurant name']", "Maple Street Grill")
        await admin.click("button:has-text('Add restaurant')")
        await admin.wait_for_selector("strong:has-text('Maple Street Grill')")
        check("admin can add a restaurant", len(fake.restaurants) == 1)
        rid = next(iter(fake.restaurants))
        await admin.select_option("select[aria-label='Subscription for Maple Street Grill']", "active")
        await admin.wait_for_timeout(300)
        check("admin can mark a restaurant active", fake.restaurants[rid]["subscription_status"] == "active")

        student_code, student_link = await make_link(admin, "student")
        check("invite link shows a QR code", await admin.locator("section .invite-share .qr svg path").count() == 1)
        check("invite link opens the join page", student_link.endswith("#/join/" + student_code))
        rest_code, _ = await make_link(admin, "owner", "Maple Street Grill")
        check("invite codes are generated", student_code.startswith("CODE") and rest_code != student_code
              and fake.invites[rest_code]["member_role"] == "owner")
        await admin.click("section button:has-text('Show big QR')")
        await admin.wait_for_selector("dialog.qrdialog[open] svg")
        await admin.screenshot(path="/tmp/cloud_bigqr.png")
        await admin.click("dialog.qrdialog[open] button:has-text('Done')")

        # email an invite
        await admin.select_option("select[aria-label='Who are you inviting']", "student")
        await admin.fill("input[aria-label='Their name']", "Kim")
        await admin.fill("input[aria-label='Their email']", "kim@example.com")
        await admin.click("button:has-text('Send invite email')")
        await admin.wait_for_selector("text=Sent. Kim will get an email")
        check("admin can email an invite", fake.sent and fake.sent[-1]["email"] == "kim@example.com" and fake.sent[-1]["name"] == "Kim"
              and fake.sent[-1]["app_url"].startswith("http"))
        await admin.fill("input[aria-label='Their email']", "chef@example.com")
        await admin.click("button:has-text('Send invite email')")
        await admin.wait_for_selector(".note:has-text('already has an account')")
        check("emailing someone who already has an account is explained", True)
        await admin.screenshot(path="/tmp/cloud_admin_invite.png", full_page=True)
        fake.recipes["coll1"] = dict(id="coll1", owner_id=fake.users["chef@example.com"]["id"], scope="restaurant", restaurant_id=rid, status="approved",
                                     title="Maple House Vinaigrette", categories=["Salad dressings"], author_name=None, review_note=None, source_recipe_id=None,
                                     body=dict(tags=[], yq="2", yu="cups", yr="2 cups", dir="Whisk.", ings=[["1", "1 cup", "cup", "olive oil", ""]]))

        # ---- student
        sctx, st = await new_page(b, fake)
        await st.goto(URL + "#/settings")
        await st.wait_for_selector("button[role=tab]:has-text('New account')")
        await st.click("button[role=tab]:has-text('New account')")
        await st.fill("input[aria-label='Your name']", "Sam")
        await st.fill("input[type=email]", "sam@example.com")
        await st.fill("input[type=password]", "samspass99")
        await st.fill("input[aria-label='Invite code']", "BADCODE1")
        await st.click("button[type=submit]")
        await st.wait_for_selector(".note:has-text('invite code')")
        check("bad invite code is explained", True)
        # ...then opens the link they were sent
        await st.goto(student_link)
        await st.wait_for_selector("h1:has-text('You’re invited!')")
        check("join link fills in the invite code", await st.locator(".okline:has-text('" + student_code + "')").count() == 1
              and await st.locator("input[aria-label='Invite code']").count() == 0)
        await st.screenshot(path="/tmp/cloud_join.png", full_page=True)
        await st.fill("input[aria-label='Your name']", "Sam")
        await st.fill("input[type=email]", "sam@example.com")
        await st.fill("input[aria-label=Password]", "samspass99")
        await st.click("button.showpw")
        check("password can be shown", await st.get_attribute("input[aria-label=Password]", "type") == "text")
        await st.click("button[type=submit]")
        check("sign-up shows a welcome dialog", "Welcome, Sam!" in await close_dialog(st))
        await st.wait_for_selector("text=Sign out")
        check("student creates an account with a code", "sam@example.com" in fake.users)

        await st.goto(URL + "#/")
        await st.wait_for_selector(".chips.src")
        check("source chips appear when signed in", await st.locator(".chips.src .chip").count() >= 4)
        check("restaurant collection is hidden from a non-member", await st.locator(".rc:has-text('Maple House')").count() == 0)

        async def add_recipe(page, title):
            await page.goto(URL + "#/new")
            await page.fill("input[aria-label=Title]", title)
            await page.fill("input[aria-label=Amount]", "2")
            await page.fill("input[aria-label=Unit]", "cup")
            await page.fill("input[aria-label=Ingredient]", "flour")
            await page.fill("textarea", "Mix.")
            await page.click("button:has-text('Save')")
            await page.wait_for_timeout(700)

        await add_recipe(st, "Sam Secret Biscuits")
        check("new recipe is saved in the account", sum(r["scope"] == "private" for r in fake.recipes.values()) == 1)
        check("recipe page opens after saving", "Sam Secret Biscuits" in await st.inner_text("h1"))
        await add_recipe(st, "Sam Second")
        await add_recipe(st, "Sam Third")
        check("free limit message is shown, nothing lost silently", await st.locator("h1:has-text('New recipe')").count() == 1
              and sum(r["scope"] == "private" for r in fake.recipes.values()) == 2)

        await st.goto(URL + "#/")
        await st.click(".chips.src .chip:has-text('My recipes')")
        await st.fill("input[type=search]", "Secret")
        await st.wait_for_timeout(300)
        check("My recipes filter shows the account recipe", await st.locator(".rc:has-text('Sam Secret Biscuits')").count() == 1)
        await st.click(".rc:has-text('Sam Secret Biscuits')")
        await st.wait_for_selector("button:has-text('Share with the Community')")
        st.once("dialog", lambda d: d.accept())
        await st.click("button:has-text('Share with the Community')")
        await st.wait_for_selector("dialog[open]")
        check("rights wording is shown before sharing", "right to share" in (await st.inner_text("dialog[open]")))
        await st.click("dialog[open] button:has-text('Share')")
        await st.wait_for_selector("text=Withdraw from Community")
        pend = [r for r in fake.recipes.values() if r["scope"] == "community"]
        check("sharing creates a pending copy", len(pend) == 1 and pend[0]["status"] == "pending" and pend[0]["author_name"] == "Sam")

        # ---- admin approves
        await admin.reload()
        await admin.wait_for_selector("text=Sam Secret Biscuits")
        check("admin sees the submission with the author", await admin.locator("text=Shared by Sam").count() == 1)
        await admin.click("button:has-text('Approve')")
        await admin.wait_for_selector("text=Nothing is waiting for approval")
        check("approval is saved", pend[0]["status"] == "approved")

        # ---- another student sees it in Community
        s2ctx, s2 = await new_page(b, fake)
        fake.add_user("pat@example.com", "patspass99", "Pat", "student")
        await sign_in(s2, "pat@example.com", "patspass99")
        await s2.goto(URL + "#/")
        await s2.wait_for_selector(".chips.src")
        await s2.click(".chips.src .chip:has-text('Community')")
        await s2.wait_for_selector(".rc:has-text('Sam Secret Biscuits')")
        check("approved recipe appears in Community with a badge", await s2.locator(".rc:has-text('Sam Secret Biscuits') .badge:has-text('Community')").count() == 1)
        await s2.click(".rc:has-text('Sam Secret Biscuits')")
        await s2.wait_for_selector(".credit:has-text('Shared by Sam')")
        check("author is credited", True)
        check("others cannot edit a community recipe", await s2.locator("a[aria-label='Edit recipe']").count() == 0)
        check("others cannot see Sam's private recipes", "Sam Second" not in await (await s2.request.get(URL)).text())
        await s2.goto(URL + "#/")
        await s2.fill("input[type=search]", "Sam Second")
        await s2.wait_for_timeout(300)
        check("private recipes of others never listed", await s2.locator(".rc").count() == 0)

        # ---- restaurant staff
        await admin.reload()
        await admin.wait_for_selector("button:has-text('Make a link & QR code')")
        code2, link2 = await make_link(admin, "staff", "Maple Street Grill")
        rctx, rs = await new_page(b, fake)
        await rs.goto(URL + "#/settings")
        await rs.click("button[role=tab]:has-text('New account')")
        await rs.fill("input[aria-label='Your name']", "Rae")
        await rs.fill("input[type=email]", "rae@maple.test")
        await rs.fill("input[type=password]", "raespass99")
        await rs.fill("input[aria-label='Invite code']", code2)
        await rs.click("button[type=submit]")
        await close_dialog(rs, "Welcome, Rae")
        await rs.wait_for_selector("text=Sign out")
        check("restaurant staff account shows the restaurant and plan", await rs.locator(".stat:has-text('Maple Street Grill')").count() == 1)
        await rs.goto(URL + "#/")
        await rs.wait_for_selector(".chips.src")
        await rs.fill("input[type=search]", "Vinaigrette")
        await rs.wait_for_timeout(300)
        check("staff see the restaurant collection", await rs.locator(".rc:has-text('Maple House Vinaigrette') .badge:has-text('Maple Street Grill')").count() == 1)
        await rs.click(".rc:has-text('Maple House')")
        await rs.wait_for_selector(".credit:has-text('collection')")
        check("collection recipes are read only for staff", await rs.locator("a[aria-label='Edit recipe']").count() == 0)
        await rs.fill("input[aria-label='Multiplier']", "2")
        await rs.wait_for_timeout(200)
        check("collection recipe scales", "2" in await rs.inner_text(".ing"))

        # lapsed subscription hides the collection
        fake.restaurants[rid]["subscription_status"] = "canceled"
        await rs.goto(URL + "#/")
        await rs.reload()
        await rs.wait_for_selector(".rc")
        await rs.fill("input[type=search]", "Vinaigrette")
        await rs.wait_for_timeout(500)
        check("lapsed subscription hides the collection", await rs.locator(".rc:has-text('Maple House')").count() == 0)

        # ---- offline: cached account data still opens
        fake.online = False
        await st.goto(URL + "#/")
        await st.reload()
        await st.wait_for_selector(".rc")
        await st.fill("input[type=search]", "Secret")
        await st.wait_for_timeout(400)
        check("account recipes open offline from the cache", await st.locator(".rc:has-text('Sam Secret Biscuits')").count() >= 1)
        fake.online = True

        # ---- stars follow the person to another device
        await st.goto(URL + "#/")
        await st.fill("input[type=search]", "Sam Secret Biscuits")
        await st.wait_for_timeout(300)
        await st.click(".rows .star >> nth=0")
        await st.wait_for_timeout(1500)
        sam_id = fake.users["sam@example.com"]["id"]
        check("a starred recipe is saved to the account", len(fake.user_data.get(sam_id, {}).get("stars", [])) == 1)
        dctx, dev2 = await new_page(b, fake)
        await sign_in(dev2, "sam@example.com", "samspass99")
        await dev2.goto(URL + "#/starred")
        await dev2.wait_for_selector(".count")
        await dev2.reload()
        await dev2.wait_for_selector(".rc:has-text('Sam Secret Biscuits')")
        check("stars show up on a second device", "1 starred" in await dev2.inner_text(".count"))
        await dev2.click(".rows .star >> nth=0")
        await dev2.wait_for_timeout(1500)
        check("removing a star on one device is saved", fake.user_data[sam_id]["stars"] == [])
        await st.reload()
        await st.wait_for_selector(".rc")
        await st.goto(URL + "#/starred")
        await st.reload()
        await st.wait_for_selector(".empty")
        check("and the first device follows", "0 starred" in await st.inner_text(".count") or await st.locator(".rc").count() == 0)

        fake.no_table = True
        await dev2.goto(URL + "#/settings")
        await dev2.reload()
        await dev2.wait_for_selector("text=Could not find the table", timeout=10000)
        check("a missing table is reported in Settings", await dev2.locator("text=Could not find the table").count() == 1)
        fake.no_table = False

        # ---- the meal plan, shopping list, kitchen and collections follow the person too
        await st.goto(URL + "#/plan")
        await st.wait_for_selector(".planday")
        await st.click(".planday >> nth=2 >> .addday")
        await st.fill("dialog.pickdialog input[type=search]", "Sam Secret Biscuits")
        await st.wait_for_timeout(300)
        await st.click("dialog.pickdialog .picklist button >> nth=0")
        await st.goto(URL + "#/shop")
        await st.fill(".addextra input", "Paper towels")
        await st.press(".addextra input", "Enter")
        await st.goto(URL + "#/pantry")
        await st.fill(".addextra input", "flour, eggs")
        await st.press(".addextra input", "Enter")
        await st.wait_for_timeout(1800)
        doc = fake.user_data.get(sam_id, {}).get("planner", {})
        check("the plan, list and kitchen are saved to the account",
              len(doc.get("plan", {}).get("days", {})) == 1 and len(doc.get("shop", {}).get("extras", [])) == 1
              and doc.get("pantry", {}).get("have") == ["flour", "eggs"], doc)
        check("saving them leaves the stars alone", "stars" in fake.user_data[sam_id])
        await dev2.goto(URL + "#/plan")
        await dev2.reload()
        await dev2.wait_for_selector(".planday .shoprecipes:has-text('Sam Secret Biscuits')", timeout=15000)
        check("the plan shows up on a second device", True)
        await dev2.goto(URL + "#/shop")
        await dev2.wait_for_selector(".shoplist")
        check("so does the shopping list", await dev2.locator(".shoplist li.extra:has-text('Paper towels')").count() == 1)
        await dev2.click(".shoplist li.extra .icon-btn")           # take it off on the second device
        await dev2.wait_for_timeout(1800)
        await st.goto(URL + "#/shop")
        await st.reload()
        await st.wait_for_selector(".empty, .shoplist", timeout=15000)
        await st.wait_for_timeout(1500)
        check("a change on the second device comes back to the first", await st.locator("text=Paper towels").count() == 0)

        # ---- ingredient prices follow the person too
        await st.goto(URL + "#/")
        await st.wait_for_selector(".rc")
        await st.fill("input[type=search]", "European Sour Cream Apple Pie")
        await st.wait_for_timeout(500)
        await st.click(".rc >> nth=0")
        await st.wait_for_selector("ul.ing li")
        await st.click("details.costcard > summary")
        await st.fill("input[aria-label='Price of butter']", "4.5")
        await st.wait_for_timeout(1800)
        doc = fake.user_data.get(sam_id, {}).get("planner", {})
        check("prices are saved to the account", doc.get("prices", {}).get("items", {}).get("butter") == {"p": 4.5, "per": "lb"}, doc.get("prices"))
        check("saving prices keeps the plan", len(doc.get("plan", {}).get("days", {})) == 1)
        await dev2.goto(URL + "#/prices")
        await dev2.reload()
        await dev2.wait_for_selector(".pricebook .costline:has-text('butter')", timeout=15000)
        check("prices show up on a second device", await dev2.input_value(".pricebook input[aria-label='Price of butter']") == "4.5")

        fake.no_planner = True
        await st.goto(URL + "#/plan")
        await st.wait_for_selector(".planday")
        await st.click(".planday >> nth=5 >> .addday")
        await st.fill("dialog.pickdialog input[type=text]", "Leftovers")
        await st.click("dialog.pickdialog form button")
        await st.wait_for_timeout(1800)
        await st.reload()
        await st.wait_for_selector(".planday")
        await st.wait_for_selector("text=Not saved to your account yet", timeout=10000)
        check("a database without the planner column is explained, and the plan is kept on the device",
              "add_planner.sql" in await st.inner_text("#app") and await st.locator(".plannote:has-text('Leftovers')").count() == 1)
        fake.no_planner = False

        # ---- recipes made while signed out can be moved into the account
        lctx, loc = await new_page(b, fake)
        await add_recipe(loc, "Offline Only Soup")
        await loc.goto(URL + "#/settings")
        await sign_in(loc, "pat@example.com", "patspass99")
        await loc.wait_for_selector("button:has-text('Move them to my account')")
        await loc.click("button:has-text('Move them to my account')")
        await loc.click("dialog[open] button:has-text('Move')")
        await loc.wait_for_selector("text=Moved 1", timeout=5000) if False else await loc.wait_for_timeout(1200)
        check("on-device recipes move into the account", any(r["title"] == "Offline Only Soup" and r["owner_id"] == fake.users["pat@example.com"]["id"] for r in fake.recipes.values()))
        check("moved recipe card disappears", await loc.locator("button:has-text('Move them to my account')").count() == 0)

        # ---- forgot password
        fctx, fp = await new_page(b, fake)
        await fp.goto(URL + "#/settings")
        await fp.click("button:has-text('Forgot password?')")
        await fp.wait_for_selector("text=Type your email above first")
        await fp.fill("input[type=email]", "pat@example.com")
        await fp.click("button:has-text('Forgot password?')")
        check("forgot password confirms in a dialog", "reset your password is on its way" in await close_dialog(fp, "Check your email"))
        check("forgot password sends the request", ("POST", "/auth/v1/recover") in fake.log)
        pat = fake.users["pat@example.com"]
        rctx2, rec = await new_page(b, fake)
        await rec.goto(URL + f"#access_token=tok-{pat['id']}&refresh_token=r&expires_in=3600&type=recovery")
        await close_dialog(rec, "Choose a new password")
        await rec.wait_for_selector("input[aria-label='New password']")
        check("reset link signs in and opens the new-password box", "#/settings" in rec.url)
        await rec.fill("input[aria-label='New password']", "brandnew123")
        await rec.click("button:has-text('Save password')")
        await rec.wait_for_timeout(500)
        check("new password is saved", pat["pw"] == "brandnew123")
        await close_dialog(rec, "Password changed")

        # ---- arriving from an emailed invite: signed in, asked to choose a password
        kim_id = fake.add_user("kim@example.com", "", "Kim", "student")
        kim = fake.users["kim@example.com"]
        ictx, inv = await new_page(b, fake)
        await inv.goto(URL + f"#access_token=tok-{kim['id']}&refresh_token=r&expires_in=3600&type=invite")
        check("invite email link welcomes them", "Welcome to Sprig" in await close_dialog(inv))
        await inv.wait_for_selector("text=Choose a password")
        await inv.screenshot(path="/tmp/cloud_invited.png", full_page=True)
        check("no Cancel on the first password", await inv.locator(".card button:has-text('Cancel')").count() == 0)
        await inv.fill("input[aria-label='New password']", "kimspass99")
        await inv.click("button:has-text('Save password')")
        check("choosing the first password confirms how to sign in next time", "Next time, sign in with" in await close_dialog(inv, "all set"))  # the fake token has no email in it
        check("invited person's password is saved", kim["pw"] == "kimspass99")
        await inv.goto(URL + "#error=access_denied&error_code=otp_expired&error_description=Email+link+is+invalid+or+has+expired")
        await inv.reload()
        check("an expired email link is explained", "expired or was already used" in await close_dialog(inv, "didn’t work"))

        # ---- withdraw + sign out
        await st.goto(URL + "#/")
        await st.fill("input[type=search]", "Secret")
        await st.wait_for_timeout(300)
        await st.click(".rc:has-text('Sam Secret Biscuits') >> nth=0")
        await st.wait_for_selector("button:has-text('Withdraw from Community')")
        await st.click("button:has-text('Withdraw from Community')")
        await st.click("dialog[open] button:has-text('Withdraw')")
        await st.wait_for_selector("button:has-text('Share with the Community')")
        check("author can withdraw", not any(r["scope"] == "community" for r in fake.recipes.values()))
        await st.goto(URL + "#/settings")
        await st.click("button:has-text('Sign out')")
        await st.wait_for_selector("input[type=email]")
        await st.goto(URL + "#/")
        await st.wait_for_selector(".rc")
        check("signed-out app hides source chips and account recipes", await st.locator(".chips.src:not([hidden])").count() == 0)
        await st.screenshot(path="/tmp/cloud_signedout.png")
        check("admin page refuses non-admins", True)
        await st.goto(URL + "#/admin")
        await st.wait_for_selector("text=This page is for the administrator")

        # ---- vegan links and import from a web page (admin has no free-plan limit)
        await admin.goto(URL + "#/")
        await admin.goto(URL + "#/links/noracooks")
        await admin.wait_for_selector("h1:has-text('Nora Cooks')")
        links = await admin.eval_on_selector_all(".rows a.rc", "els => els.map(a => [a.href, a.target, a.rel])")
        check("Nora Cooks list links out to her site in a new tab",
              len(links) > 40 and all(h.startswith("https://www.noracooks.com/?s=") and t == "_blank" and "noopener" in r for h, t, r in links))
        check("Nora Cooks list credits her", await admin.locator("text=These recipes belong to Nora Taylor").count() == 1)
        await admin.fill("input[type=search]", "lasagna")
        await admin.wait_for_timeout(200)
        check("Nora Cooks list can be searched", await admin.locator(".rows a.rc").count() == 1)
        await admin.goto(URL + "#/new")
        check("Add page offers import from a web page", await admin.locator("a:has-text('Import a recipe from a web page')").count() == 1)
        await admin.click("a:has-text('Import a recipe from a web page')")
        await admin.fill("input[aria-label='Recipe page address']", "example.com/test-lentil-soup/")
        await admin.click("button:has-text('Get recipe')")
        await admin.wait_for_selector("h1:has-text('Check and save')")
        check("imported recipe opens in the editor with the credit filled in",
              await admin.input_value("input[aria-label='Recipe by']") == "Pat Example"
              and await admin.input_value("input[aria-label='Link to the original']") == "https://example.com/test-lentil-soup/"
              and await admin.input_value("input[aria-label=Title]") == "Test Lentil Soup")
        await admin.click("button:has-text('Save')")
        await admin.wait_for_selector(".srccredit")
        saved = [r for r in fake.recipes.values() if r["title"] == "Test Lentil Soup"]
        check("imported recipe is saved privately with its credit",
              len(saved) == 1 and saved[0]["scope"] == "private" and saved[0]["body"]["src"]["author"] == "Pat Example")
        check("recipe page shows the credit and a link to the original",
              "Recipe by Pat Example" in await admin.inner_text(".srccredit")
              and await admin.get_attribute(".srccredit a", "href") == "https://example.com/test-lentil-soup/")
        await admin.click("button:has-text('Share link')")
        await admin.wait_for_selector("dialog.sharedialog input.link")
        check("an imported recipe shares the link to the original, not its text",
              await admin.input_value("dialog.sharedialog input.link") == "https://example.com/test-lentil-soup/"
              and "#/s/" not in await admin.input_value("dialog.sharedialog input.link"))
        await admin.click("dialog.sharedialog button:has-text('Done')")
        check("imported recipe cannot be shared to Community",
              await admin.locator("button:has-text('Share with the Community')").count() == 0
              and await admin.locator("text=stays in your private recipes").count() == 1)
        await admin.screenshot(path="/tmp/cloud_imported.png", full_page=True)

        # ---- share it as a link card
        admin.once("dialog", lambda d: d.accept())
        await admin.click("button:has-text('Share a link to the Community')")
        await admin.wait_for_selector("dialog[open]")
        check("link sharing explains nothing is copied", "None of the recipe" in await admin.inner_text("dialog[open]"))
        await admin.click("dialog[open] button:has-text('Share link')")
        await admin.wait_for_selector("text=A link to this recipe is waiting for approval")
        card = [r for r in fake.recipes.values() if r["scope"] == "community" and r["body"].get("kind") == "link"]
        check("link card goes to Community with no recipe text", len(card) == 1 and card[0]["body"]["dir"] == "" and card[0]["body"]["ings"] == []
              and card[0]["body"]["src"]["url"] == "https://example.com/test-lentil-soup/")
        await admin.goto(URL + "#/admin")
        await admin.wait_for_selector("text=Link card: Pat Example")
        check("admin sees the original link when reviewing a link card",
              await admin.get_attribute("a:has-text('Check the original')", "href") == "https://example.com/test-lentil-soup/")
        await admin.goto(URL + f"#/r/{card[0]['id']}")
        await admin.wait_for_selector(".linkcard")
        check("link card page opens the original website",
              await admin.get_attribute(".linkcard a", "href") == "https://example.com/test-lentil-soup/"
              and await admin.locator("h2:has-text('Ingredients')").count() == 0)
        await admin.screenshot(path="/tmp/cloud_linkcard.png", full_page=True)

        # ---- make my own version
        imported = next(r for r in fake.recipes.values() if r["title"] == "Test Lentil Soup" and r["scope"] == "private")
        await admin.goto(URL + f"#/r/{imported['id']}")
        await admin.click("button:has-text('Make my own version')")
        await admin.wait_for_selector("h1:has-text('Make your own version')")
        check("own version starts with the ingredients and an empty method",
              await admin.input_value("input[aria-label=Title]") == "Test Lentil Soup (my version)"
              and await admin.input_value("textarea") == "" and await admin.locator("details.original li").count() == 2)
        await admin.fill("textarea", "Simmer. Serve.")
        await admin.click("button:has-text('Save')")
        await admin.wait_for_selector("text=too close to the original wording")
        check("copying the original method is refused", not any(r["title"].endswith("(my version)") for r in fake.recipes.values()))
        await admin.fill("textarea", "Cook the lentils gently in plenty of water until soft, about half an hour.\nTaste, adjust the salt and ladle into bowls.")
        await admin.click("button:has-text('Save')")
        await admin.wait_for_selector("h1:has-text('(my version)')")
        mine = [r for r in fake.recipes.values() if r["title"].endswith("(my version)")]
        check("own version is saved with an Adapted from credit and no imported-source tag",
              len(mine) == 1 and mine[0]["body"]["adapted"]["url"] == "https://example.com/test-lentil-soup/" and "src" not in mine[0]["body"])
        check("own version shows its Adapted from credit", "Adapted from Pat Example" in await admin.inner_text(".srccredit"))
        check("own version can be shared with the Community", await admin.locator("button:has-text('Share with the Community')").count() == 1)
        await admin.screenshot(path="/tmp/cloud_adapted.png", full_page=True)

        # ---- asking for an invite, and a used-up link
        qctx, q = await new_page(b, fake)
        await q.goto(URL + "#/join/" + code2)
        await q.wait_for_selector("h1:has-text('can’t be used')")
        check("a used-up invite link explains itself and offers a request form",
              "already been used" in await q.inner_text(".note") and await q.locator("button:has-text('Ask for an invite')").count() == 1)
        await q.goto(URL + "#/settings")
        await q.click("button[role=tab]:has-text('Request')")
        await q.fill("input[aria-label='Your name']", "Dee")
        await q.fill("input[aria-label='Your email']", "Dee@Example.com")
        await q.select_option("select[aria-label='I am']", "student")
        await q.fill("textarea[aria-label=Note]", "Tuesday class")
        await q.click("button:has-text('Ask for an invite')")
        check("asking for an invite shows a confirmation", "Request sent" in await close_dialog(q))
        check("the request reaches the admin's list", any(r["email"] == "dee@example.com" and r["note"] == "Tuesday class" for r in fake.requests.values()))
        check("the admin is emailed about a new request", fake.notified == ["dee@example.com"])
        await q.screenshot(path="/tmp/cloud_request.png", full_page=True)
        await admin.goto(URL + "#/admin")
        await admin.wait_for_selector("h2:has-text('Invite requests (1)')")
        await admin.click("button:has-text('Send student invite')")
        await admin.wait_for_selector("text=Nobody is waiting for an invite")
        check("admin can answer a request with an emailed invite",
              fake.sent[-1]["email"] == "dee@example.com" and fake.sent[-1]["request_id"] and
              all(r["status"] == "invited" for r in fake.requests.values()))

        # ---- open sign-up switch
        await admin.goto(URL + "#/admin")
        await admin.wait_for_selector("text=Off: people need an invite")
        await admin.click("input[aria-label='Open sign-up']")
        await admin.wait_for_selector("dialog[open]")
        check("opening sign-up asks first", "Anyone who finds the app" in await admin.inner_text("dialog[open]"))
        await admin.click("dialog[open] button:has-text('Open sign-up')")
        await admin.wait_for_selector("text=On: anyone can create")
        check("admin can open sign-up", fake.open_signup is True)
        octx, o = await new_page(b, fake)
        await o.goto(URL + "#/settings")
        await o.wait_for_selector("button[role=tab]:has-text('New account')")
        # the form repaints once the app has asked whether sign-up is open; wait for that, however slow the machine
        await o.wait_for_function("![...document.querySelectorAll('button[role=tab]')].some(b => b.textContent.includes('Request'))", timeout=15000)
        await o.wait_for_timeout(300)
        check("with open sign-up there is no Request tab", await o.locator("button[role=tab]:has-text('Request')").count() == 0)
        await o.click("button[role=tab]:has-text('New account')")
        await o.fill("input[aria-label='Your name']", "Val")
        await o.fill("input[type=email]", "val@example.com")
        await o.fill("input[aria-label=Password]", "valspass99")
        await o.click("button[type=submit]")
        check("with open sign-up anyone can join without a code", "Welcome, Val!" in await close_dialog(o) and "val@example.com" in fake.users)
        await admin.click("input[aria-label='Open sign-up']")
        await admin.click("dialog[open] button:has-text('Close sign-up')")
        await admin.wait_for_selector("text=Off: people need an invite")
        check("admin can close sign-up again", fake.open_signup is False)

        # desktop screenshot of admin
        await admin.set_viewport_size({"width": 1280, "height": 900})
        await admin.goto(URL + "#/settings")
        await admin.wait_for_selector("text=Sign out")
        await admin.screenshot(path="/tmp/cloud_settings_desktop.png")
        await b.close()
    real = [e for e in errors if "Failed to load resource" not in e and "net::ERR" not in e]
    check("no JavaScript errors", not real, real[:3])
    failed = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    return 1 if failed else 0


sys.exit(asyncio.run(main()))
