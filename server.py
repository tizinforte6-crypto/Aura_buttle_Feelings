"""Бэкенд сервер: оценки emotions + sessions "rooms" (room-game-v2).

HTTP endpoints:
    GET  /                  — начало страницы с ровно zwei buttons (join room / create room)
    POST /evaluate          — оценка video (frame -> qwen3-vl model)
    GET  /api/models        — list of available Ollama models
    POST /api/rooms/create  — create a room: return new 6-digit code
    POST /api/rooms/join    — validate code; check the database; if the 6-digit
                              code is NOT in the database, automatically CREATE
                              a new room with this exact code, then add the user
    GET  /api/rooms         — list of rooms with their members
WebSocket:
    WS /ws/rooms/{code}     — live webcam streaming for one room:
                              frames are sent ONLY to the other users of the same room.

Run examples:
    python server.py                                   # serves on 127.0.0.1:5000
    uvicorn server:app --host 127.0.0.1 --port 5000    # equivalent
    curl -X POST http://127.0.0.1:5000/evaluate -F "video=@test_clip.mp4" -F "emotion=joy" -F "emotion_description=smiling happily"
"""

import os
import re
import json
import base64
import sqlite3
import secrets
import tempfile
import itertools
import time

import cv2
import requests
import uvicorn
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse

# ---------------------------------------------------------------------------
# --- 1. Клиент для Ollama (vision model) -----------------------------------
# ---------------------------------------------------------------------------


class OllamaClient:
    """Client для Ollama API: chat с vision model и list of models."""

    # main instruction to the model (kept from the original server code)
    SYSTEM_PROMPT = (
        "You will receive an image of a person, a target emotion, and a description of the emotion. "
        "Your task is to evaluate how convincingly the person in the photo is showing this emotion."
    )

    def __init__(self, base_url: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.chat_url = self.base_url + "/api/chat"
        self.tags_url = self.base_url + "/api/tags"
        self.model = model

    def ask(self, image_b64: str, emotion: str, description: str) -> str:
        """Send the frame to the model and return its raw text response."""
        # strict output format: "score|teasing text in 'yandere' anime style"
        user_text = (
            f"Target emotion: {emotion}\n"
            f"Emotion description: {description}\n"
            "Score how convincingly the person in the image is showing this emotion. "
            "Answer with EXACTLY this format on a single line, no markdown, no extra text:\n"
            "[score from 0 to 100 as a single number]|"
            "[a teasing text in 'yandere' anime style about how badly the person is showing the emotion]"
        )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": user_text, "images": [image_b64]},
            ],
            "stream": False,
        }
        # NOTE: key "format" is not passed — this build of Ollama rejects
        # value "text" there (only "json" or a JSON Schema are allowed);
        # plain text is the default behavior anyway.
        response = requests.post(self.chat_url, json=payload, timeout=120)
        response.raise_for_status()
        return response.json()["message"]["content"]

    def list_models(self):
        """Return Ollama /api/tags json; raises on network/HTTP errors."""
        response = requests.get(self.tags_url, timeout=5)
        response.raise_for_status()
        return response.json()


# ---------------------------------------------------------------------------
# --- 2. Video frame -> base64 JPEG ----------------------------------------
# ---------------------------------------------------------------------------


