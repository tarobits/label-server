import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { VitePWA } from 'vite-plugin-pwa'
import { createHash } from 'node:crypto'
export default defineConfig({
  plugins: [
    vue(),
    {
      name: 'app-build-identity',
      apply: 'build',
      transformIndexHtml: {
        order: 'post',
        handler(html) {
          return [
            {
              tag: 'meta',
              attrs: {
                name: 'app-build',
                content: createHash('sha256').update(html).digest('hex'),
              },
              injectTo: 'head',
            },
          ]
        },
      },
    },
    VitePWA({
      strategies: 'injectManifest',
      srcDir: 'src',
      filename: 'sw.ts',
      injectRegister: null,
      registerType: 'prompt',
      // Only the public app shell and build assets belong in this cache.
      // API responses, previews, and user uploads always stay on the network.
      injectManifest: {
        globPatterns: ['index.html', 'assets/*.{js,css}', '*.png', '*.ico', '*.svg'],
      },
      manifest: {
        id: '/',
        name: "Taro's Label Room",
        short_name: 'Label Room',
        lang: 'en',
        start_url: '/',
        scope: '/',
        display: 'standalone',
        theme_color: '#1f2937',
        background_color: '#111827',
        icons: [
          { src: '/pwa-192x192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
          { src: '/pwa-512x512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
          {
            src: '/pwa-maskable-512x512.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'maskable',
          },
        ],
      },
    }),
  ],
  server: { proxy: { '/api': 'http://127.0.0.1:8000', '/fonts': 'http://127.0.0.1:8000' } },
})
