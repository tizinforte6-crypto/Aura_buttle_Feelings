"""Бэкенд сервер: оценки emotions + sessions "rooms" (room-game-v2).

HTTP endpoints:
    GET  /                  — start page: served from frontend/index.html (exactly one button)
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
    python server.py                                   # serves on 0.0.0.0:5000 (network-visible)
    uvicorn server:app --host 0.0.0.0 --port 5000      # equivalent
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
import random
import asyncio
from contextlib import asynccontextmanager

import cv2
import numpy as np
import requests
import uvicorn
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# Имя модели Ollama по умолчанию — для быстрой смены модели меняйте здесь.
DEFAULT_MODEL = "qwen3-vl:4b-instruct"

# ---------------------------------------------------------------------------
# --- 1. Клиент для Ollama (vision model) -----------------------------------
# ---------------------------------------------------------------------------


class OllamaClient:
    """Client для Ollama API: chat с vision model и list of models."""

    # Голос комментатора: живой разговорный русский с доброй иронией.
    SYSTEM_PROMPT = (
        "Ты — эмоциональный, живой комментатор, который смотрит игру вместе с другом "
        "и сразу реагирует на увиденное. Говори по-человечески: разговорно, тепло, "
        "с интонацией и лёгкой дружеской язвительностью — не как судья, диктор или робот. "
        "Перед оценкой проверь, есть ли в кадре человек. Если человека нет, поставь "
        "score 0, person_present false и сообщи, что человека в кадре нет; не оценивай "
        "эмоцию по предметам, рисункам или фону. "
        "Оценивай только то, насколько убедительно человек показывает заданную эмоцию. "
        "Подшучивай над самой попыткой сыграть эмоцию, но оставайся добрым: без "
        "унижения и нападок на внешность, личность или здоровье. Реагируй с чувством — "
        "можно удивиться, рассмеяться, немного поддеть или неожиданно похвалить с "
        "иронией. Используй естественные русские разговорные обороты, меняй ритм и "
        "формулировки; не начинай каждую реплику одинаково, не говори канцелярски и "
        "не превращай ответ в сухой разбор. Всегда пиши по-русски, кириллицей."
    )

    def __init__(self, base_url: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.chat_url = self.base_url + "/api/chat"
        self.tags_url = self.base_url + "/api/tags"
        self.model = model

    def ask(self, image_b64: str, emotion: str, description: str) -> str:
        """Send the frame to the model and return its raw text response."""
        # Structured output keeps the score separate from the spoken line.
        user_text = (
            f"Целевая эмоция: {emotion}\n"
            f"Описание эмоции: {description}\n"
            "Сначала проверь, есть ли в кадре человек. Если человека нет, не оценивай "
            "эмоцию: верни score 0, person_present false и comment ровно "
            "«Человека в кадре нет — мне эмоцию угадывать по пустоте?». Не принимай "
            "за человека предметы, рисунки или фон. Если человек виден, person_present true "
            "и оцени убедительность именно заданной эмоции. Отреагируй так, словно "
            "комментируешь кадр другу вслух. Реплика должна быть живой и "
            "эмоциональной: с дружеской иронией, естественной разговорной интонацией "
            "и лёгким подколом именно исполнения — не сухое описание и не официальный "
            "вердикт. Можно выразить искреннее удивление или похвалить, но добавь "
            "игривую нотку. Скажи что-нибудь конкретное о видимой мимике, если она "
            "заметна; не выдумывай детали, мысли или события и не оценивай внешность. "
            "Меняй начало, длину и построение фраз, не повторяй заготовки. Пиши одно "
            "естественное предложение примерно 6–16 слов; допустимы восклицание и "
            "короткое обращение. Примеры только для интонации: «Ой, брови уже вжились "
            "в роль, а улыбка всё ещё на репетиции!»; «Ну вот, теперь верю — сама "
            "удивилась, да?»; «Ахаха, испуг получился такой убедительный, что я тоже "
            "чуть не моргнул». Не копируй примеры дословно. Ответ только на русском языке, без "
            "английских слов и пояснений. Оценка — целое число от 0 до 100. "
            "Верни только JSON по схеме: {\"score\": число, \"comment\": \"русская реплика\", "
            "\"person_present\": true или false}. "
            "Никакого текста до или после JSON."
        )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": user_text, "images": [image_b64]},
            ],
            "stream": False,
            "options": {"temperature": 0.82, "top_p": 0.9, "num_predict": 96},
            "format": {
                "type": "object",
                "properties": {
                    "score": {"type": "integer", "minimum": 0, "maximum": 100},
                    "comment": {"type": "string"},
                    "person_present": {"type": "boolean"},
                },
                "required": ["score", "comment", "person_present"],
                "additionalProperties": False,
            },
        }
        # NOTE: key "format" is not passed — this build of Ollama rejects
        # value "text" there (only "json" or a JSON Schema are allowed);
        # plain text is the default behavior anyway.
        response = requests.post(self.chat_url, json=payload, timeout=120)
        response.raise_for_status()
        return response.json()["message"]["content"]

    def contains_profanity(self, nickname: str) -> bool:
        """Check whether a nickname contains profanity using the configured model."""
        response = requests.post(
            self.chat_url,
            json={
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Проверь никнейм на наличие мата и обсценной брани "
                            "на русском или другом языке. Учитывай намеренно "
                            "замаскированный мат: замену букв цифрами/символами, "
                            "пробелы и разделители внутри слова. Не считай матом "
                            "обычные имена и безобидные слова только из-за похожего "
                            "звучания. Верни только JSON с булевым полем "
                            "\"contains_profanity\"."
                        ),
                    },
                    {"role": "user", "content": nickname},
                ],
                "stream": False,
                "options": {"temperature": 0, "num_predict": 20},
                "format": {
                    "type": "object",
                    "properties": {"contains_profanity": {"type": "boolean"}},
                    "required": ["contains_profanity"],
                    "additionalProperties": False,
                },
            },
            timeout=30,
        )
        response.raise_for_status()
        result = json.loads(response.json()["message"]["content"])
        flagged = result.get("contains_profanity") if isinstance(result, dict) else None
        if not isinstance(flagged, bool):
            raise ValueError("Модель вернула некорректный результат проверки никнейма")
        return flagged

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
# --- 3.5 База эмоций (JSON) и игровые константы -----------------------------
# ---------------------------------------------------------------------------

EMOTIONS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "emotions.json")

ROOM_LIFETIME = 30             # раунд длится 30 секунд
EMOTION_INTERVAL = 10          # смена эмоции — каждые 10 секунд
EMOTIONS_PER_ROOM = 3          # три эмоции на один раунд (30 / 10 = 3)
FRAME_EVAL_INTERVAL = 5.0      # раз в 5 секунд кадр отправляется в нейросеть
EVAL_STAGGER_STEP = 1.0        # сдвиг между игроками в очереди оценки (сек)
MAX_FRAME_B64 = 400_000        # отбрасываем слишком большие кадры (≈300 КБ JPEG)
OLLAMA_SEMAPHORE = asyncio.Semaphore(1)  # одна vision-задача за раз, чтобы не перегружать локальную модель


class EmotionDatabase:
    """Постоянная база эмоций: загружается из JSON при старте сервера.

    Каждая эмоция — пара "name" (название) и "description" (описание,
    как её показывать). Описание пользователю НЕ показывается — оно
    отправляется в нейросеть вместе с кадром.
    """

    def __init__(self, path: str):
        self.path = path
        self.emotions = []
        self.load()

    def load(self):
        """Загрузить список эмоций из JSON-файла.

        Поддерживает два формата: {"emotions": [...]} и просто [...] (массив).
        """
        with open(self.path, encoding="utf-8") as fh:
            data = json.load(fh)
        items = data if isinstance(data, list) else data.get("emotions", [])
        self.emotions = [
            {"name": str(e["name"]), "description": str(e["description"])}
            for e in items
            if isinstance(e, dict) and e.get("name") and e.get("description")
        ]

    def sample(self, count: int):
        """Случайный набор из `count` РАЗНЫХ эмоций для одной комнаты."""
        pool = list(self.emotions)
        random.shuffle(pool)
        return pool[:count]


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
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS leaderboard (
                nickname     TEXT NOT NULL,
                nickname_key TEXT NOT NULL UNIQUE,
                score        REAL NOT NULL DEFAULT 0
            )
            """
        )
        leaderboard_columns = {
            row[1] for row in self.conn.execute("PRAGMA table_info(leaderboard)")
        }
        if "nickname_key" not in leaderboard_columns:
            self.conn.execute("ALTER TABLE leaderboard ADD COLUMN nickname_key TEXT")
            for (nickname,) in self.conn.execute("SELECT nickname FROM leaderboard"):
                self.conn.execute(
                    "UPDATE leaderboard SET nickname_key=? WHERE nickname=?",
                    (nickname.casefold(), nickname),
                )
            self.conn.execute(
                "CREATE UNIQUE INDEX leaderboard_nickname_key "
                "ON leaderboard(nickname_key)"
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

    def add_leaderboard_scores(self, rows):
        """Добавить итоговые очки раунда в постоянный общий рейтинг."""
        with self.conn:
            self.conn.executemany(
                """
                INSERT INTO leaderboard (nickname, nickname_key, score) VALUES (?, ?, ?)
                ON CONFLICT(nickname_key) DO UPDATE SET score=score + excluded.score
                """,
                ((nickname, nickname.casefold(), score) for nickname, score in rows),
            )

    def get_leaderboard(self):
        """Вернуть игроков от большего суммарного результата к меньшему."""
        rows = self.conn.execute(
            "SELECT nickname, score FROM leaderboard ORDER BY score DESC, nickname COLLATE NOCASE"
        ).fetchall()
        return [{"nick": nickname, "score": score} for nickname, score in rows]


# ---------------------------------------------------------------------------
# --- 5. Live rooms in memory (WebSocket sessions) --------------------------
# ---------------------------------------------------------------------------


class RoomUser:
    """Один живой участник комнаты: id, никнейм, WebSocket + игровые данные."""

    def __init__(self, uid: int, nickname: str):
        self.uid = uid
        self.nickname = nickname
        self.ws = None            # WebSocket (заполняется при регистрации соединения)
        self.scores = []          # оценки (0..100) за каждую оценку нейросетью
        self.eval_offset = 0.0    # сдвиг в очереди оценки (сек), по порядку входа
        self.next_eval_at = 0.0   # когда оценивать в следующий раз (monotonic)
        self.evaluating = False   # идёт ли сейчас оценка (не запускать повторно)
        self.last_frame = None    # последний кадр (base64 JPEG) этого пользователя


class RoomManager:
    """Live rooms in memory: code -> {uid: RoomUser}. Keeps the database up to date."""

    def __init__(self, database: "RoomDatabase"):
        self.database = database
        self.rooms = {}  # code -> {uid: RoomUser}
        self.games = {}  # code -> состояние игры (таймеры + очередь эмоций)
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
        """Создать новую живую комнату с этим кодом и запустить её таймеры."""
        self.rooms[code] = {}
        self.start_game(code)

    def ensure_room(self, code: str):
        """Комната может не существовать: первый вошедший создаёт её и запускает игру."""
        if code not in self.rooms:
            self.rooms[code] = {}
            self.start_game(code)

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
        """Добавить игрока в комнату и сохранить его в БД (шаги 2 + 3)."""
        self.ensure_room(code)
        # сдвиг в очереди оценки: первый игрок — сразу, второй через 1 с и т.д.
        order = len(self.rooms[code])          # сколько игроков уже в комнате
        user.eval_offset = order * EVAL_STAGGER_STEP
        user.next_eval_at = time.monotonic() + user.eval_offset
        self.rooms[code][user.uid] = user
        self.database.log_join(user.uid, code, user.nickname)

    def remove_user(self, code: str, uid: int):
        """Убрать пользователя из комнаты и пометить его в БД (шаг 3)."""
        room = self.rooms.get(code)
        if room and uid in room:
            del room[uid]
            if not room:
                del self.rooms[code]
                self.games.pop(code, None)  # пустая комната — удаляем и её игру
        self.database.mark_left(uid)

    def peers(self, code: str, exclude_uid: int):
        """Snapshot of other members of the room (sender excluded).

        ws is None = user logged by the HTTP join POST but without a live
        WebSocket: he is not a stream target and must not appear in lists.
        Real WS members get their ws assigned right after join_room, so by the
        time any frame is broadcast their ws is set.
        """
        room = self.rooms.get(code, {})
        return [(uid, user) for uid, user in list(room.items()) if uid != exclude_uid and user.ws]

    def has_capacity(self, code: str) -> bool:
        """Комнаты не ограничивают число подключённых игроков."""
        return True

    def describe(self, code: str):
        """Public info about one room for GET /api/rooms (live members only)."""
        room = self.rooms.get(code, {})
        return {
            "users": [{"uid": uid, "nickname": user.nickname} for uid, user in room.items() if user.ws],
            "db_total": self.database.count_total_members(code),
        }

    # ------------------------------------------------------------------
    # Игровые таймеры: раунд 30 секунд, смена эмоции каждые 10 секунд
    # ------------------------------------------------------------------

    def start_game(self, code: str):
        """Подготовить игру комнаты; таймеры и оценка ждут явного старта."""
        self.games[code] = {
            "sequence": EMOTIONS.sample(EMOTIONS_PER_ROOM),  # 3 эмоции на раунд
            "emotion_index": 0,                              # текущая эмоция в очереди
            "started": False,
            "started_at": None,
            "next_emotion_at": None,
            "ends_at": None,
            "finished": False,
        }

    def begin_game(self, code: str):
        """Запустить подготовленную игру один раз по запросу игрока."""
        game = self.games.get(code)
        if game is None or game["finished"]:
            return None
        if not game["started"]:
            now = time.monotonic()
            game.update(
                started=True,
                started_at=now,
                next_emotion_at=now + EMOTION_INTERVAL,
                ends_at=now + ROOM_LIFETIME,
            )
            self.reset_eval_queue(code)
        return game

    def game(self, code: str):
        """Вернуть состояние игры комнаты или None."""
        return self.games.get(code)

    def current_emotion(self, code: str):
        """Текущая эмоция комнаты (словарь name/description) или None."""
        g = self.games.get(code)
        if g is None or not g["started"] or g["finished"]:
            return None
        return g["sequence"][g["emotion_index"]]

    def rotate_emotion(self, code: str):
        """Сменить эмоцию комнаты на следующую (раз в 10 секунд)."""
        g = self.games.get(code)
        if g is None or not g["started"]:
            return None
        if g["emotion_index"] < len(g["sequence"]) - 1:
            g["emotion_index"] += 1
        g["next_emotion_at"] = time.monotonic() + EMOTION_INTERVAL
        # смена эмоции — очередь оценки в комнате сбрасывается
        self.reset_eval_queue(code)
        return g["sequence"][g["emotion_index"]]

    def reset_eval_queue(self, code: str):
        """Сбросить очередь оценки комнаты (при смене эмоции).

        Игроки заново выстраиваются по порядку входа: первый — сразу,
        второй через 1 с и т.д. (сдвиг = порядок * EVAL_STAGGER_STEP).
        """
        room = self.rooms.get(code)
        if not room:
            return
        now = time.monotonic()
        for order, uid in enumerate(sorted(room.keys())):
            user = room[uid]
            user.eval_offset = order * EVAL_STAGGER_STEP
            user.next_eval_at = now + user.eval_offset

    # ------------------------------------------------------------------
    # Ретрансляция кадров (живой стрим) и рассылка служебных сообщений
    # ------------------------------------------------------------------

    async def _relay_one(self, code: str, uid: int, user: "RoomUser", relay: dict):
        """Отправить одно сообщение пользователю; при обрыве — убрать его."""
        try:
            await user.ws.send_json(relay)
        except Exception:
            self.remove_user(code, uid)

    async def broadcast(self, code: str, sender_uid: int, data_b64: str):
        """Ретранслировать кадр отправителя ВСЕМ остальным в комнате (шаг 4).

        Кадры не выходят за пределы комнаты. Отправка идёт параллельно
        (asyncio.gather), чтобы один медленный клиент не тормозил остальных;
        упавшее соединение отбрасывается и удаляется из комнаты.
        """
        try:
            frame = base64.b64decode(data_b64, validate=True)
        except (ValueError, TypeError):
            return
        await self.broadcast_frame(code, sender_uid, frame)

    async def broadcast_frame(self, code: str, sender_uid: int, frame: bytes):
        """Передать JPEG-кадр участникам комнаты без JSON/Base64-обёртки."""
        peers = self.peers(code, sender_uid)
        if peers:
            await asyncio.gather(
                *(self._relay_frame_one(code, sender_uid, uid, user, frame)
                  for uid, user in peers),
                return_exceptions=True,
            )

    async def _relay_frame_one(
        self, code: str, sender_uid: int, target_uid: int, user: "RoomUser", frame: bytes
    ):
        try:
            await user.ws.send_bytes(sender_uid.to_bytes(4, "big") + frame)
        except Exception:
            self.remove_user(code, target_uid)

    async def broadcast_game_started(self, code: str, remaining: float):
        """Сообщить всем игрокам, что общий игровой таймер запущен."""
        message = {"op": "game_started", "remaining": remaining}
        room = self.rooms.get(code, {})
        await asyncio.gather(
            *(self._relay_one(code, uid, user, message)
              for uid, user in list(room.items()) if user.ws is not None),
            return_exceptions=True,
        )

    async def broadcast_emotion(self, code: str, emotion: dict):
        """Разослать новую эмоцию всем участникам (только НАЗВАНИЕ, без описания)."""
        message = {"op": "emotion", "name": emotion["name"]}
        room = self.rooms.get(code, {})
        await asyncio.gather(
            *(self._relay_one(code, uid, user, message)
              for uid, user in list(room.items()) if user.ws is not None),
            return_exceptions=True,
        )

    def score_snapshot(self, code: str):
        """Средние накопленные очки участников текущего раунда."""
        snapshot = {}
        for uid, user in self.rooms.get(code, {}).items():
            if user.scores:
                snapshot[uid] = round(sum(user.scores) / len(user.scores), 1)
        return snapshot

    async def broadcast_scores(self, code: str):
        """Обновить общий счёт и лидера у всех участников комнаты."""
        message = {"op": "score_update", "scores": self.score_snapshot(code)}
        room = self.rooms.get(code, {})
        await asyncio.gather(
            *(self._relay_one(code, uid, user, message)
              for uid, user in list(room.items()) if user.ws is not None),
            return_exceptions=True,
        )

    # ------------------------------------------------------------------
    # Подсчёт результатов и победителя
    # ------------------------------------------------------------------

    def compute_results(self, code: str):
        """Средний балл каждого игрока (0..100) + победитель."""
        room = self.rooms.get(code, {})
        averages = {}
        for uid, user in room.items():
            scores = user.scores
            averages[uid] = round(sum(scores) / len(scores), 1) if scores else 0.0
        winner_uid = max(averages, key=averages.get) if averages else None
        return {
            "winner_nick": room[winner_uid].nickname if winner_uid is not None else "",
            "winner_score": averages.get(winner_uid, 0.0),
            "per_user": averages,
        }

    async def finish_room(self, code: str):
        """Завершить 30-секундный раунд: разослать результаты и закрыть комнату."""
        g = self.games.get(code)
        if g is None or g["finished"]:
            return
        g["finished"] = True
        results = self.compute_results(code)
        room = self.rooms.get(code, {})
        self.database.add_leaderboard_scores(
            (user.nickname, results["per_user"].get(uid, 0.0))
            for uid, user in room.items()
        )
        for uid, user in list(room.items()):
            payload = {
                "op": "result",
                "winner": results["winner_nick"],
                "winner_score": results["winner_score"],
                "your_score": results["per_user"].get(uid, 0.0),
            }
            if user.ws is not None:
                try:
                    await user.ws.send_json(payload)
                    await user.ws.close(code=1000)
                except Exception:
                    pass
        self.rooms.pop(code, None)
        self.games.pop(code, None)


# ---------------------------------------------------------------------------
# --- Singletons: module-level instances (separation of responsibilities) ----
# ---------------------------------------------------------------------------

OLLAMA = OllamaClient(
    os.environ.get("OLLAMA_URL", "http://localhost:11434"),
    os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL),
)
EXTRACTOR = FrameExtractor()
PARSER = FormParser()
EMOTIONS = EmotionDatabase(EMOTIONS_PATH)
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
# --- 7. Start page: served from room/room-game-v2/index.html ----------------
# ---------------------------------------------------------------------------

