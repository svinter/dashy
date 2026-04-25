import { a as store_get, c as attr, i as escape_html, e as ensure_array_like, u as unsubscribe_stores, g as stringify } from "../../../chunks/renderer.js";
import { a as getIsRestoringContext, b as getQueryClientContext, g as goto } from "../../../chunks/context.js";
import { b as base } from "../../../chunks/server.js";
import "../../../chunks/exports.js";
import "@sveltejs/kit/internal/server";
import "../../../chunks/root.js";
import { noop, notifyManager, QueryObserver } from "@tanstack/query-core";
import { r as readable, d as derived, g as get } from "../../../chunks/index.js";
function useIsRestoring() {
  return getIsRestoringContext();
}
function useQueryClient(queryClient) {
  return getQueryClientContext();
}
function isSvelteStore(obj) {
  return "subscribe" in obj && typeof obj.subscribe === "function";
}
function createBaseQuery(options, Observer, queryClient) {
  const client = useQueryClient();
  const isRestoring = useIsRestoring();
  const optionsStore = isSvelteStore(options) ? options : readable(options);
  const defaultedOptionsStore = derived([optionsStore, isRestoring], ([$optionsStore, $isRestoring]) => {
    const defaultedOptions = client.defaultQueryOptions($optionsStore);
    defaultedOptions._optimisticResults = $isRestoring ? "isRestoring" : "optimistic";
    return defaultedOptions;
  });
  const observer = new Observer(client, get(defaultedOptionsStore));
  defaultedOptionsStore.subscribe(($defaultedOptions) => {
    observer.setOptions($defaultedOptions);
  });
  const result = derived(isRestoring, ($isRestoring, set) => {
    const unsubscribe = $isRestoring ? noop : observer.subscribe(notifyManager.batchCalls(set));
    observer.updateResult();
    return unsubscribe;
  });
  const { subscribe } = derived([result, defaultedOptionsStore], ([$result, $defaultedOptionsStore]) => {
    $result = observer.getOptimisticResult($defaultedOptionsStore);
    return !$defaultedOptionsStore.notifyOnChangeProps ? observer.trackResult($result) : $result;
  });
  return { subscribe };
}
function createQuery(options, queryClient) {
  return createBaseQuery(options, QueryObserver);
}
const BASE = "/api/mobile";
async function apiFetch(path, options) {
  const res = await fetch(`${BASE}${path}`, {
    credentials: "include",
    ...options
  });
  if (res.status === 401) {
    throw new Error("UNAUTHENTICATED");
  }
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json();
}
function fetchLibbySearch(q = "") {
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  return apiFetch(`/libby/search?${params}`);
}
function _page($$renderer, $$props) {
  $$renderer.component(($$renderer2) => {
    var $$store_subs;
    let query;
    let q = "";
    let searchQ = "";
    function typeEmoji(code) {
      const map = {
        b: "📖",
        a: "📄",
        e: "✍️",
        p: "🎙️",
        v: "🎬",
        m: "🎥",
        t: "🛠️",
        w: "🌐",
        s: "📋",
        z: "📊",
        n: "📝",
        d: "📑",
        f: "🗂️",
        c: "🎓",
        r: "🔬",
        q: "💬"
      };
      return map[code] ?? "📚";
    }
    query = createQuery({
      queryKey: ["libby-search", searchQ],
      queryFn: () => fetchLibbySearch(searchQ)
    });
    if (store_get($$store_subs ??= {}, "$query", query).isError && store_get($$store_subs ??= {}, "$query", query).error?.message === "UNAUTHENTICATED") {
      goto(`${base}/login`, {});
    }
    $$renderer2.push(`<div style="display:flex; flex-direction:column; height:100%;"><div style="padding:12px 16px 10px; background:#1e293b; border-bottom:1px solid #334155; position:sticky; top:0; z-index:10;"><div style="position:relative; display:flex; align-items:center;"><svg style="position:absolute; left:10px; width:16px; height:16px; color:#64748b; pointer-events:none;" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"></circle><path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-4.35-4.35"></path></svg> <input${attr(
      "value",
      // --- Search ---
      // --- Detail overlay ---
      /* cancelled */
      // --- Edit notes ---
      // --- Clipboard with execCommand fallback (works over HTTP) ---
      // --- Add flow ---
      // Step 1: check for existing entry before any Google Books lookup
      // URLs skip the exists check — unlikely to be duplicated exactly
      // On error just fall through to lookup
      // Step 2: Google Books lookup (called after exists check passes or user overrides)
      // --- Toast ---
      q
    )} type="search" placeholder="Search your library…" autocomplete="off" autocorrect="off"${attr("spellcheck", false)} style="width:100%; padding:9px 36px 9px 34px; background:#0f172a; color:#f1f5f9; border:1px solid #334155; border-radius:8px; font-size:15px; outline:none; box-sizing:border-box; -webkit-appearance:none; appearance:none;"/> `);
    {
      $$renderer2.push("<!--[-1-->");
    }
    $$renderer2.push(`<!--]--></div></div> <div style="flex:1; overflow-y:auto;">`);
    if (store_get($$store_subs ??= {}, "$query", query).isPending) {
      $$renderer2.push("<!--[0-->");
      $$renderer2.push(`<div style="display:flex; align-items:center; justify-content:center; padding:80px 0; color:#64748b; font-size:14px;">Loading…</div>`);
    } else if (store_get($$store_subs ??= {}, "$query", query).isError) {
      $$renderer2.push("<!--[1-->");
      $$renderer2.push(`<div style="display:flex; flex-direction:column; align-items:center; padding:80px 0; gap:12px;"><p style="color:#ef4444; font-size:14px; margin:0;">Session expired</p> <a${attr("href", `${stringify(base)}/login`)} style="color:#3b82f6; font-size:14px; text-decoration:underline;">Go to Login</a></div>`);
    } else if (!store_get($$store_subs ??= {}, "$query", query).data?.items.length) {
      $$renderer2.push("<!--[2-->");
      $$renderer2.push(`<div style="display:flex; flex-direction:column; align-items:center; padding:80px 0; gap:8px; color:#64748b;"><span style="font-size:3rem;">📚</span> <p style="font-size:14px; margin:0;">${escape_html("No items yet")}</p></div>`);
    } else {
      $$renderer2.push("<!--[-1-->");
      $$renderer2.push(`<ul style="list-style:none; margin:0; padding:0;"><!--[-->`);
      const each_array = ensure_array_like(store_get($$store_subs ??= {}, "$query", query).data.items);
      for (let $$index = 0, $$length = each_array.length; $$index < $$length; $$index++) {
        let item = each_array[$$index];
        $$renderer2.push(`<li><button style="width:100%; display:flex; align-items:flex-start; gap:12px; padding:12px 16px; background:none; border:none; border-bottom:1px solid #1e293b; cursor:pointer; text-align:left; -webkit-tap-highlight-color:transparent;">`);
        if (item.cover_url) {
          $$renderer2.push("<!--[0-->");
          $$renderer2.push(`<img${attr("src", item.cover_url)} alt="" style="width:40px; height:56px; object-fit:cover; border-radius:4px; flex-shrink:0; background:#1e293b;" loading="lazy"/>`);
        } else {
          $$renderer2.push("<!--[-1-->");
          $$renderer2.push(`<div style="width:40px; height:56px; flex-shrink:0; border-radius:4px; background:#1e293b; display:flex; align-items:center; justify-content:center; font-size:22px;">${escape_html(typeEmoji(item.type_code))}</div>`);
        }
        $$renderer2.push(`<!--]--> <div style="flex:1; min-width:0;"><p style="color:#f1f5f9; font-size:14px; font-weight:500; line-height:1.3; margin:0 0 3px; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden;">${escape_html(item.name)}</p> `);
        if (item.author) {
          $$renderer2.push("<!--[0-->");
          $$renderer2.push(`<p style="color:#64748b; font-size:12px; margin:0 0 3px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${escape_html(item.author)}</p>`);
        } else {
          $$renderer2.push("<!--[-1-->");
        }
        $$renderer2.push(`<!--]--> `);
        if (item.comments) {
          $$renderer2.push("<!--[0-->");
          $$renderer2.push(`<p style="color:#475569; font-size:11px; font-style:italic; margin:0 0 4px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${escape_html(item.comments)}</p>`);
        } else {
          $$renderer2.push("<!--[-1-->");
        }
        $$renderer2.push(`<!--]--> <span style="display:inline-block; font-size:11px; padding:2px 6px; border-radius:4px; background:#0f172a; color:#94a3b8; border:1px solid #334155;">${escape_html(item.type_label ?? item.type_code.toUpperCase())}</span></div></button></li>`);
      }
      $$renderer2.push(`<!--]--></ul> <p style="text-align:center; font-size:12px; color:#475569; padding:16px 0;">${escape_html(store_get($$store_subs ??= {}, "$query", query).data.total)} item${escape_html(store_get($$store_subs ??= {}, "$query", query).data.total !== 1 ? "s" : "")}</p>`);
    }
    $$renderer2.push(`<!--]--></div></div> <button style="position:fixed; bottom:calc(4rem + env(safe-area-inset-bottom) + 16px); right:20px; width:52px; height:52px; border-radius:50%; background:#3b82f6; color:#fff; border:none; cursor:pointer; display:flex; align-items:center; justify-content:center; font-size:26px; font-weight:300; line-height:1; box-shadow:0 4px 16px rgba(59,130,246,0.4); z-index:40;" aria-label="Add to library">+</button> `);
    {
      $$renderer2.push("<!--[-1-->");
    }
    $$renderer2.push(`<!--]--> `);
    {
      $$renderer2.push("<!--[-1-->");
    }
    $$renderer2.push(`<!--]--> `);
    {
      $$renderer2.push("<!--[-1-->");
    }
    $$renderer2.push(`<!--]-->`);
    if ($$store_subs) unsubscribe_stores($$store_subs);
  });
}
export {
  _page as default
};
