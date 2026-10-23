import modal
from modal import Volume
from pathlib import Path

app = modal.App("zerowastekitchen")

model_volume = Volume.from_name("model-cache", create_if_missing=True)
MODEL_DIR = Path("/models")

download_image = (
    modal.Image.debian_slim()
    .pip_install("huggingface_hub", "hf_transfer")
    .env({"HF_HUB_ENABLE_HF_TRANSFER": "1"})
)

base_image = (
    modal.Image.debian_slim()
    .pip_install(
        "torch", "torchvision", "transformers>=5.7.0",
        "accelerate", "pillow", "einops", "sentencepiece",
        "timm", "open_clip_torch", "av", "numpy",
        "huggingface_hub", "hf_transfer"
    )
    .env({"HF_HUB_ENABLE_HF_TRANSFER": "1"})
)

tts_image = (
    modal.Image.debian_slim()
    .apt_install("libsndfile1", "ffmpeg")
    .pip_install(
        "torch==2.5.0",
        "torchaudio==2.5.0",
        "numpy",
        "soundfile",
        "transformers==4.40.0",
        "click",
        "coqui-tts"
    )
)


@app.function(
    image=download_image,
    volumes={str(MODEL_DIR): model_volume},
    secrets=[modal.Secret.from_name("huggingface-secret")],
    timeout=3600
)
def download_models():
    from huggingface_hub import snapshot_download
    import os
    token = os.environ["HF_TOKEN"]

    print("Downloading MiniCPM-V 4.6...")
    snapshot_download(
        "openbmb/MiniCPM-V-4.6",
        local_dir=str(MODEL_DIR / "minicpm-v"),
        token=token
    )
    print("Downloading tiny-aya-fire...")
    snapshot_download(
        "CohereLabs/tiny-aya-fire",
        local_dir=str(MODEL_DIR / "tiny-aya-fire"),
        token=token
    )
    print("Downloading Nemotron 4B...")
    snapshot_download(
        "nvidia/Nemotron-Mini-4B-Instruct",
        local_dir=str(MODEL_DIR / "nemotron-4b"),
        token=token
    )
    model_volume.commit()
    print("All models downloaded.")


@app.function(
    gpu="T4",
    image=base_image,
    timeout=180,
    memory=12288,
    volumes={str(MODEL_DIR): model_volume},
    secrets=[modal.Secret.from_name("huggingface-secret")]
)
def parse_receipt(image_bytes: bytes) -> dict:
    import torch
    from transformers import AutoModelForImageTextToText, AutoProcessor
    from PIL import Image
    import io, json, re

    processor = AutoProcessor.from_pretrained(
        str(MODEL_DIR / "minicpm-v"),
        trust_remote_code=True
    )
    model = AutoModelForImageTextToText.from_pretrained(
        str(MODEL_DIR / "minicpm-v"),
        torch_dtype="auto",
        device_map="auto",
        trust_remote_code=True
    )

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")

    prompt = """Extract all grocery items from this receipt.
Return as JSON only, no other text:
{
    "shop": "shop name if visible",
    "items": [
        {"name": "item name", "quantity": "1", "price": "price if visible"}
    ]
}"""

    messages = [{"role": "user", "content": [
        {"type": "image", "image": img},
        {"type": "text", "text": prompt}
    ]}]

    text = processor.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    inputs = processor(
        text=text, images=[img], return_tensors="pt"
    ).to(model.device)

    with torch.no_grad():
        outputs = model.generate(**inputs, max_new_tokens=2048)

    result = processor.decode(outputs[0], skip_special_tokens=True)

    try:
        result = result.split("</think>")[-1].strip()
        json_start = result.find("{")
        json_end = result.rfind("}") + 1
        raw_json = result[json_start:json_end]
        raw_json = re.sub(r'}\s*{', '},{', raw_json)
        parsed = json.loads(raw_json)

        parsed["items"] = [
            item for item in parsed.get("items", [])
            if item.get("name", "").strip()
            and not any(x in item["name"].upper() for x in [
                "TOTAL", "CARD", "CREDIT", "DISCOUNT", "CASH",
                "CHANGE", "VAT", "RECEIPT", "THANK", "STORE"
            ])
            and item["name"].strip().upper() not in ["WHOLE", ""]
            and not item["name"].startswith("0.")
            and not item["name"].startswith("0 ")
            and "kg @" not in item["name"].lower()
            and "£" not in item["name"]
        ]
        return parsed
    except Exception as e:
        return {"shop": "unknown", "items": [], "raw": str(e)}


