"""The category scheme: which groups exist, and how the old free-form labels map onto them.

This is the file to edit if you want different groups. Everything else reads from here.

* SECTIONS      the groups, in display order, under their section headings
* IMPLIES       a recipe in the key group is also placed in the value group(s)
* TAG_MAP       exact (lower-case) old label -> groups; an empty list means "not a category"
                (source names, months, personal markers) so the label is kept only as a search tag
* TAG_PATTERNS  regular expressions for labels not listed in TAG_MAP
* TITLE_RULES   used only when a recipe's labels gave no group at all: guess from the title
"""

SECTIONS = [
    ("Course & type", [
        "Appetizers & Snacks", "Soups & Stews", "Salads & Dressings", "Breakfast & Brunch",
        "Main Dishes", "Vegetables & Sides", "Pasta, Rice & Grains", "Breads & Baking",
        "Sauces & Condiments", "Beverages & Cocktails",
    ]),
    ("Desserts", [
        "Desserts", "Cakes", "Cookies & Bars", "Pies & Pastries", "Candy & Chocolate",
    ]),
    ("Main ingredient", [
        "Meats", "Beef", "Pork", "Poultry", "Seafood", "Eggs & Cheese", "Fruit",
    ]),
    ("Diet", [
        "Vegetarian & Vegan", "Light & Special Diets",
    ]),
    ("Cuisine", [
        "Mexican & Southwestern", "Italian", "Asian & Indian", "Cajun & Creole",
        "British, Irish & Canadian", "German & Pennsylvania Dutch", "Other World Cuisines",
    ]),
    ("Style & occasion", [
        "Quick & Easy", "Microwave & Slow Cooker", "Grill & BBQ", "Holidays & Entertaining",
    ]),
    ("Other", ["Uncategorized"]),
]

UNCATEGORIZED = "Uncategorized"

IMPLIES = {
    "Cakes": ["Desserts"],
    "Cookies & Bars": ["Desserts"],
    "Pies & Pastries": ["Desserts"],
    "Candy & Chocolate": ["Desserts"],
    "Beef": ["Meats"],
    "Pork": ["Meats"],
}

_APP = ["Appetizers & Snacks"]
_SOUP = ["Soups & Stews"]
_SALAD = ["Salads & Dressings"]
_BREAK = ["Breakfast & Brunch"]
_MAIN = ["Main Dishes"]
_VEG = ["Vegetables & Sides"]
_GRAIN = ["Pasta, Rice & Grains"]
_BREAD = ["Breads & Baking"]
_SAUCE = ["Sauces & Condiments"]
_BEV = ["Beverages & Cocktails"]
_DESSERT = ["Desserts"]
_CAKE = ["Cakes"]
_COOKIE = ["Cookies & Bars"]
_PIE = ["Pies & Pastries"]
_CANDY = ["Candy & Chocolate"]
_BEEF = ["Beef"]
_PORK = ["Pork"]
_MEAT = ["Meats"]
_POULTRY = ["Poultry"]
_SEAFOOD = ["Seafood"]
_EGGCHEESE = ["Eggs & Cheese"]
_FRUIT = ["Fruit"]
_VEGAN = ["Vegetarian & Vegan"]
_LIGHT = ["Light & Special Diets"]
_MEX = ["Mexican & Southwestern"]
_ITAL = ["Italian"]
_ASIAN = ["Asian & Indian"]
_CAJUN = ["Cajun & Creole"]
_BRIT = ["British, Irish & Canadian"]
_GERMAN = ["German & Pennsylvania Dutch"]
_WORLD = ["Other World Cuisines"]
_QUICK = ["Quick & Easy"]
_SLOW = ["Microwave & Slow Cooker"]
_GRILL = ["Grill & BBQ"]
_HOLIDAY = ["Holidays & Entertaining"]
_NONE = []

