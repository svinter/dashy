import { f as fallback, s as slot, b as bind_props, a as store_get, e as ensure_array_like, c as attr, d as attr_class, g as stringify, h as attr_style, i as escape_html, u as unsubscribe_stores } from "../../chunks/renderer.js";
import { s as setQueryClientContext, g as goto } from "../../chunks/context.js";
import { p as page } from "../../chunks/stores.js";
import { b as base } from "../../chunks/server.js";
import "../../chunks/exports.js";
import "@sveltejs/kit/internal/server";
import "../../chunks/root.js";
import { w as writable } from "../../chunks/index.js";
import { o as onDestroy } from "../../chunks/index-server.js";
import { QueryClient } from "@tanstack/query-core";
function QueryClientProvider($$renderer, $$props) {
  $$renderer.component(($$renderer2) => {
    let client = fallback($$props["client"], () => new QueryClient(), true);
    setQueryClientContext(client);
    onDestroy(() => {
      client.unmount();
    });
    $$renderer2.push(`<!--[-->`);
    slot($$renderer2, $$props, "default", {});
    $$renderer2.push(`<!--]-->`);
    bind_props($$props, { client });
  });
}
const authed = writable(null);
function BottomNav($$renderer, $$props) {
  $$renderer.component(($$renderer2) => {
    var $$store_subs;
    let current;
    const tabs = [
      { href: `${base}/libby`, label: "Libby", icon: "📚" },
      { href: `${base}/glance`, label: "Glance", icon: "📅" }
    ];
    current = store_get($$store_subs ??= {}, "$page", page).url.pathname;
    $$renderer2.push(`<nav class="fixed bottom-0 left-0 right-0 z-50" style="position: fixed; bottom: 0; left: 0; right: 0; background: #1e293b; border-top: 1px solid #334155; padding-bottom: max(0.5rem, env(safe-area-inset-bottom)); z-index: 50;"><div class="flex" style="display: flex;"><!--[-->`);
    const each_array = ensure_array_like(tabs);
    for (let $$index = 0, $$length = each_array.length; $$index < $$length; $$index++) {
      let tab = each_array[$$index];
      const active = current.startsWith(tab.href);
      $$renderer2.push(`<a${attr("href", tab.href)}${attr_class(`flex-1 flex flex-col items-center gap-0.5 py-2 transition-colors ${stringify(active ? "text-accent" : "text-muted")}`)}${attr_style(` flex: 1; display: flex; flex-direction: column; align-items: center; gap: 2px; padding: 0.5rem 0; text-decoration: none; color: ${stringify(active ? "#3b82f6" : "#64748b")}; transition: color 0.15s; `)}><span class="text-xl leading-none" style="font-size: 1.25rem; line-height: 1;">${escape_html(tab.icon)}</span> <span class="text-xs font-medium" style="font-size: 0.75rem; font-weight: 500;">${escape_html(tab.label)}</span></a>`);
    }
    $$renderer2.push(`<!--]--></div></nav>`);
    if ($$store_subs) unsubscribe_stores($$store_subs);
  });
}
function _layout($$renderer, $$props) {
  $$renderer.component(($$renderer2) => {
    var $$store_subs;
    let isLogin, isRoot;
    const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 6e4, retry: 1 } } });
    isLogin = store_get($$store_subs ??= {}, "$page", page).url.pathname.endsWith("/login");
    isRoot = store_get($$store_subs ??= {}, "$page", page).url.pathname === base || store_get($$store_subs ??= {}, "$page", page).url.pathname === base + "/";
    if (store_get($$store_subs ??= {}, "$authed", authed) === true && isRoot) {
      goto(`${base}/libby`, {});
    }
    if (store_get($$store_subs ??= {}, "$authed", authed) === false && !isLogin) {
      goto(`${base}/login`, {});
    }
    QueryClientProvider($$renderer2, {
      client: queryClient,
      children: ($$renderer3) => {
        $$renderer3.push(`<div class="flex flex-col h-screen bg-surface text-text overflow-hidden" style="display:flex; flex-direction:column; height:100vh; background:#0f172a; color:#f1f5f9; overflow:hidden;">`);
        if (store_get($$store_subs ??= {}, "$authed", authed) === null) {
          $$renderer3.push("<!--[0-->");
          $$renderer3.push(`<div class="flex-1 flex items-center justify-center" style="flex:1; display:flex; align-items:center; justify-content:center;"><div style="font-size:14px; color:#94a3b8;">Loading…</div></div>`);
        } else {
          $$renderer3.push("<!--[-1-->");
          $$renderer3.push(`<main class="flex-1 overflow-y-auto pb-safe-nav" style="flex:1; overflow-y:auto; padding-bottom:calc(4rem + env(safe-area-inset-bottom));"><!--[-->`);
          slot($$renderer3, $$props, "default", {});
          $$renderer3.push(`<!--]--></main> `);
          if (!isLogin && store_get($$store_subs ??= {}, "$authed", authed)) {
            $$renderer3.push("<!--[0-->");
            BottomNav($$renderer3);
          } else {
            $$renderer3.push("<!--[-1-->");
          }
          $$renderer3.push(`<!--]-->`);
        }
        $$renderer3.push(`<!--]--></div>`);
      },
      $$slots: { default: true }
    });
    if ($$store_subs) unsubscribe_stores($$store_subs);
  });
}
export {
  _layout as default
};