class FrameExtractor:
    """Extraction of the middle frame from video bytes -> base64 JPEG."""

    def extract(self, video_bytes: bytes) -> "str | None":
        """Main function: takes video bytes and returns a frame or None."""
        # OpenCV cannot read video from memory: write bytes into a temp file first;
        # it is deleted in the finally block in all cases.
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
                tmp_path = tmp.name
                tmp.write(video_bytes)

            cap = cv2.VideoCapture(tmp_path)
            # frame count from the container metadata (can be wrong or absent)
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

            if total > 0:
                # fast path: read straight up to the middle frame
                frame = self._frame_by_index(cap, total // 2)
            else:
                frame = None

            if frame is None:
                # fallback: metadata was wrong — collect all frames and take middle one
                cap.release()
                cap = cv2.VideoCapture(tmp_path)
                frame = self._middle_from_all_frames(cap)

            cap.release()
            if frame is None:
                return None
            return self._encode_jpg_b64(frame)
        finally:
            if tmp_path:
                os.unlink(tmp_path)

    def _frame_by_index(self, cap, target: int):
        """Read from the video until frame number `target` (0-based)."""
        frame = None
        idx = -1
        while idx < target:
            ok, frame = cap.read()
            if not ok:  # read failed or video ended earlier than expected
                frame = None
                break
            idx += 1
        return frame

    def _middle_from_all_frames(self, cap):
        """Read the whole video and return its middle frame (or None)."""
        frames = []
        while True:
            ok, current = cap.read()
            if not ok:  # end of video
                break
            frames.append(current)
        if frames:
            return frames[len(frames) // 2]
        return None

    def _encode_jpg_b64(self, frame) -> "str | None":
        """Encode the frame to JPEG then base64 (ASCII string)."""
        ok, buf = cv2.imencode(".jpg", frame)
        if not ok:
            return None
        return base64.b64encode(buf.tobytes()).decode("ascii")


# ---------------------------------------------------------------------------
# --- 3. Normalization of multipart form fields -----------------------------
# ---------------------------------------------------------------------------


class FormParser:
    """Normalize parsed multipart fields to bytes (file, str or FieldItem)."""

    def to_bytes(self, item) -> bytes:
        # multipart fields can come as objects with `.value`, dicts with "value",
        # or plain values
        if hasattr(item, "value"):
            value = item.value
        elif isinstance(item, dict):
            value = item.get("value")
        else:
            value = item
        if hasattr(value, "read"):  # uploaded files are file-like objects
            value = value.read()
        if isinstance(value, str):  # plain strings are converted to bytes
            value = value.encode("utf-8")
        return value


# ---------------------------------------------------------------------------
# --- 4. Database of rooms (sqlite) ----------------------------------------
# ---------------------------------------------------------------------------

DB_PATH = os.environ.get("ROOM_DB", "rooms.db")
ROOM_CODE_RE = re.compile(r"\d{6}")  # room code: exactly 6 digits (0–9)


class RoomDatabase:
    """Database of room users (sqlite): save and update on disconnect."""

    def __init__(self, path: str):
        self.conn = sqlite3.connect(path)
        # one table: one line per join request
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS room_users (
                uid      INTEGER NOT NULL,
                code     TEXT    NOT NULL,
                nickname TEXT    NOT NULL,
                status   TEXT    DEFAULT 'active',
                joined   REAL,
                left     REAL
            )
            """
        )
        self.conn.commit()

    def log_join(self, uid: int, code: str, nickname: str):
        """Save user who joined a room (step 2 of the flow)."""
        self.conn.execute(
            "INSERT INTO room_users VALUES (?,?,?,?,?,?)",
            (uid, code, nickname, "active", time.time(), None),
        )
        self.conn.commit()

    def mark_left(self, uid: int):
        """Mark user as disconnected (step 3: remove from room)."""
        # single quotes = SQL string literals; column names cannot be bind params
        self.conn.execute(
            "UPDATE room_users SET status='left', left=? WHERE uid=? AND status='active'",
            (time.time(), uid),
        )
        self.conn.commit()

    def room_exists(self, code: str) -> bool:
        """Step 1 of the join flow: does this code already exist in the database?"""
        row = self.conn.execute(
            "SELECT COUNT(*) FROM room_users WHERE code=?", (code,)
        ).fetchone()
        return row[0] > 0

    def count_total_members(self, code: str) -> int:
        """How many users ever joined this room (history in the database)."""
        row = self.conn.execute(
            "SELECT COUNT(*) FROM room_users WHERE code=?", (code,)
        ).fetchone()
        return row[0]


# ---------------------------------------------------------------------------
# --- 5. Live rooms in memory (WebSocket sessions) --------------------------
# ---------------------------------------------------------------------------


class RoomUser:
    """One live user of a room: id, nickname, WebSocket session."""

    def __init__(self, uid: int, nickname: str):
        self.uid = uid
        self.nickname = nickname
        self.ws = None  # WebSocket object (set when connection registers)


class RoomManager:
    """Live rooms in memory: code -> {uid: RoomUser}. Keeps the database up to date."""

    def __init__(self, database: "RoomDatabase"):
        self.database = database
        self.rooms = {}  # code -> {uid: RoomUser}
        self._uid_counter = itertools.count(1)

    def new_uid(self) -> int:
        """New unique user id (monotonic, never reused)."""
        return next(self._uid_counter)

    def valid_code(self, code) -> bool:
        """Validate room code: exactly 6 digits (0–9)."""
        return bool(ROOM_CODE_RE.fullmatch(str(code or "")))

    def create_code(self) -> str:
        """Generate new 6-digit code that is not live already."""
        while True:
            code = f"{secrets.randbelow(1_000_000):06d}"
            if code not in self.rooms:
                return code

    def create_room(self, code: str):
        """Create a new live room with this exact code (auto-create on join)."""
        self.rooms[code] = {}

    def ensure_room(self, code: str):
        """Room may not exist yet: whoever joins a missing room becomes its first member."""
        self.rooms.setdefault(code, {})

    def join_room(self, code: str, nickname: str) -> "RoomUser":
        """Join flow (steps 1-3 of the rule):
        1) check the database whether this code already exists;
        2) if NOT — automatically create a new room with this exact code;
        3) add the user to it and proceed with the normal room logic.
        Returns the new user and whether the room was auto-created."""
        if not self.database.room_exists(code):
            self.create_room(code)  # step 2: auto-create the room
            created = True
        else:
            created = False
        user = RoomUser(uid=self.new_uid(), nickname=nickname)
        self.add_user(code, user)  # step 3: add the user + normal room logic
        return user, created

    def add_user(self, code: str, user: "RoomUser"):
        """Register user in the room and save him into the database (step 2 + 3)."""
        self.ensure_room(code)
        self.rooms[code][user.uid] = user
        self.database.log_join(user.uid, code, user.nickname)

    def remove_user(self, code: str, uid: int):
        """Remove user from the room and mark him left in the database (step 3)."""
        room = self.rooms.get(code)
        if room and uid in room:
            del room[uid]
            if not room:
                del self.rooms[code]
        self.database.mark_left(uid)

    def peers(self, code: str, exclude_uid: int):
        """Snapshot of other members of the room (sender excluded)."""
        room = self.rooms.get(code, {})
        return [(uid, user) for uid, user in list(room.items()) if uid != exclude_uid]

    def describe(self, code: str):
        """Public info about one room for GET /api/rooms."""
        room = self.rooms.get(code, {})
        return {
            "users": [{"uid": uid, "nickname": user.nickname} for uid, user in room.items()],
            "db_total": self.database.count_total_members(code),
        }

    async def broadcast(self, code: str, sender_uid: int, data_b64: str):
        """Relay one frame of sender to all OTHER members of the same room (step 4).

        Frames never cross room boundaries: we only iterate this room's sessions.
        If a send fails, the peer is already disconnected: remove him from the room.
        """
        relay = {"op": "frame", "from": sender_uid, "data": data_b64}
        for uid, user in self.peers(code, sender_uid):
            try:
                await user.ws.send_json(relay)
            except Exception:
                # WebSocket of the peer is dead: cleanup (step 3: remove on disconnect)
                self.remove_user(code, uid)


# ---------------------------------------------------------------------------
# --- Singletons: module-level instances (separation of responsibilities) ----
# ---------------------------------------------------------------------------

OLLAMA = OllamaClient(
    os.environ.get("OLLAMA_URL", "http://localhost:11434"),
    os.environ.get("OLLAMA_MODEL", "qwen3-vl:4b-instruct"),
)
EXTRACTOR = FrameExtractor()
PARSER = FormParser()
DATABASE = RoomDatabase(DB_PATH)
MANAGER = RoomManager(DATABASE)


# ---------------------------------------------------------------------------
# --- 6. Backward-compatible function API (tests import these names) --------
# ---------------------------------------------------------------------------


def extract_frame(video_bytes: bytes) -> "str | None":
    """Wrapper: logic lives now in FrameExtractor.extract."""
    return EXTRACTOR.extract(video_bytes)


def ask_model(image_b64: str, emotion: str, description: str) -> str:
    """Wrapper: logic lives now in OllamaClient.ask."""
    return OLLAMA.ask(image_b64, emotion, description)


# ---------------------------------------------------------------------------
# --- 7. Start page: exactly two buttons + webcam client ---------------------
# ---------------------------------------------------------------------------

INDEX_HTML = """<!doctype html>
<html>
<head><meta charset="utf-8"><title>Rooms</title></head>
<body style="background:#111;color:#eee;font-family:monospace">
<h3>Rooms (demo client)</h3>
<!-- start screen with exactly two buttons -->
<button id="btnJoin" onclick="startJoin()">Join room</button>
<button id="btnCreate" onclick="startCreate()">Create room</button>
<script>
// ---- button 1: join room with 6-digit code ----
async function startJoin() {
  const code = prompt("Room code (exactly 6 digits):");
  if (!/^[0-9]{6}$/.test(code || "")) { alert("Error: code must be exactly 6 digits"); return; }
  const nickname = prompt("Nickname:") || "guest";
  const r = await fetch("api/rooms/join", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({code: code, nickname: nickname})});
  const j = await r.json();
  if (j.ok) openRoom(code, nickname); else alert("Server says: " + (j.error || "failed"));
}