TAG_MAP = {
    # --- course & type
    "appetizers": _APP, "dips": _APP, "snacks": _APP, "nuts": _APP, "first cours": _APP,
    "soups": _SOUP, "soup": _SOUP, "stew": _SOUP, "stews": _SOUP, "soups/stews": _SOUP, "chili": _SOUP,
    "salads": _SALAD, "salad": _SALAD, "dressings": _SALAD,
    "breakfast": _BREAK, "brunch": _BREAK, "pancakes": _BREAK, "cereal": _BREAK,
    "main dish": _MAIN, "main dishes": _MAIN, "main-": _MAIN, "dish": _MAIN, "entree": _MAIN,
    "casseroles": _MAIN, "casserole": _MAIN, "sandwiches": _MAIN,
    "pizza": _MAIN + _ITAL,
    "vegetables": _VEG, "vegetable": _VEG, "side dish": _VEG, "side dishes": _VEG, "beans": _VEG,
    "lentil/bean": _VEG, "potatoes": _VEG, "asparagus": _VEG,
    "pasta": _GRAIN, "rice": _GRAIN, "grains": _GRAIN, "grain": _GRAIN, "spaghetti": _GRAIN,
    "rice/grains": _GRAIN, "barley": _GRAIN, "starch": _GRAIN,
    "breads": _BREAD, "bread": _BREAD, "muffins": _BREAD, "master mix": _BREAD, "crackers": _BREAD,
    "yeast": _BREAD, "breadmaker": _BREAD, "bread machi": _BREAD, "bakery": _BREAD,
    "mixes": _BREAD, "mix": _BREAD,
    "sauces": _SAUCE, "sauces and": _SAUCE, "salsa": _SAUCE, "condiments": _SAUCE, "spreads": _SAUCE,
    "toppings": _SAUCE, "marinades": _SAUCE, "relishes": _SAUCE, "spices": _SAUCE, "herbs": _SAUCE,
    "pickles": _SAUCE, "preserves": _SAUCE, "jams": _SAUCE,
    "beverages": _BEV, "cocktails": _BEV, "alcohol": _BEV, "drinks": _BEV,
    # --- desserts
    "desserts": _DESSERT, "deseerts": _DESSERT, "puddings": _DESSERT, "ice cream": _DESSERT,
    "cakes": _CAKE, "cheesecake": _CAKE, "cheesecakes": _CAKE,
    "cookies": _COOKIE, "bars": _COOKIE, "brownies": _COOKIE, "mrs.fields": _COOKIE,
    "pies": _PIE, "pies and ta": _PIE, "tarts": _PIE, "pastry": _PIE,
    "candies": _CANDY, "candy": _CANDY, "candy bars": _CANDY, "chocolate": _CANDY, "ghirardelli": _CANDY,
    # --- main ingredient
    "meats": _MEAT, "meat": _MEAT, "lamb": _MEAT, "veal": _MEAT, "game": _MEAT, "kangaroo": _MEAT,
    "carnivore": _MEAT,
    "beef": _BEEF, "brisket": _BEEF, "ground beef": _BEEF, "hamburger": _BEEF, "pot roast": _BEEF,
    "corned": _BEEF,
    "pork": _PORK,
    "poultry": _POULTRY, "chicken": _POULTRY, "turkey": _POULTRY,
    "seafood": _SEAFOOD, "fish": _SEAFOOD, "shellfish": _SEAFOOD, "shrimp": _SEAFOOD, "tuna": _SEAFOOD,
    "fish and se": _SEAFOOD, "fish*shell": _SEAFOOD,
    "cheese": _EGGCHEESE, "cheese/eggs": _EGGCHEESE, "eggs": _EGGCHEESE,
    "fruits": _FRUIT, "fruit": _FRUIT, "berries": _FRUIT, "plums": _FRUIT,
    # --- diet
    "vegetarian": _VEGAN, "vegan": _VEGAN, "veggie": _VEGAN, "ovo-lacto": _VEGAN, "lacto": _VEGAN,
    "ovo": _VEGAN, "opt. lacto": _VEGAN, "tofu": _VEGAN, "meat sub": _VEGAN,
    "lowcal": _LIGHT, "low-cal": _LIGHT, "lowfat": _LIGHT, "low-fat": _LIGHT, "low fat": _LIGHT,
    "fat-free": _LIGHT, "fat": _LIGHT, "low": _LIGHT, "diabetic": _LIGHT, "healthy and": _LIGHT,
    "wt-watchers": _LIGHT, "deal-a-meal": _LIGHT, "mcdougall": _LIGHT, "allergy": _LIGHT,
    "wheat-free": _LIGHT, "gluten-free": _LIGHT, "low-gluten": _LIGHT,
    # --- cuisine
    "mexican": _MEX, "tex-mex": _MEX, "texas": _MEX,
    "italian": _ITAL,
    "thai": _ASIAN, "chinese": _ASIAN, "indian": _ASIAN, "oriental": _ASIAN, "japanese": _ASIAN,
    "korean": _ASIAN, "vietnamese": _ASIAN, "east/orient": _ASIAN, "curry": _ASIAN,
    "stir-fry": _ASIAN, "stir fry": _ASIAN, "wok": _ASIAN,
    "cajun": _CAJUN, "creole": _CAJUN, "acadian": _CAJUN,
    "irish": _BRIT, "scottish": _BRIT, "british": _BRIT, "canadian": _BRIT, "french can": _BRIT,
    "nova scotia": _BRIT, "newfdland": _BRIT,
    "german": _GERMAN, "penndutch": _GERMAN, "penn-dutch": _GERMAN, "amish": _GERMAN,
    "french": _WORLD, "greek": _WORLD, "spanish": _WORLD, "jewish": _WORLD, "african-amr": _WORLD,
    "russian": _WORLD, "swedish": _WORLD, "australian": _WORLD, "moroccan": _WORLD,
    "south ameri": _WORLD, "mid-east": _WORLD, "iran": _WORLD, "hungary": _WORLD,
    "hungarian": _WORLD, "austrian": _WORLD, "hawaiian": _WORLD, "ethnic": _WORLD,
    # --- style & occasion
    "quick": _QUICK, "easy": _QUICK, "quick meals": _QUICK, "kids": _QUICK,
    "microwave": _SLOW, "slow cooker": _SLOW, "crockpot": _SLOW, "crock": _SLOW, "pressure": _SLOW,
    "bar-b-q": _GRILL, "barbecue": _GRILL, "bbq": _GRILL, "grill/broil": _GRILL,
    "holiday": _HOLIDAY, "holidays": _HOLIDAY, "christmas": _HOLIDAY, "valentine's": _HOLIDAY,
    "entertain": _HOLIDAY, "company": _HOLIDAY,
    # --- not categories: source names, months, personal markers. Kept as search tags only.
    **{t: _NONE for t in (
        "famfavorite", "favorites", "digest", "1941", "misc", "sharon", "armstrong", "none", "dec.",
        "benoit", "august", "syd's book", "prodigy", "ceideburg 2", "cyberealm", "sept.", "oct.",
        "july", "nov.", "jan.", "feb95", "mar95", "cereal box", "masterchefs", "usenet", "osg",
        "harned 1994", "mom's best", "frisco", "kaz", "info", "staebler", "mine", "relf", "baird",
        "sparkie", "kump", "kooknet", "cook4u", "upload", "e", "m", "v", "g", "test", "quiz",
        "untested", "blank", "archive", "genie", "dpiinc", "24fa", "wrv", "jackie olde", "mark's",
        "pitzer", "kohl", "chronicle", "sainsbury", "garrett", "prod.svc.", "rosie's", "coca-cola",
        "biosphere 2", "heritage", "classic", "old", "improv", "humor", "hints", "info/tips",
        "basics", "basic", "american", "swiss", "baby food", "new york", "garlic", "freezer",
        "spicy", "leftovers", "flowers", "loaf",
    )},
}

