import { c as attr, i as escape_html, d as attr_class, g as stringify } from "../../../chunks/renderer.js";
import { o as onDestroy } from "../../../chunks/index-server.js";
function _page($$renderer, $$props) {
  $$renderer.component(($$renderer2) => {
    let loading = false;
    onDestroy(() => {
    });
    $$renderer2.push(`<div class="flex flex-col h-full"><header class="flex items-center gap-2 px-3 pt-safe-top pb-2 bg-panel border-b border-border sticky top-0 z-10"><button${attr("disabled", loading, true)} class="p-2 text-muted hover:text-text disabled:opacity-40 active:scale-90 transition-transform" aria-label="Back 4 weeks"><svg class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M15 19l-7-7 7-7"></path></svg></button> <div class="flex-1 min-w-0 text-center"><h1 class="text-sm font-semibold truncate">${escape_html("Glance")}</h1></div> <button${attr("disabled", loading, true)} class="text-xs text-accent disabled:opacity-40 px-1">Today</button> <button${attr("disabled", loading, true)} class="p-2 text-muted hover:text-text disabled:opacity-40 active:scale-90 transition-transform" aria-label="Refresh"><svg${attr_class(`w-5 h-5 ${stringify("")}`)} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path></svg></button> <button${attr("disabled", loading, true)} class="p-2 text-muted hover:text-text disabled:opacity-40 active:scale-90 transition-transform" aria-label="Forward 4 weeks"><svg class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7"></path></svg></button></header> <div class="flex-1 overflow-auto bg-surface">`);
    {
      $$renderer2.push("<!--[-1-->");
    }
    $$renderer2.push(`<!--]--></div></div>`);
  });
}
export {
  _page as default
};
