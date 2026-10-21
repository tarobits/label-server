<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  ArrowRightStartOnRectangleIcon,
  ChevronRightIcon,
  Cog6ToothIcon,
  UserCircleIcon,
} from '@heroicons/vue/24/outline'
import { useAuthStore } from '../auth'
import { useWorkspaceStore } from '../workspace'
const auth = useAuthStore()
const workspace = useWorkspaceStore()
const route = useRoute()
const menu = ref<HTMLDetailsElement | null>(null)
const panel = ref<HTMLElement | null>(null)
const open = ref(false)
const signingOut = ref(false)
const panelId = useId()
const position = ref({ left: '20px', top: '20px' })
function place() {
  const trigger = menu.value,
    flyout = panel.value,
    sidebar = trigger?.closest('aside')
  if (!trigger || !flyout || !sidebar) return
  const anchor = trigger.getBoundingClientRect(),
    edge = sidebar.getBoundingClientRect()
  const mobile = window.matchMedia('(max-width: 850px)').matches
  position.value = {
    left: `${Math.max(12, Math.min(mobile ? anchor.right - flyout.offsetWidth : edge.right + 12, innerWidth - flyout.offsetWidth - 12))}px`,
    top: `${Math.max(12, Math.min(mobile ? edge.bottom + 8 : anchor.bottom - flyout.offsetHeight, innerHeight - flyout.offsetHeight - 12))}px`,
  }
}
async function toggle(event: MouseEvent) {
  open.value = !open.value
  if (open.value) {
    await nextTick()
    place()
    if (event.detail === 0) panel.value?.querySelector('a')?.focus()
  }
}
function moveOut(event: KeyboardEvent) {
  const fields = panel.value?.querySelectorAll<HTMLElement>('a[href], button:not(:disabled)')
  if (!fields?.length) return
  if (event.shiftKey && event.target === fields[0]) {
    event.preventDefault()
    close(true)
  } else if (!event.shiftKey && event.target === fields[fields.length - 1]) {
    event.preventDefault()
    close()
    const main = document.getElementById('main-content')
    const next = [
      ...(main?.querySelectorAll<HTMLElement>(
        'a[href], button, input, select, textarea, [tabindex]',
      ) ?? []),
    ].find(
      (element) =>
        element.tabIndex >= 0 &&
        !element.matches(':disabled') &&
        !element.closest('[inert]') &&
        element.getClientRects().length &&
        getComputedStyle(element).visibility !== 'hidden',
    )
    ;(next ?? main)?.focus()
  }
}
function enterFlyout(event: KeyboardEvent) {
  if (!open.value || event.shiftKey) return
  const first = panel.value?.querySelector<HTMLElement>('a[href], button:not(:disabled)')
  if (!first) return
  event.preventDefault()
  first.focus()
}
function focusOutside(event: FocusEvent) {
  const next = event.relatedTarget
  if (!(next instanceof Node) || (!menu.value?.contains(next) && !panel.value?.contains(next)))
    close()
}
function close(focus = false) {
  if (!open.value) return
  open.value = false
  if (focus) menu.value?.querySelector('summary')?.focus()
}
function escape(event: KeyboardEvent) {
  if (!open.value) return
  event.preventDefault()
  event.stopPropagation()
  close(true)
}
function outside(event: PointerEvent) {
  if (
    event.target instanceof Node &&
    !menu.value?.contains(event.target) &&
    !panel.value?.contains(event.target)
  )
    close()
}
watch(
  () => route.path,
  () => close(),
)
onMounted(() => {
  document.addEventListener('pointerdown', outside)
  window.addEventListener('resize', place)
  window.addEventListener('scroll', place, true)
})
onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', outside)
  window.removeEventListener('resize', place)
  window.removeEventListener('scroll', place, true)
})
async function logout() {
  if (signingOut.value) return
  signingOut.value = true
  try {
    await auth.logout()
  } catch {
    workspace.actionError = 'Could not sign out. Please try again.'
  } finally {
    signingOut.value = false
  }
}
</script>
<template>
  <details
    ref="menu"
    class="account-menu"
    :open="open"
    :class="{ active: route.path === '/account' }"
    @keydown.esc="escape"
    @focusout="focusOutside"
  >
    <summary
      :aria-label="`Account: ${auth.user?.username}`"
      :aria-expanded="open"
      :aria-controls="panelId"
      @click.prevent="toggle"
      @keydown.tab="enterFlyout"
    >
      <UserCircleIcon class="account-icon" /><span class="account-name">{{
        auth.user?.username
      }}</span
      ><ChevronRightIcon class="account-chevron" />
    </summary>
  </details>
  <Teleport to="body">
    <Transition
      name="account-flyout"
      @before-enter="(element) => ((element as HTMLElement).inert = false)"
      @before-leave="(element) => ((element as HTMLElement).inert = true)"
    >
      <div
        v-if="open"
        :id="panelId"
        ref="panel"
        class="account-flyout"
        :style="position"
        role="group"
        aria-label="Account"
        @keydown.esc="escape"
        @keydown.tab="moveOut"
        @focusout="focusOutside"
      >
        <RouterLink to="/account"><Cog6ToothIcon />Account settings</RouterLink>
        <button type="button" :aria-disabled="signingOut" :aria-busy="signingOut" @click="logout">
          <ArrowRightStartOnRectangleIcon />Sign out
        </button>
      </div>
    </Transition>
  </Teleport>
