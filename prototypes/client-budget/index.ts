/** T-015 kanonik Vue 3 / TypeScript prototip girişi.
 *
 * Üretim uygulaması admin paneldeki saf modüldür. Prototip aynı fonksiyonları
 * yeniden yazmadan dışa açar; gerçek cihaz harness'i `probeCanvasCeiling` ile
 * bu girişten çalıştırılır.
 */
export {
  CLIENT_ACTION,
  DEVICE_CLASS,
  OPERATION,
  SAFE_MEGAPIXELS,
  budgetFor,
  captureCapabilities,
  classifyDevice,
  decideClientProcessing,
  detectBrowser,
  probeCanvasCeiling,
} from "../../../admin-panel/frontend/src/lib/media/upload/deviceBudget.js";
