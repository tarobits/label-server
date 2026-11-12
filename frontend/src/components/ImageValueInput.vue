<script setup lang="ts">
import { onBeforeUnmount } from 'vue'
import { api } from '../shared/api'
import { useAuthStore } from '../auth/auth'
import { useWorkspaceStore } from '../shared/workspace'
import type { ImageValue } from '../templates/editor'
import type { ImageAsset } from '../shared/types'

const props = defineProps<{
  modelValue: ImageValue | null
  label: string
  name?: string
  required?: boolean
  disabled?: boolean
  context?: object
}>()
const emit = defineEmits<{ 'update:modelValue': [value: ImageValue | null]; change: [] }>()
const w = useWorkspaceStore()
const auth = useAuthStore()
let mounted = true
onBeforeUnmount(() => {
  mounted = false
})
function select(event: Event) {
  const id = (event.target as HTMLSelectElement).value
  emit('update:modelValue', id ? { image_asset: id } : null)
  emit('change')
}
async function upload(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  const context = props.context
  if (!file) return
  if (file.size > 5_000_000) {
    w.actionError = 'Upload an image of at most 5 MB.'
    input.value = ''
    return
  }
  let asset: ImageAsset | undefined
  const ok = await w.action(async () => {
    asset = await api<ImageAsset>(
      `/image-assets?name=${encodeURIComponent(file.name)}`,
      'POST',
      file,
    )
    if (asset.archived) asset = await api<ImageAsset>(`/image-assets/${asset.id}/restore`, 'POST')
  }, 'Image uploaded.')
  if (ok && asset && mounted && props.context === context) {
    emit('update:modelValue', { image_asset: asset.id })
    emit('change')
  }
  input.value = ''
}
</script>

<template>
  <div class="image-value-input">
    <label
      >{{ label
      }}<select
        :value="modelValue?.image_asset ?? ''"
        :name="name"
        :required="required"
        :disabled="disabled || w.busy"
        @change="select"
      >
        <option value="">{{ $t('imageValueInput.noImage') }}</option>
        <option
          v-if="modelValue && !w.images.some((asset) => asset.id === modelValue?.image_asset)"
          :value="modelValue.image_asset"
        >
          {{ $t('common.selectedImage') }}
        </option>
        <option v-for="asset in w.images" :key="asset.id" :value="asset.id">
          {{ asset.name }}
        </option>
      </select></label
    >
    <label v-if="auth.can('images.create_personal')"
      >{{ $t('common.upload') }} {{ label.toLowerCase()
      }}<input
        type="file"
        accept=".png,.jpg,.jpeg,.webp,.gif,.bmp,.svg"
        :disabled="disabled || w.busy"
        @change="upload"
    /></label>
  </div>
</template>

<style scoped>
.image-value-input {
  display: grid;
  gap: 12px;
  min-width: 0;
}
input {
  max-width: 100%;
}
</style>
