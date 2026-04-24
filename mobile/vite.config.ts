import { sveltekit } from '@sveltejs/vite-plugin-svelte';
import { SvelteKitPWA } from '@vite-pwa/sveltekit';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [
    sveltekit(),
    SvelteKitPWA({
      srcDir: 'src',
      mode: 'development',
      strategies: 'generateSW',
      registerType: 'autoUpdate',
      includeManifestIcons: false,
      manifest: {
        name: 'Mobly',
        short_name: 'Mobly',
        description: 'Dashy mobile companion',
        theme_color: '#0f172a',
        background_color: '#0f172a',
        display: 'standalone',
        orientation: 'portrait',
        scope: '/m/',
        start_url: '/m/',
        icons: [
          {
            src: '/m/icons/icon-192.png',
            sizes: '192x192',
            type: 'image/png',
          },
          {
            src: '/m/icons/icon-512.png',
            sizes: '512x512',
            type: 'image/png',
          },
        ],
      },
      workbox: {
        globPatterns: ['**/*.{js,css,html,ico,png,svg,woff2}'],
        navigateFallback: '/m/index.html',
        navigateFallbackAllowlist: [/^\/m/],
      },
      devOptions: {
        enabled: false,
        suppressWarnings: true,
        type: 'module',
      },
    }),
  ],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
});
