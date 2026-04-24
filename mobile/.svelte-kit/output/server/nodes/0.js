

export const index = 0;
let component_cache;
export const component = async () => component_cache ??= (await import('../entries/pages/_layout.svelte.js')).default;
export const universal = {
  "ssr": false,
  "prerender": false
};
export const universal_id = "src/routes/+layout.ts";
export const imports = ["_app/immutable/nodes/0.DT7dBE3m.js","_app/immutable/chunks/Bzak7iHL.js","_app/immutable/chunks/D3gbBZbj.js","_app/immutable/chunks/Bu5-Xfov.js","_app/immutable/chunks/mV3WEij6.js","_app/immutable/chunks/B_JSTXDE.js","_app/immutable/chunks/BIS0NNLO.js","_app/immutable/chunks/BD9RZtQ1.js","_app/immutable/chunks/C7v8kFZs.js","_app/immutable/chunks/mC1AaEgb.js","_app/immutable/chunks/DFuOD32c.js","_app/immutable/chunks/CV_3cAQr.js","_app/immutable/chunks/D8YEG-aL.js","_app/immutable/chunks/PFHfdXVR.js"];
export const stylesheets = ["_app/immutable/assets/0.B28APjFu.css"];
export const fonts = [];