FRONTEND_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "room", "room-game-v2"
)
FRONTEND_FILE = os.path.join(FRONTEND_DIR, "index.html")


def load_index_html() -> str:
    """Read the active frontend from room/room-game-v2/index.html.

    Read at request time, not at import: the page can be edited and the browser
    refreshed without restarting the server; a missing file gives an explicit
    error page instead of silently serving a stale two-button copy.
    """
    try:
        with open(FRONTEND_FILE, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return "<!doctype html><h1>room/room-game-v2/index.html is missing</h1><p>Restore the room frontend files and restart the server.</p>"


# ---------------------------------------------------------------------------
# --- 8. FastAPI app: endpoints ---------------------------------------------
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app):
    """Запустить фоновый игровой цикл при старте и остановить при завершении."""
    task = asyncio.create_task(game_loop())
    yield
    task.cancel()


app = FastAPI(lifespan=lifespan)


@app.middleware("http")
async def disable_frontend_caching(request: Request, call_next):
    response = await call_next(request)
    if (request.url.path in {"/", "/index.html"}
            or request.url.path.startswith(("/js/", "/css/", "/assets/"))):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# Раздаём стили, скрипты и изображения непосредственно из папки room.
app.mount("/css", StaticFiles(directory=os.path.join(FRONTEND_DIR, "css")), name="css")
app.mount("/js", StaticFiles(directory=os.path.join(FRONTEND_DIR, "js")), name="js")
app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIR, "assets")), name="assets")


