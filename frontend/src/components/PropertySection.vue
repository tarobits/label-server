<script setup lang="ts">
import { ref, useId } from 'vue'
import { ChevronDownIcon } from '@heroicons/vue/20/solid'

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
    <Transition name="property-expand">
      <div v-show="open" :id="id" class="property-section-body" :inert="!open">
        <div class="property-section-clip">
          <div class="property-section-content"><slot /></div>
        </div>
      </div>
    </Transition>
  </section>
</template>
