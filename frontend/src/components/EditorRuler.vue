<script setup lang="ts">
import { computed } from 'vue'
const props = defineProps<{
  length: number
  scale: number
  vertical?: boolean
  position: number | null
  selection?: { start: number; end: number } | null
  selectionKey?: string
}>()
const major = computed(() => (props.scale < 6 ? 10 : 5))
const ticks = computed(() => {
  const step = props.scale < 6 ? 2 : 1
  return Array.from({ length: Math.floor(props.length / step) + 1 }, (_, i) => i * step)
})
const range = computed(() =>
  props.selection
    ? {
        start: Math.max(0, Math.min(props.length, props.selection.start)) * props.scale,
        end: Math.max(0, Math.min(props.length, props.selection.end)) * props.scale,
      }
    : null,
)
</script>
<template>
  <svg
    class="editor-ruler"
    :class="vertical ? 'editor-ruler-left' : 'editor-ruler-top'"
    :width="vertical ? 28 : length * scale"
    :height="vertical ? length * scale : 28"
    role="img"
    :aria-label="vertical ? 'Left ruler (mm)' : 'Top ruler (mm)'"
  >
    <rect
      v-if="range"
      :key="selectionKey"
      class="ruler-selection"
      :x="vertical ? 0 : range.start"
      :y="vertical ? range.start : 0"
      :width="vertical ? 28 : range.end - range.start"
      :height="vertical ? range.end - range.start : 28"
    />
    <g v-for="tick in ticks" :key="tick">
      <line
        :x1="vertical ? (tick % major === 0 ? 17 : 23) : tick * scale"
        :x2="vertical ? 28 : tick * scale"
        :y1="vertical ? tick * scale : tick % major === 0 ? 17 : 23"
        :y2="vertical ? tick * scale : 28"
      />
      <text
        v-if="tick % major === 0"
        :x="vertical ? 2 : tick * scale + 3"
        :y="vertical ? tick * scale + 11 : 12"
      >
        {{ tick }}
      </text>
    </g>
    <line
      v-if="position !== null"
      class="ruler-cursor"
      :x1="vertical ? 0 : position * scale"
      :x2="vertical ? 28 : position * scale"
      :y1="vertical ? position * scale : 0"
      :y2="vertical ? position * scale : 28"
    />
  </svg>
</template>
