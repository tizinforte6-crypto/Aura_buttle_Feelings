# Test 1: verification of video frame extraction (extract_frame from server.py)
import os
import sys
import base64

import cv2               # OpenCV for decoding/decoding the frame image
import numpy as np       # numpy for converting bytes to an image array

# Add the project root to sys.path so that `import server` works from the tests/ dir
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from server import extract_frame  # import the function under test

# Root dir of the project and the path to the test video clip
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIP = os.path.join(ROOT, "test_clip.mp4")

# Read the raw video file bytes
with open(CLIP, "rb") as fh:
    video_bytes = fh.read()

# Extract the middle frame as a base64-encoded JPEG string
b64 = extract_frame(video_bytes)
if b64 is None:
    print("FAIL: extract_frame returned None")
    raise SystemExit(1)

# Decode base64 back to an image (numpy array -> OpenCV image) to verify the result
frame = cv2.imdecode(np.frombuffer(base64.b64decode(b64), np.uint8), cv2.IMREAD_COLOR)
if frame is None:
    print("FAIL: could not decode frame image")
    raise SystemExit(1)

# Save the frame as an artifact for the next test (test_2_model.py reads it)
out = os.path.join(ROOT, "out", "extracted_frame.jpg")
os.makedirs(os.path.dirname(out), exist_ok=True)
cv2.imwrite(out, frame)

# Print the frame size and finish successfully
h, w = frame.shape[:2]
print(f"PASS: middle frame {w}x{h} saved to {out}")
raise SystemExit(0)
