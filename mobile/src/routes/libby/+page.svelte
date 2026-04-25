<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { base } from '$app/paths';
  import { createQuery } from '@tanstack/svelte-query';
  import {
    fetchLibbySearch, checkLibbyExists, lookupLibbyBook, addLibbyItem, patchLibbyNotes,
    type LibbySearchResult, type LibbyLookupResult, type LibbyAddResult, type LibbyAddDuplicate,
  } from '$lib/api';

  // --- Search ---
  let q = '';
  let searchQ = '';
  let debounceTimer: ReturnType<typeof setTimeout> | null = null;
  let searchInput: HTMLInputElement;

  // --- Detail overlay ---
  let selected: LibbySearchResult | null = null;
  let editingNotes = false;
  let editNotesText = '';
  let savingNotes = false;

  // --- Add flow ---
  type AddState = 'input' | 'checking' | 'exists' | 'searching' | 'preview' | 'nomatch' | 'adding' | 'added';
  let showAdd = false;
  let addState: AddState = 'input';
  let addInput = '';
  let addNotes = '';
  let addType = 'b';
  let addPreview: LibbyLookupResult | null = null;
  let addResult: LibbyAddResult | null = null;
  let addExisting: { existing_id: number; existing_name: string } | null = null;

  // --- Toast + share ---
  let toast: string | null = null;
  let toastTimer: ReturnType<typeof setTimeout> | null = null;
  let canShare = false;

  $: query = createQuery({
    queryKey: ['libby-search', searchQ],
    queryFn: () => fetchLibbySearch(searchQ),
  });

  // Redirect to login on auth failure (e.g. server restart)
  $: if ($query.isError && ($query.error as Error)?.message === 'UNAUTHENTICATED') {
    goto(`${base}/login`, { replaceState: true });
  }

  onMount(() => {
    searchInput?.focus();
    canShare = typeof navigator !== 'undefined' && 'share' in navigator;
  });

  // --- Search ---
  function onInput() {
    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => { searchQ = q; }, 300);
  }

  function clearSearch() {
    q = '';
    searchQ = '';
    if (debounceTimer) clearTimeout(debounceTimer);
    searchInput?.focus();
  }

  // --- Detail overlay ---
  function openDetail(item: LibbySearchResult) {
    selected = item;
    editingNotes = false;
  }
  function closeDetail() {
    selected = null;
    editingNotes = false;
  }

  function itemUrl(item: LibbySearchResult): string | null {
    if (item.amazon_url || item.url || item.amazon_short_url) {
      return item.amazon_url || item.url || item.amazon_short_url;
    }
    if (item.type_code === 'b') {
      return `https://www.amazon.com/s?k=${encodeURIComponent(item.name)}&i=stripbooks`;
    }
    return null;
  }

  function openUrl(item: LibbySearchResult) {
    const url = itemUrl(item);
    if (url) window.open(url, '_blank', 'noopener,noreferrer');
  }

  async function shareItem(item: LibbySearchResult) {
    const shareUrl = itemUrl(item) ?? undefined;
    const shareData: ShareData = {
      title: item.name,
      text: item.author ? `${item.name} — ${item.author}` : item.name,
    };
    if (shareUrl) shareData.url = shareUrl;
    try {
      await navigator.share(shareData);
    } catch (_) { /* cancelled */ }
  }

  function copyItem(item: LibbySearchResult) {
    const url = itemUrl(item);
    const byAuthor = item.author ? ` by ${item.author}` : '';
    const text = url ? `${item.name}${byAuthor}\n${url}` : `${item.name}${byAuthor}`;
    copyText(text);
    showToast('Copied');
  }

  // --- Edit notes ---
  function startEditNotes() {
    editNotesText = selected?.comments ?? '';
    editingNotes = true;
  }

  function cancelEditNotes() {
    editingNotes = false;
  }

  async function saveNotes() {
    if (!selected) return;
    savingNotes = true;
    try {
      const result = await patchLibbyNotes(selected.id, editNotesText.trim() || null);
      selected = { ...selected, comments: result.comments };
      editingNotes = false;
      $query.refetch();
    } catch (e: unknown) {
      showToast((e as Error).message || 'Save failed');
    } finally {
      savingNotes = false;
    }
  }

  // --- Clipboard with execCommand fallback (works over HTTP) ---
  function copyText(text: string) {
    if (navigator.clipboard) {
      navigator.clipboard.writeText(text).catch(() => execCopy(text));
    } else {
      execCopy(text);
    }
  }

  function execCopy(text: string) {
    const el = document.createElement('textarea');
    el.value = text;
    el.style.cssText = 'position:fixed;top:0;left:0;opacity:0;pointer-events:none;';
    document.body.appendChild(el);
    el.focus();
    el.select();
    try { document.execCommand('copy'); } catch (_) {}
    document.body.removeChild(el);
  }

  // --- Add flow ---
  function openAdd() {
    showAdd = true;
    addState = 'input';
    addInput = '';
    addNotes = '';
    addType = 'b';
    addPreview = null;
    addResult = null;
    addExisting = null;
  }

  function closeAdd() {
    showAdd = false;
    addState = 'input';
    addInput = '';
    addNotes = '';
    addType = 'b';
    addPreview = null;
    addResult = null;
    addExisting = null;
  }

  // Step 1: check for existing entry before any Google Books lookup
  async function doSubmit() {
    const raw = addInput.trim();
    if (!raw || addState === 'checking') return;
    // URLs skip the exists check — unlikely to be duplicated exactly
    if (/^https?:\/\//.test(raw)) {
      doLookup();
      return;
    }
    addState = 'checking';
    try {
      const check = await checkLibbyExists(raw);
      if (check.exists) {
        addExisting = { existing_id: check.existing_id, existing_name: check.existing_name };
        addState = 'exists';
      } else {
        doLookup();
      }
    } catch (e: unknown) {
      if ((e as Error).message === 'UNAUTHENTICATED') {
        goto(`${base}/login`, { replaceState: true });
        return;
      }
      // On error just fall through to lookup
      doLookup();
    }
  }

  // Step 2: Google Books lookup (called after exists check passes or user overrides)
  async function doLookup() {
    addState = 'searching';
    try {
      const result = await lookupLibbyBook(addInput.trim());
      addPreview = result;
      addState = result.matched ? 'preview' : 'nomatch';
    } catch (e: unknown) {
      if ((e as Error).message === 'UNAUTHENTICATED') {
        goto(`${base}/login`, { replaceState: true });
        return;
      }
      showToast((e as Error).message || 'Lookup failed');
      addState = 'input';
    }
  }

  async function doConfirmAdd(usePreview: boolean) {
    if (!addPreview) return;
    addState = 'adding';
    try {
      const isbn = usePreview ? addPreview.isbn : null;
      const result = await addLibbyItem({
        name: usePreview && addPreview.matched ? addPreview.name : addInput.trim(),
        author: usePreview ? addPreview.author : null,
        cover_url: usePreview ? addPreview.cover_url : null,
        isbn,
        notes: addNotes.trim() || null,
        type_code: usePreview ? 'b' : addType,
        url: usePreview ? addPreview.info_link : null,
        amazon_url: isbn ? `https://www.amazon.com/s?k=${encodeURIComponent(isbn)}&i=stripbooks` : null,
        force: true,
      });
      addResult = result as LibbyAddResult;
      addState = 'added';
      $query.refetch();
    } catch (e: unknown) {
      if ((e as Error).message === 'UNAUTHENTICATED') {
        goto(`${base}/login`, { replaceState: true });
        return;
      }
      showToast((e as Error).message || 'Failed to add');
      addState = addPreview.matched ? 'preview' : 'nomatch';
    }
  }

  // --- Toast ---
  function showToast(msg: string) {
    toast = msg;
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toast = null; }, 2500);
  }

  function typeEmoji(code: string): string {
    const map: Record<string, string> = {
      b: '📖', a: '📄', e: '✍️', p: '🎙️', v: '🎬',
      m: '🎥', t: '🛠️', w: '🌐', s: '📋', z: '📊',
      n: '📝', d: '📑', f: '🗂️', c: '🎓', r: '🔬', q: '💬',
    };
    return map[code] ?? '📚';
  }
