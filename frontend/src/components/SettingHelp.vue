<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, useId, watch } from 'vue'
import { InformationCircleIcon } from '@heroicons/vue/24/outline'

export type SettingExplanation = { title: string; text: string; related?: string }
const props = defineProps<{ help: SettingExplanation; for?: string; label?: string }>()
const id = useId()
const trigger = ref<HTMLButtonElement>()
const bubble = ref<HTMLElement>()
const open = ref(false)
const position = ref({ left: '0px', top: '0px', visibility: 'hidden' as 'hidden' | 'visible' })
let pinned = false
let closing: ReturnType<typeof setTimeout> | undefined

function show() {
  clearTimeout(closing)
  window.dispatchEvent(new CustomEvent('setting-help-open', { detail: id }))
  open.value = true
}
function close() {
  clearTimeout(closing)
  pinned = false
  open.value = false
}
function leave() {
  clearTimeout(closing)
  closing = setTimeout(() => {
    if (!pinned && document.activeElement !== trigger.value) close()
  }, 150)
}
function toggle() {
  if (pinned) close()
  else {
    pinned = true
    show()
  }
}
function place() {
  if (!trigger.value || !bubble.value) return
  const anchor = trigger.value.getBoundingClientRect()
  const rect = bubble.value.getBoundingClientRect()
  const padding = 12
  const left = Math.max(padding, Math.min(anchor.left, innerWidth - rect.width - padding))
  const below = anchor.bottom + 8
  const top =
    below + rect.height <= innerHeight - padding
      ? below
      : Math.max(padding, anchor.top - rect.height - 8)
  position.value = { left: `${left}px`, top: `${top}px`, visibility: 'visible' }
}
function outside(event: PointerEvent) {
  const target = event.target as Node
  if (!trigger.value?.contains(target) && !bubble.value?.contains(target)) close()
}
function escape(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    event.stopPropagation()
    close()
  }
}
function otherHelp(event: Event) {
  if ((event as CustomEvent<string>).detail !== id) close()
}
function scroll(event: Event) {
  if (event.target !== bubble.value) close()
}
watch(open, async (value, _, onCleanup) => {
  if (!value) return
  position.value.visibility = 'hidden'
  window.addEventListener('pointerdown', outside)
  window.addEventListener('keydown', escape, true)
  window.addEventListener('resize', close)
  window.addEventListener('setting-help-open', otherHelp)
  // Close when its field moves out of view, including scrolling the inspector.
  window.addEventListener('scroll', scroll, true)
  onCleanup(() => {
    window.removeEventListener('pointerdown', outside)
    window.removeEventListener('keydown', escape, true)
    window.removeEventListener('resize', close)
    window.removeEventListener('setting-help-open', otherHelp)
    window.removeEventListener('scroll', scroll, true)
  })
  await nextTick()
  place()
})
onBeforeUnmount(() => clearTimeout(closing))
</script>

<template>
  <span class="setting-heading">
    <label v-if="props.for" :for="props.for">{{ label ?? help.title }}</label>
    <button
      ref="trigger"
      type="button"
      class="setting-info"
      :aria-label="`About ${help.title}`"
      :aria-describedby="open ? id : undefined"
      @pointerenter="$event.pointerType === 'mouse' && show()"
      @pointerleave="leave"
      @focus="show"
      @blur="close"
      @click.stop="toggle"
    >
      <InformationCircleIcon aria-hidden="true" />
    </button>
  </span>
  <Teleport to="body">
    <Transition name="notice">
      <div
        v-if="open"
        :id="id"
        ref="bubble"
        role="tooltip"
        class="setting-tooltip motion-reveal"
        :style="position"
        @pointerenter="show"
        @pointerleave="leave"
      >
        <strong>{{ help.title }}</strong>
        <p>{{ help.text }}</p>
        <p v-if="help.related" class="setting-related">{{ help.related }}</p>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.setting-heading {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.setting-heading label {
  flex: initial;
  min-width: 0;
}
.setting-info {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 28px;
  width: 28px;
  min-height: 28px;
  padding: 4px;
  border: 0;
  background: transparent;
  color: var(--muted);
}
.setting-info:hover,
.setting-info:focus-visible {
  color: var(--ink);
  background: var(--overlay);
}
.setting-info svg {
  width: 20px;
  height: 20px;
}
.setting-tooltip {
  position: fixed;
  z-index: 200;
  width: 320px;
  max-width: calc(100vw - 24px);
  max-height: calc(100dvh - 24px);
  overflow-y: auto;
  padding: 16px;
  border: 1px solid var(--border-strong);
  border-radius: 8px;
  background: var(--surface-dense);
  color: var(--text-label);
  font-size: 13px;
  font-weight: 400;
  line-height: 1.5;
  overflow-wrap: anywhere;
}
.setting-tooltip p {
  margin-top: 8px;
}
.setting-related {
  color: var(--text-secondary);
}
@media (pointer: coarse) {
  .setting-info {
    flex-basis: 44px;
    width: 44px;
    min-height: 44px;
  }
}
</style>
