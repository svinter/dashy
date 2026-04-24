<script lang="ts">
  import { createQuery } from '@tanstack/svelte-query';
  import { fetchLibby, type LibbyItem } from '$lib/api';

  const query = createQuery({
    queryKey: ['libby'],
    queryFn: fetchLibby,
    refetchOnWindowFocus: true,
  });

  function dueColor(days: number | null): string {
    if (days === null) return 'text-muted';
    if (days < 0) return 'text-danger font-semibold';
    if (days <= 2) return 'text-danger';
    if (days <= 5) return 'text-warn';
    return 'text-ok';
  }

  function dueLabel(item: LibbyItem): string {
    if (!item.loan_due_date) return '';
    const d = item.days_left;
    if (d === null) return item.loan_due_date;
    if (d < 0) return `Overdue by ${Math.abs(d)}d`;
    if (d === 0) return 'Due today';
    if (d === 1) return 'Due tomorrow';
    return `${d}d left`;
  }

  function typeLabel(item: LibbyItem): string {
    return item.type_label || item.type_code.toUpperCase();
  }

  async function doRefresh() {
    await $query.refetch();
  }
</script>

<div class="flex flex-col h-full">
  <!-- Top bar -->
  <header class="flex items-center justify-between px-4 pt-safe-top pb-3 bg-panel border-b border-border sticky top-0 z-10">
    <h1 class="text-lg font-semibold">Libby</h1>
    <button
      on:click={doRefresh}
      disabled={$query.isFetching}
      class="p-2 text-muted hover:text-text disabled:opacity-40 active:scale-90 transition-transform"
      aria-label="Refresh"
    >
      <svg class="w-5 h-5 {$query.isFetching ? 'animate-spin' : ''}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path stroke-linecap="round" stroke-linejoin="round"
          d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
      </svg>
    </button>
  </header>

  <!-- Content -->
  <div class="flex-1 overflow-y-auto">
    {#if $query.isPending}
      <div class="flex items-center justify-center py-20 text-muted text-sm">Loading…</div>

    {:else if $query.isError}
      <div class="flex flex-col items-center justify-center py-20 gap-3">
        <p class="text-danger text-sm">Failed to load loans</p>
        <button on:click={doRefresh} class="text-accent text-sm underline">Try again</button>
      </div>

    {:else if $query.data?.items.length === 0}
      <div class="flex flex-col items-center justify-center py-20 gap-2 text-muted">
        <span class="text-4xl">📚</span>
        <p class="text-sm">No active loans</p>
      </div>

    {:else}
      <ul class="divide-y divide-border">
        {#each $query.data?.items ?? [] as item (item.id)}
          <li class="px-4 py-3 flex items-start gap-3">
            {#if item.cover_url}
              <img
                src={item.cover_url}
                alt=""
                class="w-10 h-14 object-cover rounded flex-shrink-0 bg-panel"
                loading="lazy"
              />
            {:else}
              <div class="w-10 h-14 flex-shrink-0 rounded bg-panel flex items-center justify-center text-lg">
                📖
              </div>
            {/if}

            <div class="flex-1 min-w-0">
              <p class="text-sm font-medium leading-snug line-clamp-2">{item.name}</p>
              {#if item.author}
                <p class="text-xs text-muted mt-0.5 truncate">{item.author}</p>
              {/if}
              <div class="flex items-center gap-2 mt-1.5">
                <span class="text-xs px-1.5 py-0.5 rounded bg-surface text-muted border border-border">
                  {typeLabel(item)}
                </span>
                {#if item.loan_due_date}
                  <span class="text-xs {dueColor(item.days_left)}">
                    {dueLabel(item)}
                  </span>
                {/if}
              </div>
            </div>
          </li>
        {/each}
      </ul>

      <p class="text-center text-xs text-muted py-4">
        {$query.data?.total ?? 0} loan{($query.data?.total ?? 0) !== 1 ? 's' : ''}
      </p>
    {/if}
  </div>
</div>
