<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, useId } from 'vue'
import { LanguageIcon, CheckIcon } from '@heroicons/vue/24/outline'
import { useAuthStore } from '../auth/auth'
import { deviceLanguage, locale, t, type Language } from '../shared/i18n'

const props = defineProps<{ account?: boolean; save?: (language: Language) => Promise<unknown> }>()
const auth = props.account ? useAuthStore() : null
const root = ref<HTMLElement>()
const trigger = ref<HTMLButtonElement>()
const panel = ref<HTMLElement>()
const open = ref(false)
const panelId = useId()
const languages = [
  { value: 'en' as const, name: 'English' },
  { value: 'de' as const, name: 'Deutsch' },
]
const busy = ref(false)
const error = ref('')
let disposed = false
onBeforeUnmount(() => {
  disposed = true
  document.removeEventListener('pointerdown', outside)
})
onMounted(() => document.addEventListener('pointerdown', outside))
function close(restoreFocus = false) {
  open.value = false
  if (restoreFocus) trigger.value?.focus()
}
async function toggle() {
  if (open.value) return close()
  open.value = true
  await nextTick()
  panel.value?.querySelector<HTMLElement>('[aria-checked="true"]')?.focus()
}
function outside(event: PointerEvent) {
  if (event.target instanceof Node && !root.value?.contains(event.target)) close()
}
function leave(event: FocusEvent) {
  if (event.relatedTarget instanceof Node && !root.value?.contains(event.relatedTarget)) close()
}
function move(event: KeyboardEvent) {
  const options = [...panel.value!.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]')]
  const index = options.indexOf(document.activeElement as HTMLButtonElement)
  if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  const target =
    event.key === 'Home'
      ? 0
      : event.key === 'End'
        ? options.length - 1
        : (index + (event.key === 'ArrowDown' ? 1 : -1) + options.length) % options.length
  options[target]?.focus()
}
async function change(next: Language) {
  if (busy.value) return
  error.value = ''
  busy.value = true
  try {
    if (props.save) await props.save(next)
    else if (props.account) await auth?.saveLanguage(next)
    else deviceLanguage.value = next
    if (!disposed) close(true)
  } catch {
    if (disposed) return
    error.value = t('errors.languageSave')
  } finally {
    if (!disposed) busy.value = false
  }
}
</script>

<template>
  <div ref="root" class="language-picker" @focusout="leave" @keydown.esc.stop.prevent="close(true)">
    <button
      ref="trigger"
      class="secondary language-trigger"
      :aria-label="$t('account.language')"
      aria-haspopup="menu"
      :aria-expanded="open"
      :aria-controls="panelId"
      :aria-busy="busy"
      @click="toggle"
      @keydown.down.prevent="!open && toggle()"
    >
      <LanguageIcon aria-hidden="true" />
    </button>
    <Transition
      name="language-menu"
      @before-enter="(element) => ((element as HTMLElement).inert = false)"
      @before-leave="(element) => ((element as HTMLElement).inert = true)"
    >
      <div
        v-if="open"
        :id="panelId"
        ref="panel"
        class="language-menu"
        role="menu"
        :aria-label="$t('account.language')"
        @keydown="move"
      >
        <button
          v-for="language in languages"
          :key="language.value"
          role="menuitemradio"
          :lang="language.value"
          :aria-checked="locale === language.value"
          :aria-disabled="busy"
          tabindex="-1"
          @click="change(language.value)"
        >
          {{ language.name }}<CheckIcon v-if="locale === language.value" aria-hidden="true" />
        </button>
        <Transition name="notice"
          ><p v-if="error" class="alert danger" role="alert">{{ error }}</p></Transition
        >
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.language-picker {
  position: relative;
  flex: 0 0 auto;
}
.language-trigger {
  width: 44px;
  height: 44px;
  padding: 10px;
}
.language-trigger svg {
  width: 22px;
  height: 22px;
}
.language-menu {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  z-index: 50;
  width: min(220px, calc(100vw - 32px));
  padding: 6px;
  background: var(--surface);
  border: 1px solid var(--line-strong);
  border-radius: 12px;
}
.language-menu button {
  display: flex;
  align-items: center;
  justify-content: space-between;
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
.language-menu button:hover {
  background: var(--overlay);
}
.language-menu button[aria-disabled='true'] {
  opacity: 0.45;
  cursor: wait;
}
.language-menu svg {
  width: 20px;
  height: 20px;
}
.language-menu .alert {
  margin: 8px 0 0;
}
.language-menu-enter-active {
  transition:
    transform var(--motion-enter) var(--motion-ease),
    opacity var(--motion-state) ease-out,
    clip-path var(--motion-enter) var(--motion-ease);
}
.language-menu-leave-active {
  pointer-events: none;
  transition:
    transform var(--motion-exit) ease-in,
    opacity var(--motion-exit) ease-in;
}
.language-menu-enter-from {
  opacity: 0;
  transform: translateY(-8px);
  clip-path: inset(0 0 100% 0 round 12px);
}
.language-menu-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}
:global(:root[data-motion='reduce']) .language-menu-enter-active,
:global(:root[data-motion='reduce']) .language-menu-leave-active {
  transition: opacity var(--motion-fast) ease-out;
}
:global(:root[data-motion='reduce']) .language-menu-enter-from,
:global(:root[data-motion='reduce']) .language-menu-leave-to {
  transform: none;
  clip-path: none;
}
</style>
