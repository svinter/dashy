import { s as ssr_context, g as getContext, f as fallback, a as slot, b as bind_props, c as store_get, e as ensure_array_like, d as attr, h as attr_class, i as stringify, j as escape_html, u as unsubscribe_stores } from "../../chunks/renderer.js";
import "@sveltejs/kit/internal";
import "../../chunks/exports.js";
import "../../chunks/utils.js";
import "@sveltejs/kit/internal/server";
import "../../chunks/root.js";
import "../../chunks/state.svelte.js";
import "clsx";
import { w as writable } from "../../chunks/index.js";
import { b as base } from "../../chunks/server.js";
import { QueryClient } from "@tanstack/query-core";
import { s as setQueryClientContext } from "../../chunks/context.js";
function onDestroy(fn) {
  /** @type {SSRContext} */
  ssr_context.r.on_destroy(fn);
}
const getStores = () => {
  const stores$1 = getContext("__svelte__");
  return {
    /** @type {typeof page} */
    page: {
      subscribe: stores$1.page.subscribe
    },
    /** @type {typeof navigating} */
    navigating: {
      subscribe: stores$1.navigating.subscribe
    },
    /** @type {typeof updated} */
    updated: stores$1.updated
  };
};
const page = {
  subscribe(fn) {
    const store = getStores().page;
    return store.subscribe(fn);
  }
};
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
    $$renderer2.push(`<nav class="fixed bottom-0 left-0 right-0 bg-panel border-t border-border safe-bottom z-50" style="padding-bottom: max(0.5rem, env(safe-area-inset-bottom))"><div class="flex"><!--[-->`);
    const each_array = ensure_array_like(tabs);
    for (let $$index = 0, $$length = each_array.length; $$index < $$length; $$index++) {
      let tab = each_array[$$index];
      const active = current.startsWith(tab.href);
      $$renderer2.push(`<a${attr("href", tab.href)}${attr_class(`flex-1 flex flex-col items-center gap-0.5 py-2 transition-colors ${stringify(active ? "text-accent" : "text-muted hover:text-text")}`)}><span class="text-xl leading-none">${escape_html(tab.icon)}</span> <span class="text-xs font-medium">${escape_html(tab.label)}</span></a>`);
    }
    $$renderer2.push(`<!--]--></div></nav>`);
    if ($$store_subs) unsubscribe_stores($$store_subs);
  });
}
function _layout($$renderer, $$props) {
  $$renderer.component(($$renderer2) => {
    var $$store_subs;
    let isLogin;
    const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 6e4, retry: 1 } } });
    isLogin = store_get($$store_subs ??= {}, "$page", page).url.pathname === "/m/login" || store_get($$store_subs ??= {}, "$page", page).url.pathname === "/login";
    QueryClientProvider($$renderer2, {
      client: queryClient,
      children: ($$renderer3) => {
        $$renderer3.push(`<div class="flex flex-col h-screen bg-surface text-text overflow-hidden">`);
        if (store_get($$store_subs ??= {}, "$authed", authed) === null) {
          $$renderer3.push("<!--[0-->");
          $$renderer3.push(`<div class="flex-1 flex items-center justify-center"><div class="text-muted text-sm">Loading…</div></div>`);
        } else {
          $$renderer3.push("<!--[-1-->");
          $$renderer3.push(`<main class="flex-1 overflow-y-auto pb-safe-nav"><!--[-->`);
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
