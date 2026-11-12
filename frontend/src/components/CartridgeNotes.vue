<script setup lang="ts">
import { ref } from 'vue'
import type { Cartridge } from '../shared/types'
import { api } from '../shared/api'
import { useWorkspaceStore } from '../shared/workspace'
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
    <template #summary>{{ $t('cartridgeNotes.notes') }}</template>
    <form class="form-stack inset" @submit.prevent="save">
      <label
        >{{ $t('cartridgeNotes.cartridgeNotes')
        }}<textarea v-model="notes" rows="4" maxlength="10000" />
      </label>
      <button class="secondary" :disabled="w.busy">{{ $t('common.saveNotes') }}</button>
    </form>
  </AnimatedDetails>
</template>