# Labels not in TAG_MAP are tried against these (first hit wins for that label).
TAG_PATTERNS = [
    (r"soup|stew|chowder|chili|bisque", _SOUP),
    (r"salad|dressing", _SALAD),
    (r"cheesecake|\bcakes?\b", _CAKE),
    (r"cookie|brownie", _COOKIE),
    (r"\bpies?\b|tart|pastr", _PIE),
    (r"candy|candies|fudge|chocolate", _CANDY),
    (r"dessert|pudding|ice cream", _DESSERT),
    (r"bread|muffin|biscuit|\brolls?\b|bak(e|ing)", _BREAD),
    (r"appetiz|snack|\bdips?\b|hors", _APP),
    (r"breakfast|brunch|pancake|waffle", _BREAK),
    (r"beef|steak|brisket|burger", _BEEF),
    (r"\bpork|\bham\b|bacon|sausage", _PORK),
    (r"chicken|turkey|poultry|duck", _POULTRY),
    (r"fish|seafood|shrimp|salmon|crab|lobster", _SEAFOOD),
    (r"vegetarian|vegan", _VEGAN),
    (r"low.?(cal|fat|carb|sod)|diabet|gluten|healthy|diet", _LIGHT),
    (r"mexic|tex.?mex", _MEX),
    (r"ital", _ITAL),
    (r"chin|thai|japan|korea|viet|asia|india|orient", _ASIAN),
    (r"cajun|creole", _CAJUN),
    (r"irish|scot|brit|canad", _BRIT),
    (r"germ|dutch|amish", _GERMAN),
    (r"cocktail|beverage|drink|punch", _BEV),
    (r"sauce|gravy|condiment|marinade|relish|salsa|jam|pickle", _SAUCE),
    (r"vegetable|side", _VEG),
    (r"pasta|noodle|rice|grain", _GRAIN),
    (r"holiday|christmas|easter|thanksgiving|party", _HOLIDAY),
    (r"bbq|barbe|grill", _GRILL),
    (r"quick|easy|fast", _QUICK),
    (r"microwave|crock|slow", _SLOW),
]

