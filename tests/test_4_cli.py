# Test 4 (CLI): send a PHOTO (not a video) + emotion + description to the Qwen model
# and print the model's final answer to the console.
#
# The exact same logic and instructions as in server.py are reused:
#   - the image is JPEG-encoded and base64-encoded just like extract_frame does;
#   - SYSTEM_PROMPT, the prompt format, the model and the Ollama API call
#     come from ask_model imported from server.
#
# Usage: python tests/test_4_cli.py
#   photo path: photo.jpg
#   emotion - description: joy - smiling happily

import os
import sys

import base64
import cv2

# Add the project root to sys.path so that `import server` works from the tests/ dir
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from server import ask_model  # reuse the exact model-call logic from the server code

# --- Step 1: ask the user for the path to the photo file ---
photo_path = input("Enter the path to the photo file: ").strip()

photo_path = os.path.expanduser(photo_path)  # allow paths like ~/pics/photo.jpg
if not os.path.isfile(photo_path):
    print(f"FAIL: photo file not found: {photo_path}")
    raise SystemExit(1)

# --- Step 2: ask for the target emotion and its description in ONE line ---
# Expected format: "emotion - description" (Example: joy - smiling happily)
emotion_line = input("Enter target emotion and description (emotion - description): ")

# --- Step 3: parse the line, separating emotion and description ---
# Split at the first " - " (space-hyphen-space); fall back to a plain "-".
# Only the first hyphen is a separator, so a description may contain hyphens.
if " - " in emotion_line:
    emotion, description = emotion_line.split(" - ", 1)
elif " - " not in emotion_line and "-" in emotion_line:
    emotion, description = emotion_line.split("-", 1)
    emotion, description = emotion.strip(), description.strip()
else:
    # No hyphen at all: the whole line is the emotion, the description stays empty
    emotion, description = emotion_line.strip(), ""

emotion = emotion.strip()
description = description.strip()
if not emotion:
    print("FAIL: empty emotion (expected format: 'emotion - description')")
    raise SystemExit(1)
print(f"Parsed -> emotion: '{emotion}' | description: '{description}'")

# --- Step 4: encode the photo exactly like the server code encodes a frame ---
photo = cv2.imread(photo_path)
if photo is None:
    print(f"FAIL: could not read image: {photo_path}")
    raise SystemExit(1)

# JPEG-encode, then base64-encode (same steps as in extract_frame in server.py)
ok, buf = cv2.imencode(".jpg", photo)
if not ok:
    print("FAIL: JPEG encode error")
    raise SystemExit(1)
image_b64 = base64.b64encode(buf.tobytes()).decode("ascii")

# ask_model applies the server's exact SYSTEM_PROMPT + user prompt + model choice
try:
    raw = ask_model(image_b64, emotion, description)
except Exception as exc:
    print(f"FAIL: model request failed: {exc}")
    print("Hint: is Ollama running at the OLLAMA_URL (default http://localhost:11434)?")
    raise SystemExit(1)

# --- Step 5: print the model's final response directly to the console ---
print("Model response:")
print(raw)

# Also show the split the server's /evaluate endpoint would return (["score", "text"])
parts = raw.strip().split("|")
if len(parts) > 2:
    parts = [parts[0], "|".join(parts[1:])]
elif len(parts) == 1:
    parts = parts + [""]
print(f"Server-style split: {parts}")

raise SystemExit(0)
