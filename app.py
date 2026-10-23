import gradio as gr
import modal
import io
import sys
import os
import sqlite3
import concurrent.futures
import soundfile as sf
import numpy as np
from PIL import Image as PILImage

sys.path.append(os.path.dirname(__file__))
from utils import (
    estimate_expiry, format_parsed_items,
    save_to_db, expiry_status, init_db
)

os.makedirs("/data", exist_ok=True)
DB_PATH = "/data/pantry.db"

CHARACTERS = {
    "Grandma (Ammamma)": "Warm loving grandma who hates food waste.",
    "Chef": "Sharp professional chef. Direct and brilliant.",
    "Fitness Coach": "Enthusiastic fitness coach obsessed with gains.",
    "Food Critic": "Pompous but secretly warm food critic.",
}

CUISINES = ["South Indian", "North Indian", "Italian", "Mediterranean", "East Asian", "Surprise me"]

# TTS backend: True = VoxCPMService class (OpenBMB VoxCPM2, full-recipe narration)
# False = legacy "text_to_speech" function (Coqui XTTS-v2, dialogue only)
USE_VOXCPM = True

CHAR_EMOJI = {
    "Grandma (Ammamma)": "🧓",
    "Chef": "👨‍🍳",
    "Fitness Coach": "💪",
    "Food Critic": "⭐"
}


