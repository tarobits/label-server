<script setup lang="ts">
import { t } from './shared/i18n'

import { storeToRefs } from 'pinia'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { isNavigationFailure, NavigationFailureType, useRoute, useRouter } from 'vue-router'
import Icon from './components/Icon.vue'
import BrandLogo from './components/BrandLogo.vue'
import AccountMenu from './components/AccountMenu.vue'
import NotificationBell from './components/NotificationBell.vue'
import CartridgeConsent from './components/CartridgeConsent.vue'
import { reducedMotion } from './shared/preferences'
import ConfirmDialog from './components/ConfirmDialog.vue'
import CartridgeCheckPrompt from './components/CartridgeCheckPrompt.vue'
import MotionTrack from './components/MotionTrack.vue'
import RouteSurface from './components/RouteSurface.vue'
import VersionStatus from './components/VersionStatus.vue'
import SourceLink from './components/SourceLink.vue'
import ChangelogNotice from './components/ChangelogNotice.vue'
import ServerUnavailable from './components/ServerUnavailable.vue'
import AppUpdateNotice from './components/AppUpdateNotice.vue'
import { serverUnavailable } from './shared/serverConnection'
import SignIn from './views/SignIn.vue'
import AccountRecovery from './views/AccountRecovery.vue'
import RelationshipMigration from './views/RelationshipMigration.vue'
import { useAuthStore } from './auth/auth'
import { useWorkspaceStore } from './shared/workspace'
import { useLiveRefresh } from './shared/live'
const w = useWorkspaceStore()
const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
let migrationPromptedFor = ''
watch(
  () => [auth.user?.id, auth.session?.migration_required],
  () => {
    if (
      auth.user?.is_admin &&
      auth.session?.migration_required &&
      migrationPromptedFor !== auth.user.id
    ) {
      migrationPromptedFor = auth.user.id
      void router.replace('/migration')
    }
  },
)
const navigation = ref<InstanceType<typeof MotionTrack> | null>(null)
const navigationPending = ref(false)
const pageDirection = ref(1)
const routeStage = ref<HTMLElement | null>(null)
let previousHeight = 0
let resize: Animation | undefined
let navigationSequence = 0
const removeGuard = router.beforeResolve(async (to, from) => {
  if (!auth.user || auth.session?.relationship_migration_required) return
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
    ? t('app.printersConnected', { connected: connectedPrinters.value, total: w.printers.length })
    : w.destinations.some((destination) => destination.kind === 'group')
      ? t('common.distributionGroupsAvailable')
      : t('common.noPrintersAssigned'),
)
const reviewPrinters = computed(() =>
  w.printerStatuses.filter(
    (printer) => printer.needs_review.length && auth.printer(printer.printer_id, 'review'),
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
const navCounts = computed<Record<string, number>>(() => ({
  '/queue': w.totalQueued,
  '/requests': w.overview.pending_requests,
}))
const links = computed(() =>
  [
    ['/', 'common.overview', 'overview'],
    ['/queue', 'common.printQueue', 'queue'],
    ['/requests', 'common.printRequests', 'requests'],
    ['/runs', 'common.csvRuns', 'csv'],
    ['/templates', 'common.templates', 'template'],
    ['/fonts', 'common.fonts', 'font'],
    ['/images', 'common.images', 'image'],
    ['/profiles', 'common.tapeProfiles', 'tape'],
    ['/cartridges', 'resourceAccess.cartridges', 'cartridge'],
    ['/activity', 'common.printActivity', 'activity'],
    ['/audit', 'common.auditLog', 'activity'],
    ['/notification-history', 'common.notificationDelivery', 'bell'],
    ['/usage', 'common.tapeUsage', 'tape'],
    ['/group-accounts', 'common.groupAccounts', 'users'],
    ['/printers', 'common.printersGroups', 'printer'],
    ['/companions', 'companions.companions', 'printer'],
    ['/resource-access', 'common.locationsAccess', 'users'],
    ['/migration', 'common.ownershipMigration', 'users'],
    ['/admin', 'common.administration', 'users'],
  ].filter(([path]) => {
    if (path === '/audit')
      return (
        auth.can('audit.view_all') ||
        auth.anyPrinter('view_audit') ||
        Object.values(auth.user?.cartridge_permissions ?? {}).some((permissions) =>
          permissions.includes('cartridge.view_audit'),
        )
      )
    if (path === '/migration') return auth.user?.is_admin && auth.session?.migration_required
    if (path === '/resource-access')
      return (
        auth.can('locations.manage') ||
        !!auth.user?.managed_location_ids?.length ||
        auth.can('printers.edit_all') ||
        auth.can('cartridges.edit_all') ||
        auth.anyPrinter('configure') ||
        auth.anyPrinter('manage_user_access') ||
        Object.values(auth.user?.cartridge_permissions ?? {}).some((permissions) =>
          permissions.some((p) =>
            ['cartridge.manage_access', 'cartridge.edit_details'].includes(p),
          ),
        )
      )
    if (auth.user?.is_admin) return true
    if (path === '/notification-history' || path === '/companions') return false
    if (path === '/admin') return auth.user?.is_admin
    if (path === '/printers')
      return (
        auth.can('printers.manage') ||
        ['configure', 'swap_cartridges', 'hold_resume', 'review'].some(auth.anyPrinter)
      )
    if (path === '/profiles') return auth.can('inventory.manage')
    if (path === '/cartridges')
      return (
        auth.can('inventory.manage') ||
        Object.values(auth.user?.cartridge_permissions ?? {}).some((permissions) =>
          permissions.includes('cartridge.view'),
        )
      )
    if (path === '/activity') return true
    return true
  }),
)
const allowed = computed(() => {
  if (route.path === '/audit')
    return (
      auth.can('audit.view_all') ||
      auth.anyPrinter('view_audit') ||
      Object.values(auth.user?.cartridge_permissions ?? {}).some((permissions) =>
        permissions.includes('cartridge.view_audit'),
      )
    )
  if (auth.user?.is_admin) return true
  if (route.path === '/notification-history' || route.path === '/companions') return false
  if (route.path === '/admin' || route.path === '/access-holds' || route.path === '/migration')
    return !!auth.user?.is_admin
  if (route.path === '/printers')
    return (
      auth.can('printers.manage') ||
      ['configure', 'swap_cartridges', 'hold_resume', 'review'].some(auth.anyPrinter)
    )
  if (route.path === '/profiles') return auth.can('inventory.manage')
  if (route.path === '/cartridges')
    return (
      auth.can('inventory.manage') ||
      Object.values(auth.user?.cartridge_permissions ?? {}).some((permissions) =>
        permissions.includes('cartridge.view'),
      )
    )
  if (route.path === '/activity' || route.path.startsWith('/batches/')) return true
  if (route.path === '/templates/new') return auth.canCreateTemplates
  if (route.path.endsWith('/edit')) return true
  if (route.path === '/new')
    return auth.anyPrinter('submit_requests') || auth.anyPrinter('submit_directly')
  return true
})
function skipToContent() {
  document.getElementById('main-content')?.focus()
}
useLiveRefresh(async () => {
  if (auth.user && !serverUnavailable.value && !auth.session?.relationship_migration_required)
    await w.refresh()
})
watch(serverUnavailable, async (unavailable, previouslyUnavailable) => {
  if (unavailable || !previouslyUnavailable) return
  await auth.refresh(true)
  if (auth.user && !auth.session?.relationship_migration_required) await w.refresh(true)
})
watch(
  () => [auth.user?.id, route.path],
  ([id]) => {
    if (id && !auth.session?.relationship_migration_required) void w.setRoute(route.path)
  },
  { immediate: true },
)
onMounted(auth.refresh)
</script>
<template>
  <ConfirmDialog />
  <ServerUnavailable />
  <AppUpdateNotice />
  <main v-if="!auth.ready" class="panel empty">
    <p>{{ auth.error || 'Opening your workspace…' }}</p>
    <button v-if="auth.error" @click="auth.refresh(true)">{{ $t('common.retry') }}</button>
  </main>
  <AccountRecovery
    v-else-if="['/forgot-password', '/reset-password', '/verify-email'].includes(route.path)"
    :key="route.path"
  />
  <SignIn v-else-if="!auth.user" />
  <main
    v-else-if="auth.session?.relationship_migration_required"
    id="main-content"
    class="maintenance-shell"
    tabindex="-1"
  >
    <header class="row wrap spread">
      <BrandLogo /><button class="secondary" @click="auth.logout()">
        {{ $t('common.signOut') }}
      </button>
    </header>
    <RelationshipMigration v-if="auth.user.is_admin" />
    <section v-else class="panel">
      <h1>{{ $t('app.maintenanceInProgress') }}</h1>
      <p>{{ $t('app.anAdministratorIsRepairingDatabaseRelationshipsPrintingIsPaused') }}</p>
    </section>
    <footer class="page-footer"><VersionStatus /><SourceLink /></footer>
  </main>
  <template v-else>
    <ChangelogNotice v-if="loaded" :key="auth.user.id" />
    <CartridgeCheckPrompt v-if="loaded" :key="auth.user.id" />
    <a class="skip" href="#main-content" @click.prevent="skipToContent">{{
      $t('common.skipToContent')
    }}</a>
    <div class="app-shell">
      <aside class="sidebar">
        <RouterLink class="brand-link" to="/"><BrandLogo /></RouterLink>
        <MotionTrack
          ref="navigation"
          tag="nav"
          :identity="activeSection"
          selector="a.selected"
          :aria-label="$t('app.mainNavigation')"
        >
          <RouterLink
            v-for="[path, label, icon] in links"
            :key="path"
            :to="path!"
            :class="{ selected: activeSection === path }"
            :aria-current="
              route.path === path ? 'page' : activeSection === path ? 'location' : undefined
            "
            ><Icon :name="icon!" />{{ $t(label!)
            }}<Transition name="notice"
              ><span v-if="navCounts[path!]" class="nav-count motion-reveal">{{
                navCounts[path!]
              }}</span></Transition
            ></RouterLink
          >
        </MotionTrack>
        <div class="account-controls"><AccountMenu /><NotificationBell /></div>
        <CartridgeConsent />
        <div class="sidebar-footer">
          <span
            v-if="connectionError || w.printers.length"
            class="status-dot"
            :class="{
              off: connectionError || !connectedPrinters,
            }"
          ></span
          >{{ connectionError ? $t('common.serverUnavailable') : fleetSummary }}
        </div>
      </aside>
      <div class="main-wrap">
        <main id="main-content" tabindex="-1" :style="{ '--page-direction': pageDirection }">
          <p
            v-if="auth.session?.migration_required && route.path !== '/migration'"
            class="alert warning"
          >
            {{ $t('app.printingIsPausedForTheOwnershipMigration')
            }}<RouterLink v-if="auth.user?.is_admin" to="/migration">
              {{ $t('app.continueSetup') }}</RouterLink
            >
          </p>
          <Transition name="notice">
            <div
              v-if="navigationPending"
              class="navigation-progress"
              role="progressbar"
              :aria-label="$t('common.loadingPage')"
            />
          </Transition>
          <header class="page-header">
            <div>
              <Transition
                name="page-title"
                @before-leave="(element) => ((element as HTMLElement).inert = true)"
              >
                <h1 :key="String(route.meta.title)">{{ $t(String(route.meta.title)) }}</h1>
              </Transition>
            </div>
            <RouterLink
              v-if="
                route.path !== '/new' &&
                (auth.anyPrinter('submit_requests') || auth.anyPrinter('submit_directly'))
              "
              class="button primary"
              to="/new"
              ><Icon name="plus" />{{ $t('app.newLabel') }}</RouterLink
            >
          </header>
          <Transition name="notice">
            <div v-if="connectionError" class="alert danger" role="alert">
              {{ connectionError }}
              <button class="text-button" @click="w.refresh(true)">{{ $t('common.retry') }}</button>
            </div>
          </Transition>
          <Transition name="notice">
            <div v-if="actionError" class="alert danger" role="alert">
              {{ actionError
              }}<button
                class="text-button"
                :aria-label="$t('app.dismissError')"
                @click="actionError = ''"
              >
                {{ $t('app.dismiss') }}
              </button>
            </div>
          </Transition>
          <Transition name="notice">
            <div v-if="success" class="alert success" role="status">
              {{ success
              }}<button
                class="text-button"
                :aria-label="$t('app.dismissMessage')"
                @click="success = ''"
              >
                {{ $t('app.dismiss') }}
              </button>
            </div>
          </Transition>
          <div
            v-for="printer in route.path.startsWith('/batches/') ? [] : reviewPrinters"
            :key="printer.printer_id"
            class="alert warning"
          >
            <span
              ><strong>{{ $t('app.printingIsPausedOn') }} {{ printer.printer_name }}.</strong>
              {{ $t('app.anInterruptedBatchNeedsYourReview') }}</span
            ><RouterLink :to="`/batches/${printer.needs_review[0]}`">{{
              $t('common.reviewBatch')
            }}</RouterLink>
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
              ><strong
                >{{ w.accessHolds.length }}
                {{ $t('common.labelsPausedAfterAnAccessChange') }}</strong
              >
            </span>
            <RouterLink to="/access-holds">{{ $t('app.reviewPausedLabels') }}</RouterLink>
          </div>
          <div v-if="loaded && !w.destinations.length && needsPrinter" class="panel empty">
            <h2>
              {{
                auth.can('printers.manage') ? 'Add your first printer' : 'No printers assigned yet'
              }}
            </h2>
            <p v-if="!auth.can('printers.manage')">
              {{ $t('common.askYourAdministratorToAssignYouARoleWith') }}
            </p>
            <RouterLink v-if="auth.can('printers.manage')" class="button primary" to="/printers">{{
              $t('common.setUpPrinters')
            }}</RouterLink>
          </div>
          <div v-if="!allowed" class="panel empty">
            <h2>{{ $t('app.accessRestricted') }}</h2>
            <RouterLink to="/">{{ $t('app.backToOverview') }}</RouterLink>
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
            <span class="row wrap"><VersionStatus /><SourceLink /></span>
            <span
              >{{ $t('common.madeWithBy') }}
              <a href="https://github.com/tarobits" target="_blank">{{ $t('common.tarobits') }}</a
              >.</span
            >
          </footer>
        </main>
      </div>
    </div>
  </template>
</template>

<style scoped>
.maintenance-shell {
  width: min(1100px, 100%);
  margin: 0 auto;
  padding: clamp(16px, 4vw, 40px);
  display: grid;
  gap: 24px;
}
.printer-picker {
  padding: 12px 20px;
}
.printer-picker label {
  font-size: 12px;
}
</style>