@app.get("/")
@app.get("/index.html")
async def start_page():
    """Главная страница проекта room/room-game-v2."""
    return HTMLResponse(load_index_html())


@app.get("/api/models")
async def models_endpoint():
    """List of available Ollama models (fallback: configured model only)."""
    try:
        return OLLAMA.list_models()
    except Exception:
        return {"models": [{"name": OLLAMA.model}]}


@app.get("/api/leaderboard")
async def leaderboard_endpoint():
    """Вернуть постоянный рейтинг игроков по сумме очков за раунды."""
    return DATABASE.get_leaderboard()


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
    score, text, person_present = parse_model_response(raw)
    if score is None:
        print(f"[evaluate] Неожиданный ответ модели: {raw!r}", flush=True)
        score = 50
        text = ""
    if person_present is False:
        score = 0
        text = no_person_comment()
    else:
        text = russian_comment(text, score, emotion)
    return JSONResponse([str(score), text])


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
    try:
        if await asyncio.to_thread(OLLAMA.contains_profanity, nickname):
            return JSONResponse(
                {"error": "Нецензурный никнейм. Выберите другое имя."},
                status_code=400,
            )
    except Exception as exc:
        print(f"[nickname] Ошибка проверки имени: {exc}", flush=True)
        return JSONResponse(
            {"error": "Не удалось проверить имя. Попробуйте войти позже."},
            status_code=503,
        )
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
        binary message                 — raw JPEG bytes from the webcam
        {"op":"start"}                 — start the room's game once
        {"op":"leave"}                 — user leaves voluntarily
    Protocol server -> client:
        {"op":"joined","code":...,"user_id":...,"peers":[...]}
        {"op":"game_started","remaining":...} — shared game start and remaining time
        binary message                 — 4-byte sender id followed by JPEG bytes
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
                    # Сырой JPEG оставляем бинарным для ретрансляции;
                    # Base64 создаём только при редкой оценке нейросетью.
                    if user is not None:
                        if len(raw) > MAX_FRAME_B64 * 3 // 4:
                            continue
                        user.last_frame = raw
                        await MANAGER.broadcast_frame(code, user.uid, raw)
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
                    if len(nickname) > 64:
                        await websocket.send_json({
                            "op": "error",
                            "reason": "Имя слишком длинное (максимум 64 символа)",
                        })
                        await websocket.close(code=1008, reason="nickname too long")
                        break
                    try:
                        has_profanity = await asyncio.to_thread(
                            OLLAMA.contains_profanity, nickname
                        )
                    except Exception as exc:
                        print(f"[nickname] Ошибка проверки имени: {exc}", flush=True)
                        await websocket.send_json({
                            "op": "error",
                            "reason": "Не удалось проверить имя. Попробуйте войти позже.",
                        })
                        await websocket.close(code=1011, reason="nickname check unavailable")
                        break
                    if has_profanity:
                        await websocket.send_json({
                            "op": "error",
                            "reason": "Нецензурный никнейм. Выберите другое имя.",
                        })
                        await websocket.close(code=1008, reason="profanity in nickname")
                        break
                    # шаги 1-3: проверка БД, авто-создание комнаты, добавление игрока
                    user, _created = MANAGER.join_room(code, nickname[:64])
                    user.ws = websocket
                    peers = [{"uid": uid, "nickname": u.nickname} for uid, u in MANAGER.peers(code, user.uid)]
                    await websocket.send_json(
                        {"op": "joined", "code": code, "user_id": user.uid, "peers": peers}
                    )
                    game = MANAGER.game(code)
                    if game and game["started"]:
                        await websocket.send_json({
                            "op": "game_started",
                            "remaining": max(0, game["ends_at"] - time.monotonic()),
                        })
                    # сообщаем эмоцию только после фактического старта игры
                    emotion = MANAGER.current_emotion(code)
                    if game and game["started"] and emotion is not None:
                        await websocket.send_json({"op": "emotion", "name": emotion["name"]})
                else:
                    await websocket.send_json({"op": "error", "reason": 'first message must be {"op":"join"}'})
                continue

            if op == "frame":
                data = msg.get("data")
                if isinstance(data, str) and data:
                    # защита от слишком больших кадров — сохраняем стабильный FPS
                    if len(data) > MAX_FRAME_B64:
                        continue
                    # Сохраняем последний кадр; нейросеть использует его только
                    # после старта игры, а видеопоток в лобби остаётся доступен.
                    user.last_frame = data
                    # шаг 4: кадр уходит ТОЛЬКО другим участникам комнаты
                    await MANAGER.broadcast(code, user.uid, data)
            elif op == "start":
                game = MANAGER.begin_game(code)
                if game is not None:
                    await MANAGER.broadcast_game_started(
                        code, max(0, game["ends_at"] - time.monotonic())
                    )
                    emotion = MANAGER.current_emotion(code)
                    if emotion is not None:
                        await MANAGER.broadcast_emotion(code, emotion)
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
# --- 8.5 Игровой цикл: оценка кадров + ротация эмоций + итоги ---------------
# ---------------------------------------------------------------------------

