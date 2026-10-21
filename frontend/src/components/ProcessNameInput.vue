<script setup lang="ts">
import { ref, watch } from 'vue'
const props = defineProps<{ templateName: string }>()
const name = defineModel<string>({ required: true })
const customized = ref(false)
const input = ref<HTMLInputElement | null>(null)
watch(
  () => props.templateName,
  (value) => {
    if (!customized.value) name.value = value
  },
  { immediate: true },
)
function edit(event: Event) {
  customized.value = true
  name.value = (event.target as HTMLInputElement).value
}
function revert() {
  customized.value = false
  name.value = props.templateName
  input.value?.focus()
}
</script>

<template>
  <div class="process-name-input">
    <label
      >Process name<input
        ref="input"
        :value="name"
        name="process_name"
        required
        maxlength="100"
        @input="edit"
    /></label>
    <button v-if="customized" type="button" class="secondary" @click="revert">
      Revert to original
    </button>
  </div>
</template>

<style scoped>
.process-name-input {
  display: flex;
  align-items: end;
  flex-wrap: wrap;
  gap: 12px;
}
label {
  flex: 1 1 220px;
  min-width: 0;
}
.process-name-input > button {
  align-self: flex-end;
}
</style>
