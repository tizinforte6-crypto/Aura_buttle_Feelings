/* Настройки игры */
const CFG = {
  ROUND_SEC: 30,      // длительность раунда, сек
  SCORE_MS: 10000,    // обновление очков, мс
  FEEL_MS: 10000,     // обновление «Чувство», мс
  SUB_MS: 2000,       // обновление субтитров, мс
  LOBBY_MS: 2000,     // опрос списка игроков в лобби, мс
  API_BASE: "",       // TODO: адрес вашего бэкенда, напр. "https://my-server.com/api"
  USE_MOCK: false,    // серверная игра: комнаты и озвучиваемые фразы идут из WebSocket
  LIVE_LIFETIME_SEC: 30,
  TTS_MODE: "browser", // основной голос — браузер; Piper используется как запасной
  PIPER: {
    VOICE: "ru_RU-irina-medium",   // женский русский голос Piper
    SERVER_URL: "",                // "" — Piper работает прямо в браузере (WASM, модель ~63 МБ качается один раз)
                                   // "http://localhost:5000" — свой Piper-сервер: python -m piper.http_server -m ru_RU-irina-medium --port 5000
    LIB_URL: "https://cdn.jsdelivr.net/npm/@mintplex-labs/piper-tts-web@1.0.4/+esm"  // библиотека для режима WASM
  },
  GITHUB_URL: "https://github.com/tizinforte6-crypto/Aura_buttle_Feelings"      // TODO: вставьте ссылку на GitHub, напр. "https://github.com/user/repo"
};
const COLORS = ["#8f7cf0","#5fb0f5","#b79cf5","#4cc9c0","#7f9cf5","#c792ea","#6fd0f0","#9fb4f8"];