def parse_model_response(raw: str):
    """Разобрать ответ модели -> (score, текст, наличие человека).

    person_present бывает None для старого формата без этого поля.
    """
    s = (raw or "").strip()
    try:
        structured = json.loads(s)
    except (json.JSONDecodeError, TypeError):
        structured = None
    if isinstance(structured, dict):
        score = structured.get("score")
        text = structured.get("comment")
        person_present = structured.get("person_present")
        if isinstance(score, int) and not isinstance(score, bool) and isinstance(text, str):
            if person_present is not None and not isinstance(person_present, bool):
                person_present = None
            return max(0, min(100, score)), text, person_present
    m = re.match(
        r"\s*(?:\[\s*)?(?:(?:score|оценка)\s*[:=]\s*)?"
        r"(\d{1,3})(?:\s*\])?(.*)",
        s,
        re.IGNORECASE | re.DOTALL,
    )
    if m is None:
        return None, "", None
    text = m.group(2).strip().lstrip("|:;,-= \t\r\n").rstrip("]")
    text = re.sub(r"^comment\s*[:=]\s*", "", text, flags=re.IGNORECASE)
    return max(0, min(100, int(m.group(1)))), text, None


def parse_score(raw: str):
    """Backward-compatible parser for score and comment."""
    score, text, _person_present = parse_model_response(raw)
    return score, text


