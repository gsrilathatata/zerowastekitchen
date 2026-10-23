---
title: ZeroWasteKitchen
emoji: 🌿
colorFrom: green
colorTo: yellow
sdk: gradio
app_file: app.py
pinned: false
tags:
  - track:backyard
  - sponsor:openbmb
  - sponsor:nvidia
  - sponsor:modal
  - achievement:offgrid
  - achievement:offbrand
  - achievement:sharing
  - achievement:fieldnotes
  - gradio
  - small-models
thumbnail: >-
  https://cdn-uploads.huggingface.co/production/uploads/6516b9f096c4535d048ea75f/r9PhCsUjTu0hVkaroudDh.png
short_description: Save food and save the world, ZerowasteKitechen helps
---

# 🌿 ZeroWasteKitchen

**Scan receipts · track expiry · cook with personality**

A household wastes hundreds of pounds of food a year, mostly because nobody remembers what's in the fridge until it's too late. ZeroWasteKitchen closes that loop: photograph your grocery receipt, and a team of small AI models tracks what you bought, estimates when it expires, and — when something's about to turn — has a Telugu grandmother tell you exactly what to cook with it, out loud.

Built for the **Hugging Face Build Small Hackathon**, June 2026.

## 🔗 Links

- 🎬 **Demo video:** https://youtu.be/x4_G4RFYlSQ
- 🐦 **X / Twitter:** https://x.com/srilatha_t/status/2065977080404222083
- 📓 **Field Notes blog:** https://huggingface.co/blog/build-small-hackathon/zerowastekitchen
- 🤗 **Live Space:** https://huggingface.co/spaces/build-small-hackathon/zerowastekitchen

## How it works

```
📷 Receipt photo
   │
   ▼
MiniCPM-V 4.6 ──── reads the receipt, extracts items as JSON
   │
   ▼
Nemotron-Mini-4B ── estimates shelf life per item
   │
   ▼
SQLite pantry ───── 🔴 cook today · 🟡 use this week · 🟢 fine
   │
   ▼  "Cook with what I have"
   │
   ├─ tiny-aya-fire ──── in-character reaction from your chosen persona
   ├─ Nemotron-Mini-4B ─ two-pass recipe generation (select → compose)
   │
   ▼
VoxCPM2 ─────────── narrates the dialogue and full recipe in a
                    designed, consistent character voice
```

Every model is small (0.5B–4.6B parameters), every model runs on a single T4 GPU, and every model comes from a hackathon sponsor.

## The stack

| Component | Model | Maker | Runs on |
|---|---|---|---|
| Receipt OCR | MiniCPM-V 4.6 | OpenBMB | Modal T4 |
| Expiry estimation | Nemotron-Mini-4B-Instruct | NVIDIA | Modal T4 |
| Character dialogue | tiny-aya-fire | Cohere Labs | Modal T4 |
| Recipe generation | Nemotron-Mini-4B-Instruct | NVIDIA | Modal T4 |
| Voice (TTS) | VoxCPM2 | OpenBMB | Modal T4 |
| Frontend | Gradio | — | HF Spaces (CPU) |
| Pantry storage | SQLite | — | HF Spaces persistent /data |

## The characters

| | Persona | Voice |
|---|---|---|
| 🧓 | **Grandma (Ammamma)** — warm Telugu grandmother who hates waste | Designed by VoxCPM2 from a text description: *"a very elderly Indian grandmother, soft aged voice full of warmth, slow gentle storytelling pace"* |
| 👨‍🍳 | **Chef** — sharp, impatient, brilliant | Brisk professional male voice |
| 💪 | **Fitness Coach** — gains and clean eating | Loud enthusiastic male voice |
| ⭐ | **Food Critic** — pompous but secretly warm | Posh theatrical female voice |

No voice actors, no reference recordings. Each voice is **designed once from a natural-language description** using VoxCPM2's Voice Design, cached on a Modal volume, then **Hi-Fi cloned** (reference audio + exact transcript) for every chunk of narration — so the character sounds identical from greeting to "Step 5".

## Engineering notes: making small models behave

Small models are brilliant at narrow tasks and shaky at open-ended composition. The interesting engineering in this project is the scaffolding:

**Two-pass recipe generation.** Asked to "cook from this pantry," a 4B model happily invents a banana-and-cabbage curry using all 14 items at once. The fix wasn't a bigger model — it was decomposing the task: **Pass 1** asks Nemotron to *select* 4–6 ingredients that genuinely belong together; Python then validates the selection against the real pantry and hard-filters fruit out of savoury dishes; **Pass 2** generates the recipe seeing *only* the chosen items, guided by a few-shot example. The model physically cannot over-stuff a dish it was never shown.

**Load once, serve many.** Nemotron serves two functions (expiry + recipe) from a single Modal `Cls` container — the model loads once per container via `@modal.enter()`, not once per request. The 5GB VoxCPM2 checkpoint and 1.9GB XTTS model are baked into their Modal images at build time, so containers never download at runtime.

**Receipt noise is the real enemy.** UK grocery receipts produce items like `CURRIS LEAVES PACKET` and `GREEN B/YEVE.CHILLIES`. A filter list strips totals, card lines, and weight fragments; names are title-cased before prompting so the model treats them as food, not shouting.

## Run it locally

```bash
git clone https://github.com/srilathatatag/zerowastekitchen
cd zerowastekitchen
pip install gradio modal pillow soundfile numpy

# one-time Modal setup
python -m modal token set --token-id YOUR_ID --token-secret YOUR_SECRET
modal deploy modal_services.py   # deploys all GPU functions

python app.py
```

Secrets required: a Hugging Face token in a Modal secret named `huggingface-secret` (`HF_TOKEN`), and `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET` in HF Spaces settings for the deployed Space.

## Project structure

```
app.py               Gradio UI — calls Modal functions by name
modal_services.py    All GPU work: OCR, expiry, dialogue, recipe, TTS
utils.py             DB helpers, expiry fallbacks, formatting
requirements.txt     Frontend deps (the heavy ML deps live in Modal images)
```

## Known limitations & future work

- Recipes are *sensible*, not *brilliant* — the honest ceiling of a 4B model with prompting alone. Future work: LoRA fine-tune Nemotron-Mini-4B on the open RecipeNLG dataset (~2M recipes), formatted as pantry-list -> recipe pairs, to push ingredient coherence beyond what scaffolding achieves.
- Full-recipe narration takes a couple of minutes on a T4 (a 2B diffusion TTS, chunk by chunk). A toggle lets you narrate just the character's greeting instead.
- The pantry resets if the Space's persistent storage is rebuilt — acceptable for a demo, a managed DB in production.
- Expiry estimates are model judgement, not food-safety advice.

---

*Built solo in two weeks for the HF Build Small Hackathon — proof that five small models, pointed at the right narrow tasks, beat one big model pointed at everything.* 🌿