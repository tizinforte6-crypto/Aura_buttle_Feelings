# Test 3: end-to-end check of the server — start server.py, upload the video to /evaluate
import os
import sys
import time
import subprocess

import requests          # HTTP client for requests to the running server

# Add the project root to sys.path (not strictly needed here, but kept for consistency)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

# Project root, test video, and base URL of the server under test
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIP = os.path.join(ROOT, "test_clip.mp4")
BASE = "http://127.0.0.1:5000"

# Start the server as a separate process (like `python server.py`);
# its logs are redirected to a pipe so they can be printed on failure
proc = subprocess.Popen(
    [sys.executable, os.path.join(ROOT, "server.py")],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
)

# Wait until the server becomes reachable: poll /api/models for up to 20 seconds
deadline = time.time() + 20
connected = False
while time.time() < deadline:
    try:
        r = requests.get(BASE + "/api/models", timeout=1)
        connected = True
        break
    except Exception:
        time.sleep(0.5)   # server not ready yet: wait and retry

if not connected:
    # Server never started: terminate it and dump the log for debugging
    proc.terminate()
    out = proc.stdout.read().decode("utf-8", "replace")
    print("FAIL: server did not become reachable")
    print(out)
    raise SystemExit(1)

# Read the raw video bytes from the test clip
with open(CLIP, "rb") as fh:
    video_bytes = fh.read()

try:
    # Multipart POST to /evaluate: the video file part + emotion + description
    r = requests.post(
        BASE + "/evaluate",
        files={"video": ("test_clip.mp4", video_bytes)},
        data={"emotion": "surprise", "emotion_description": "wide open eyes and a dropped jaw, caught off guard"},
        timeout=60,
    )
    print(f"HTTP status: {r.status_code}")
    print(f"JSON body: {r.json()}")
    # The server is OK when it returns 200 and a 2-element list ["score", "text"]
    ok = r.status_code == 200 and isinstance(r.json(), list) and len(r.json()) == 2
finally:
    # Cleanup: always terminate the server process (kill it if it hangs)
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()

print(f"evaluate endpoint: {'PASS' if ok else 'FAIL'}")
raise SystemExit(0 if ok else 1)
