<script setup lang="ts">
import { reducedMotion } from '../preferences'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = withDefaults(
  defineProps<{ identity: string; selector: string; tag?: string; underline?: boolean }>(),
  { tag: 'div', underline: false },
)
const root = ref<HTMLElement | null>(null)
const indicator = ref<HTMLElement | null>(null)
const ready = ref(false)
defineExpose({ element: root })
let bounds: { x: number; y: number; width: number; height: number } | undefined
let animation: Animation | undefined
let observer: ResizeObserver | undefined

function cancel() {
  animation?.cancel()
  animation = undefined
}
function measure(animate = false) {
  const host = root.value
  const marker = indicator.value
  const selected = host?.querySelector<HTMLElement>(props.selector)
  if (!host || !marker || !selected || !selected.offsetWidth) {
    ready.value = false
    return
  }
  const frame = host.getBoundingClientRect()
  const item = selected.getBoundingClientRect()
  const next = {
    x: item.left - frame.left + host.scrollLeft - host.clientLeft,
    y: (props.underline ? item.bottom - 2 : item.top) - frame.top + host.scrollTop - host.clientTop,
    width: item.width,
    height: props.underline ? 2 : item.height,
  }
  // Continue a rapid selection change from the marker's visible position.
  const current = marker.getBoundingClientRect()
  const from =
    animation && ready.value
      ? {
          x: current.left - frame.left + host.scrollLeft - host.clientLeft,
          y: current.top - frame.top + host.scrollTop - host.clientTop,
          width: current.width,
          height: current.height,
        }
      : bounds
  cancel()
  Object.assign(marker.style, {
    width: `${next.width}px`,
    height: `${next.height}px`,
    transform: `translate(${next.x}px, ${next.y}px)`,
  })
  if (animate && from && !reducedMotion.value && !document.hidden && marker.animate) {
    animation = marker.animate(
      [
        {
          transform: `translate(${from.x}px, ${from.y}px) scale(${from.width / next.width}, ${from.height / next.height})`,
        },
        { transform: `translate(${next.x}px, ${next.y}px) scale(1)` },
      ],
      { duration: 260, easing: 'cubic-bezier(0.16, 1, 0.3, 1)' },
    )
  }
  bounds = next
  ready.value = true
}
watch(
  () => props.identity,
  () => measure(true),
  { flush: 'post' },
)
watch(reducedMotion, cancel)
onMounted(() => {
  measure()
  observer = new ResizeObserver(() => measure())
  if (root.value) observer.observe(root.value)
})
onBeforeUnmount(() => {
  observer?.disconnect()
  cancel()
})
</script>

<template>
  <component
    :is="tag"
    ref="root"
    class="motion-track"
    :class="{ 'motion-track-ready': ready, 'motion-track-underline': underline }"
  >
    <span ref="indicator" class="motion-indicator" aria-hidden="true" />
    <slot />
  </component>
</template>
