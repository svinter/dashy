<script lang="ts">
  import '../app.css';
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { QueryClient, QueryClientProvider } from '@tanstack/svelte-query';
  import { authed } from '$lib/auth';
  import { checkAuth } from '$lib/api';
  import BottomNav from '$lib/BottomNav.svelte';

  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 60_000,
        retry: 1,
      },
    },
  });

  $: isLogin = $page.url.pathname === '/m/login' || $page.url.pathname === '/login';

  onMount(async () => {
    const ok = await checkAuth();
    authed.set(ok);
    if (!ok && !isLogin) {
      goto('/login');
    }
  });
</script>

<QueryClientProvider client={queryClient}>
  <div class="flex flex-col h-screen bg-surface text-text overflow-hidden">
    {#if $authed === null}
      <!-- Loading auth -->
      <div class="flex-1 flex items-center justify-center">
        <div class="text-muted text-sm">Loading…</div>
      </div>
    {:else}
      <main class="flex-1 overflow-y-auto pb-safe-nav">
        <slot />
      </main>
      {#if !isLogin && $authed}
        <BottomNav />
      {/if}
    {/if}
  </div>
</QueryClientProvider>
