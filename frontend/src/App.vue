<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { isNavigationFailure, NavigationFailureType, useRoute, useRouter } from 'vue-router'
import Icon from './components/Icon.vue'
import BrandLogo from './components/BrandLogo.vue'
import AccountMenu from './components/AccountMenu.vue'
import { reducedMotion } from './preferences'
import ConfirmDialog from './components/ConfirmDialog.vue'
import MotionTrack from './components/MotionTrack.vue'
import RouteSurface from './components/RouteSurface.vue'
import VersionStatus from './components/VersionStatus.vue'
import ChangelogNotice from './components/ChangelogNotice.vue'
import SignIn from './views/SignIn.vue'
import { useAuthStore } from './auth'
import { useWorkspaceStore } from './workspace'
import { useLiveRefresh } from './live'
const w = useWorkspaceStore()
const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const navigation = ref<InstanceType<typeof MotionTrack> | null>(null)
const navigationPending = ref(false)
const pageDirection = ref(1)
const routeStage = ref<HTMLElement | null>(null)
let previousHeight = 0
let resize: Animation | undefined
let navigationSequence = 0
const removeGuard = router.beforeResolve(async (to, from) => {
  if (!auth.user) return
  const ticket = ++navigationSequence
  if (to.path === from.path && !navigationPending.value) return
  navigationPending.value = true
  try {
    // Fetch before committing the route so the current page stays mounted.
    await w.setRoute(to.path)
    if (ticket !== navigationSequence) return
    const index = (path: string) =>
      links.value.findIndex(([link]) => link === `/${path.split('/')[1]}`)
    const next = index(to.path),
      previous = index(from.path)
    pageDirection.value = next >= 0 && previous >= 0 && next < previous ? -1 : 1
  } finally {
    if (ticket === navigationSequence) navigationPending.value = false
  }
})
onBeforeUnmount(removeGuard)
const removeAfter = router.afterEach((_to, _from, failure) => {
  // Selecting the current page cancels an outstanding navigation too.
  if (navigationPending.value && isNavigationFailure(failure, NavigationFailureType.duplicated)) {
    navigationSequence++
    navigationPending.value = false
    void w.setRoute(route.path)
  }
})
onBeforeUnmount(removeAfter)
function lockOutgoing(element: Element) {
  ;(element as HTMLElement).inert = true
  element.querySelectorAll<HTMLInputElement>('input, select, textarea, button').forEach((field) => {
    if (!field.disabled) {
      field.disabled = true
      field.setAttribute('data-motion-disabled', '')
    }
  })
  resize?.cancel()
  previousHeight = routeStage.value?.getBoundingClientRect().height ?? 0
  if (routeStage.value) routeStage.value.style.minHeight = `${previousHeight}px`
}
function unlockPage(element: Element) {
  ;(element as HTMLElement).inert = false
  element.querySelectorAll<HTMLInputElement>('[data-motion-disabled]').forEach((field) => {
    field.disabled = false
    field.removeAttribute('data-motion-disabled')
  })
}
function settlePage(event: Event) {
  ;(event.currentTarget as HTMLElement).getAnimations().forEach((animation) => animation.finish())
  resize?.finish()
}
function fitIncoming(element: Element) {
  const stage = routeStage.value
  if (!stage) return
  stage.style.minHeight = ''
  if (!previousHeight || reducedMotion.value) return
  resize = stage.animate(
    [
      { height: `${previousHeight}px` },
      { height: `${Math.max(180, element.getBoundingClientRect().height)}px` },
    ],
    { duration: 320, easing: 'cubic-bezier(0.16, 1, 0.3, 1)' },
  )
  previousHeight = 0
}
onBeforeUnmount(() => resize?.cancel())
watch(reducedMotion, () => resize?.cancel())
const activeSection = computed(() => {
  if (route.path.startsWith('/batches/')) return '/activity'
  if (route.path === '/access-holds') return '/admin'
  return `/${route.path.split('/')[1]}`
})
watch(
  () => [auth.user?.id, activeSection.value],
  async () => {
    await nextTick()
    const nav = navigation.value?.element
    const selected = nav?.querySelector<HTMLElement>('.selected')
    if (!nav || !selected || nav.scrollWidth <= nav.clientWidth) return
    const item = selected.getBoundingClientRect()
    const bounds = nav.getBoundingClientRect()
    nav.scrollLeft += item.left - bounds.left - (bounds.width - item.width) / 2
  },
)
const needsPrinter = computed(() => route.path === '/new')
const designPage = computed(
  () =>
    route.path === '/new' || route.path.startsWith('/templates/') || route.path.startsWith('/runs'),
)
const connectedPrinters = computed(
  () => w.printerStatuses.filter((printer) => printer.connected).length,
)
const fleetSummary = computed(() =>
  w.printers.length
    ? `${connectedPrinters.value} of ${w.printers.length} printers connected`
    : w.destinations.some((destination) => destination.kind === 'group')
      ? 'Distribution groups available'
      : 'No printers assigned',
)
const reviewPrinters = computed(() =>
  w.printerStatuses.filter(
    (printer) => printer.needs_review.length && auth.atLeast(printer.printer_id, 'moderator'),
  ),
)
watch(
  () => (designPage.value ? route.query.printer : undefined),
  (value) => {
    if (typeof value === 'string') w.selectedPrinter = value
  },
  { immediate: true },
)
const { loaded, connectionError, actionError, success } = storeToRefs(w)
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
    if (auth.user?.is_admin) return true
    if (path === '/admin') return auth.user?.is_admin
    if (path === '/printers') return auth.can('printers.manage') || auth.any('moderator')
    if (['/profiles', '/cartridges'].includes(path!)) return auth.can('inventory.manage')
    if (path === '/activity') return w.printers.some((p) => auth.atLeast(p.id, 'moderator'))
    return true
  }),
)
const allowed = computed(() => {
  if (auth.user?.is_admin) return true
  if (route.path === '/admin' || route.path === '/access-holds') return !!auth.user?.is_admin
  if (route.path === '/printers') return auth.can('printers.manage') || auth.any('moderator')
  if (['/profiles', '/cartridges'].includes(route.path)) return auth.can('inventory.manage')
  if (route.path === '/activity' || route.path.startsWith('/batches/'))
    return w.printers.some((p) => auth.atLeast(p.id, 'moderator'))
  if (route.path === '/templates/new') return auth.canCreateTemplates
  if (route.path.endsWith('/edit')) return true
  if (route.path === '/new') return auth.any('request')
  return true
})
function skipToContent() {
  document.getElementById('main-content')?.focus()
}
useLiveRefresh(async () => {
  if (auth.user) await w.refresh()
})
watch(
  () => [auth.user?.id, route.path],
  ([id]) => {
    if (id) void w.setRoute(route.path)
  },
  { immediate: true },
)
onMounted(auth.refresh)
</script>
<template>
  <ConfirmDialog />
  <main v-if="!auth.ready" class="panel empty">
    <p>{{ auth.error || 'Opening your workspace…' }}</p>
    <button v-if="auth.error" @click="auth.refresh(true)">Retry</button>
  </main>
  <SignIn v-else-if="!auth.user" />
  <template v-else>
    <ChangelogNotice v-if="loaded" :key="auth.user.id" />
    <a class="skip" href="#main-content" @click.prevent="skipToContent">Skip to content</a>
    <div class="app-shell">
      <aside class="sidebar">
        <RouterLink class="brand-link" to="/"><BrandLogo /></RouterLink>
        <MotionTrack
          ref="navigation"
          tag="nav"
          :identity="activeSection"
          selector="a.selected"
          aria-label="Main navigation"
        >
          <RouterLink
            v-for="[path, label, icon] in links"
            :key="path"
            :to="path!"
            :class="{ selected: activeSection === path }"
            :aria-current="
              route.path === path ? 'page' : activeSection === path ? 'location' : undefined
            "
            ><Icon :name="icon!" />{{ label
            }}<span v-if="path === '/queue' && w.totalQueued" class="nav-count">{{
              w.totalQueued
            }}</span></RouterLink
          >
        </MotionTrack>
        <div v-if="designPage && w.destinations.length > 1" class="printer-picker">
          <label
            >Design destination<select v-model="w.selectedPrinter">
              <option v-for="printer in w.destinations" :key="printer.id" :value="printer.id">
                {{ printer.name }}
              </option>
            </select></label
          >
        </div>
        <AccountMenu />
        <div class="sidebar-footer">
          <span
            v-if="connectionError || w.printers.length"
            class="status-dot"
            :class="{
              off: connectionError || !connectedPrinters,
            }"
          ></span
          >{{ connectionError ? 'Server unavailable' : fleetSummary }}
        </div>
      </aside>
      <div class="main-wrap">
        <main id="main-content" tabindex="-1" :style="{ '--page-direction': pageDirection }">
          <Transition name="notice">
            <div
              v-if="navigationPending"
              class="navigation-progress"
              role="progressbar"
              aria-label="Loading page"
            />
          </Transition>
          <header class="page-header">
            <div>
              <Transition
                name="page-title"
                @before-leave="(element) => ((element as HTMLElement).inert = true)"
              >
                <h1 :key="String(route.meta.title)">{{ route.meta.title }}</h1>
              </Transition>
            </div>
            <RouterLink
              v-if="route.path !== '/new' && auth.any('request')"
              class="button primary"
              to="/new"
              ><Icon name="plus" />New label</RouterLink
            >
          </header>
          <Transition name="notice">
            <div v-if="connectionError" class="alert danger" role="alert">
              {{ connectionError }}
              <button class="text-button" @click="w.refresh(true)">Retry</button>
            </div>
          </Transition>
          <Transition name="notice">
            <div v-if="actionError" class="alert danger" role="alert">
              {{ actionError
              }}<button class="text-button" aria-label="Dismiss error" @click="actionError = ''">
                Dismiss
              </button>
            </div>
          </Transition>
          <Transition name="notice">
            <div v-if="success" class="alert success" role="status">
              {{ success
              }}<button class="text-button" aria-label="Dismiss message" @click="success = ''">
                Dismiss
              </button>
            </div>
          </Transition>
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
            v-if="w.accessHolds.length && route.path !== '/access-holds'"
            class="alert warning"
            role="status"
          >
            <span
              ><strong>{{ w.accessHolds.length }} labels paused after an access change.</strong>
            </span>
            <RouterLink to="/access-holds">Review paused labels</RouterLink>
          </div>
          <div v-if="loaded && !w.destinations.length && needsPrinter" class="panel empty">
            <h2>
              {{
                auth.can('printers.manage') ? 'Add your first printer' : 'No printers assigned yet'
              }}
            </h2>
            <p v-if="!auth.can('printers.manage')">
              Ask your administrator to assign you a role with access to a printer or distribution
              group.
            </p>
            <RouterLink v-if="auth.can('printers.manage')" class="button primary" to="/printers"
              >Set up printers</RouterLink
            >
          </div>
          <div v-if="!allowed" class="panel empty">
            <h2>Access restricted</h2>
            <RouterLink to="/">Back to overview</RouterLink>
          </div>
          <div
            v-else-if="loaded && (w.destinations.length || !needsPrinter)"
            ref="routeStage"
            class="route-stage"
          >
            <RouterView :key="auth.user.id" v-slot="{ Component }">
              <Transition
                name="page"
                mode="out-in"
                appear
                @before-leave="lockOutgoing"
                @enter="fitIncoming"
                @leave-cancelled="unlockPage"
              >
                <RouteSurface
                  v-if="w.routeReady || navigationPending"
                  :key="route.path"
                  :location="{ ...route }"
                  @focusin="settlePage"
                  @pointerdown.capture="settlePage"
                >
                  <component :is="Component" />
                </RouteSurface>
              </Transition>
            </RouterView>
          </div>
          <footer class="page-footer">
            <VersionStatus />
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
.printer-picker {
  padding: 12px 20px;
}
.printer-picker label {
  font-size: 12px;
}
</style>
