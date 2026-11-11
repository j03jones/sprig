"""Outside recipe collections the app links to (titles and links only, no recipe content).

Each entry opens the recipe on the author's own website, so the author keeps the visit and the
credit. Links use the site's own search so they keep working if a page address changes.
tools/gen_unitdata.py copies this into web/js/linkdata.js for the phone app.
"""
from urllib.parse import quote_plus

NORA_COOKS = {
    "id": "noracooks",
    "site": "Nora Cooks",
    "author": "Nora Taylor",
    "home": "https://www.noracooks.com/",
    "group": "Vegetarian & Vegan",
    "blurb": "Easy vegan comfort food by Nora Taylor. Every recipe opens on her website.",
    "sections": [
        ("Main dishes", [
            "The Best Vegan Mac and Cheese", "The Best Vegan Lasagna", "Vegan Buffalo Mac and Cheese",
            "Vegan Chicken Nuggets", "Vegan Bolognese", "Vegan Pad Thai", "Chili Cornbread Casserole (Vegan)",
            "Vegan Eggplant Parmesan", "Vegan Paella", "Grilled Tofu", "Cheesy Broccoli Rice Vegan Casserole",
            "Vegan Pizza with Tempeh Sausage", "Vegan Burrito Bowl", "Vegan Burritos", "Vegan Philly Cheesesteak",
            "Creamy Skillet White Beans with Spinach and Basil", "15 Minute Tahini Pasta",
            "Impossible Meatloaf (Stuffed with Cheese)", "Easy Vegan Meatballs", "Vegan Stuffed Jumbo Shells with Spinach",
        ]),
        ("Soups & lunch", [
            "Veggie Chili", "Instant Pot Tomato Soup (Vegan)", "Vegan Bánh Mì",
        ]),
        ("Appetizers & dips", [
            "Vegan Brie Dip with Pepper Jelly", "Vegan Stuffed Mushrooms", "Vegan Sausage Rolls", "Easy Salsa Recipe",
            "5 Ingredient Vegan Queso", "Vegan Queso Blanco", "Mexican Street Corn Dip (Dairy Free)",
            "Easy Vegan Nacho Cheese Sauce",
        ]),
        ("Breakfast", [
            "Pumpkin Coffee Cake", "1 Bowl Vegan Blueberry Muffins", "Vegan Breakfast Sausage", "Vegan Egg Muffins",
            "Vegan Buckwheat Pancakes", "Freezer Whole Grain Pancakes",
        ]),
        ("Desserts", [
            "Vegan Chocolate Cake", "Vegan Chocolate Sheet Cake", "Vegan Blueberry Cake",
            "Easy Vanilla Vegan Gluten Free Cake", "Vegan Oreo Cheesecake", "The Best Vegan Tiramisu",
            "Vegan Chocolate Tart", "Vegan Banana Pudding", "Vegan Bread Pudding", "Easy Blackberry Cobbler",
            "Vegan Carmelitas", "Vegan Strawberry Cheesecake Crumble Bars", "Vegan Peanut Butter Cups",
            "Funfetti Vegan Cupcakes", "Vegan Mint Chocolate Oreo Cupcakes",
        ]),
        ("Cookies", [
            "Vegan Peanut Butter Cookies (1 Bowl)", "Vegan Lemon Shortbread Cookies",
            "Raspberry Almond Vegan Thumbprint Cookies",
        ]),
        ("Basics, sides & drinks", [
            "Vegan Feta Cheese", "Heavy Cream Substitute (Vegan)", "Vegan Cheddar Bay Biscuits", "Vegan Hot Chocolate",
        ]),
    ],
}

COLLECTIONS = [NORA_COOKS]


def link_for(collection: dict, title: str) -> str:
    """Search link on the author's site for one recipe title."""
    return f"{collection['home']}?s={quote_plus(title)}"


def as_json() -> list:
    """The collections with every link filled in, for the phone app."""
    out = []
    for c in COLLECTIONS:
        out.append({
            **{k: v for k, v in c.items() if k != "sections"},
            "sections": [[name, [[t, link_for(c, t)] for t in titles]] for name, titles in c["sections"]],
        })
    return out
