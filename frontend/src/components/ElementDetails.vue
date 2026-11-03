<script setup lang="ts">
import { DocumentDuplicateIcon, TrashIcon } from '@heroicons/vue/24/outline'

const name = defineModel<string>('name', { default: '' })
defineEmits<{ change: []; duplicate: []; remove: [] }>()
</script>

<template>
  <div class="element-details">
    <label>Element name<input v-model="name" maxlength="100" @change="$emit('change')" /></label>
    <div class="row wrap">
      <button class="small" aria-label="Duplicate element" @click="$emit('duplicate')">
        <DocumentDuplicateIcon aria-hidden="true" />Duplicate
      </button>
      <button class="small danger-text" aria-label="Delete element" @click="$emit('remove')">
        <TrashIcon aria-hidden="true" />Delete
      </button>
    </div>
  </div>
</template>

<style scoped>
.element-details {
  display: grid;
  gap: 12px;
}
button svg {
  width: 20px;
  height: 20px;
  flex-shrink: 0;
}
</style>
