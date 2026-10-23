import sqlite3
import os
from datetime import datetime, timedelta

import os
DB_PATH = os.getenv("DB_PATH", "db/pantry.db")

# Use HF Spaces persistent storage if available
if os.path.exists("/data"):
    DB_PATH = "/data/pantry.db"

SHELF_LIFE = {
    "spinach": 5, "leaves": 5, "chillies": 7, "tomato": 7,
    "tomatoes": 7, "carrots": 14, "carrot": 14, "milk": 7,
    "paneer": 5, "yoghurt": 14, "avocado": 5, "pears": 7,
    "almonds": 180, "cashew": 180, "nuts": 180, "seeds": 365,
    "paste": 365, "rice": 180, "lentils": 365, "gourd": 5,
    "aubergine": 7, "beans": 5, "jeera": 365, "dhaniya": 365,
}

def estimate_expiry(item_name: str) -> str:
    name_lower = item_name.lower()
    for key, days in SHELF_LIFE.items():
        if key in name_lower:
            return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
    return (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")

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

def format_parsed_items(items):
    lines = []
    for item in items:
        emoji, days = expiry_status(item.get("expiry", ""))
        if days <= 1:
            label = "expires today"
        elif days <= 5:
            label = f"expires in {days} days"
        else:
            label = f"expires in {days} days"
        lines.append(f"{emoji} {item['name']} (qty: {item.get('quantity','1')}) — {label}")
    return "\n".join(lines)

def init_db(db_path=DB_PATH):
    os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS pantry (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_name TEXT UNIQUE,
        quantity TEXT,
        price TEXT,
        purchase_date TEXT,
        estimated_expiry TEXT,
        shop TEXT,
        used INTEGER DEFAULT 0
    )''')
    conn.commit()
    conn.close()

def save_to_db(items: list, shop: str, db_path=DB_PATH):
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    for item in items:
        c.execute('''
            INSERT INTO pantry (item_name, quantity, price, purchase_date, estimated_expiry, shop)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(item_name) DO UPDATE SET
                quantity = quantity || '+' || excluded.quantity,
                estimated_expiry = excluded.estimated_expiry,
                purchase_date = excluded.purchase_date
        ''', (
            item["name"],
            item.get("quantity", "1"),
            item.get("price", ""),
            datetime.now().strftime("%Y-%m-%d"),
            item.get("expiry", ""),
            shop
        ))
    conn.commit()
    conn.close()
    return len(items)

def get_pantry():
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT item_name, quantity, estimated_expiry, shop FROM pantry WHERE used=0 ORDER BY estimated_expiry ASC")
    rows = c.fetchall()
    conn.close()
    
    if not rows:
        return "Your pantry is empty — scan a receipt to get started."
    
    red = [r for r in rows if expiry_status(r[2])[1] <= 1]
    amber = [r for r in rows if 1 < expiry_status(r[2])[1] <= 5]
    green = [r for r in rows if expiry_status(r[2])[1] > 5]

    lines = []
    
    # Summary
    lines.append(f"📦 {len(rows)} items in pantry")
    lines.append(f"🔴 {len(red)} expiring today  🟡 {len(amber)} expiring soon  🟢 {len(green)} fine")
    lines.append("─" * 40)

    if red:
        lines.append("\n🔴 COOK TODAY:")
        for r in red:
            lines.append(f"  • {r[0]} (x{r[1]})")

    if amber:
        lines.append("\n🟡 USE THIS WEEK:")
        for r in amber:
            emoji, days = expiry_status(r[2])
            lines.append(f"  • {r[0]} (x{r[1]}) — {days} days left")

    if green:
        lines.append("\n🟢 ALL GOOD:")
        for r in green:
            emoji, days = expiry_status(r[2])
            lines.append(f"  • {r[0]} (x{r[1]}) — {days} days")

    return "\n".join(lines)

def mark_used(item_name):
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE pantry SET used=1 WHERE item_name=? AND used=0", (item_name,))
    conn.commit()
    conn.close()
    return get_pantry()