<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps<{ identity: string }>()
const surface = ref<HTMLElement | null>(null)
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)')
let arrival: Animation | undefined

function cancelArrival() {
  arrival?.cancel()
  arrival = undefined
}

// Keep the routed view mounted: query changes, polling, and form edits must not
// replay the arrival or discard local state. A new identity interrupts cleanly.
watch(
  [surface, () => props.identity],
  ([element], _, onCleanup) => {
    cancelArrival()
    if (!element?.animate) return
    const duration = parseFloat(getComputedStyle(element).getPropertyValue('--motion-state'))
    if (!Number.isFinite(duration) || duration <= 0) return
    arrival = element.animate([{ opacity: reducedMotion.matches ? 0.85 : 0.6 }, { opacity: 1 }], {
      duration,
      easing: 'cubic-bezier(0.16, 1, 0.3, 1)',
    })
    onCleanup(cancelArrival)
  },
  { flush: 'post' },
)

onMounted(() => reducedMotion.addEventListener('change', cancelArrival))
onBeforeUnmount(() => {
  reducedMotion.removeEventListener('change', cancelArrival)
  cancelArrival()
})
</script>

<template>
  <div ref="surface"><slot /></div>
</template>
