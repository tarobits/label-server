<script setup lang="ts">
import { computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import Icon from './components/Icon.vue'
import ConfirmDialog from './components/ConfirmDialog.vue'
import SignIn from './views/SignIn.vue'
import { auth } from './auth'
import { workspace as w } from './workspace'
const route = useRoute()
const needsPrinter = computed(() => route.path === '/new')
const fleetPage = computed(
  () => ['/', '/activity'].includes(route.path) || route.path.startsWith('/batches/'),
)
const connectedPrinters = computed(
  () => w.printerStatuses.value.filter((printer) => printer.connected).length,
)
const fleetSummary = computed(() =>
  w.printers.value.length
    ? `${connectedPrinters.value} of ${w.printers.value.length} printers connected`
    : w.destinations.value.some((destination) => destination.kind === 'group')
      ? 'Distribution groups available'
      : 'No printers assigned',
)
const reviewPrinters = computed(() =>
  w.printerStatuses.value.filter(
    (printer) => printer.needs_review.length && auth.atLeast(printer.printer_id, 'moderator'),
  ),
)
watch(
  () => route.query.printer,
  (value) => {
    if (typeof value === 'string') w.selectedPrinter.value = value
  },
  { immediate: true },
)
const { status, loaded, connectionError, actionError, success } = w
const links = computed(() =>
  [
    ['/', 'Overview', 'overview'],
    ['/queue', 'Print queue', 'queue'],
    ['/requests', 'Print requests', 'requests'],
    ['/runs', 'CSV runs', 'csv'],
    ['/templates', 'Templates', 'template'],
    ['/fonts', 'Fonts', 'font'],
    ['/images', 'Images', 'image'],
    ['/profiles', 'Tape profiles', 'tape'],
    ['/cartridges', 'Cartridges', 'cartridge'],
    ['/activity', 'Activity', 'activity'],
    ['/printers', 'Printers & groups', 'printer'],
    ['/admin', 'Administration', 'users'],
  ].filter(([path]) => {
    if (auth.user.value?.is_admin) return true
    if (path === '/admin') return auth.user.value?.is_admin
    if (path === '/printers') return auth.can('printers.manage') || auth.any('moderator')
    if (['/profiles', '/cartridges'].includes(path!)) return auth.can('inventory.manage')
    if (path === '/activity') return w.printers.value.some((p) => auth.atLeast(p.id, 'moderator'))
    return true
  }),
)
const allowed = computed(() => {
  if (auth.user.value?.is_admin) return true
  if (route.path === '/admin' || route.path === '/access-holds') return !!auth.user.value?.is_admin
  if (route.path === '/printers') return auth.can('printers.manage') || auth.any('moderator')
  if (['/profiles', '/cartridges'].includes(route.path)) return auth.can('inventory.manage')
  if (route.path === '/activity' || route.path.startsWith('/batches/'))
    return w.printers.value.some((p) => auth.atLeast(p.id, 'moderator'))
  if (route.path.endsWith('/edit') || route.path === '/templates/new') return true
  if (route.path === '/new') return auth.any('request')
  return true
})
let timer: ReturnType<typeof setTimeout> | undefined
let stopped = false
function skipToContent() {
  document.getElementById('main-content')?.focus()
}
async function poll() {
  clearTimeout(timer)
  if (!auth.user.value) return
  await w.refresh()
  if (!stopped && auth.user.value) timer = setTimeout(poll, 2500)
}
watch(
  () => auth.user.value?.id,
  (id) => {
    clearTimeout(timer)
    w.clear()
    if (id) void poll()
  },
)
onMounted(auth.refresh)
async function logout() {
  try {
    await auth.logout()
  } catch {
    w.actionError.value = 'Could not sign out. Please try again.'
  }
}
onUnmounted(() => {
  stopped = true
  clearTimeout(timer)
})
</script>
<template>
  <ConfirmDialog />
  <main v-if="!auth.ready.value" class="panel empty">
    <p>{{ auth.error.value || 'Opening your workspace…' }}</p>
    <button v-if="auth.error.value" @click="auth.refresh">Retry</button>
  </main>
  <SignIn v-else-if="!auth.user.value" />
  <template v-else>
    <a class="skip" href="#main-content" @click.prevent="skipToContent">Skip to content</a>
    <div class="app-shell">
      <aside class="sidebar">
        <RouterLink class="brand" to="/"
          ><span class="brand-icon"><Icon name="printer" /></span
          ><span>Label room</span></RouterLink
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
        <div v-if="!fleetPage && w.destinations.value.length > 1" class="printer-picker">
          <label
            >Design destination<select v-model="w.selectedPrinter.value">
              <option v-for="printer in w.destinations.value" :key="printer.id" :value="printer.id">
                {{ printer.name }}
              </option>
            </select></label
          >
        </div>
        <div class="sidebar-footer">
          <span
            v-if="status || connectionError || (fleetPage && w.printers.value.length)"
            class="status-dot"
            :class="{
              off: connectionError || (fleetPage ? !connectedPrinters : !status?.connected),
            }"
          ></span
          >{{
            connectionError
              ? 'Server unavailable'
              : fleetPage
                ? fleetSummary
                : status?.connected
                  ? `${status.printer_name} connected`
                  : w.destinations.value.find((d) => d.id === w.selectedPrinter.value)?.kind ===
                      'group'
                    ? 'Distribution group selected'
                    : !w.printers.value.length
                      ? 'No printers assigned'
                      : 'Printer disconnected'
          }}<small>{{
            fleetPage
              ? 'Your printer fleet'
              : (status?.printer_name ??
                (w.selectedPrinter.value
                  ? w.destinationName(w.selectedPrinter.value)
                  : 'Your label workspace'))
          }}</small>
        </div>
      </aside>
      <div class="main-wrap">
        <div class="topbar">
          <span>YOUR LABEL WORKSPACE</span>
          <div class="row">
            <span>{{ auth.user.value.username }}</span
            ><button class="text-button sign-out" @click="logout">Sign out</button
            ><RouterLink v-if="auth.can('printers.manage')" to="/printers" class="printer-pill">{{
              !w.printers.value.length ? 'ADD PRINTER' : 'PRINTERS'
            }}</RouterLink>
          </div>
        </div>
        <main id="main-content" tabindex="-1">
          <header class="page-header">
            <div>
              <h1>{{ route.meta.title }}</h1>
            </div>
            <RouterLink
              v-if="route.path !== '/new' && auth.any('request')"
              class="button primary"
              to="/new"
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
            v-for="printer in route.path.startsWith('/batches/') ? [] : reviewPrinters"
            :key="printer.printer_id"
            class="alert warning"
          >
            <span
              ><strong>Printing is paused on {{ printer.printer_name }}.</strong> An interrupted
              batch needs your review.</span
            ><RouterLink :to="`/batches/${printer.needs_review[0]}`">Review batch →</RouterLink>
          </div>
          <div v-if="!loaded" class="empty panel">
            {{ connectionError ? 'Waiting for the server…' : 'Loading your workspace…' }}
          </div>
          <div
            v-if="w.accessHolds.value.length && route.path !== '/access-holds'"
            class="alert warning"
            role="status"
          >
            <span
              ><strong
                >{{ w.accessHolds.value.length }} labels paused after an access change.</strong
              >
              Review and release or cancel their queued copies.</span
            >
            <RouterLink to="/access-holds">Review paused labels</RouterLink>
          </div>
          <div v-if="loaded && !w.destinations.value.length && needsPrinter" class="panel empty">
            <h2>
              {{
                auth.can('printers.manage') ? 'Add your first printer' : 'No printers assigned yet'
              }}
            </h2>
            <p>
              {{
                auth.can('printers.manage')
                  ? 'Set up a Brother PT-P710BT to start designing and printing labels.'
                  : 'Ask your administrator to assign you a role with access to a printer or distribution group.'
              }}
            </p>
            <RouterLink v-if="auth.can('printers.manage')" class="button primary" to="/printers"
              >Set up printers</RouterLink
            >
          </div>
          <div v-if="!allowed" class="panel empty">
            <h2>Access restricted</h2>
            <p>Your account does not have permission to open this page.</p>
            <RouterLink to="/">Back to overview</RouterLink>
          </div>
          <RouterView
            v-else-if="loaded && (w.destinations.value.length || !needsPrinter)"
            :key="auth.user.value.id"
          />
          <footer class="page-footer">
            <span
              >Made with ♥ by
              <a href="https://github.com/tarobits" target="_blank">tarobits</a>.</span
            >
          </footer>
        </main>
      </div>
    </div>
  </template>
</template>

<style scoped>
.sign-out {
  white-space: nowrap;
}
.printer-picker {
  padding: 12px 20px;
}
.printer-picker label {
  font-size: 12px;
}
</style>