// ---- button 2: create room (server generates new 6-digit code) ----
async function startCreate() {
  const r = await fetch("api/rooms/create", {method: "POST"});
  const j = await r.json();
  const nickname = prompt("Nickname:") || "host";
  alert("Your room code: " + j.code + ". Send it to friends to join.");
  openRoom(j.code, nickname);
}

// ---- webcam exchange: own video + frames of other users of the same room ----
async function openRoom(code, nickname) {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(proto + "://" + location.host + "/ws/rooms/" + encodeURIComponent(code));
  ws.onopen = function () { ws.send(JSON.stringify({op: "join", nickname: nickname})); };
  const slots = {}; // user_id -> <img> with someone else's video
  ws.onmessage = function (event) {
    let msg;
    try { msg = JSON.parse(event.data); } catch (err) { return; }
    if (msg.op === "frame" && msg.from) {
      if (!slots[msg.from]) {
        const img = document.createElement("img");
        img.style.width = "200px";
        document.body.appendChild(img);
        slots[msg.from] = img;
      }
      slots[msg.from].src = "data:image/jpeg;base64," + msg.data;
    }
  };
  // own video element: every user sees his own webcam
  let stream = null;
  try { stream = await navigator.mediaDevices.getUserMedia({video: true}); }
  catch (err) { alert("No webcam access: " + err); return; }
  const selfVideo = document.createElement("video");
  selfVideo.srcObject = stream;
  selfVideo.autoplay = true;
  selfVideo.muted = true;
  selfVideo.setAttribute("playsinline", "");
  selfVideo.play();
  document.body.appendChild(selfVideo);
  // capture frames (downscaled JPEG) and send them to the server every 800 ms
  const canvas = document.createElement("canvas");
  canvas.width = 320;
  canvas.height = 240;
  const ctx = canvas.getContext("2d");
  setInterval(function () {
    if (stream.readyState !== "live") { ws.close(); return; }
    if (selfVideo.readyState < 2) return; // video metadata not loaded yet
    ctx.drawImage(selfVideo, 0, 0, canvas.width, canvas.height);
    const url = canvas.toDataURL("image/jpeg", 0.5);
    ws.send(JSON.stringify({op: "frame", data: url.slice(23)})); // strip "data:image/jpeg;base64," prefix
  }, 800);
}
</script>
</body>
</html>
"""

# ---------------------------------------------------------------------------
# --- 8. FastAPI app: endpoints ---------------------------------------------
# ---------------------------------------------------------------------------

app = FastAPI()


@app.get("/")
@app.get("/index.html")
async def start_page():
    """Start page: exactly two buttons (join room / create room)."""
    return HTMLResponse(INDEX_HTML)


@app.get("/api/models")
async def models_endpoint():
    """List of available Ollama models (fallback: configured model only)."""
    try:
        return OLLAMA.list_models()
    except Exception:
        return {"models": [{"name": OLLAMA.model}]}


@app.post("/evaluate")
async def evaluate(request: Request):
    """Evaluate a video: middle frame -> vision model -> ["score", "teasing text"]."""
    form = await request.form()
    for field in ("video", "emotion", "emotion_description"):
        if field not in form:
            return JSONResponse({"error": f"missing '{field}'"}, status_code=400)
    video_bytes = PARSER.to_bytes(form["video"])
    image_b64 = EXTRACTOR.extract(video_bytes)
    if image_b64 is None:
        return JSONResponse({"error": "could not extract a frame from video"}, status_code=502)
    emotion = PARSER.to_bytes(form["emotion"]).decode("utf-8", "replace")
    description = PARSER.to_bytes(form["emotion_description"]).decode("utf-8", "replace")
    try:
        raw = OLLAMA.ask(image_b64, emotion, description)
    except Exception as exc:
        return JSONResponse({"error": f"model request failed: {exc}"}, status_code=502)
    parts = raw.strip().split("|")
    return JSONResponse(parts)


@app.post("/api/rooms/create")
async def create_room_endpoint():
    """Create a room: generate new 6-digit code and return it to the user."""
    code = MANAGER.create_code()
    return {"ok": True, "code": code}


@app.post("/api/rooms/join")
async def join_room_endpoint(request: Request):
    """Join request: validate 6-digit code, then steps 1-3 via join_room
    (check database, auto-create room when the code is new, add the user)."""
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "body must be JSON with 'code' and 'nickname'"}, status_code=400)
    if not isinstance(data, dict):
        return JSONResponse({"error": "JSON body must be an object"}, status_code=400)
    code = str(data.get("code", "")).strip()
    nickname = str(data.get("nickname", "")).strip()
    if not code:
        return JSONResponse({"error": "missing 'code'"}, status_code=400)
    if not MANAGER.valid_code(code):
        # step 2: code must be exactly 6 digits (0-9)
        return JSONResponse({"error": "code must be exactly 6 digits (0-9)"}, status_code=400)
    if not nickname:
        nickname = "guest"
    if len(nickname) > 64:
        return JSONResponse({"error": "nickname too long (max 64 chars)"}, status_code=400)
    user, created = MANAGER.join_room(code, nickname)
    return {"ok": True, "uid": user.uid, "code": code, "created": created}


@app.get("/api/rooms")
async def rooms_endpoint():
    """List of live rooms: members in memory + total members ever joined (database)."""
    return {"rooms": {code: MANAGER.describe(code) for code in list(MANAGER.rooms)}}


@app.websocket("/ws/rooms/{code}")
async def room_stream(websocket: WebSocket):
    """Live webcam session for one room (steps 3-5).

    Protocol client -> server:
        {"op":"join","nickname":...}   — first message, registers the user
        {"op":"frame","data":...}      — one frame (base64 JPEG) from the webcam
        binary message                 — raw JPEG bytes (same as frame, server wraps it)
        {"op":"leave"}                 — user leaves voluntarily
    Protocol server -> client:
        {"op":"joined","code":...,"user_id":...,"peers":[...]}
        {"op":"frame","from":uid,"data":...}  — relayed frame of ANOTHER user of this room
    """
    try:
        code = websocket.path_params.get("code", "")
    except AttributeError:  # older starlette builds: scope fallback
        code = websocket.scope.get("path_params", {}).get("code", "")
    if not ROOM_CODE_RE.fullmatch(code or ""):
        # invalid code on the URL: close connection immediately
        await websocket.close(code=1008, reason="room code must be exactly 6 digits")
        return

    await websocket.accept()
    user = None
    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break  # client disconnected: finally block removes him from the room

            text = message.get("text")
            raw = message.get("bytes")
            if text is None and raw is not None:
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    # raw binary JPEG frame: wrap into base64 and relay as usual
                    if user is not None:
                        await MANAGER.broadcast(code, user.uid, base64.b64encode(raw).decode("ascii"))
                    continue
            if text is None:
                continue
            try:
                msg = json.loads(text)
            except ValueError:
                continue  # ignore anything that is not JSON

            if not isinstance(msg, dict):
                continue
            op = msg.get("op")

            if user is None:
                if op == "join":
                    nickname = str(msg.get("nickname") or "").strip() or "guest"
                    # steps 1-3: DB check, auto-create the room if the code is new, add the user
                    user, _created = MANAGER.join_room(code, nickname[:64])
                    user.ws = websocket
                    peers = [{"uid": uid, "nickname": u.nickname} for uid, u in MANAGER.peers(code, user.uid)]
                    await websocket.send_json(
                        {"op": "joined", "code": code, "user_id": user.uid, "peers": peers}
                    )
                else:
                    await websocket.send_json({"op": "error", "reason": 'first message must be {"op":"join"}'})
                continue

            if op == "frame":
                data = msg.get("data")
                if isinstance(data, str) and data:
                    # step 4: send frame to other users of the same room only
                    await MANAGER.broadcast(code, user.uid, data)
            elif op == "leave":
                await websocket.send_json({"op": "left", "user_id": user.uid})
                break  # finally block does the cleanup
            elif op == "info":
                peers = [{"uid": uid, "nickname": u.nickname} for uid, u in MANAGER.peers(code, user.uid)]
                await websocket.send_json({"op": "info", "code": code, "peers": peers})
            else:
                await websocket.send_json({"op": "error", "reason": f"unknown op {op!r}"})
    finally:
        # step 3: on any disconnect remove the user from the room (also in database)
        if user is not None:
            MANAGER.remove_user(code, user.uid)


# ---------------------------------------------------------------------------
# --- 9. Main: same as `uvicorn server:app --port 5000` ----------------------
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=5000)
