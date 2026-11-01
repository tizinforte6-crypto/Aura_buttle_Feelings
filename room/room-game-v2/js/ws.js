/* Игровая сессия: WebSocket, камера и события текущей комнаты. */
const Session = (() => {
  let socket = null, uid = null, ended = true, joinedAt = 0;
  let lastText = "", lastScore = null, scores = {}, emotion = null, result = null;
  let joinError = "", startedState = null;
  const frames = new Map();
  const peerFrameUrls = new Map();
  let camera = null, canvas = null, frameWorker = null, track = null, cameraTimer = null, ownFrame = null, ownFrameUrl = null;
  let encodingFrame = false;
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const wsUrl = code => `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/ws/rooms/${code}`;

  function reset() {
    uid = null;
    joinedAt = 0;
    lastText = "";
    lastScore = null;
    scores = {};
    emotion = null;
    result = null;
    joinError = "";
    startedState = null;
    ownFrame = null;
    if (ownFrameUrl) URL.revokeObjectURL(ownFrameUrl);
    ownFrameUrl = null;
    peerFrameUrls.forEach(url => URL.revokeObjectURL(url));
    peerFrameUrls.clear();
    frames.clear();
  }

  function showPeerFrame(from, blob) {
    const url = URL.createObjectURL(blob);
    const previousUrl = peerFrameUrls.get(from);
    if (previousUrl) URL.revokeObjectURL(previousUrl);
    peerFrameUrls.set(from, url);
    frames.set(from, url);
    const image = document.getElementById(`cam-${from}`);
    if (image) image.src = url;
  }

  function handle(message) {
    if (!message || typeof message !== "object") return;
    if (message.op === "joined") {
      uid = message.user_id;
      ended = false;
      joinedAt = performance.now();
      document.dispatchEvent(new CustomEvent("live:joined", { detail: uid }));
    } else if (message.op === "game_started") {
      startedState = message;
      joinedAt = performance.now();
      document.dispatchEvent(new CustomEvent("live:started", { detail: message }));
    } else if (message.op === "emotion") {
      emotion = message.name;
      document.dispatchEvent(new CustomEvent("live:emotion", { detail: emotion }));
    } else if (message.op === "score") {
      lastText = message.text || "";
      lastScore = message.score;
    } else if (message.op === "score_update") {
      scores = message.scores || {};
    } else if (message.op === "result") {
      result = message;
      document.dispatchEvent(new CustomEvent("live:result", { detail: message }));
    } else if (message.op === "error") {
      if (uid === null) joinError = message.reason || "Не удалось войти в комнату";
      console.warn("[ws] " + (message.reason || ""));
    }
  }

  function stopCamera() {
    if (cameraTimer) clearInterval(cameraTimer);
    cameraTimer = null;
    if (track) track.stop();
    track = null;
    if (camera) camera.srcObject = null;
    camera = null;
    if (frameWorker) frameWorker.terminate();
    frameWorker = null;
    encodingFrame = false;
  }

  function startCamera() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      console.warn("[cam] Браузер не поддерживает доступ к камере");
      return;
    }
    navigator.mediaDevices.getUserMedia({
      video: {
        width: { ideal: 640 },
        height: { ideal: 480 },
        frameRate: { ideal: 25, max: 30 }
      }
    })
      .then(stream => {
        camera = document.createElement("video");
        camera.srcObject = stream;
        camera.muted = true;
        camera.playsInline = true;
        camera.play().catch(error => console.warn("[cam] Не удалось включить камеру:", error));
        track = stream.getVideoTracks()[0];
        canvas = document.createElement("canvas");
        const sendFrame = blob => {
          encodingFrame = false;
          if (!blob || ended || !socket || socket.readyState !== WebSocket.OPEN
              || socket.bufferedAmount > 512_000) return;
          if (ownFrameUrl) URL.revokeObjectURL(ownFrameUrl);
          ownFrameUrl = URL.createObjectURL(blob);
          ownFrame = ownFrameUrl;
          const image = document.getElementById(`cam-${uid}`);
          if (image) image.src = ownFrameUrl;
          socket.send(blob);
        };
        try {
          if (window.OffscreenCanvas && window.createImageBitmap) {
            frameWorker = new Worker("/js/frame-worker.js");
            frameWorker.onmessage = event => {
              encodingFrame = false;
              if (event.data.error) {
                console.warn("[cam] Не удалось обработать кадр в фоновом потоке:", event.data.error);
                frameWorker.terminate();
                frameWorker = null;
                return;
              }
              sendFrame(event.data.blob);
            };
            frameWorker.onerror = error => {
              console.warn("[cam] Фоновая обработка кадров отключена:", error.message);
              frameWorker.terminate();
              frameWorker = null;
              encodingFrame = false;
            };
          }
        } catch (error) {
          console.warn("[cam] Фоновая обработка кадров недоступна:", error);
          frameWorker = null;
        }
        cameraTimer = setInterval(() => {
          if (ended || !socket || !camera) {
            stopCamera();
            return;
          }
          if (socket.readyState !== WebSocket.OPEN || socket.bufferedAmount > 512_000
              || camera.readyState < 2 || encodingFrame) return;
          try {
            const width = camera.videoWidth, height = camera.videoHeight;
            if (!width || !height) return;
            const scale = Math.min(1, 480 / width, 360 / height);
            const frameWidth = Math.max(1, Math.round(width * scale));
            const frameHeight = Math.max(1, Math.round(height * scale));
            encodingFrame = true;
            if (frameWorker && window.createImageBitmap) {
              createImageBitmap(camera, {
                resizeWidth: frameWidth,
                resizeHeight: frameHeight,
                resizeQuality: "medium"
              })
                .then(bitmap => {
                  if (!frameWorker) {
                    bitmap.close();
                    encodingFrame = false;
                    return;
                  }
                  frameWorker.postMessage({ bitmap, width: frameWidth, height: frameHeight }, [bitmap]);
                })
                .catch(error => {
                  encodingFrame = false;
                  console.warn("[cam] Не удалось получить кадр для фоновой обработки:", error);
                  if (frameWorker) frameWorker.terminate();
                  frameWorker = null;
                });
              return;
            }
            if (canvas.width !== frameWidth) canvas.width = frameWidth;
            if (canvas.height !== frameHeight) canvas.height = frameHeight;
            canvas.getContext("2d").drawImage(camera, 0, 0, frameWidth, frameHeight);
            if (canvas.toBlob) {
              canvas.toBlob(sendFrame, "image/jpeg", 0.55);
            } else {
              fetch(canvas.toDataURL("image/jpeg", 0.55))
                .then(response => response.blob())
                .then(sendFrame)
                .catch(error => {
                  encodingFrame = false;
                  console.warn("[cam] Не удалось закодировать кадр:", error);
                });
            }
          } catch (error) {
            console.warn("[cam] Не удалось передать кадр:", error);
            stopCamera();
          }
        }, 40);
      })
      .catch(error => console.warn("[cam] Нет доступа к камере:", error));
  }

  async function leave() {
    if (socket && !ended) {
      try {
        socket.send(JSON.stringify({ op: "leave" }));
        socket.close();
      } catch (error) {
        console.warn("[ws] Не удалось корректно закрыть соединение:", error);
      }
    }
    socket = null;
    ended = true;
    reset();
    stopCamera();
  }

  async function join(code, nickname) {
    await leave();
    reset();
    ended = false;
    const activeSocket = new WebSocket(wsUrl(code));
    socket = activeSocket;
    activeSocket.addEventListener("open", () => {
      activeSocket.send(JSON.stringify({ op: "join", nickname }));
    });
    activeSocket.binaryType = "blob";
    activeSocket.addEventListener("message", event => {
      if (event.data instanceof Blob) {
        event.data.arrayBuffer().then(buffer => {
          if (buffer.byteLength <= 4) return;
          const bytes = new Uint8Array(buffer);
          const from = new DataView(buffer).getUint32(0, false);
          if (uid !== null && String(from) !== String(uid)) {
            showPeerFrame(from, new Blob([bytes.subarray(4)], { type: "image/jpeg" }));
          }
        }).catch(error => console.warn("[cam] Не удалось получить кадр:", error));
        return;
      }
      try {
        const message = JSON.parse(event.data);
        if (message.op === "frame" && message.data && message.from !== undefined && message.from !== uid) {
          const binary = Uint8Array.from(atob(message.data), char => char.charCodeAt(0));
          showPeerFrame(message.from, new Blob([binary], { type: "image/jpeg" }));
        } else {
          handle(message);
        }
      } catch (error) {
        console.warn("[ws] Получено некорректное сообщение:", error);
      }
    });
    activeSocket.addEventListener("close", () => {
      ended = true;
      stopCamera();
    });
    activeSocket.addEventListener("error", () => {
      ended = true;
      stopCamera();
    });

    const startedAt = Date.now();
    while (uid === null) {
      if (joinError || Date.now() - startedAt > 5000 || ended) {
        return { ok: false, error: joinError || "Нет связи с сервером" };
      }
      await sleep(100);
    }
    startCamera();
    return { ok: true, playerId: uid };
  }

  return {
    join,
    leave,
    startRound: () => {
      if (!socket || socket.readyState !== WebSocket.OPEN) throw new Error("Нет связи с комнатой");
      socket.send(JSON.stringify({ op: "start" }));
    },
    gameStarted: () => startedState,
    isLive: () => socket !== null && !ended && uid !== null,
    liveLeft: () => startedState
      ? Math.max(0, startedState.remaining - (performance.now() - joinedAt) / 1000)
      : CFG.LIVE_LIFETIME_SEC,
    textFor: playerId => uid !== null && String(playerId) === String(uid) ? lastText : "",
    scores: () => ({ ...scores }),
    feeling: () => uid === null || emotion === null ? {} : { [uid]: emotion },
    result: () => result,
    videoUrl: playerId => uid === null ? null : (String(playerId) === String(uid) ? ownFrame : frames.get(playerId)),
  };
})();