def no_person_comment() -> str:
    return "Человека в кадре нет — мне эмоцию угадывать по пустоте?"


def russian_comment(text: str, score: int, emotion: str) -> str:
    """Вернуть язвительную русскую реплику, если ответ модели непригоден."""
    comment = " ".join((text or "").split()).strip(" \"'«»")
    cyrillic = sum("А" <= char.upper() <= "Я" or char == "Ё" or char == "ё" for char in comment)
    latin = sum("A" <= char.upper() <= "Z" for char in comment)
    if comment and cyrillic >= 8 and latin == 0 and len(comment) <= 180:
        return comment

    subject = emotion.strip().rstrip(".!?") or "эмоция"
    if score < 40:
        options = (
            f"Ой, «{subject}» где-то потерялась — давай ещё дубль!",
            f"Это сейчас была «{subject}»? Брови уже требуют пересъёмку!",
            f"Ну, «{subject}» пока не убедила — зато попытка была смелая!",
        )
    elif score < 70:
        options = (
            f"Уже почти «{subject}» — ещё чуть-чуть, и я поверю!",
            f"О, «{subject}» намечается! Остальному лицу уже сообщили?",
            f"Слушай, «{subject}» почти получилась. Вот это прогресс!",
        )
    else:
        options = (
            f"Ого, вот это «{subject}»! Не ожидал, а ты хорош!",
            f"Ну всё, «{subject}» сыграна! Вот это ты выдал!",
            f"Вот это «{subject}» — почти придраться не к чему. Почти!",
        )
    return random.choice(options)