@app.function(
    gpu="T4",
    image=base_image,
    timeout=300,
    memory=8192,
    volumes={str(MODEL_DIR): model_volume},
    secrets=[modal.Secret.from_name("huggingface-secret")]
)
def estimate_expiry_llm(item_names: list) -> dict:
    import torch
    from transformers import AutoTokenizer, AutoModelForCausalLM
    from datetime import datetime, timedelta

    tokenizer = AutoTokenizer.from_pretrained(str(MODEL_DIR / "nemotron-4b"))
    model = AutoModelForCausalLM.from_pretrained(
        str(MODEL_DIR / "nemotron-4b"),
        torch_dtype=torch.float16,
        device_map="auto"
    )

    expiry_map = {}
    for item in item_names:
        prompt = f"""<|system|>
You are a food safety expert.
<|user|>
How many days does "{item}" last in a refrigerator after purchase?
Reply with a single integer only. No explanation.
<|assistant|>
"""
        inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=10,
                pad_token_id=tokenizer.eos_token_id,
                eos_token_id=tokenizer.eos_token_id
            )
        response = tokenizer.decode(
            outputs[0][inputs["input_ids"].shape[1]:],
            skip_special_tokens=True
        ).strip()

        try:
            days = int(''.join(filter(str.isdigit, response)))
            days = max(1, min(days, 365))
        except:
            days = 7

        expiry_map[item] = (
            datetime.now() + timedelta(days=days)
        ).strftime("%Y-%m-%d")

    return expiry_map


@app.function(
    gpu="T4",
    image=base_image,
    timeout=180,
    memory=8192,
    volumes={str(MODEL_DIR): model_volume},
    secrets=[modal.Secret.from_name("huggingface-secret")]
)
def generate_dialogue(character: str, expiring_items: list, cuisine: str) -> str:
    import torch
    import re
    from transformers import AutoTokenizer, AutoModelForCausalLM

    tokenizer = AutoTokenizer.from_pretrained(str(MODEL_DIR / "tiny-aya-fire"))
    model = AutoModelForCausalLM.from_pretrained(
        str(MODEL_DIR / "tiny-aya-fire"),
        torch_dtype=torch.float16,
        device_map="auto"
    )

    character_prompts = {
        "Grandma (Ammamma)": """You are Ammamma, a warm loving grandma who hates food waste.
Speak warmly in English. Mention the specific expiring items by name.
Express urgency about using them before they go bad.
Show love and excitement about cooking. 2-3 sentences only. Be specific and concise.""",
        "Chef": "You are a sharp professional chef. Be direct and impatient but brilliant. Mention the expiring items. 2-3 sentences only.",
        "Fitness Coach": "You are an enthusiastic fitness coach obsessed with gains and clean eating. Mention the expiring items. 2-3 sentences only.",
        "Food Critic": "You are a pompous food critic who is secretly warm. Be dramatic about the expiring items. 2-3 sentences only.",
    }

    system = character_prompts.get(character, character_prompts["Grandma (Ammamma)"])
    items_str = ", ".join(expiring_items[:5])

    prompt = f"""<|system|>
{system}
<|user|>
These grocery items are expiring soon: {items_str}
We are cooking {cuisine} food today.
Give your in-character reaction. 2-3 sentences maximum.
<|assistant|>
"""

    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=100,
            temperature=0.8,
            do_sample=True,
            pad_token_id=tokenizer.eos_token_id,
            eos_token_id=tokenizer.eos_token_id
        )

    response = tokenizer.decode(
        outputs[0][inputs["input_ids"].shape[1]:],
        skip_special_tokens=True
    ).strip()

    # Clean up leaked content
    response = response.split("<|system|>")[0].strip()
    response = response.split("system|>")[0].strip()
    response = response.split("<|user|>")[0].strip()
    response = response.split("user|>")[0].strip()
    response = response.split("<|")[0].strip()
    response = response.split("##")[0].strip()
    response = response.split("Can you")[0].strip()
    response = response.split("Please")[0].strip()
    response = response.split("Ammamma,")[0].strip()
    response = re.sub(r'#\w*', '', response).strip()

    # Limit to 3 sentences
    sentences = [s.strip() for s in response.split(".") if s.strip()]
    response = ". ".join(sentences[:3]) + "."

    return response


