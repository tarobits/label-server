<script setup lang="ts">
import { ref } from 'vue'
import type { Cartridge } from '../types'
import { api } from '../api'
import { useWorkspaceStore } from '../workspace'
import AnimatedDetails from './AnimatedDetails.vue'
const props = defineProps<{ cartridge: Cartridge }>()
const w = useWorkspaceStore()
const notes = ref('')
async function save() {
  await w.action(
    () => api(`/cartridges/${props.cartridge.id}/notes`, 'PUT', { notes: notes.value }),
    'Notes saved.',
  )
}
</script>
<template>
  <AnimatedDetails
    @toggle="
      (open) => {
        if (open) notes = cartridge.notes ?? ''
      }
    "
  >
    <template #summary>Notes</template>
    <form class="form-stack inset" @submit.prevent="save">
      <label>Cartridge notes<textarea v-model="notes" rows="4" maxlength="10000" /></label>
      <button class="secondary" :disabled="w.busy">Save notes</button>
    </form>
  </AnimatedDetails>
</template>
