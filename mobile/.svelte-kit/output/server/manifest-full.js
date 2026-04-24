export const manifest = (() => {
function __memo(fn) {
	let value;
	return () => value ??= (value = fn());
}

return {
	appDir: "_app",
	appPath: "m/_app",
	assets: new Set([]),
	mimeTypes: {},
	_: {
		client: {start:"_app/immutable/entry/start.CFjGOokG.js",app:"_app/immutable/entry/app.C3gDCXIi.js",imports:["_app/immutable/entry/start.CFjGOokG.js","_app/immutable/chunks/B8-FHjim.js","_app/immutable/chunks/Bu5-Xfov.js","_app/immutable/chunks/mV3WEij6.js","_app/immutable/entry/app.C3gDCXIi.js","_app/immutable/chunks/Bu5-Xfov.js","_app/immutable/chunks/BIS0NNLO.js","_app/immutable/chunks/Bzak7iHL.js","_app/immutable/chunks/mV3WEij6.js","_app/immutable/chunks/BD9RZtQ1.js","_app/immutable/chunks/PFHfdXVR.js","_app/immutable/chunks/B_JSTXDE.js"],stylesheets:[],fonts:[],uses_env_dynamic_public:false},
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
