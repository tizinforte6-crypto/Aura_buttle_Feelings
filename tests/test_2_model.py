# Test 2: check the model request (ask_model from server.py) and the output format
import os
import sys
import base64

import cv2               # OpenCV for reading/encoding the frame image

# Add the project root to sys.path so that `import server` works from the tests/ dir
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from server import ask_model  # import the function under test

# Project root and the frame saved earlier by test_1_extract.py
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRAME = os.path.join(ROOT, "out", "extracted_frame.jpg")

frame = cv2.imread(FRAME)
if frame is None:
    print("FAIL: run test_1_extract.py first (out/extracted_frame.jpg missing)")
    raise SystemExit(1)

# JPEG-encode the frame again (same way as in the server code)
ok, buf = cv2.imencode(".jpg", frame)
if not ok:
    print("FAIL: encode error")
    raise SystemExit(1)

# Base64-encode the JPEG bytes for the model API
image_b64 = base64.b64encode(buf.tobytes()).decode("ascii")

# Ask the model with an example emotion ("surprise") and its description
raw = ask_model(image_b64, "surprise", "wide open eyes and a dropped jaw, caught off guard")
print(f"raw model output (repr): {raw!r}")

# Save the raw model answer to a file for inspection
with open(os.path.join(ROOT, "out", "model_raw.txt"), "w") as fh:
    fh.write(raw)

# Validate the "score|text" format:
# there must be exactly 2 parts split by '|', and the score must be a number 0..100
parts = raw.strip().split("|")
has_pipe = len(parts) == 2
score = parts[0].strip().strip("[]")            # take the first part and strip brackets/spaces
score_ok = score.isdigit() and 0 <= int(score) <= 100
print(f"parts: {len(parts)} | score='{score}' | pipe-format: {'PASS' if has_pipe and score_ok else 'FAIL'}")
raise SystemExit(0 if has_pipe and score_ok else 1)
