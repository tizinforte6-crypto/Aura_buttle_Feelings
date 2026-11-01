/* ============================================================
   ОЗВУЧКА СУБТИТРОВ — Piper, русский женский голос ru_RU-irina-medium.
   Tts.speak(text) вызывается из round.js, когда текст субтитров ИЗМЕНИЛСЯ
   (файл / БД / API): новая фраза обрывает предыдущую.

   Режимы (config.js → CFG.TTS_MODE / CFG.PIPER):
   - "piper", SERVER_URL = ""  → Piper в браузере (WASM, библиотека @mintplex-labs/piper-tts-web).
                                  При входе в комнату модель скачивается заранее (Tts.warmup()).
   - "piper", SERVER_URL задан → запросы на ваш Piper-сервер: POST {"text": "..."} → WAV.
   - "browser"                 → встроенный голос браузера.
   Если Piper не загрузился / сервер недоступен — автоматический откат на голос браузера.
   ============================================================ */
const Tts = (() => {
  const synth = "speechSynthesis" in window ? window.speechSynthesis : null;
  const P = CFG.PIPER;
  let enabled = true, audio = null, timer = null;
  let bVoice = null;                            // голос браузера (запасной)
  let lib = null, piperFail = false, browserTtsFailed = false, warm = null;
  let pending = null, busy = false, gen = 0;    // очередь «только последняя фраза»
  const cache = new Map();                      // text → blob URL (повторные фразы звучат мгновенно)

  const label = text => {
    const status = $("voiceStatus");
    if (status) status.textContent = text;
  };
  const usePiper = () => (CFG.TTS_MODE === "piper" || browserTtsFailed) && !piperFail;

  /* ---------- запасной голос браузера (женский русский) ---------- */
  const MALE   = /pavel|dmitr|yuri|yury|maxim|ivan|sergey|павел|дмитр|юрий|максим|иван|сергей/i;
  const FEMALE = /milena|irina|svetlana|tatyana|katya|alena|alyona|dariya|elena|anna|female|google|милена|ирина|светлана|татьяна|катя|алёна|дарья|елена|анна/i;
  function pickBrowserVoice() {
    if (!synth) return;
    const ru = synth.getVoices().filter(v => /^ru/i.test(v.lang));
    bVoice = ru.find(v => FEMALE.test(v.name) && /google|microsoft|natural|premium|enhanced/i.test(v.name) && !MALE.test(v.name))
      || ru.find(v => FEMALE.test(v.name) && !MALE.test(v.name))
      || ru.find(v => !MALE.test(v.name))
      || ru[0] || null;
    if (CFG.TTS_MODE !== "piper") label(bVoice ? "Голос: " + bVoice.name : "");
  }
  if (synth) { pickBrowserVoice(); synth.addEventListener("voiceschanged", pickBrowserVoice); }

  function fallbackToPiper(text) {
    if (CFG.TTS_MODE !== "browser" || piperFail) return false;
    browserTtsFailed = true;
    label("Готовлю качественный русский голос…");
    pending = text;
    pump();
    return true;
  }

  function speakBrowser(text, immediate = false) {
    if (!synth || typeof SpeechSynthesisUtterance === "undefined") {
      if (fallbackToPiper(text)) return;
      label("Голос недоступен в этом браузере");
      return;
    }
    pickBrowserVoice();
    clearTimeout(timer);
    const speak = () => {
      const u = new SpeechSynthesisUtterance(text);
      u.lang = "ru-RU";
      if (bVoice) u.voice = bVoice;
      u.rate = 0.96;
      u.pitch = 1.04;
      u.volume = 1;
      u.onstart = () => label(bVoice ? "Голос: " + bVoice.name : "Говорю по-русски");
      u.onerror = event => {
        if (event.error !== "canceled" && event.error !== "interrupted") {
          if (!fallbackToPiper(text)) label("Не удалось включить голос");
        }
      };
      synth.speak(u);
    };
    if (immediate) {
      speak();
      return;
    }
    synth.cancel();
    timer = setTimeout(speak, 60); // пауза после cancel(): некоторые браузеры пропускают первую фразу
  }

  /* ---------- Piper ---------- */
  async function loadLib() {
    if (!lib) lib = import(P.LIB_URL).then(m => (m.predict ? m : (m.default || m)));
    return lib;
  }

  function failPiper(err) {
    console.warn("[Piper] недоступен, переключаюсь на голос браузера:", err);
    piperFail = true; pickBrowserVoice();
    label(bVoice ? "Piper недоступен — голос: " + bVoice.name : "Piper недоступен");
  }

  // Предзагрузка модели (вызывается при входе в комнату, чтобы первая фраза не ждала 63 МБ)
  function warmup() {
    if (!usePiper() || warm) return warm;
    if (P.SERVER_URL) { label("Голос: Irina (Piper, сервер)"); return (warm = Promise.resolve()); }
    label("Голос Irina: загрузка…");
    warm = loadLib()
      .then(t => t.download(P.VOICE, pr => { if (pr && pr.total) label(`Голос Irina: загрузка ${Math.round(pr.loaded * 100 / pr.total)}%`); }))
      .then(() => label("Голос: Irina (Piper)"))
      .catch(failPiper);
    return warm;
  }

  async function synthPiper(text) {
    await warmup();
    if (!usePiper()) throw new Error("Piper не загрузился");
    if (P.SERVER_URL) {
      const res = await fetch(P.SERVER_URL, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) });
      if (!res.ok) throw new Error("Piper server HTTP " + res.status);
      return res.blob();
    }
    const t = await loadLib();
    return t.predict({ text, voiceId: P.VOICE });
  }

  function remember(text, url) {
    cache.set(text, url);
    if (cache.size > 40) { const k = cache.keys().next().value; URL.revokeObjectURL(cache.get(k)); cache.delete(k); }
  }

  function play(url, text) {
    if (!audio) audio = new Audio();
    audio.pause();
    audio.src = url;
    audio.currentTime = 0;
    audio.muted = false;
    audio.play().then(() => label("Голос: Irina (Piper)")).catch(err => {
      console.warn("[Piper] Браузер заблокировал воспроизведение, использую голос браузера:", err);
      speakBrowser(text);
    });
  }

  // Берёт только самую свежую фразу; устаревшие, пока шёл синтез, пропускаются
  async function pump() {
    if (busy) return;
    busy = true;
    let last = "";
    try {
      while (pending !== null) {
        const text = pending, g = gen; pending = null; last = text;
        let url = cache.get(text);
        if (!url) { url = URL.createObjectURL(await synthPiper(text)); remember(text, url); }
        if (g === gen && enabled) play(url, text);
      }
    } catch (e) { failPiper(e); if (last && enabled) speakBrowser(last); }
    busy = false;
  }

  function stop() {
    gen++; pending = null; clearTimeout(timer);
    if (synth) synth.cancel();
    if (audio) { audio.pause(); audio.currentTime = 0; }
  }

  return {
    speak(text) {
      if (!enabled || !text) return;
      if (usePiper()) { stop(); pending = text; pump(); }
      else speakBrowser(text);
    },
    activate(text) {
      if (!enabled) return;
      if (usePiper()) {
        pending = text || "Озвучивание включено";
        pump();
        return;
      }
      speakBrowser(text || "Озвучивание включено", true);
    },
    stop, warmup,
    // «разбудить» звук по клику пользователя (политика автозапуска браузеров)
    prime() {
      if (synth && typeof SpeechSynthesisUtterance !== "undefined") {
        synth.speak(new SpeechSynthesisUtterance(" "));
      }
      if (typeof Audio !== "undefined") {
        if (!audio) audio = new Audio();
        audio.muted = true;
        audio.src = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAgD4AAAB9AAACABAAZGF0YQAAAAA=";
        audio.play().then(() => {
          audio.pause();
          audio.currentTime = 0;
          audio.muted = false;
        }).catch(() => { audio.muted = false; });
      }
      if (!synth) label("Готовлю нейроголос…");
    },
    toggle() { enabled = !enabled; if (!enabled) stop(); return enabled; }
  };
})();

$("btnVoice").onclick = () => {
  const enabled = Tts.toggle();
  if (enabled) {
    Tts.prime();
    Tts.activate($("mySub").textContent.trim());
  }
  $("btnVoice").textContent = enabled ? "🔊 Озвучка включена" : "🔇 Озвучка выключена";
  $("btnVoice").setAttribute("aria-pressed", String(enabled));
  $("btnVoice").setAttribute("aria-label", enabled ? "Выключить озвучивание фраз" : "Включить озвучивание фраз");
};
