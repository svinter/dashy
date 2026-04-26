<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { authed } from '$lib/auth';

  const NAV_WEEKS = 8;

  // Start date as ISO string (YYYY-MM-DD), always a Monday
  let startIso = '';
  let blobUrl: string | null = null;
  let loading = false;
  let error: string | null = null;

  function firstMondayOfMonth(d: Date): Date {
    const first = new Date(d.getFullYear(), d.getMonth(), 1);
    const dow = first.getDay(); // 0=Sun
    const offset = dow === 0 ? 1 : dow === 1 ? 0 : 8 - dow;
    // Go back to the Monday on or before the 1st
    const monday = new Date(first);
    monday.setDate(1 - (dow === 0 ? 6 : dow - 1));
    return monday;
  }

  function toIso(d: Date): string {
    return d.toISOString().slice(0, 10);
  }

  function addWeeks(iso: string, n: number): string {
    const d = new Date(iso + 'T12:00:00');
    d.setDate(d.getDate() + n * 7);
    return toIso(d);
  }

  function rangeLabel(iso: string): string {
    const start = new Date(iso + 'T12:00:00');
    const end = new Date(iso + 'T12:00:00');
    end.setDate(end.getDate() + 12 * 7 - 1);
    const fmtMonth = (d: Date) => d.toLocaleDateString('en-US', { month: 'short', year: 'numeric' });
    const sm = fmtMonth(start);
    const em = fmtMonth(end);
    return sm === em ? sm : `${sm} – ${em}`;
  }

  async function loadImage() {
    if (!startIso) return;
    loading = true;
    error = null;
    try {
      const res = await fetch(`/api/mobile/glance/render?start=${startIso}`, {
        credentials: 'include',
      });
      if (res.status === 401) {
        authed.set(false); // triggers layout's reactive redirect to /m/login
        return;
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const newUrl = URL.createObjectURL(blob);
      if (blobUrl) URL.revokeObjectURL(blobUrl);
      blobUrl = newUrl;
    } catch (e: unknown) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }

  function goBack() {
    startIso = addWeeks(startIso, -NAV_WEEKS);
    loadImage();
  }

  function goForward() {
    startIso = addWeeks(startIso, NAV_WEEKS);
    loadImage();
  }

  function goToday() {
    startIso = toIso(firstMondayOfMonth(new Date()));
    loadImage();
  }

  onMount(() => {
    startIso = toIso(firstMondayOfMonth(new Date()));
    loadImage();
  });

  onDestroy(() => {
    if (blobUrl) URL.revokeObjectURL(blobUrl);
  });
</script>

<div class="flex flex-col h-full">
  <!-- Top bar -->
  <header class="flex items-center gap-2 px-3 pt-safe-top pb-2 bg-panel border-b border-border sticky top-0 z-10">
    <button
      on:click={goBack}
      disabled={loading}
      class="p-2 text-muted hover:text-text disabled:opacity-40 active:scale-90 transition-transform"
      aria-label="Back 8 weeks"
    >
      <svg class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path stroke-linecap="round" stroke-linejoin="round" d="M15 19l-7-7 7-7" />
      </svg>
    </button>

    <div class="flex-1 min-w-0 text-center">
      <h1 class="text-sm font-semibold truncate">{startIso ? rangeLabel(startIso) : 'Glance'}</h1>
    </div>

    <button
      on:click={goToday}
      disabled={loading}
      class="text-xs text-accent disabled:opacity-40 px-1"
    >
      Today
    </button>

    <button
      on:click={() => { if (!loading) loadImage(); }}
      disabled={loading}
      class="p-2 text-muted hover:text-text disabled:opacity-40 active:scale-90 transition-transform"
      aria-label="Refresh"
    >
      <svg class="w-5 h-5 {loading ? 'animate-spin' : ''}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path stroke-linecap="round" stroke-linejoin="round"
          d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
      </svg>
    </button>

    <button
      on:click={goForward}
      disabled={loading}
      class="p-2 text-muted hover:text-text disabled:opacity-40 active:scale-90 transition-transform"
      aria-label="Forward 8 weeks"
    >
      <svg class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7" />
      </svg>
    </button>
  </header>

  <!-- Image area -->
  <div class="flex-1 overflow-auto bg-surface">
    {#if loading && !blobUrl}
      <div class="flex items-center justify-center h-full text-muted text-sm">
        <svg class="w-6 h-6 animate-spin mr-2" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round"
            d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
        </svg>
        Loading…
      </div>

    {:else if error}
      <div class="flex flex-col items-center justify-center h-full gap-3 p-6">
        <p class="text-danger text-sm text-center">{error}</p>
        <button on:click={loadImage} class="text-accent text-sm underline">Try again</button>
      </div>

    {:else if blobUrl}
      <div class="relative">
        {#if loading}
          <div class="absolute inset-0 bg-surface/50 flex items-center justify-center z-10">
            <svg class="w-8 h-8 animate-spin text-accent" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round"
                d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
          </div>
        {/if}
        <img
          src={blobUrl}
          alt="Glance calendar view"
          class="w-full block"
          style="image-rendering: crisp-edges;"
        />
      </div>
    {/if}
  </div>
</div>