def get_pantry_display():
    init_db(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT item_name, quantity, estimated_expiry FROM pantry WHERE used=0 ORDER BY estimated_expiry ASC")
    rows = c.fetchall()
    conn.close()
    if not rows:
        return "Your pantry is empty — scan a receipt to get started."

    red = [r for r in rows if expiry_status(r[2])[1] <= 1]
    amber = [r for r in rows if 1 < expiry_status(r[2])[1] <= 5]
    green = [r for r in rows if expiry_status(r[2])[1] > 5]

    lines = []
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
            _, days = expiry_status(r[2])
            lines.append(f"  • {r[0]} (x{r[1]}) — {days} days left")

    if green:
        lines.append("\n🟢 ALL GOOD:")
        for r in green:
            _, days = expiry_status(r[2])
            lines.append(f"  • {r[0]} (x{r[1]}) — {days} days")

    return "\n".join(lines)


def mark_used_local(item_name):
    init_db(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE pantry SET used=1 WHERE item_name=? AND used=0", (item_name,))
    rows_affected = c.rowcount
    conn.commit()
    conn.close()
    return get_pantry_display()


def parse_receipt_gradio(image):
    if image is None:
        return "Please upload a receipt image.", [], ""
    try:
        img_bytes = io.BytesIO()
        if not isinstance(image, PILImage.Image):
            image = PILImage.fromarray(image)
        image.save(img_bytes, format="JPEG")
        img_bytes = img_bytes.getvalue()

        parse_fn = modal.Function.from_name("zerowastekitchen", "parse_receipt")
        result = parse_fn.remote(img_bytes)

        nemotron_cls = modal.Cls.from_name("zerowastekitchen", "NemotronService")
        item_names = [i["name"] for i in result.get("items", [])]
        expiry_map = nemotron_cls().estimate_expiry.remote(item_names)

        for item in result.get("items", []):
            item["expiry"] = expiry_map.get(
                item["name"],
                estimate_expiry(item["name"])
            )

        save_to_db(result["items"], result.get("shop", "unknown"), DB_PATH)

        n = len(result["items"])
        shop = result.get("shop", "unknown")
        status = f"✅ {n} item{'s' if n != 1 else ''} saved to pantry (from {shop})"
        return format_parsed_items(result["items"]), result["items"], status

    except Exception as e:
        return f"Error: {str(e)}", [], "❌ Nothing saved — see error above"


def generate_recipe_with_audio(character, cuisine, use_expiring, read_full_recipe):
    try:
        init_db(DB_PATH)
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            "SELECT item_name, quantity, estimated_expiry FROM pantry WHERE used=0 ORDER BY estimated_expiry ASC"
        )
        rows = c.fetchall()
        conn.close()

        if not rows:
            return "Your pantry is empty — scan a receipt first.", None

        all_items = [{"name": r[0], "quantity": r[1], "expiry": r[2]} for r in rows]

        for item in all_items:
            _, days = expiry_status(item["expiry"])
            item["days_left"] = days

        if use_expiring:
            featured = [i for i in all_items if i["days_left"] <= 5]
            if not featured:
                featured = all_items[:1]
        else:
            # Checkbox off: feature a varied selection from the whole pantry
            import random
            featured = random.sample(all_items, min(3, len(all_items)))

        expiring = featured
        expiring_names = [i["name"] for i in featured]

        dialogue_fn = modal.Function.from_name("zerowastekitchen", "generate_dialogue")
        recipe_fn = modal.Cls.from_name("zerowastekitchen", "NemotronService")().generate_recipe
        if USE_VOXCPM:
            tts_fn = modal.Cls.from_name("zerowastekitchen", "VoxCPMService")().narrate
        else:
            tts_fn = modal.Function.from_name("zerowastekitchen", "text_to_speech")

        with concurrent.futures.ThreadPoolExecutor() as executor:
            dialogue_future = executor.submit(
                dialogue_fn.remote, character, expiring_names[:5], cuisine
            )
            recipe_future = executor.submit(
                recipe_fn.remote, all_items, expiring, cuisine
            )
            dialogue = dialogue_future.result()
            recipe = recipe_future.result()

        speech_text = f"{dialogue}\n{recipe}" if read_full_recipe else dialogue
        audio_bytes = tts_fn.remote(speech_text, character)

        emoji = CHAR_EMOJI.get(character, "🧓")
        output = f"{emoji} {character} says:\n\"{dialogue}\"\n\n"
        output += recipe

        buf = io.BytesIO(audio_bytes)
        audio_np, sr = sf.read(buf)

        return output, (sr, audio_np)

    except Exception as e:
        return f"Error: {str(e)}", None


with gr.Blocks(title="ZeroWasteKitchen", theme=gr.themes.Soft()) as app:
    items_state = gr.State([])

    gr.Markdown("# 🌿 ZeroWasteKitchen\n*Scan receipts · track expiry · cook with personality*")

    with gr.Tabs():

        with gr.Tab("1 · Upload receipt"):
            gr.Markdown("### Upload your grocery receipt")
            receipt_image = gr.Image(
                label="Receipt photo",
                type="pil",
                sources=["upload", "webcam"]
            )
            parse_btn = gr.Button("Parse receipt", variant="primary")
            parsed_output = gr.Textbox(
                label="Parsed items",
                lines=10,
                interactive=False
            )
            save_status = gr.Textbox(
                label="",
                interactive=False,
                max_lines=1
            )
            parse_btn.click(
                fn=parse_receipt_gradio,
                inputs=[receipt_image],
                outputs=[parsed_output, items_state, save_status]
            )

        with gr.Tab("2 · My pantry"):
            gr.Markdown("### Your current pantry")
            refresh_btn = gr.Button("Refresh", size="sm")
            pantry_output = gr.Textbox(
                label="Pantry status",
                lines=15,
                interactive=False,
                value="Click Refresh to load pantry"
            )
            with gr.Row():
                mark_item = gr.Textbox(
                    label="Item name to mark as used",
                    placeholder="e.g. CURRIS LEAVES PACKET"
                )
                mark_btn = gr.Button("Mark as used", size="sm")
            refresh_btn.click(fn=get_pantry_display, outputs=[pantry_output])
            mark_btn.click(
                fn=mark_used_local,
                inputs=[mark_item],
                outputs=[pantry_output]
            )

        with gr.Tab("3 · Cook"):
            gr.Markdown("### Pick your character and cuisine")
            with gr.Row():
                character = gr.Dropdown(
                    choices=list(CHARACTERS.keys()),
                    value="Grandma (Ammamma)",
                    label="Character"
                )
                cuisine = gr.Dropdown(
                    choices=CUISINES,
                    value="South Indian",
                    label="Cuisine"
                )
            use_expiring = gr.Checkbox(
                label="Prioritise expiring items",
                value=True
            )
            read_full_recipe = gr.Checkbox(
                label="🔊 Read the full recipe aloud (takes longer)",
                value=True
            )
            cook_btn = gr.Button(
                "Cook with what I have",
                variant="primary"
            )
            recipe_output = gr.Textbox(
                label="Your recipe",
                lines=20,
                interactive=False
            )
            audio_output = gr.Audio(
                label="🔊 Hear it",
                type="numpy",
                autoplay=True
            )
            cook_btn.click(
                fn=generate_recipe_with_audio,
                inputs=[character, cuisine, use_expiring, read_full_recipe],
                outputs=[recipe_output, audio_output]
            )

    app.load(fn=get_pantry_display, outputs=[pantry_output])

if __name__ == "__main__":
    app.launch(server_name="0.0.0.0")