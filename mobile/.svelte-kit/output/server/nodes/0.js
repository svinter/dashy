

export const index = 0;
let component_cache;
export const component = async () => component_cache ??= (await import('../entries/pages/_layout.svelte.js')).default;
export const universal = {
  "ssr": false,
  "prerender": false
};
export const universal_id = "src/routes/+layout.ts";
export const imports = ["_app/immutable/nodes/0.DV7-9MXf.js","_app/immutable/chunks/Bzak7iHL.js","_app/immutable/chunks/69_IOA4Y.js","_app/immutable/chunks/DIeogL5L.js","_app/immutable/chunks/BpZ1yv4S.js","_app/immutable/chunks/D-WKM5Fl.js","_app/immutable/chunks/BGGiHX45.js","_app/immutable/chunks/Do0rDoNi.js","_app/immutable/chunks/CqpzSybk.js","_app/immutable/chunks/BN7BA4Zs.js","_app/immutable/chunks/CvmdZg48.js","_app/immutable/chunks/DNm0cmnJ.js","_app/immutable/chunks/DxdE54Ux.js","_app/immutable/chunks/B1D2DcCs.js","_app/immutable/chunks/CbkIAQm9.js","_app/immutable/chunks/Dlm0xzMk.js","_app/immutable/chunks/oVOihvnG.js"];
export const stylesheets = ["_app/immutable/assets/0.DvoxXx6E.css"];
export const fonts = [];