def fit_frame_640(image_b64: str) -> str:
    """Уменьшить JPEG-кадр так, чтобы большая сторона была не больше 640px.

    Если декодировать не удалось или сторона уже <= 640 — возвращаем как есть.
    """
    try:
        arr = np.frombuffer(base64.b64decode(image_b64), dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    except Exception:
        return image_b64
    if img is None:
        return image_b64
    h, w = img.shape[:2]
    longest = max(h, w)
    if longest <= 640:
        return image_b64
    scale = 640.0 / longest
    resized = cv2.resize(
        img,
        (max(1, int(w * scale)), max(1, int(h * scale))),
        interpolation=cv2.INTER_AREA,
    )
    ok, out = cv2.imencode(".jpg", resized)
    if not ok:
        return image_b64
    return base64.b64encode(out.tobytes()).decode("ascii")


async def evaluate_user_frame(user: "RoomUser", code: str, image_b64: str | bytes, emotion: dict):
    """Отправить один кадр в нейросеть (в фоне) и сохранить результат.

    Вызывается каждые 5 секунд. Нейросеть возвращает "score|текст",
    где текст — саркастичная реплика в стиле "яндере". Результат
    (score и текст РАЗДЕЛЬНО) уходит обратно пользователю.
    """
    game = MANAGER.game(code)
    if game is None or not game["started"] or game["finished"]:
        user.evaluating = False
        return
    try:
        if isinstance(image_b64, bytes):
            image_b64 = base64.b64encode(image_b64).decode("ascii")
        # кадр для модели — не больше 640px по большей стороне
        image_b64 = fit_frame_640(image_b64)
        async with OLLAMA_SEMAPHORE:
            game = MANAGER.game(code)
            if (user.ws is None
                    or MANAGER.rooms.get(code, {}).get(user.uid) is not user
                    or game is None or not game["started"] or game["finished"]):
                user.evaluating = False
                return
            raw = await asyncio.to_thread(
                OLLAMA.ask, image_b64, emotion["name"], emotion["description"]
            )
    except Exception as exc:
        # логируем причину: модель недоступна / неверное имя / таймаут
        print(f"[evaluate] Ошибка модели ({emotion['name']}): {exc!r}", flush=True)
        user.evaluating = False
        game = MANAGER.game(code)
        if (user.ws is None
                or MANAGER.rooms.get(code, {}).get(user.uid) is not user
                or game is None or not game["started"] or game["finished"]):
            return
        if user.ws is not None:
            try:
                await user.ws.send_json({
                    "op": "score",
                    "score": 0,
                    "text": "Модель недоступна",
                    "emotion": emotion["name"],
                })
            except Exception:
                pass
        return
    user.evaluating = False
    game = MANAGER.game(code)
    if (user.ws is None
            or MANAGER.rooms.get(code, {}).get(user.uid) is not user
            or game is None or not game["started"] or game["finished"]):
        return
    score, text, person_present = parse_model_response(raw)
    if score is None:
        print(f"[evaluate] Неожиданный ответ модели: {raw!r}", flush=True)
        if user.ws is not None:
            try:
                await user.ws.send_json({
                    "op": "score",
                    "score": None,
                    "text": "Не удалось оценить кадр, попробуй ещё раз",
                    "emotion": emotion["name"],
                })
            except Exception:
                pass
        return
    if person_present is False:
        score = 0
        text = no_person_comment()
    else:
        text = russian_comment(text, score, emotion["name"])
    user.scores.append(score)
    await MANAGER.broadcast_scores(code)
    print(f"[evaluate] {emotion['name']}: {score} | {text}", flush=True)
    if user.ws is not None:
        try:
            await user.ws.send_json({
                "op": "score",
                "score": score,           # число 0..100 — показывается отдельно
                "text": text,             # яндере-реплика — показывается отдельно
                "emotion": emotion["name"],
            })
        except Exception:
            pass


async def game_loop():
    """Фоновый цикл: каждую секунду проверяет комнаты.

    - после старта каждые 5 секунд оценивает последний кадр каждого игрока нейросетью
      и рассылает новый результат (score + текст);
    - каждые 10 секунд меняет эмоцию и рассылает её (только название);
    - через 30 секунд считает средний балл, определяет победителя
      и рассылает итоги, затем закрывает комнату.
    """
    print("[game_loop] Старт игрового цикла", flush=True)
    while True:
        await asyncio.sleep(1)
        now = time.monotonic()
        for code in list(MANAGER.rooms):
            g = MANAGER.game(code)
            if g is None or g["finished"] or not g["started"]:
                continue
            if now >= g["ends_at"]:
                await MANAGER.finish_room(code)
                continue
            if now >= g["next_emotion_at"]:
                emotion = MANAGER.rotate_emotion(code)
                if emotion is not None:
                    await MANAGER.broadcast_emotion(code, emotion)
            # каждые 5 секунд — оценка последнего кадра каждого игрока
            emotion = MANAGER.current_emotion(code)
            if emotion is None:
                continue
            for uid, user in list(MANAGER.rooms.get(code, {}).items()):
                if user.ws is None or user.last_frame is None:
                    continue
                if user.evaluating or now < user.next_eval_at:
                    continue
                user.evaluating = True
                user.next_eval_at += FRAME_EVAL_INTERVAL  # следующий раз — через 5 с
                print(f"[evaluate] Запуск оценки uid={user.uid} эмоция={emotion['name']}", flush=True)
                asyncio.create_task(
                    evaluate_user_frame(user, code, user.last_frame, emotion)
                )


# ---------------------------------------------------------------------------
# --- 9. Main: same as `uvicorn server:app --port 5000` ----------------------
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 10. Доступ к серверу из интернета (ngrok / cloudflared / проброс порта)
# ---------------------------------------------------------------------------
# Сервер уже слушает 0.0.0.0 (все сетевые интерфейсы), поэтому он доступен
# с любого устройства в локальной сети по адресу http://<LAN-IP>:5000.
# Чтобы открыть его из интернета:
#
#   Вариант A (рекомендуется) — публичный туннель ngrok или cloudflared:
#       ngrok http 5000
#       # либо
#       cloudflared tunnel --url http://localhost:5000
#     После запуска в терминале появится публичный HTTPS-адрес вида
#     https://xxxx.ngrok-free.app  или  https://xxxx.trycloudflare.com.
#     Откройте его в браузере — по HTTPS камера работает везде
#     (в Firefox и на телефоне).
#
#   Вариант B — проброс порта на роутере:
#     1) В настройках роутера создайте правило Port Forwarding:
#        внешний порт 5000 -> внутренний порт 5000 -> IP вашего компьютера.
#     2) Узнайте свой публичный IP (например, на сайте whatismyip.com).
#     3) Откройте http://<публичный_IP>:5000 в браузере.
#     Внимание: без HTTPS браузеры (Firefox/Chrome) не дадут доступ к камере.
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # host="0.0.0.0" -> сервер слушает на всех интерфейсах, доступен по IP:5000
    # с телефона / другого компьютера в одной Wi-Fi-сети (127.0.0.1 — только локально)
    #
    # HTTPS: если заданы SSL_KEYFILE/SSL_CERTFILE (и оба файла существуют),
    # сервер поднимается по HTTPS. Без HTTPS браузеры не дают доступ к камере —
    # getUserMedia работает только в защищённом контексте (https или localhost).
    ssl_keyfile = os.environ.get("SSL_KEYFILE")
    ssl_certfile = os.environ.get("SSL_CERTFILE")
    if not (ssl_keyfile and ssl_certfile
            and os.path.isfile(ssl_keyfile) and os.path.isfile(ssl_certfile)):
        ssl_keyfile = None
        ssl_certfile = None
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=5000,
        ssl_keyfile=ssl_keyfile,
        ssl_certfile=ssl_certfile,
    )
