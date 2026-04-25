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
  class="fixed bottom-0 left-0 right-0 z-50"
  style="
    position: fixed;
    bottom: 0; left: 0; right: 0;
    background: #1e293b;
    border-top: 1px solid #334155;
    padding-bottom: max(0.5rem, env(safe-area-inset-bottom));
    z-index: 50;
  "
>
  <div class="flex" style="display: flex;">
    {#each tabs as tab}
      {@const active = current.startsWith(tab.href)}
      <a
        href={tab.href}
        class="flex-1 flex flex-col items-center gap-0.5 py-2 transition-colors
               {active ? 'text-accent' : 'text-muted'}"
        style="
          flex: 1;
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 2px;
          padding: 0.5rem 0;
          text-decoration: none;
          color: {active ? '#3b82f6' : '#64748b'};
          transition: color 0.15s;
        "
      >
        <span class="text-xl leading-none" style="font-size: 1.25rem; line-height: 1;">{tab.icon}</span>
        <span class="text-xs font-medium" style="font-size: 0.75rem; font-weight: 500;">{tab.label}</span>
      </a>
    {/each}
  </div>
</nav>
