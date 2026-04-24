<script lang="ts">
  import { page } from '$app/stores';
  import { base } from '$app/paths';

  const tabs = [
    { href: `${base}/libby`, label: 'Libby', icon: '📚' },
    { href: `${base}/glance`, label: 'Glance', icon: '📅' },
  ];

  $: current = $page.url.pathname;
</script>

<nav
  class="fixed bottom-0 left-0 right-0 bg-panel border-t border-border safe-bottom z-50"
  style="padding-bottom: max(0.5rem, env(safe-area-inset-bottom))"
>
  <div class="flex">
    {#each tabs as tab}
      {@const active = current.startsWith(tab.href)}
      <a
        href={tab.href}
        class="flex-1 flex flex-col items-center gap-0.5 py-2 transition-colors
               {active ? 'text-accent' : 'text-muted hover:text-text'}"
      >
        <span class="text-xl leading-none">{tab.icon}</span>
        <span class="text-xs font-medium">{tab.label}</span>
      </a>
    {/each}
  </div>
</nav>
