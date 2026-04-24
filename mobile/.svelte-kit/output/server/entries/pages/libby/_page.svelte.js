import { d as attr, c as store_get, h as attr_class, i as stringify, e as ensure_array_like, j as escape_html, u as unsubscribe_stores } from "../../../chunks/renderer.js";
import { c as createQuery, a as fetchLibby } from "../../../chunks/api.js";
function _page($$renderer, $$props) {
  $$renderer.component(($$renderer2) => {
    var $$store_subs;
    const query = createQuery({
      queryKey: ["libby"],
      queryFn: fetchLibby,
      refetchOnWindowFocus: true
    });
    function dueColor(days) {
      if (days === null) return "text-muted";
      if (days < 0) return "text-danger font-semibold";
      if (days <= 2) return "text-danger";
      if (days <= 5) return "text-warn";
      return "text-ok";
    }
    function dueLabel(item) {
      if (!item.loan_due_date) return "";
      const d = item.days_left;
      if (d === null) return item.loan_due_date;
      if (d < 0) return `Overdue by ${Math.abs(d)}d`;
      if (d === 0) return "Due today";
      if (d === 1) return "Due tomorrow";
      return `${d}d left`;
    }
    function typeLabel(item) {
      return item.type_label || item.type_code.toUpperCase();
    }
    $$renderer2.push(`<div class="flex flex-col h-full"><header class="flex items-center justify-between px-4 pt-safe-top pb-3 bg-panel border-b border-border sticky top-0 z-10"><h1 class="text-lg font-semibold">Libby</h1> <button${attr("disabled", store_get($$store_subs ??= {}, "$query", query).isFetching, true)} class="p-2 text-muted hover:text-text disabled:opacity-40 active:scale-90 transition-transform" aria-label="Refresh"><svg${attr_class(`w-5 h-5 ${stringify(store_get($$store_subs ??= {}, "$query", query).isFetching ? "animate-spin" : "")}`)} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path></svg></button></header> <div class="flex-1 overflow-y-auto">`);
    if (store_get($$store_subs ??= {}, "$query", query).isPending) {
      $$renderer2.push("<!--[0-->");
      $$renderer2.push(`<div class="flex items-center justify-center py-20 text-muted text-sm">Loading…</div>`);
    } else if (store_get($$store_subs ??= {}, "$query", query).isError) {
      $$renderer2.push("<!--[1-->");
      $$renderer2.push(`<div class="flex flex-col items-center justify-center py-20 gap-3"><p class="text-danger text-sm">Failed to load loans</p> <button class="text-accent text-sm underline">Try again</button></div>`);
    } else if (store_get($$store_subs ??= {}, "$query", query).data?.items.length === 0) {
      $$renderer2.push("<!--[2-->");
      $$renderer2.push(`<div class="flex flex-col items-center justify-center py-20 gap-2 text-muted"><span class="text-4xl">📚</span> <p class="text-sm">No active loans</p></div>`);
    } else {
      $$renderer2.push("<!--[-1-->");
      $$renderer2.push(`<ul class="divide-y divide-border"><!--[-->`);
      const each_array = ensure_array_like(store_get($$store_subs ??= {}, "$query", query).data?.items ?? []);
      for (let $$index = 0, $$length = each_array.length; $$index < $$length; $$index++) {
        let item = each_array[$$index];
        $$renderer2.push(`<li class="px-4 py-3 flex items-start gap-3">`);
        if (item.cover_url) {
          $$renderer2.push("<!--[0-->");
          $$renderer2.push(`<img${attr("src", item.cover_url)} alt="" class="w-10 h-14 object-cover rounded flex-shrink-0 bg-panel" loading="lazy"/>`);
        } else {
          $$renderer2.push("<!--[-1-->");
          $$renderer2.push(`<div class="w-10 h-14 flex-shrink-0 rounded bg-panel flex items-center justify-center text-lg">📖</div>`);
        }
        $$renderer2.push(`<!--]--> <div class="flex-1 min-w-0"><p class="text-sm font-medium leading-snug line-clamp-2">${escape_html(item.name)}</p> `);
        if (item.author) {
          $$renderer2.push("<!--[0-->");
          $$renderer2.push(`<p class="text-xs text-muted mt-0.5 truncate">${escape_html(item.author)}</p>`);
        } else {
          $$renderer2.push("<!--[-1-->");
        }
        $$renderer2.push(`<!--]--> <div class="flex items-center gap-2 mt-1.5"><span class="text-xs px-1.5 py-0.5 rounded bg-surface text-muted border border-border">${escape_html(typeLabel(item))}</span> `);
        if (item.loan_due_date) {
          $$renderer2.push("<!--[0-->");
          $$renderer2.push(`<span${attr_class(`text-xs ${stringify(dueColor(item.days_left))}`)}>${escape_html(dueLabel(item))}</span>`);
        } else {
          $$renderer2.push("<!--[-1-->");
        }
        $$renderer2.push(`<!--]--></div></div></li>`);
      }
      $$renderer2.push(`<!--]--></ul> <p class="text-center text-xs text-muted py-4">${escape_html(store_get($$store_subs ??= {}, "$query", query).data?.total ?? 0)} loan${escape_html((store_get($$store_subs ??= {}, "$query", query).data?.total ?? 0) !== 1 ? "s" : "")}</p>`);
    }
    $$renderer2.push(`<!--]--></div></div>`);
    if ($$store_subs) unsubscribe_stores($$store_subs);
  });
}
export {
  _page as default
};
