/**
 * Copyright 2018 Google Inc. All Rights Reserved.
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *     http://www.apache.org/licenses/LICENSE-2.0
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

// If the loader is already loaded, just stop.
if (!self.define) {
  let registry = {};

  // Used for `eval` and `importScripts` where we can't get script URL by other means.
  // In both cases, it's safe to use a global var because those functions are synchronous.
  let nextDefineUri;

  const singleRequire = (uri, parentUri) => {
    uri = new URL(uri + ".js", parentUri).href;
    return registry[uri] || (
      
        new Promise(resolve => {
          if ("document" in self) {
            const script = document.createElement("script");
            script.src = uri;
            script.onload = resolve;
            document.head.appendChild(script);
          } else {
            nextDefineUri = uri;
            importScripts(uri);
            resolve();
          }
        })
      
      .then(() => {
        let promise = registry[uri];
        if (!promise) {
          throw new Error(`Module ${uri} didn’t register its module`);
        }
        return promise;
      })
    );
  };

  self.define = (depsNames, factory) => {
    const uri = nextDefineUri || ("document" in self ? document.currentScript.src : "") || location.href;
    if (registry[uri]) {
      // Module is already loading or loaded.
      return;
    }
    let exports = {};
    const require = depUri => singleRequire(depUri, uri);
    const specialDeps = {
      module: { uri },
      exports,
      require
    };
    registry[uri] = Promise.all(depsNames.map(
      depName => specialDeps[depName] || require(depName)
    )).then(deps => {
      factory(...deps);
      return exports;
    });
  };
}
define(['./workbox-5a5d9309'], (function (workbox) { 'use strict';

  self.skipWaiting();
  workbox.clientsClaim();

  /**
   * The precacheAndRoute() method efficiently caches and responds to
   * requests for URLs in the manifest.
   * See https://goo.gl/S9QRab
   */
  workbox.precacheAndRoute([{
    "url": "registerSW.js",
    "revision": "402b66900e731ca748771b6fc5e7a068"
  }, {
    "url": "_app/immutable/nodes/5.BWb_u3fm.js",
    "revision": null
  }, {
    "url": "_app/immutable/nodes/4.BdGFISRa.js",
    "revision": null
  }, {
    "url": "_app/immutable/nodes/3.DFqKnlQs.js",
    "revision": null
  }, {
    "url": "_app/immutable/nodes/2.BxkvbENq.js",
    "revision": null
  }, {
    "url": "_app/immutable/nodes/1.Ck8od_hU.js",
    "revision": null
  }, {
    "url": "_app/immutable/nodes/0.DT7dBE3m.js",
    "revision": null
  }, {
    "url": "_app/immutable/entry/start.C5Jar85O.js",
    "revision": null
  }, {
    "url": "_app/immutable/entry/app.DP4mneDb.js",
    "revision": null
  }, {
    "url": "_app/immutable/chunks/mV3WEij6.js",
    "revision": null
  }, {
    "url": "_app/immutable/chunks/mC1AaEgb.js",
    "revision": null
  }, {
    "url": "_app/immutable/chunks/PFHfdXVR.js",
    "revision": null
  }, {
    "url": "_app/immutable/chunks/DFuOD32c.js",
    "revision": null
  }, {
    "url": "_app/immutable/chunks/D8YEG-aL.js",
    "revision": null
  }, {
    "url": "_app/immutable/chunks/D3gbBZbj.js",
    "revision": null
  }, {
    "url": "_app/immutable/chunks/C_GWhP3y.js",
    "revision": null
  }, {
    "url": "_app/immutable/chunks/CV_3cAQr.js",
    "revision": null
  }, {
    "url": "_app/immutable/chunks/C7v8kFZs.js",
    "revision": null
  }, {
    "url": "_app/immutable/chunks/Bzak7iHL.js",
    "revision": null
  }, {
    "url": "_app/immutable/chunks/Bu5-Xfov.js",
    "revision": null
  }, {
    "url": "_app/immutable/chunks/B_JSTXDE.js",
    "revision": null
  }, {
    "url": "_app/immutable/chunks/BIS0NNLO.js",
    "revision": null
  }, {
    "url": "_app/immutable/chunks/BD9RZtQ1.js",
    "revision": null
  }, {
    "url": "_app/immutable/assets/0.B28APjFu.css",
    "revision": null
  }, {
    "url": "manifest.webmanifest",
    "revision": "1828317c2296be9a4440d7daeb2a5088"
  }], {});
  workbox.cleanupOutdatedCaches();
  workbox.registerRoute(new workbox.NavigationRoute(workbox.createHandlerBoundToURL("/m/index.html"), {
    allowlist: [/^\/m/]
  }));

}));
