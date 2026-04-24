import { c as store_get, j as escape_html, d as attr, h as attr_class, i as stringify, e as ensure_array_like, k as attr_style, u as unsubscribe_stores } from "../../../chunks/renderer.js";
import { c as createQuery, f as fetchGlance } from "../../../chunks/api.js";
function _page($$renderer, $$props) {
  $$renderer.component(($$renderer2) => {
    var $$store_subs;
    const query = createQuery({
      queryKey: ["glance"],
      queryFn: fetchGlance,
      refetchOnWindowFocus: true
    });
    const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
    function sortedDates(days) {
      return Object.keys(days).sort();
    }
    function todayIso() {
      return (/* @__PURE__ */ new Date()).toISOString().slice(0, 10);
    }
    function dayName(iso) {
      const d = /* @__PURE__ */ new Date(iso + "T12:00:00");
      return DAY_NAMES[d.getDay() === 0 ? 6 : d.getDay() - 1];
    }
    function dayNum(iso) {
      return String(parseInt(iso.slice(8, 10)));
    }
    function memberColor(member_id, members) {
      if (!member_id) return "#64748b";
      return members.find((m) => m.id === member_id)?.color ?? "#64748b";
    }
    $$renderer2.push(`<div class="flex flex-col h-full"><header class="flex items-center justify-between px-4 pt-safe-top pb-3 bg-panel border-b border-border sticky top-0 z-10"><div><h1 class="text-lg font-semibold">Glance</h1> `);
    if (store_get($$store_subs ??= {}, "$query", query).data) {
      $$renderer2.push("<!--[0-->");
      $$renderer2.push(`<p class="text-xs text-muted">Week of ${escape_html(store_get($$store_subs ??= {}, "$query", query).data.week_start)}</p>`);
    } else {
      $$renderer2.push("<!--[-1-->");
    }
    $$renderer2.push(`<!--]--></div> <button${attr("disabled", store_get($$store_subs ??= {}, "$query", query).isFetching, true)} class="p-2 text-muted hover:text-text disabled:opacity-40 active:scale-90 transition-transform" aria-label="Refresh"><svg${attr_class(`w-5 h-5 ${stringify(store_get($$store_subs ??= {}, "$query", query).isFetching ? "animate-spin" : "")}`)} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path></svg></button></header> <div class="flex-1 overflow-y-auto">`);
    if (store_get($$store_subs ??= {}, "$query", query).isPending) {
      $$renderer2.push("<!--[0-->");
      $$renderer2.push(`<div class="flex items-center justify-center py-20 text-muted text-sm">Loading…</div>`);
    } else if (store_get($$store_subs ??= {}, "$query", query).isError) {
      $$renderer2.push("<!--[1-->");
      $$renderer2.push(`<div class="flex flex-col items-center justify-center py-20 gap-3"><p class="text-danger text-sm">Failed to load Glance</p> <button class="text-accent text-sm underline">Try again</button></div>`);
    } else if (store_get($$store_subs ??= {}, "$query", query).data) {
      $$renderer2.push("<!--[2-->");
      const data = store_get($$store_subs ??= {}, "$query", query).data;
      const today = todayIso();
      const dates = sortedDates(data.days);
      $$renderer2.push(`<div class="px-3 py-3 space-y-2"><!--[-->`);
      const each_array = ensure_array_like(dates);
      for (let $$index_2 = 0, $$length = each_array.length; $$index_2 < $$length; $$index_2++) {
        let iso = each_array[$$index_2];
        const day = data.days[iso];
        const isToday = iso === today;
        $$renderer2.push(`<div${attr_class(`rounded-xl overflow-hidden border ${stringify(isToday ? "border-accent" : "border-border")} bg-panel`)}><div${attr_class(`flex items-center gap-2 px-3 py-2 ${stringify(isToday ? "bg-accent/10" : "bg-surface")}`)}><span${attr_class(`text-xs font-medium ${stringify(isToday ? "text-accent" : "text-muted")} w-7`)}>${escape_html(dayName(iso))}</span> <span${attr_class(`text-sm font-semibold ${stringify(isToday ? "text-accent" : "text-text")}`)}>${escape_html(dayNum(iso))}</span> `);
        if (isToday) {
          $$renderer2.push("<!--[0-->");
          $$renderer2.push(`<span class="text-xs text-accent ml-auto">today</span>`);
        } else {
          $$renderer2.push("<!--[-1-->");
        }
        $$renderer2.push(`<!--]--></div> `);
        if (day.trips.length > 0) {
          $$renderer2.push("<!--[0-->");
          $$renderer2.push(`<div class="px-3 pb-1 pt-1 flex flex-wrap gap-1.5"><!--[-->`);
          const each_array_1 = ensure_array_like(day.trips);
          for (let $$index = 0, $$length2 = each_array_1.length; $$index < $$length2; $$index++) {
            let trip = each_array_1[$$index];
            $$renderer2.push(`<span class="text-xs px-2 py-1 rounded-full font-medium"${attr_style(`background-color: ${stringify(trip.color_data || "#334155")}; color: ${stringify(trip.text_color || "#f1f5f9")}`)}>`);
            if (trip.location) {
              $$renderer2.push("<!--[0-->");
              $$renderer2.push(`✈ ${escape_html(trip.location)}`);
            } else {
              $$renderer2.push("<!--[-1-->");
              $$renderer2.push(`✈ trip`);
            }
            $$renderer2.push(`<!--]--></span>`);
          }
          $$renderer2.push(`<!--]--></div>`);
        } else {
          $$renderer2.push("<!--[-1-->");
        }
        $$renderer2.push(`<!--]--> `);
        if (day.entries.length > 0) {
          $$renderer2.push("<!--[0-->");
          $$renderer2.push(`<div class="px-3 pb-2 pt-1 space-y-1"><!--[-->`);
          const each_array_2 = ensure_array_like(day.entries);
          for (let $$index_1 = 0, $$length2 = each_array_2.length; $$index_1 < $$length2; $$index_1++) {
            let entry = each_array_2[$$index_1];
            $$renderer2.push(`<div class="flex items-start gap-2">`);
            if (entry.member_id) {
              $$renderer2.push("<!--[0-->");
              $$renderer2.push(`<span class="w-2 h-2 rounded-full flex-shrink-0 mt-1.5"${attr_style(`background-color: ${stringify(memberColor(entry.member_id, data.members))}`)}></span>`);
            } else {
              $$renderer2.push("<!--[-1-->");
              $$renderer2.push(`<span class="w-2 h-2 rounded-full flex-shrink-0 mt-1.5 bg-border"></span>`);
            }
            $$renderer2.push(`<!--]--> <div class="flex-1 min-w-0">`);
            if (entry.color_data && entry.label) {
              $$renderer2.push("<!--[0-->");
              $$renderer2.push(`<span class="inline-block text-xs px-1.5 py-0.5 rounded font-medium"${attr_style(`background-color: ${stringify(entry.color_data)}; color: ${stringify(entry.text_color || "#f1f5f9")}`)}>${escape_html(entry.label)}</span>`);
            } else {
              $$renderer2.push("<!--[-1-->");
              $$renderer2.push(`<span class="text-xs text-text">${escape_html(entry.label)}</span>`);
            }
            $$renderer2.push(`<!--]--> `);
            if (entry.notes) {
              $$renderer2.push("<!--[0-->");
              $$renderer2.push(`<p class="text-xs text-muted mt-0.5 line-clamp-2">${escape_html(entry.notes)}</p>`);
            } else {
              $$renderer2.push("<!--[-1-->");
            }
            $$renderer2.push(`<!--]--></div></div>`);
          }
          $$renderer2.push(`<!--]--></div>`);
        } else {
          $$renderer2.push("<!--[-1-->");
        }
        $$renderer2.push(`<!--]--> `);
        if (day.trips.length === 0 && day.entries.length === 0) {
          $$renderer2.push("<!--[0-->");
          $$renderer2.push(`<div class="px-3 pb-2 text-xs text-muted italic">—</div>`);
        } else {
          $$renderer2.push("<!--[-1-->");
        }
        $$renderer2.push(`<!--]--></div>`);
      }
      $$renderer2.push(`<!--]--></div> `);
      if (data.members.length > 0) {
        $$renderer2.push("<!--[0-->");
        $$renderer2.push(`<div class="px-4 py-3 flex flex-wrap gap-3 border-t border-border"><!--[-->`);
        const each_array_3 = ensure_array_like(data.members);
        for (let $$index_3 = 0, $$length = each_array_3.length; $$index_3 < $$length; $$index_3++) {
          let member = each_array_3[$$index_3];
          $$renderer2.push(`<div class="flex items-center gap-1.5"><span class="w-3 h-3 rounded-full"${attr_style(`background-color: ${stringify(member.color)}`)}></span> <span class="text-xs text-muted">${escape_html(member.name || member.id)}</span></div>`);
        }
        $$renderer2.push(`<!--]--></div>`);
      } else {
        $$renderer2.push("<!--[-1-->");
      }
      $$renderer2.push(`<!--]-->`);
    } else {
      $$renderer2.push("<!--[-1-->");
    }
    $$renderer2.push(`<!--]--></div></div>`);
    if ($$store_subs) unsubscribe_stores($$store_subs);
  });
}
export {
  _page as default
};
