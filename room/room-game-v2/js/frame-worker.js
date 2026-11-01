let canvas = null;
let context = null;

self.onmessage = async event => {
  const { bitmap, width, height } = event.data;
  try {
    if (!canvas || canvas.width !== width || canvas.height !== height) {
      canvas = new OffscreenCanvas(width, height);
      context = canvas.getContext("2d");
    }
    context.drawImage(bitmap, 0, 0, width, height);
    bitmap.close();
    const blob = await canvas.convertToBlob({ type: "image/jpeg", quality: 0.55 });
    self.postMessage({ blob });
  } catch (error) {
    bitmap.close();
    self.postMessage({ error: error.message || "Не удалось обработать кадр" });
  }
};
