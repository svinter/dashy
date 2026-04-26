export const manifest = (() => {
function __memo(fn) {
	let value;
	return () => value ??= (value = fn());
}

return {
	appDir: "_app",
	appPath: "m/_app",
	assets: new Set(["icons/icon-192.png","icons/icon-512.png"]),
	mimeTypes: {".png":"image/png"},
	_: {
		client: {start:"_app/immutable/entry/start.CiUZcV7e.js",app:"_app/immutable/entry/app.Bb0pXuKV.js",imports:["_app/immutable/entry/start.CiUZcV7e.js","_app/immutable/chunks/D6H9-K3h.js","_app/immutable/chunks/BpZ1yv4S.js","_app/immutable/chunks/DIeogL5L.js","_app/immutable/entry/app.Bb0pXuKV.js","_app/immutable/chunks/BpZ1yv4S.js","_app/immutable/chunks/DIeogL5L.js","_app/immutable/chunks/BGGiHX45.js","_app/immutable/chunks/Bzak7iHL.js","_app/immutable/chunks/AsXazkwT.js","_app/immutable/chunks/oVOihvnG.js","_app/immutable/chunks/D-WKM5Fl.js"],stylesheets:[],fonts:[],uses_env_dynamic_public:false},
		nodes: [
			__memo(() => import('./nodes/0.js')),
			__memo(() => import('./nodes/1.js')),
			__memo(() => import('./nodes/2.js')),
			__memo(() => import('./nodes/3.js')),
			__memo(() => import('./nodes/4.js')),
			__memo(() => import('./nodes/5.js'))
		],
		remotes: {
			
		},
		routes: [
			{
				id: "/",
				pattern: /^\/$/,
				params: [],
				page: { layouts: [0,], errors: [1,], leaf: 2 },
				endpoint: null
			},
			{
				id: "/glance",
				pattern: /^\/glance\/?$/,
				params: [],
				page: { layouts: [0,], errors: [1,], leaf: 3 },
				endpoint: null
			},
			{
				id: "/libby",
				pattern: /^\/libby\/?$/,
				params: [],
				page: { layouts: [0,], errors: [1,], leaf: 4 },
				endpoint: null
			},
			{
				id: "/login",
				pattern: /^\/login\/?$/,
				params: [],
				page: { layouts: [0,], errors: [1,], leaf: 5 },
				endpoint: null
			}
		],
		prerendered_routes: new Set([]),
		matchers: async () => {
			
			return {  };
		},
		server_assets: {}
	}
}
})();
