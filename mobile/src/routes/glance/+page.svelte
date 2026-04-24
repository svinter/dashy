<script lang="ts">
  import { createQuery } from '@tanstack/svelte-query';
  import { fetchGlance, type GlanceMember, type GlanceDay } from '$lib/api';

  const query = createQuery({
    queryKey: ['glance'],
    queryFn: fetchGlance,
    refetchOnWindowFocus: true,
  });

  const DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

  function sortedDates(days: Record<string, GlanceDay>): string[] {
    return Object.keys(days).sort();
  }

  function todayIso(): string {
    return new Date().toISOString().slice(0, 10);
  }

  function dayName(iso: string): string {
    const d = new Date(iso + 'T12:00:00');
    return DAY_NAMES[d.getDay() === 0 ? 6 : d.getDay() - 1];
  }

  function dayNum(iso: string): string {
    return String(parseInt(iso.slice(8, 10)));
  }

  function memberColor(member_id: string | null, members: GlanceMember[]): string {
    if (!member_id) return '#64748b';
    return members.find(m => m.id === member_id)?.color ?? '#64748b';
  }

  function memberTextColor(member_id: string | null, members: GlanceMember[]): string {
    if (!member_id) return '#fff';
    return members.find(m => m.id === member_id)?.text_color ?? '#fff';
  }

  async function doRefresh() {
    await $query.refetch();
  }
</script>

<div class="flex flex-col h-full">
  <!-- Top bar -->
  <header class="flex items-center justify-between px-4 pt-safe-top pb-3 bg-panel border-b border-border sticky top-0 z-10">
    <div>
      <h1 class="text-lg font-semibold">Glance</h1>
      {#if $query.data}
        <p class="text-xs text-muted">Week of {$query.data.week_start}</p>
      {/if}
    </div>
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

  <div class="flex-1 overflow-y-auto">
    {#if $query.isPending}
      <div class="flex items-center justify-center py-20 text-muted text-sm">Loading…</div>

    {:else if $query.isError}
      <div class="flex flex-col items-center justify-center py-20 gap-3">
        <p class="text-danger text-sm">Failed to load Glance</p>
        <button on:click={doRefresh} class="text-accent text-sm underline">Try again</button>
      </div>

    {:else if $query.data}
      {@const data = $query.data}
      {@const today = todayIso()}
      {@const dates = sortedDates(data.days)}

      <div class="px-3 py-3 space-y-2">
        {#each dates as iso (iso)}
          {@const day = data.days[iso]}
          {@const isToday = iso === today}

          <div class="rounded-xl overflow-hidden border {isToday ? 'border-accent' : 'border-border'} bg-panel">
            <!-- Day header -->
            <div class="flex items-center gap-2 px-3 py-2 {isToday ? 'bg-accent/10' : 'bg-surface'}">
              <span class="text-xs font-medium {isToday ? 'text-accent' : 'text-muted'} w-7">{dayName(iso)}</span>
              <span class="text-sm font-semibold {isToday ? 'text-accent' : 'text-text'}">{dayNum(iso)}</span>
              {#if isToday}
                <span class="text-xs text-accent ml-auto">today</span>
              {/if}
            </div>

            <!-- Trips for this day -->
            {#if day.trips.length > 0}
              <div class="px-3 pb-1 pt-1 flex flex-wrap gap-1.5">
                {#each day.trips as trip}
                  <span
                    class="text-xs px-2 py-1 rounded-full font-medium"
                    style="background-color: {trip.color_data || '#334155'}; color: {trip.text_color || '#f1f5f9'}"
                  >
                    {#if trip.location}✈ {trip.location}{:else}✈ trip{/if}
                  </span>
                {/each}
              </div>
            {/if}

            <!-- Entries for this day -->
            {#if day.entries.length > 0}
              <div class="px-3 pb-2 pt-1 space-y-1">
                {#each day.entries as entry}
                  <div class="flex items-start gap-2">
                    <!-- Member color dot -->
                    {#if entry.member_id}
                      <span
                        class="w-2 h-2 rounded-full flex-shrink-0 mt-1.5"
                        style="background-color: {memberColor(entry.member_id, data.members)}"
                      ></span>
                    {:else}
                      <span class="w-2 h-2 rounded-full flex-shrink-0 mt-1.5 bg-border"></span>
                    {/if}
                    <div class="flex-1 min-w-0">
                      {#if entry.color_data && entry.label}
                        <span
                          class="inline-block text-xs px-1.5 py-0.5 rounded font-medium"
                          style="background-color: {entry.color_data}; color: {entry.text_color || '#f1f5f9'}"
                        >
                          {entry.label}
                        </span>
                      {:else}
                        <span class="text-xs text-text">{entry.label}</span>
                      {/if}
                      {#if entry.notes}
                        <p class="text-xs text-muted mt-0.5 line-clamp-2">{entry.notes}</p>
                      {/if}
                    </div>
                  </div>
                {/each}
              </div>
            {/if}

            {#if day.trips.length === 0 && day.entries.length === 0}
              <div class="px-3 pb-2 text-xs text-muted italic">—</div>
            {/if}
          </div>
        {/each}
      </div>

      <!-- Members legend -->
      {#if data.members.length > 0}
        <div class="px-4 py-3 flex flex-wrap gap-3 border-t border-border">
          {#each data.members as member}
            <div class="flex items-center gap-1.5">
              <span class="w-3 h-3 rounded-full" style="background-color: {member.color}"></span>
              <span class="text-xs text-muted">{member.name || member.id}</span>
            </div>
          {/each}
        </div>
      {/if}
    {/if}
  </div>
</div>
