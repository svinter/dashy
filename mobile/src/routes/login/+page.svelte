<script lang="ts">
  import { goto } from '$app/navigation';
  import { base } from '$app/paths';
  import { login } from '$lib/api';
  import { authed } from '$lib/auth';

  let password = '';
  let error = '';
  let loading = false;

  async function handleSubmit() {
    error = '';
    loading = true;
    try {
      await login(password);
      authed.set(true);
      goto(`${base}/libby`);
    } catch (e) {
      error = e instanceof Error ? e.message : 'Login failed';
    } finally {
      loading = false;
    }
  }
</script>

<div class="min-h-screen flex items-center justify-center px-6 bg-surface">
  <div class="w-full max-w-sm">
    <h1 class="text-2xl font-semibold text-text text-center mb-2">Mobly</h1>
    <p class="text-muted text-sm text-center mb-8">Dashy on the go</p>

    <form on:submit|preventDefault={handleSubmit} class="space-y-4">
      <div>
        <input
          type="password"
          bind:value={password}
          placeholder="Password"
          autocomplete="current-password"
          disabled={loading}
          class="w-full px-4 py-3 rounded-xl bg-panel border border-border text-text
                 placeholder-muted focus:outline-none focus:border-accent text-base"
        />
      </div>

      {#if error}
        <p class="text-danger text-sm text-center">{error}</p>
      {/if}

      <button
        type="submit"
        disabled={loading || !password}
        class="w-full py-3 rounded-xl bg-accent text-white font-semibold text-base
               disabled:opacity-50 active:scale-95 transition-transform"
      >
        {loading ? 'Signing in…' : 'Sign in'}
      </button>
    </form>
  </div>
</div>
