import gradio as gr
import sqlite3
import json
import os
from datetime import datetime, timedelta

DB_PATH = "db/pantry.db"

def init_db():
    os.makedirs("db", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS pantry (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_name TEXT,
        quantity TEXT,
        purchase_date TEXT,
        estimated_expiry TEXT,
        category TEXT,
        used INTEGER DEFAULT 0
    )''')
    conn.commit()
    conn.close()

SHELF_LIFE = {
    "spinach": 5, "baby spinach": 5, "tomatoes": 7, "cherry tomatoes": 7,
    "yoghurt": 14, "greek yoghurt": 14, "milk": 7, "eggs": 21,
    "chicken": 2, "basmati rice": 180, "rice": 180, "lentils": 365,
    "coconut milk": 365, "butter": 30, "cheese": 21, "bread": 7,
    "onion": 30, "garlic": 60, "potato": 30, "carrot": 21,
    "cucumber": 7, "pepper": 7, "courgette": 7, "mushroom": 5,
}

def estimate_expiry(item_name):
    name_lower = item_name.lower()
    for key, days in SHELF_LIFE.items():
        if key in name_lower:
            expiry = datetime.now() + timedelta(days=days)
            return expiry.strftime("%Y-%m-%d")
    expiry = datetime.now() + timedelta(days=7)
    return expiry.strftime("%Y-%m-%d")

def expiry_status(expiry_str):
    try:
        expiry = datetime.strptime(expiry_str, "%Y-%m-%d")
        days_left = (expiry - datetime.now()).days
        if days_left <= 1:
            return "🔴", days_left
        elif days_left <= 5:
            return "🟡", days_left
        else:
            return "🟢", days_left
    except:
        return "🟢", 999

DUMMY_ITEMS = [
    {"name": "Baby spinach 200g", "qty": "1", "expiry": (datetime.now() + timedelta(days=0)).strftime("%Y-%m-%d")},
    {"name": "Cherry tomatoes 400g", "qty": "1", "expiry": (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")},
    {"name": "Greek yoghurt 500g", "qty": "1", "expiry": (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d")},
    {"name": "Basmati rice 1kg", "qty": "1", "expiry": (datetime.now() + timedelta(days=180)).strftime("%Y-%m-%d")},
    {"name": "Coconut milk 400ml", "qty": "2", "expiry": (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")},
]

CHARACTERS = {
    "Grandma (Paati)": "You are Paati, a warm but judgemental South Indian grandma. You speak in a mix of English with occasional Tamil words. You scold gently about food waste, express love through feeding people, and always know the best traditional recipe for any ingredient.",
    "Chef": "You are a sharp, no-nonsense professional chef. You are direct, technically precise, slightly impatient with bad ingredients, but brilliant at making something out of nothing.",
    "Fitness Coach": "You are an enthusiastic fitness coach. Every recipe must be high protein, low waste, macro-balanced. You relate everything back to gains, recovery, and clean eating.",
    "Food Critic": "You are a pompous but secretly warm food critic. You critique the ingredients dramatically before reluctantly producing a brilliant recipe.",
}

CUISINES = ["South Indian", "North Indian", "Italian", "Mediterranean", "East Asian", "Surprise me"]

def parse_receipt(image):
    if image is None:
        return format_parsed_items(DUMMY_ITEMS), DUMMY_ITEMS
    return format_parsed_items(DUMMY_ITEMS), DUMMY_ITEMS

def format_parsed_items(items):
    lines = []
    for item in items:
        emoji, days = expiry_status(item["expiry"])
        if days <= 1:
            label = "expires today"
        elif days <= 5:
            label = f"expires in {days} days"
        else:
            label = f"expires in {days} days"
        lines.append(f"{emoji} {item['name']} (qty: {item['qty']}) — {label}")
    return "\n".join(lines)

def save_to_pantry(items_state):
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    for item in items_state:
        c.execute('''INSERT INTO pantry (item_name, quantity, purchase_date, estimated_expiry, category)
                     VALUES (?, ?, ?, ?, ?)''',
                  (item["name"], item["qty"], datetime.now().strftime("%Y-%m-%d"),
                   item["expiry"], "general"))
    conn.commit()
    conn.close()
    return "Saved to pantry"

def get_pantry():
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, item_name, quantity, estimated_expiry FROM pantry WHERE used=0 ORDER BY estimated_expiry ASC")
    rows = c.fetchall()
    conn.close()
    if not rows:
        return "Your pantry is empty — scan a receipt to get started."
    lines = []
    expiring_today = 0
    for row in rows:
        emoji, days = expiry_status(row[3])
        if days <= 1:
            expiring_today += 1
            label = "TODAY"
        elif days <= 5:
            label = f"{days} days"
        else:
            label = f"{days} days"
        lines.append(f"{emoji} {row[1]} (x{row[2]}) — {label}")
    header = ""
    if expiring_today > 0:
        header = f"🚨 {expiring_today} item(s) expiring today — cook them now!\n\n"
    return header + "\n".join(lines)

def mark_used(item_name):
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE pantry SET used=1 WHERE item_name=? AND used=0", (item_name,))
    conn.commit()
    conn.close()
    return get_pantry()

def generate_recipe(character, cuisine, use_expiring):
    expiring = [i for i in DUMMY_ITEMS if expiry_status(i["expiry"])[1] <= 5]
    all_items = DUMMY_ITEMS
    items_to_use = expiring if use_expiring and expiring else all_items

    char_voice = {
        "Grandma (Paati)": "🧓 Paati says:\n\"Ayo! That spinach is dying and you haven't touched it? Shame on you! Come, I'll show you a proper keerai kootu.\"\n\n",
        "Chef": "👨‍🍳 Chef says:\n\"Right. You've got spinach on its last legs and some tomatoes. We're making something. Pay attention.\"\n\n",
        "Fitness Coach": "💪 Coach says:\n\"Perfect! Spinach is iron-rich, tomatoes are antioxidants. We're making a macro-friendly power bowl. Let's GO.\"\n\n",
        "Food Critic": "⭐ Critic says:\n\"These ingredients are... humble. And yet. With sufficient technique, even the wilting spinach can achieve greatness.\"\n\n",
    }

    cuisine_recipes = {
        "South Indian": {
            "name": "Keerai kootu with coconut dal",
            "ingredients": ["Baby spinach", "Cherry tomatoes", "Coconut milk", "Basmati rice", "Mustard seeds", "Curry leaves", "Turmeric"],
            "steps": [
                "Blanch spinach for 2 mins, drain and roughly chop.",
                "Heat oil, temper mustard seeds and curry leaves.",
                "Add tomatoes, cook till soft — about 5 mins.",
                "Add coconut milk and turmeric, simmer 3 mins.",
                "Fold in spinach, season with salt.",
                "Serve over steamed basmati rice."
            ]
        },
        "Italian": {
            "name": "Spinach and tomato pasta",
            "ingredients": ["Baby spinach", "Cherry tomatoes", "Garlic", "Olive oil", "Pasta", "Parmesan"],
            "steps": [
                "Cook pasta al dente, reserve 1 cup pasta water.",
                "Sauté garlic in olive oil until golden.",
                "Add tomatoes, cook until they burst — 4 mins.",
                "Wilt spinach in the pan — 1 min.",
                "Toss pasta with vegetables and pasta water.",
                "Finish with parmesan and black pepper."
            ]
        },
    }

    recipe = cuisine_recipes.get(cuisine, cuisine_recipes["South Indian"])
    voice = char_voice.get(character, char_voice["Grandma (Paati)"])

    expiring_tags = [f"⚠️ {i['name']}" for i in items_to_use if expiry_status(i["expiry"])[1] <= 3]

    output = voice
    output += f"🍽️ Recipe: {recipe['name']}\n"
    output += f"Cuisine: {cuisine}\n\n"
    if expiring_tags:
        output += f"Using before they go: {', '.join(expiring_tags)}\n\n"
    output += "Ingredients:\n"
    for ing in recipe["ingredients"]:
        output += f"  • {ing}\n"
    output += "\nSteps:\n"
    for i, step in enumerate(recipe["steps"], 1):
        output += f"  {i}. {step}\n"
    output += "\n[🔊 Bark TTS voice coming soon]"
    return output

init_db()

with gr.Blocks(title="ZeroWasteKitchen", theme=gr.themes.Soft()) as app:
    items_state = gr.State(DUMMY_ITEMS)

    gr.Markdown("# 🌿 ZeroWasteKitchen\n*Scan receipts · track expiry · cook with personality*")

    with gr.Tabs():

        with gr.Tab("1 · Upload receipt"):
            gr.Markdown("### Upload your grocery receipt")
            receipt_image = gr.Image(label="Receipt photo", type="pil", sources=["upload", "webcam"])
            parse_btn = gr.Button("Parse receipt", variant="primary")
            parsed_output = gr.Textbox(label="Parsed items", lines=8, interactive=False)
            save_btn = gr.Button("Save to pantry →")
            save_status = gr.Textbox(label="", interactive=False, max_lines=1)

            parse_btn.click(fn=parse_receipt, inputs=[receipt_image], outputs=[parsed_output, items_state])
            save_btn.click(fn=lambda s: save_to_pantry(s), inputs=[items_state], outputs=[save_status])

        with gr.Tab("2 · My pantry"):
            gr.Markdown("### Your current pantry")
            refresh_btn = gr.Button("Refresh", size="sm")
            pantry_output = gr.Textbox(label="Pantry status", lines=12, interactive=False, value=get_pantry())
            with gr.Row():
                mark_item = gr.Textbox(label="Item name to mark as used", placeholder="e.g. Baby spinach 200g")
                mark_btn = gr.Button("Mark as used", size="sm")
            refresh_btn.click(fn=get_pantry, outputs=[pantry_output])
            mark_btn.click(fn=mark_used, inputs=[mark_item], outputs=[pantry_output])

        with gr.Tab("3 · Cook"):
            gr.Markdown("### Pick your character and cuisine")
            with gr.Row():
                character = gr.Dropdown(
                    choices=list(CHARACTERS.keys()),
                    value="Grandma (Paati)",
                    label="Character"
                )
                cuisine = gr.Dropdown(
                    choices=CUISINES,
                    value="South Indian",
                    label="Cuisine"
                )
            use_expiring = gr.Checkbox(label="Prioritise expiring items", value=True)
            cook_btn = gr.Button("Cook with what I have", variant="primary")
            recipe_output = gr.Textbox(label="Your recipe", lines=20, interactive=False)
            cook_btn.click(fn=generate_recipe, inputs=[character, cuisine, use_expiring], outputs=[recipe_output])

if __name__ == "__main__":
    app.launch()