# Title words, used only for recipes whose labels produced no group.
TITLE_RULES = [
    (r"veggie|vegan|seitan|tempeh|\btofu\b|\bvlf\b|meatless", _VEGAN),
    (r"\bcheesecakes?\b|\bcakes?\b|cupcake|torte", _CAKE),
    (r"cookie|brownie|\bbars\b|biscotti", _COOKIE),
    (r"\bpies?\b|\btarts?\b|cobbler|crisp", _PIE),
    (r"candy|fudge|truffle|toffee|brittle", _CANDY),
    (r"pudding|custard|mousse|ice cream|sorbet", _DESSERT),
    (r"soup|stew|chowder|chili|bisque|gumbo", _SOUP),
    (r"salad|slaw|vinaigrette", _SALAD),
    (r"pancake|waffle|omelet|omelette|french toast|granola|crepe|mush\b|porridge", _BREAK),
    (r"bread|muffin|biscuit|\brolls?\b|scone|bun\b|buns\b|baking mix", _BREAD),
    (r"pizza", _MAIN + _ITAL),
    (r"lasagn|spaghetti|pasta|macaroni|noodle|fettuccin|ravioli", _GRAIN),
    (r"\brice\b|risotto|pilaf|couscous|barley|grain|\boat(s|meal)?\b|cereal|polenta|quinoa|gallo pinto", _GRAIN),
    (r"chicken|turkey|\bduck\b", _POULTRY),
    (r"\bbeef\b|steak|brisket|meatloaf|meatball|burger|pot roast", _BEEF),
    (r"\bpork\b|\bham\b|bacon|sausage|\bribs?\b|scrapple", _PORK),
    (r"salmon|shrimp|\bfish\b|tuna|crab|lobster|scallop|clam|oyster|trout|\bcod\b", _SEAFOOD),
    (r"quiche|frittata|\beggs?\b|souffle|cheese", _EGGCHEESE),
    (r"margarita|smoothie|lemonade|punch|\bcoffee\b|\bwine\b|cocktails\b", _BEV),
    (r"sauce|gravy|relish|salsa|marinade|\bjam\b|jelly|chutney|pickle|butter\b|dressing|syrup|seasoning", _SAUCE),
    (r"\bdips?\b|spread|hummus|guacamole|appetizer|canape|nachos", _APP),
    (r"casserole|stir.?fry|roast|enchilada|taco|burrito", _MAIN),
    (r"quick meal|quick & easy|\beasy\b", _QUICK),
    (r"potato|beans?\b|corn\b|squash|broccoli|spinach|carrot|cabbage|asparagus|mushroom|lentil|chick ?peas?", _VEG),
]