</script>

<div style="display:flex; flex-direction:column; height:100%;">

  <!-- Search bar -->
  <div style="
    padding:12px 16px 10px;
    background:#1e293b; border-bottom:1px solid #334155;
    position:sticky; top:0; z-index:10;
  ">
    <div style="position:relative; display:flex; align-items:center;">
      <svg style="position:absolute; left:10px; width:16px; height:16px; color:#64748b; pointer-events:none;" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="11" cy="11" r="8"/><path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-4.35-4.35"/>
      </svg>
      <input
        bind:this={searchInput}
        bind:value={q}
        on:input={onInput}
        type="search"
        placeholder="Search your library…"
        autocomplete="off"
        autocorrect="off"
        spellcheck={false}
        style="
          width:100%; padding:9px 36px 9px 34px;
          background:#0f172a; color:#f1f5f9;
          border:1px solid #334155; border-radius:8px;
          font-size:15px; outline:none; box-sizing:border-box;
          -webkit-appearance:none; appearance:none;
        "
      />
      {#if q}
        <button
          on:click={clearSearch}
          style="position:absolute; right:8px; background:none; border:none; color:#64748b; cursor:pointer; padding:4px; line-height:1; font-size:16px;"
          aria-label="Clear search"
        >✕</button>
      {/if}
    </div>
  </div>

  <!-- Results list -->
  <div style="flex:1; overflow-y:auto;">
    {#if $query.isPending}
      <div style="display:flex; align-items:center; justify-content:center; padding:80px 0; color:#64748b; font-size:14px;">Loading…</div>

    {:else if $query.isError}
      <div style="display:flex; flex-direction:column; align-items:center; padding:80px 0; gap:12px;">
        <p style="color:#ef4444; font-size:14px; margin:0;">Session expired</p>
        <a
          href="{base}/login"
          style="color:#3b82f6; font-size:14px; text-decoration:underline;"
        >Go to Login</a>
      </div>

    {:else if !$query.data?.items.length}
      <div style="display:flex; flex-direction:column; align-items:center; padding:80px 0; gap:8px; color:#64748b;">
        <span style="font-size:3rem;">📚</span>
        <p style="font-size:14px; margin:0;">{q ? 'No results' : 'No items yet'}</p>
      </div>

    {:else}
      <ul style="list-style:none; margin:0; padding:0;">
        {#each $query.data.items as item (item.id)}
          <li>
            <button
              on:click={() => openDetail(item)}
              style="
                width:100%; display:flex; align-items:flex-start; gap:12px;
                padding:12px 16px; background:none; border:none;
                border-bottom:1px solid #1e293b;
                cursor:pointer; text-align:left;
                -webkit-tap-highlight-color:transparent;
              "
            >
              {#if item.cover_url}
                <img
                  src={item.cover_url}
                  alt=""
                  style="width:40px; height:56px; object-fit:cover; border-radius:4px; flex-shrink:0; background:#1e293b;"
                  loading="lazy"
                />
              {:else}
                <div style="width:40px; height:56px; flex-shrink:0; border-radius:4px; background:#1e293b; display:flex; align-items:center; justify-content:center; font-size:22px;">
                  {typeEmoji(item.type_code)}
                </div>
              {/if}
              <div style="flex:1; min-width:0;">
                <p style="color:#f1f5f9; font-size:14px; font-weight:500; line-height:1.3; margin:0 0 3px; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden;">
                  {item.name}
                </p>
                {#if item.author}
                  <p style="color:#64748b; font-size:12px; margin:0 0 3px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">{item.author}</p>
                {/if}
                {#if item.comments}
                  <p style="color:#475569; font-size:11px; font-style:italic; margin:0 0 4px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">{item.comments}</p>
                {/if}
                <span style="display:inline-block; font-size:11px; padding:2px 6px; border-radius:4px; background:#0f172a; color:#94a3b8; border:1px solid #334155;">
                  {item.type_label ?? item.type_code.toUpperCase()}
                </span>
              </div>
            </button>
          </li>
        {/each}
      </ul>
      <p style="text-align:center; font-size:12px; color:#475569; padding:16px 0;">
        {$query.data.total} item{$query.data.total !== 1 ? 's' : ''}
      </p>
    {/if}
  </div>
</div>

<!-- Floating + button -->
<button
  on:click={openAdd}
  style="
    position:fixed;
    bottom:calc(4rem + env(safe-area-inset-bottom) + 16px); right:20px;
    width:52px; height:52px; border-radius:50%;
    background:#3b82f6; color:#fff; border:none; cursor:pointer;
    display:flex; align-items:center; justify-content:center;
    font-size:26px; font-weight:300; line-height:1;
    box-shadow:0 4px 16px rgba(59,130,246,0.4); z-index:40;
  "
  aria-label="Add to library"
>+</button>

<!-- Detail overlay -->
{#if selected}
  <!-- svelte-ignore a11y-click-events-have-key-events a11y-no-static-element-interactions -->
  <div
    on:click|self={closeDetail}
    style="position:fixed; inset:0; z-index:60; background:rgba(0,0,0,0.7); display:flex; align-items:flex-end;"
  >
    <div style="
      width:100%; background:#1e293b; border-radius:16px 16px 0 0;
      padding-bottom:max(1.5rem, env(safe-area-inset-bottom));
      max-height:85vh; overflow-y:auto; box-sizing:border-box;
    ">
      <!-- Handle + close -->
      <div style="display:flex; align-items:center; justify-content:center; padding:12px 16px 4px; position:relative;">
        <div style="width:36px; height:4px; background:#334155; border-radius:2px;"></div>
        <button
          on:click={closeDetail}
          style="position:absolute; right:12px; background:none; border:none; color:#64748b; font-size:20px; cursor:pointer; padding:4px; line-height:1;"
          aria-label="Close"
        >✕</button>
      </div>

      <div style="padding:12px 16px 16px;">
        <!-- Cover + meta -->
        <div style="display:flex; gap:16px; margin-bottom:16px;">
          {#if selected.cover_url}
            <img
              src={selected.cover_url} alt=""
              style="width:80px; height:112px; object-fit:cover; border-radius:6px; flex-shrink:0; background:#0f172a;"
            />
          {:else}
            <div style="width:80px; height:112px; flex-shrink:0; border-radius:6px; background:#0f172a; display:flex; align-items:center; justify-content:center; font-size:40px;">
              {typeEmoji(selected.type_code)}
            </div>
          {/if}
          <div style="flex:1; min-width:0; display:flex; flex-direction:column; justify-content:center; gap:6px;">
            <p style="color:#f1f5f9; font-size:16px; font-weight:600; line-height:1.3; margin:0;">{selected.name}</p>
            {#if selected.author}
              <p style="color:#94a3b8; font-size:13px; margin:0;">{selected.author}</p>
            {/if}
            {#if selected.comments && !editingNotes}
              <p style="color:#64748b; font-size:12px; font-style:italic; line-height:1.4; margin:0;">{selected.comments}</p>
            {/if}
            <span style="display:inline-block; font-size:11px; padding:2px 8px; border-radius:4px; background:#0f172a; color:#94a3b8; border:1px solid #334155; width:fit-content;">
              {selected.type_label ?? selected.type_code.toUpperCase()}
            </span>
          </div>
        </div>

        {#if selected.synopsis}
          <p style="color:#cbd5e1; font-size:14px; line-height:1.6; margin:0 0 16px;">{selected.synopsis}</p>
        {/if}

        <!-- Notes edit section -->
        {#if editingNotes}
          <div style="margin-bottom:14px;">
            <textarea
              bind:value={editNotesText}
              placeholder="Add notes…"
              rows="3"
              style="
                width:100%; padding:10px 12px;
                background:#0f172a; color:#f1f5f9;
                border:1px solid #475569; border-radius:8px;
                font-size:14px; outline:none; resize:none;
                margin-bottom:8px; box-sizing:border-box;
                font-family:inherit; line-height:1.5;
              "
            ></textarea>
            <div style="display:flex; gap:8px;">
              <button
                on:click={cancelEditNotes}
                style="flex:1; padding:9px; border-radius:8px; background:#0f172a; border:1px solid #334155; color:#94a3b8; font-size:13px; cursor:pointer;"
              >Cancel</button>
              <button
                on:click={saveNotes}
                disabled={savingNotes}
                style="flex:2; padding:9px; border-radius:8px; background:#3b82f6; border:none; color:#fff; font-size:13px; font-weight:500; cursor:{savingNotes ? 'default' : 'pointer'}; opacity:{savingNotes ? 0.6 : 1};"
              >{savingNotes ? 'Saving…' : 'Save notes'}</button>
            </div>
          </div>
        {:else}
          <button
            on:click={startEditNotes}
            style="display:flex; align-items:center; gap:5px; background:none; border:none; color:#64748b; font-size:12px; cursor:pointer; padding:0 0 14px; line-height:1;"
          >✏️ {selected.comments ? 'Edit notes' : 'Add notes'}</button>
        {/if}

        <!-- Actions: [Share] [Open] [Copy] -->
        <div style="display:flex; gap:8px;">
          {#if canShare}
            <button
              on:click={() => selected && shareItem(selected)}
              style="flex:1; padding:11px 6px; border-radius:8px; background:#0f172a; border:1px solid #334155; color:#f1f5f9; font-size:13px; cursor:pointer; display:flex; align-items:center; justify-content:center; gap:5px;"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/>
                <line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/>
              </svg>
              Share
            </button>
          {/if}
          {#if selected && itemUrl(selected)}
            <button
              on:click={() => selected && openUrl(selected)}
              style="flex:1; padding:11px 6px; border-radius:8px; background:#3b82f6; border:none; color:#fff; font-size:13px; cursor:pointer; display:flex; align-items:center; justify-content:center; gap:5px;"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/>
                <polyline stroke-linecap="round" stroke-linejoin="round" points="15 3 21 3 21 9"/>
                <line stroke-linecap="round" stroke-linejoin="round" x1="10" y1="14" x2="21" y2="3"/>
              </svg>
              Open
            </button>
          {/if}
          <button
            on:click={() => selected && copyItem(selected)}
            style="flex:1; padding:11px 6px; border-radius:8px; background:#0f172a; border:1px solid #334155; color:#f1f5f9; font-size:13px; cursor:pointer; display:flex; align-items:center; justify-content:center; gap:5px;"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
              <path stroke-linecap="round" stroke-linejoin="round" d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/>
            </svg>
            Copy
          </button>
        </div>
      </div>
    </div>
  </div>
{/if}

<!-- Add to library sheet -->
{#if showAdd}
  <!-- svelte-ignore a11y-click-events-have-key-events a11y-no-static-element-interactions -->
  <div
    on:click|self={closeAdd}
    style="position:fixed; inset:0; z-index:60; background:rgba(0,0,0,0.7); display:flex; align-items:flex-end;"
  >
    <div style="
      width:100%; background:#1e293b; border-radius:16px 16px 0 0;
      padding:16px 16px max(1.5rem, env(safe-area-inset-bottom));
      box-sizing:border-box;
    ">
      <!-- Header -->
      <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:16px;">
        <h2 style="color:#f1f5f9; font-size:16px; font-weight:600; margin:0;">
          {addState === 'added' ? 'Added to Library' : addState === 'exists' ? 'Already in Library' : 'Add to Library'}
        </h2>
        <button
          on:click={closeAdd}
          style="background:none; border:none; color:#64748b; font-size:20px; cursor:pointer; padding:4px; line-height:1;"
          aria-label="Close"
        >✕</button>
      </div>

      <!-- STATE: input -->
      {#if addState === 'input'}
        <input
          bind:value={addInput}
          type="text"
          placeholder="Book title or URL…"
          autocomplete="off"
          on:keydown={(e) => { if (e.key === 'Enter') doSubmit(); }}
          style="
            width:100%; padding:10px 12px;
            background:#0f172a; color:#f1f5f9;
            border:1px solid #334155; border-radius:8px;
            font-size:15px; outline:none;
            margin-bottom:12px; box-sizing:border-box;
            -webkit-appearance:none; appearance:none;
          "
        />
        <button
          on:click={doSubmit}
          disabled={!addInput.trim()}
          style="
            width:100%; padding:12px;
            background:{addInput.trim() ? '#3b82f6' : '#1e3a5f'};
            color:{addInput.trim() ? '#fff' : '#475569'};
            border:none; border-radius:8px;
            font-size:15px; font-weight:500;
            cursor:{addInput.trim() ? 'pointer' : 'default'};
          "
        >Search</button>

      <!-- STATE: checking (exists check in progress) -->
      {:else if addState === 'checking'}
        <div style="display:flex; align-items:center; justify-content:center; padding:24px 0; color:#64748b; font-size:14px; gap:10px;">
          <svg style="animation:spin 1s linear infinite;" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" stroke-width="2">
            <path d="M21 12a9 9 0 11-6.219-8.56"/>
          </svg>
          Checking library…
        </div>

      <!-- STATE: exists — already in library, confirm before lookup -->
      {:else if addState === 'exists' && addExisting}
        <div style="margin-bottom:16px; padding:14px; background:#0f172a; border-radius:8px; border:1px solid #475569;">
          <p style="color:#fbbf24; font-size:13px; font-weight:500; margin:0 0 6px;">Already in your library</p>
          <p style="color:#f1f5f9; font-size:14px; margin:0;">"{addExisting.existing_name}"</p>
        </div>
        <p style="color:#94a3b8; font-size:13px; margin:0 0 14px;">Add another copy anyway?</p>
        <div style="display:flex; gap:8px;">
          <button
            on:click={() => { addState = 'input'; addExisting = null; }}
            style="flex:1; padding:11px; border-radius:8px; background:#0f172a; border:1px solid #334155; color:#94a3b8; font-size:14px; cursor:pointer;"
          >No, go back</button>
          <button
            on:click={doLookup}
            style="flex:2; padding:11px; border-radius:8px; background:#475569; border:none; color:#fff; font-size:14px; cursor:pointer;"
          >Yes, add anyway</button>
        </div>

      <!-- STATE: searching -->
      {:else if addState === 'searching'}
        <div style="display:flex; align-items:center; justify-content:center; padding:24px 0; color:#64748b; font-size:14px; gap:10px;">
          <svg style="animation:spin 1s linear infinite;" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" stroke-width="2">
            <path d="M21 12a9 9 0 11-6.219-8.56"/>
          </svg>
          Searching Google Books…
        </div>

      <!-- STATE: preview (Google Books match found) -->
      {:else if addState === 'preview' && addPreview}
        <div style="display:flex; gap:14px; margin-bottom:14px;">
          {#if addPreview.cover_url}
            <img src={addPreview.cover_url} alt="" style="width:64px; height:90px; object-fit:cover; border-radius:5px; flex-shrink:0; background:#0f172a;" />
          {:else}
            <div style="width:64px; height:90px; flex-shrink:0; border-radius:5px; background:#0f172a; display:flex; align-items:center; justify-content:center; font-size:30px;">📖</div>
          {/if}
          <div style="flex:1; min-width:0; display:flex; flex-direction:column; justify-content:center; gap:4px;">
            <p style="color:#f1f5f9; font-size:15px; font-weight:600; line-height:1.3; margin:0;">{addPreview.name}</p>
            {#if addPreview.author}
              <p style="color:#94a3b8; font-size:13px; margin:0;">{addPreview.author}</p>
            {/if}
            <span style="display:inline-block; font-size:11px; padding:2px 6px; border-radius:4px; background:#0f172a; color:#94a3b8; border:1px solid #334155; width:fit-content;">Book</span>
          </div>
        </div>
        <textarea
          bind:value={addNotes}
          placeholder="Notes (optional)…"
          rows="3"
          style="
            width:100%; padding:10px 12px;
            background:#0f172a; color:#f1f5f9;
            border:1px solid #334155; border-radius:8px;
            font-size:14px; outline:none; resize:none;
            margin-bottom:12px; box-sizing:border-box;
            font-family:inherit; line-height:1.5;
          "
        ></textarea>
        <div style="display:flex; gap:8px;">
          <button
            on:click={closeAdd}
            style="flex:1; padding:11px; border-radius:8px; background:#0f172a; border:1px solid #334155; color:#94a3b8; font-size:14px; cursor:pointer;"
          >Cancel</button>
          <button
            on:click={() => doConfirmAdd(true)}
            style="flex:2; padding:11px; border-radius:8px; background:#3b82f6; border:none; color:#fff; font-size:14px; font-weight:500; cursor:pointer;"
          >Add to Library</button>
        </div>

      <!-- STATE: nomatch (no Google Books result) -->
      {:else if addState === 'nomatch' && addPreview}
        <p style="color:#94a3b8; font-size:13px; margin:0 0 14px;">
          No match found for "<span style="color:#f1f5f9;">{addPreview.name}</span>"
        </p>
        <label for="add-type" style="display:block; color:#94a3b8; font-size:12px; margin-bottom:6px;">Type</label>
        <select
          id="add-type"
          bind:value={addType}
          style="
            width:100%; padding:10px 12px;
            background:#0f172a; color:#f1f5f9;
            border:1px solid #334155; border-radius:8px;
            font-size:14px; outline:none;
            margin-bottom:12px; box-sizing:border-box;
            -webkit-appearance:none; appearance:none;
          "
        >
          <option value="b">📖 Book</option>
          <option value="a">📄 Article</option>
          <option value="v">🎬 Video</option>
          <option value="p">🎙️ Podcast</option>
          <option value="n">📝 Other</option>
        </select>
        <textarea
          bind:value={addNotes}
          placeholder="Notes (optional)…"
          rows="3"
          style="
            width:100%; padding:10px 12px;
            background:#0f172a; color:#f1f5f9;
            border:1px solid #334155; border-radius:8px;
            font-size:14px; outline:none; resize:none;
            margin-bottom:12px; box-sizing:border-box;
            font-family:inherit; line-height:1.5;
          "
        ></textarea>
        <div style="display:flex; gap:8px;">
          <button
            on:click={closeAdd}
            style="flex:1; padding:11px; border-radius:8px; background:#0f172a; border:1px solid #334155; color:#94a3b8; font-size:14px; cursor:pointer;"
          >Cancel</button>
          <button
            on:click={() => doConfirmAdd(false)}
            style="flex:2; padding:11px; border-radius:8px; background:#475569; border:none; color:#fff; font-size:14px; cursor:pointer;"
          >Add Anyway</button>
        </div>

      <!-- STATE: adding -->
      {:else if addState === 'adding'}
        <div style="display:flex; align-items:center; justify-content:center; padding:24px 0; color:#64748b; font-size:14px; gap:10px;">
          <svg style="animation:spin 1s linear infinite;" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" stroke-width="2">
            <path d="M21 12a9 9 0 11-6.219-8.56"/>
          </svg>
          Adding…
        </div>

      <!-- STATE: added (success with cover/author) -->
      {:else if addState === 'added' && addResult}
        <div style="display:flex; gap:14px; margin-bottom:16px;">
          {#if addResult.cover_url}
            <img src={addResult.cover_url} alt="" style="width:64px; height:90px; object-fit:cover; border-radius:5px; flex-shrink:0; background:#0f172a;" />
          {:else}
            <div style="width:64px; height:90px; flex-shrink:0; border-radius:5px; background:#0f172a; display:flex; align-items:center; justify-content:center; font-size:30px;">📖</div>
          {/if}
          <div style="flex:1; min-width:0; display:flex; flex-direction:column; justify-content:center; gap:4px;">
            <p style="color:#22c55e; font-size:12px; font-weight:500; margin:0 0 2px;">Added ✓</p>
            <p style="color:#f1f5f9; font-size:15px; font-weight:600; line-height:1.3; margin:0;">{addResult.name}</p>
            {#if addResult.author}
              <p style="color:#94a3b8; font-size:13px; margin:0;">{addResult.author}</p>
            {/if}
          </div>
        </div>
        <button
          on:click={closeAdd}
          style="width:100%; padding:12px; border-radius:8px; background:#0f172a; border:1px solid #334155; color:#f1f5f9; font-size:15px; cursor:pointer;"
        >Done</button>
      {/if}
    </div>
  </div>
{/if}

<!-- Toast -->
{#if toast}
  <div style="
    position:fixed;
    bottom:calc(5.5rem + env(safe-area-inset-bottom));
    left:50%; transform:translateX(-50%);
    background:#334155; color:#f1f5f9;
    padding:8px 18px; border-radius:20px;
    font-size:14px; box-shadow:0 4px 12px rgba(0,0,0,0.4);
    z-index:70; white-space:nowrap; pointer-events:none;
  ">{toast}</div>
{/if}

<style>
  @keyframes spin { to { transform: rotate(360deg); } }
</style>
