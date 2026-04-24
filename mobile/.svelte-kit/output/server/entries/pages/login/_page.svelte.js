import { d as attr, j as escape_html } from "../../../chunks/renderer.js";
import "@sveltejs/kit/internal";
import "../../../chunks/exports.js";
import "../../../chunks/utils.js";
import "@sveltejs/kit/internal/server";
import "../../../chunks/root.js";
import "../../../chunks/state.svelte.js";
function _page($$renderer, $$props) {
  $$renderer.component(($$renderer2) => {
    let password = "";
    let loading = false;
    $$renderer2.push(`<div class="min-h-screen flex items-center justify-center px-6 bg-surface"><div class="w-full max-w-sm"><h1 class="text-2xl font-semibold text-text text-center mb-2">Mobly</h1> <p class="text-muted text-sm text-center mb-8">Dashy on the go</p> <form class="space-y-4"><div><input type="password"${attr("value", password)} placeholder="Password" autocomplete="current-password"${attr("disabled", loading, true)} class="w-full px-4 py-3 rounded-xl bg-panel border border-border text-text placeholder-muted focus:outline-none focus:border-accent text-base"/></div> `);
    {
      $$renderer2.push("<!--[-1-->");
    }
    $$renderer2.push(`<!--]--> <button type="submit"${attr("disabled", !password, true)} class="w-full py-3 rounded-xl bg-accent text-white font-semibold text-base disabled:opacity-50 active:scale-95 transition-transform">${escape_html("Sign in")}</button></form></div></div>`);
  });
}
export {
  _page as default
};
