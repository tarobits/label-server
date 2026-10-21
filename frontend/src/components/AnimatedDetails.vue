<script setup lang="ts">
import { ref, useId } from 'vue'
import ExpandableContent from './ExpandableContent.vue'

const emit = defineEmits<{ toggle: [open: boolean] }>()
const expanded = ref(false)
const rendered = ref(false)
const id = useId()

function toggle() {
  expanded.value = !expanded.value
  if (expanded.value) rendered.value = true
  emit('toggle', expanded.value)
}
function closed() {
  if (!expanded.value) rendered.value = false
}
</script>

<template>
  <details :open="rendered" :data-expanded="expanded">
    <summary :aria-expanded="expanded" :aria-controls="id" @click.prevent="toggle">
      <slot name="summary" />
    </summary>
    <ExpandableContent :id="id" :open="expanded" @closed="closed"><slot /></ExpandableContent>
  </details>
</template>
