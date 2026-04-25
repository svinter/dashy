<script lang="ts">
  import { page } from '$app/stores';
</script>

<!-- Inline styles only — shown when Tailwind/CSS may not be available -->
<div style="min-height:100vh; background:#1c0a0a; color:#fca5a5; font-family:monospace; padding:2rem; box-sizing:border-box;">
  <div style="font-size:1.1rem; font-weight:600; margin-bottom:1rem;">Mobly error</div>
  <div style="font-size:0.85rem; color:#f87171; margin-bottom:0.5rem;">
    Status: {$page.status}
  </div>
  {#if $page.error?.message}
    <pre style="font-size:0.8rem; color:#fca5a5; white-space:pre-wrap; word-break:break-all; margin:0 0 1rem;">{$page.error.message}</pre>
  {/if}
  <a href="/m/libby" style="color:#60a5fa; font-size:0.85rem;">← back to Libby</a>
</div>
