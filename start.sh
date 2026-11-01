#!/usr/bin/env bash
# start.sh — скрипт запуска: виртуальное окружение -> Ollama + модель -> сервер на 0.0.0.0:5000
set -Eeuo pipefail

fail() {
    echo "Ошибка запуска: $*" >&2
    exit 1
}

# ------------------------------------------------------------
# 0. Переходим в папку, где лежит сам скрипт,
#    чтобы пути не зависели от того, откуда его запустили
# ------------------------------------------------------------
DIR="$(dirname "$(readlink -f "$0")")"
cd "$DIR" || fail "не удалось перейти в каталог проекта: $DIR"

# ------------------------------------------------------------
# 1. Активируем виртуальное окружение Python (если оно есть)
# ------------------------------------------------------------
if [ -f ".venv/bin/activate" ]; then
    source ".venv/bin/activate"            # активация .venv
    echo "Activated virtual environment: .venv"
elif [ -f "venv/bin/activate" ]; then
    source "venv/bin/activate"             # активация venv (альтернативное имя)
    echo "Activated virtual environment: venv"
else
    echo "Virtual environment not found, using system Python"
fi

command -v python >/dev/null 2>&1 || fail "Python не найден"
command -v curl >/dev/null 2>&1 || fail "curl не найден"
command -v ollama >/dev/null 2>&1 || fail "Ollama не найдена"

LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
[ -n "$LAN_IP" ] || LAN_IP="127.0.0.1"

# Не запускать вторую копию поверх уже работающего сервера.
if curl -kfsS -o /dev/null --max-time 2 "https://127.0.0.1:5000/"; then
    echo "HTTPS-сервер уже работает: https://$LAN_IP:5000"
    exit 0
fi
if (echo > /dev/tcp/127.0.0.1/5000) 2>/dev/null; then
    fail "порт 5000 уже занят другим процессом; остановите его или освободите порт"
fi

# ------------------------------------------------------------
# 2. Ollama: запуск сервиса (если ещё не запущен)
# ------------------------------------------------------------
if curl -fsS -o /dev/null --max-time 3 "http://localhost:11434/api/tags"; then
    echo "Ollama is already running on port 11434"
else
    echo "Starting Ollama..."
    if systemctl start ollama 2>/dev/null; then
        :
    else
        nohup ollama serve > ollama.log 2>&1 &
    fi

    ollama_ready=false
    for _ in {1..30}; do
        if curl -fsS -o /dev/null --max-time 2 "http://localhost:11434/api/tags"; then
            ollama_ready=true
            break
        fi
        sleep 1
    done
    [ "$ollama_ready" = true ] || fail "Ollama не запустилась на localhost:11434"
fi

# ------------------------------------------------------------
# 3. Модель Ollama — имя задаётся ОДИН раз здесь (быстрая смена)
#    ⚠ эта строка загружает модель в память — не запускайте, пока GPU занят
# ------------------------------------------------------------
MODEL="qwen3-vl:4b-instruct"
ollama pull "$MODEL" || fail "не удалось загрузить модель $MODEL"

# передаём модель / URL серверу (в server.py те же значения по умолчанию)
export OLLAMA_URL="http://localhost:11434"
export OLLAMA_MODEL="$MODEL"

# ------------------------------------------------------------
# 4. Самоподписанный HTTPS-сертификат (нужен для камеры)
#    getUserMedia (камера) работает только на HTTPS или localhost.
#    По http://<IP> браузеры молча блокируют камеру, поэтому для доступа
#    с любого устройства в сети поднимаем HTTPS. Сертификат создаётся
#    один раз и дальше переиспользуется.
# ------------------------------------------------------------
if [ ! -f cert.pem ] || [ ! -f key.pem ]; then
    command -v openssl >/dev/null 2>&1 || fail "openssl не найден — нельзя запустить HTTPS"
    openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem \
        -days 365 -nodes -subj "/CN=$LAN_IP" \
        -addext "subjectAltName=IP:$LAN_IP,IP:127.0.0.1,DNS:localhost" \
        >/dev/null 2>&1 || fail "не удалось создать сертификат (нужен openssl 1.1.1+)"
    echo "Создан самоподписанный сертификат (IP: $LAN_IP)"
fi

[ -s cert.pem ] && [ -s key.pem ] || fail "сертификат HTTPS или ключ отсутствует/пуст"
export SSL_KEYFILE="$DIR/key.pem"
export SSL_CERTFILE="$DIR/cert.pem"

# ------------------------------------------------------------
# 5. Запускаем FastAPI-сервер на 0.0.0.0:5000 (HTTPS)
#    host=0.0.0.0 -> доступен с других устройств (телефона) в сети
# ------------------------------------------------------------
echo "Server address: https://$LAN_IP:5000"
echo "  (при первом заходе примите предупреждение о самоподписанном сертификате)"
python -m uvicorn server:app --host 0.0.0.0 --port 5000 \
    --ssl-keyfile "$SSL_KEYFILE" --ssl-certfile "$SSL_CERTFILE"
