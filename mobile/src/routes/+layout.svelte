<script lang="ts">
  import '../app.css';
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { base } from '$app/paths';
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

  $: isLogin = $page.url.pathname.endsWith('/login');
  $: isRoot = $page.url.pathname === base || $page.url.pathname === base + '/';

  // Redirect /m → /m/libby on both initial load and SPA navigation
  $: if ($authed === true && isRoot) {
    goto(`${base}/libby`, { replaceState: true });
  }

  // Redirect to login whenever auth state drops to false (e.g. server restart)
  $: if ($authed === false && !isLogin) {
    goto(`${base}/login`, { replaceState: true });
  }

  onMount(async () => {
    const ok = await checkAuth();
    authed.set(ok);
    if (!ok && !isLogin) {
      goto(`${base}/login`);
    }
  });
</script>

<QueryClientProvider client={queryClient}>
  <div
    class="flex flex-col h-screen bg-surface text-text overflow-hidden"
    style="display:flex; flex-direction:column; height:100vh; background:#0f172a; color:#f1f5f9; overflow:hidden;"
  >
    {#if $authed === null}
      <div
        class="flex-1 flex items-center justify-center"
        style="flex:1; display:flex; align-items:center; justify-content:center;"
      >
        <div style="font-size:14px; color:#94a3b8;">Loading…</div>
      </div>
    {:else}
      <main
        class="flex-1 overflow-y-auto pb-safe-nav"
        style="flex:1; overflow-y:auto; padding-bottom:calc(4rem + env(safe-area-inset-bottom));"
      >
        <slot />
      </main>
      {#if !isLogin && $authed}
        <BottomNav />
      {/if}
    {/if}
  </div>
</QueryClientProvider>
