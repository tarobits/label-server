<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import Icon from './components/Icon.vue'
import ConfirmDialog from './components/ConfirmDialog.vue'
import { workspace as w } from './workspace'
const route = useRoute()
const { status, loaded, connectionError, actionError, success } = w
const links = [
  ['/', 'Overview', 'overview'],
  ['/queue', 'Print queue', 'queue'],
  ['/runs', 'CSV runs', 'csv'],
  ['/templates', 'Templates', 'template'],
  ['/fonts', 'Fonts', 'font'],
  ['/images', 'Images', 'image'],
  ['/profiles', 'Tape profiles', 'tape'],
  ['/cartridges', 'Cartridges', 'cartridge'],
  ['/activity', 'Activity', 'activity'],
  ['/settings', 'Printer & settings', 'settings'],
]
let timer: ReturnType<typeof setTimeout> | undefined
let stopped = false
function skipToContent() {
  document.getElementById('main-content')?.focus()
}
async function poll() {
  await w.refresh()
  if (!stopped) timer = setTimeout(poll, 2500)
}
onMounted(poll)
onUnmounted(() => {
  stopped = true
  clearTimeout(timer)
})
</script>
<template>
  <ConfirmDialog />
  <a class="skip" href="#main-content" @click.prevent="skipToContent">Skip to content</a>
  <div class="app-shell">
    <aside class="sidebar">
      <RouterLink class="brand" to="/"
        ><span class="brand-icon"><Icon name="printer" /></span
        ><span>Label room<small>HOMELAB PRINT STUDIO</small></span></RouterLink
      >
      <div class="nav-label">WORKSPACE</div>
      <nav aria-label="Main navigation">
        <RouterLink
          v-for="[path, label, icon] in links"
          :key="path"
          :to="path!"
          :class="{ selected: route.path === path }"
          ><Icon :name="icon!" />{{ label
          }}<span v-if="path === '/queue' && w.totalQueued.value" class="nav-count">{{
            w.totalQueued.value
          }}</span></RouterLink
        >
      </nav>
      <div class="sidebar-footer">
        <span class="status-dot" :class="{ off: !status?.connected || connectionError }"></span
        >{{
          connectionError
            ? 'Server unavailable'
            : status?.connected
              ? `${status.printer_name} connected`
              : 'Printer disconnected'
        }}<small>{{
          status?.backend === 'mock' ? 'Brother PT-P710BT · USB available' : 'USB printer'
        }}</small>
      </div>
    </aside>
    <div class="main-wrap">
      <div class="topbar">
        <span>YOUR LABEL WORKSPACE</span
        ><RouterLink to="/settings" class="mock-pill">{{
          status?.backend === 'mock' ? 'MOCK MODE' : 'USB PRINTER'
        }}</RouterLink>
      </div>
      <main id="main-content" tabindex="-1">
        <header class="page-header">
          <div>
            <h1>{{ route.meta.title }}</h1>
            <p>{{ route.meta.subtitle }}</p>
          </div>
          <RouterLink v-if="route.path !== '/new'" class="button primary" to="/new"
            ><Icon name="plus" />New label</RouterLink
          >
        </header>
        <div v-if="connectionError" class="alert danger" role="alert">
          {{ connectionError }} <button class="text-button" @click="w.refresh">Retry</button>
        </div>
        <div v-if="actionError" class="alert danger" role="alert">
          {{ actionError
          }}<button class="text-button" aria-label="Dismiss error" @click="actionError = ''">
            Dismiss
          </button>
        </div>
        <div v-if="success" class="alert success" role="status">
          {{ success
          }}<button class="text-button" aria-label="Dismiss message" @click="success = ''">
            Dismiss
          </button>
        </div>
        <div
          v-if="status?.needs_review.length && !route.path.startsWith('/batches/')"
          class="alert warning"
        >
          <span><strong>Printing is paused.</strong> An interrupted batch needs your review.</span
          ><RouterLink :to="`/batches/${status.needs_review[0]}`">Review batch →</RouterLink>
        </div>
        <div v-if="!loaded" class="empty panel">
          {{ connectionError ? 'Waiting for the server…' : 'Loading your workspace…' }}
        </div>
        <div v-if="status?.automatic_printing_held" class="alert warning" role="status">
          <span
            ><strong>Automatic printing is held.</strong> Keep adding labels to build a larger
            batch. Manual printing is still available.</span
          >
        </div>
        <RouterView v-if="loaded" />
        <footer class="page-footer">
          Built for the little things that deserve a label.<span>{{
            status?.backend === 'mock' ? 'Mock mode · No physical printing' : status?.printer_name
          }}</span>
        </footer>
      </main>
    </div>
  </div>
</template>
