<script setup lang="ts">
import { ref, onBeforeUnmount } from 'vue'
import ExpandableContent from './ExpandableContent.vue'
const model = defineModel<string | null>({ default: null })
defineProps<{ policy: 'disabled' | 'optional' | 'required'; disabled?: boolean }>()
const error = ref(''),
  input = ref<HTMLInputElement | null>(null),
  mime = ref('image/jpeg')
let generation = 0
onBeforeUnmount(() => generation++)
function clear() {
  generation++
  model.value = null
  error.value = ''
  if (input.value) {
    input.value.value = ''
    input.value.focus()
  }
}
async function choose(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  generation++
  model.value = null
  error.value = ''
  if (!file) return
  mime.value = file.type
  const ticket = generation
  if (file.size > 5_000_000 || !['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
    error.value = 'Choose a PNG, JPEG or WebP photo up to 5 MB.'
    return
  }
  try {
    const encoded = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = () => resolve(String(reader.result).split(',')[1] ?? '')
      reader.onerror = () => reject(new Error('Photo could not be read.'))
      reader.readAsDataURL(file)
    })
    if (ticket === generation) model.value = encoded
  } catch {
    if (ticket === generation) error.value = 'Photo could not be read.'
  }
}
</script>
<template>
  <div v-if="policy !== 'disabled'" class="form-stack">
    <label
      >Evidence photo{{ policy === 'required' ? ' (required)' : ' (optional)' }}
      <input
        ref="input"
        type="file"
        accept="image/jpeg,image/png,image/webp"
        :disabled="disabled"
        @change="choose"
      />
    </label>
    <Transition name="notice"
      ><p v-if="error" role="alert" class="alert danger">{{ error }}</p></Transition
    >
    <ExpandableContent :open="!!model">
      <div class="evidence-preview">
        <img v-if="model" :src="`data:${mime};base64,${model}`" alt="Selected evidence photo" />
        <button type="button" class="secondary" :disabled="disabled" @click="clear">
          Remove photo
        </button>
      </div>
    </ExpandableContent>
  </div>
</template>
<style scoped>
.evidence-preview {
  display: grid;
  justify-items: start;
  gap: 12px;
}
.evidence-preview img {
  max-width: 100%;
  max-height: 220px;
  object-fit: contain;
  border-radius: 8px;
}
</style>
