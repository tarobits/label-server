<script setup lang="ts">
import { ref, useId } from 'vue'
import { ChevronDownIcon } from '@heroicons/vue/20/solid'
import ExpandableContent from './ExpandableContent.vue'

const props = withDefaults(defineProps<{ title: string; initiallyOpen?: boolean }>(), {
  initiallyOpen: false,
})
const open = ref(props.initiallyOpen)
const id = useId()
</script>

<template>
  <section class="property-section">
    <h3>
      <button
        type="button"
        :id="`${id}-heading`"
        :aria-expanded="open"
        :aria-controls="id"
        @click="open = !open"
      >
        {{ title }}
        <ChevronDownIcon :class="{ collapsed: !open }" />
      </button>
    </h3>
    <ExpandableContent :id="id" :open="open" class="property-section-body">
      <div class="property-section-content"><slot /></div>
    </ExpandableContent>
  </section>
</template>