@app.function(
    gpu="T4",
    image=base_image,
    timeout=240,
    memory=8192,
    volumes={str(MODEL_DIR): model_volume},
    secrets=[modal.Secret.from_name("huggingface-secret")]
)
def generate_recipe_llm(
    all_items: list,
    expiring_items: list,
    cuisine: str
) -> str:
    import torch
    from transformers import AutoTokenizer, AutoModelForCausalLM

    tokenizer = AutoTokenizer.from_pretrained(str(MODEL_DIR / "nemotron-4b"))
    model = AutoModelForCausalLM.from_pretrained(
        str(MODEL_DIR / "nemotron-4b"),
        torch_dtype=torch.float16,
        device_map="auto"
    )

    all_names = ", ".join([i["name"] for i in all_items[:15]])
    expiring_names = ", ".join([i["name"] for i in expiring_items[:5]])

    prompt = f"""<|system|>
You are an expert vegetarian cook specialising in {cuisine} cuisine.
Generate recipes using ONLY the ingredients provided.
Never invent ingredients not in the list.
<|user|>
My pantry contains: {all_names}

Please use these first as they expire soon: {expiring_names}

Create a {cuisine} vegetarian recipe where the expiring items are the hero ingredients.
Only use ingredients from the pantry list above.

Format exactly as:
RECIPE NAME: ...
INGREDIENTS USED: ...
STEPS:
1. ...
2. ...
3. ...
4. ...
5. ...
Stop here. Do not write more than 5 steps.
<|assistant|>
"""

    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=500,
            temperature=0.7,
            do_sample=True,
            pad_token_id=tokenizer.eos_token_id,
            eos_token_id=tokenizer.eos_token_id
        )

    response = tokenizer.decode(
        outputs[0][inputs["input_ids"].shape[1]:],
        skip_special_tokens=True
    ).strip()

    response = response.split("##")[0].strip()

    # Force truncate to 5 steps
    lines = response.split("\n")
    step_count = 0
    truncated = []
    for line in lines:
        truncated.append(line)
        if line.strip() and line.strip()[0].isdigit() and ". " in line:
            step_count += 1
            if step_count >= 5:
                break

    response = "\n".join(truncated)
    return response


@app.function(
    gpu="T4",
    image=tts_image,
    timeout=600,
    memory=8192,
    volumes={str(MODEL_DIR): model_volume},
    secrets=[modal.Secret.from_name("huggingface-secret")]
)
def text_to_speech(text: str, character: str) -> bytes:
    import torch
    import io
    import os
    import soundfile as sf

    os.environ["COQUI_TOS_AGREED"] = "1"
    from TTS.api import TTS

    tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2")

    speaker_map = {
        "Grandma (Ammamma)": "Claribel Dervla",
        "Chef": "Damien Black",
        "Fitness Coach": "Abrahan Mack",
        "Food Critic": "Annmarie Nele",
    }
    speaker = speaker_map.get(character, "Claribel Dervla")

    # Deduplicate and limit sentences
    sentences = text.replace("!", ".").replace("?", ".").split(".")
    seen = []
    for s in sentences:
        s = s.strip()
        if s and s not in seen:
            seen.append(s)
        if len(seen) >= 3:
            break
    short_text = ". ".join(seen) + "."

    wav = tts.tts(
        text=short_text,
        speaker=speaker,
        language="en"
    )

    buf = io.BytesIO()
    sf.write(buf, wav, samplerate=24000, format="WAV")
    return buf.getvalue()


@app.local_entrypoint()
def main():
    test_items = ["INDIA WALA PANEER", "CURRIS LEAVES PACKET", "BASMATI RICE"]

    print("Testing expiry estimation...")
    expiry_map = estimate_expiry_llm.remote(test_items)
    print(expiry_map)

    print("\nTesting Ammamma dialogue...")
    dialogue = generate_dialogue.remote(
        "Grandma (Ammamma)",
        ["INDIA WALA PANEER", "CURRIS LEAVES PACKET"],
        "South Indian"
    )
    print(dialogue)

    print("\nTesting recipe generation...")
    all_items = [{"name": i} for i in test_items]
    expiring = [{"name": i} for i in test_items[:2]]
    recipe = generate_recipe_llm.remote(all_items, expiring, "South Indian")
    print(recipe)

    print("\nTesting TTS...")
    audio_bytes = text_to_speech.remote(dialogue, "Grandma (Ammamma)")
    with open("test_audio.wav", "wb") as f:
        f.write(audio_bytes)
    print("Audio saved to test_audio.wav")