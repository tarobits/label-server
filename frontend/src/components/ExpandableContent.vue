<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { reducedMotion } from '../preferences'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ closed: [] }>()
const viewport = ref<HTMLElement | null>(null)
const content = ref<HTMLElement | null>(null)
const visible = ref(props.open)
let animation: Animation | undefined
let observer: ResizeObserver | undefined
let measuredHeight = 0
let targetHeight = 0
let generation = 0
let laidOut = false

function settle() {
  animation?.cancel()
  animation = undefined
  if (viewport.value) viewport.value.dataset.expanding = 'false'
  visible.value = props.open
  if (!props.open) emit('closed')
}

function finishExpansion() {
  if (props.open && animation) settle()
}

function expand(from: number, to: number, opacity = 1) {
  const element = viewport.value
  animation?.cancel()
  animation = undefined
  targetHeight = to
  if (!element?.animate || reducedMotion.value || document.hidden || Math.abs(from - to) < 0.5) {
    settle()
    return
  }
  const style = getComputedStyle(element)
  const token = style.getPropertyValue(props.open ? '--motion-enter' : '--motion-state').trim()
  const duration = parseFloat(token) * (token.endsWith('ms') ? 1 : 1000)
  if (!Number.isFinite(duration) || duration <= 0) {
    settle()
    return
  }
  // Animation bookkeeping must not rerender slots with uncommitted form edits.
  element.dataset.expanding = 'true'
  const run = element.animate(
    [
      { height: `${from}px`, opacity },
      { height: `${to}px`, opacity: props.open ? 1 : 0 },
    ],
    { duration, easing: style.getPropertyValue('--motion-ease').trim(), fill: 'both' },
  )
  animation = run
  run.onfinish = () => {
    if (animation === run) settle()
  }
}

watch(
  () => props.open,
  async (open) => {
    const ticket = ++generation
    const element = viewport.value
    const from = element?.getBoundingClientRect().height ?? 0
    const opacity = element && visible.value ? Number(getComputedStyle(element).opacity) : 0.6
    // Keep the content mounted and visible until the closing animation finishes.
    visible.value = true
    await nextTick()
    if (ticket !== generation || !content.value) return
    measuredHeight = content.value.getBoundingClientRect().height
    expand(from, open ? measuredHeight : 0, opacity)
  },
)

onMounted(() => {
  if (viewport.value) viewport.value.dataset.expanding = 'false'
  measuredHeight = content.value?.getBoundingClientRect().height ?? 0
  laidOut = Boolean(content.value?.getClientRects().length)
  observer = new ResizeObserver(() => {
    const height = content.value?.getBoundingClientRect().height ?? 0
    const previous = measuredHeight
    const wasLaidOut = laidOut
    laidOut = Boolean(content.value?.getClientRects().length)
    measuredHeight = height
    if (!props.open || !visible.value || Math.abs(height - previous) < 0.5) return
    // Showing a containing tab already has its own transition.
    if (!laidOut || !wasLaidOut) {
      if (animation) settle()
      return
    }
    // Editing a field must not move it, including fields revealed by a checkbox.
    if (content.value?.contains(document.activeElement)) {
      finishExpansion()
      return
    }
    // A nested disclosure already animates its parent's natural height.
    if (content.value?.querySelector('[data-expanding="true"]')) {
      if (animation) settle()
      return
    }
    if (animation && Math.abs(height - targetHeight) < 0.5) return
    const element = viewport.value!
    expand(
      animation ? element.getBoundingClientRect().height : previous,
      height,
      Number(getComputedStyle(element).opacity),
    )
  })
  if (content.value) observer.observe(content.value)
})
watch(reducedMotion, () => {
  if (reducedMotion.value) settle()
})
onBeforeUnmount(() => {
  generation++
  animation?.cancel()
  observer?.disconnect()
})
</script>

<template>
  <div
    ref="viewport"
    class="disclosure-body"
    :hidden="!visible"
    :inert="!open"
    @focusin="finishExpansion"
    @pointerdown.capture="finishExpansion"
  >
    <div ref="content" class="disclosure-content"><slot /></div>
  </div>
</template>

<style scoped>
.disclosure-body[data-expanding='true'] {
  overflow: clip;
}
.disclosure-content {
  display: flow-root;
}
</style>
