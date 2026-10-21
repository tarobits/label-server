<script setup lang="ts">
import { reducedMotion } from '../preferences'
import { onBeforeUnmount, ref, watch } from 'vue'

const props = withDefaults(defineProps<{ identity: string; order?: number }>(), { order: 0 })
const surface = ref<HTMLElement | null>(null)
let arrival: Animation | undefined
let lastOrder = props.order

function cancelArrival() {
  arrival?.cancel()
  arrival = undefined
}

// Keep panel fields mounted: polling and edits must not replay the swipe or
// discard local state. A new selection interrupts the previous arrival.
watch(
  [surface, () => props.identity],
  ([element], _, onCleanup) => {
    cancelArrival()
    const direction = props.order < lastOrder ? -1 : 1
    lastOrder = props.order
    if (!element?.animate || document.hidden) return
    const duration = parseFloat(getComputedStyle(element).getPropertyValue('--motion-enter'))
    if (!Number.isFinite(duration) || duration <= 0) return
    const frames = reducedMotion.value
      ? [{ opacity: 0.85 }, { opacity: 1 }]
      : [
          { opacity: 0.55, transform: `translateX(${direction * 24}px)` },
          { opacity: 1, transform: 'translateX(0)' },
        ]
    arrival = element.animate(frames, {
      duration: reducedMotion.value ? 100 : duration,
      easing: 'cubic-bezier(0.16, 1, 0.3, 1)',
    })
    onCleanup(cancelArrival)
  },
  { flush: 'post' },
)

watch(reducedMotion, cancelArrival)
onBeforeUnmount(() => {
  cancelArrival()
})
</script>

<template>
  <div ref="surface" @focusin="cancelArrival" @pointerdown.capture="cancelArrival"><slot /></div>
</template>
