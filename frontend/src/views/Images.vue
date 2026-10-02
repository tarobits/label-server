<script setup lang="ts">
import { ref } from 'vue'
import { api } from '../api'
import { workspace as w } from '../workspace'
import type { ImageAsset } from '../types'
const file = ref<File | null>(null),
  input = ref<HTMLInputElement | null>(null)
function choose(event: Event) {
  file.value = (event.target as HTMLInputElement).files?.[0] ?? null
}
async function upload() {
  const chosen = file.value
  if (!chosen) return
  if (chosen.size > 5_000_000) {
    w.actionError.value = 'Upload an image of at most 5 MB.'
    return
  }
  if (
    await w.action(
      () =>
        api<ImageAsset>(`/image-assets?name=${encodeURIComponent(chosen.name)}`, 'POST', chosen),
      'Image added to the library. Choose it in an image element in the template editor.',
    )
  ) {
    file.value = null
    if (input.value) input.value.value = ''
  }
}
async function visibility(asset: ImageAsset) {
  await w.action(
    () =>
      api(
        `/image-assets/${asset.id}${asset.archived ? '/restore' : ''}`,
        asset.archived ? 'POST' : 'DELETE',
      ),
    asset.archived
      ? 'Image restored to the picker.'
      : 'Image hidden. Saved layouts and queued jobs retain it.',
  )
}
</script>
<template>
  <section class="panel form-stack">
    <h2>Upload an image</h2>
    <p class="help">
      PNG, JPEG, WebP, BMP, still GIF or simple SVG, up to 5 MB. Bitmaps are limited to 16
      megapixels and 8192 pixels per side.
    </p>
    <p class="help">
      SVG supports paths and basic shapes. Convert text to paths and remove styles, embedded images,
      filters and external references before uploading.
    </p>
    <label
      >Image file<input
        ref="input"
        type="file"
        accept=".png,.jpg,.jpeg,.webp,.bmp,.gif,.svg"
        :disabled="w.busy.value"
        @change="choose"
    /></label>
    <button class="primary" :disabled="!file || w.busy.value" @click="upload">Upload image</button>
  </section>
  <section class="panel">
    <h2>Image library</h2>
    <p class="help">
      Hiding an image removes it from new selections. Saved templates and queued jobs keep the
      original artwork and their own brightness and contrast settings.
    </p>
    <p v-if="!w.images.value.length" class="empty">Upload your first image to get started.</p>
    <div v-else class="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Format</th>
            <th>Dimensions</th>
            <th>Status</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="asset in w.images.value" :key="asset.id">
            <td>
              {{ asset.name }}<small>{{ asset.id.slice(0, 12) }}</small>
            </td>
            <td>{{ asset.kind === 'svg' ? 'SVG' : 'Bitmap' }}</td>
            <td>{{ asset.width }} × {{ asset.height }}</td>
            <td>{{ asset.archived ? 'Hidden' : 'Available' }}</td>
            <td>
              <button class="text-button" :disabled="w.busy.value" @click="visibility(asset)">
                {{ asset.archived ? 'Restore' : 'Hide' }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <RouterLink class="button secondary open-templates" to="/templates">Open templates</RouterLink>
  </section>
</template>
<style scoped>
.open-templates {
  margin-top: 18px;
}
</style>