</template>
<style scoped>
.account-menu {
  flex-shrink: 0;
  margin-top: 24px;
  min-width: 0;
}
summary {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 44px;
  padding: 10px 14px;
  border-radius: 6px;
  color: var(--ink);
  cursor: pointer;
  transition: background-color var(--motion-fast) ease-out;
}
summary::before {
  display: none;
}
summary:hover,
details[open] > summary,
.active > summary {
  background: var(--overlay);
}
.account-icon {
  width: 20px;
  height: 20px;
  flex-shrink: 0;
  color: var(--text-secondary);
}
.account-name {
  min-width: 0;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
}
.account-chevron {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
  transition: transform var(--motion-state) var(--motion-ease);
}
[open] .account-chevron {
  transform: rotate(90deg);
}
.account-flyout {
  position: fixed;
  z-index: 50;
  width: min(240px, calc(100vw - 24px));
  max-height: calc(100dvh - 24px);
  overflow: auto;
  padding: 6px;
  background: var(--surface);
  border: 1px solid var(--line-strong);
  border-radius: 12px;
}
.account-flyout a,
.account-flyout button {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 12px;
  width: 100%;
  min-height: 44px;
  padding: 12px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--ink);
  font-size: 13px;
  font-weight: 500;
}
.account-flyout a:hover,
.account-flyout button:hover {
  background: var(--overlay);
  text-decoration: none;
}
.account-flyout button[aria-disabled='true'] {
  opacity: 0.45;
  cursor: wait;
}
.account-flyout svg {
  width: 20px;
  height: 20px;
  flex-shrink: 0;
  color: var(--text-secondary);
}
.account-flyout-enter-active {
  transition:
    transform var(--motion-enter) var(--motion-ease),
    opacity var(--motion-state) ease-out,
    clip-path var(--motion-enter) var(--motion-ease);
}
.account-flyout-leave-active {
  pointer-events: none;
  transition:
    transform var(--motion-exit) ease-in,
    opacity var(--motion-exit) ease-in;
}
.account-flyout-enter-from {
  opacity: 0;
  transform: translateX(-18px);
  clip-path: inset(0 100% 0 0 round 12px);
}
.account-flyout-leave-to {
  opacity: 0;
  transform: translateX(-10px);
}
:global(:root[data-motion='reduce'] .account-chevron) {
  transition: none;
}
:global(:root[data-motion='reduce'] .account-flyout-enter-active),
:global(:root[data-motion='reduce'] .account-flyout-leave-active) {
  transition: opacity var(--motion-fast) ease-out;
}
:global(:root[data-motion='reduce'] .account-flyout-enter-from),
:global(:root[data-motion='reduce'] .account-flyout-leave-to) {
  transform: none;
  clip-path: none;
}
@media (max-width: 850px) {
  .account-menu {
    margin-top: 0;
    max-width: 140px;
  }
  summary {
    padding: 8px;
    gap: 7px;
  }
}
</style>
