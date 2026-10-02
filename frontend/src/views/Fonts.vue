<script setup lang="ts">
import { ref } from 'vue'
import { api } from '../api'
import { workspace as w } from '../workspace'
import type { FontAsset } from '../types'
const file = ref<File | null>(null),
  input = ref<HTMLInputElement | null>(null)
function choose(event: Event) {
  file.value = (event.target as HTMLInputElement).files?.[0] ?? null
}
async function upload() {
  if (!file.value) return
  if (file.value.size > 5_000_000) {
    w.actionError.value = 'Upload a font of at most 5 MB.'
    return
  }
  if (
    await w.action(
      () => api<FontAsset>('/font-assets', 'POST', file.value),
      'Font added to the library. Hidden fonts can be restored below.',
    )
  ) {
    file.value = null
    if (input.value) input.value.value = ''
  }
}
async function visibility(font: FontAsset) {
  await w.action(
    () =>
      api(
        `/font-assets/${font.id}${font.archived ? '/restore' : ''}`,
        font.archived ? 'POST' : 'DELETE',
      ),
    font.archived
      ? 'Font restored to the picker.'
      : 'Font hidden from the picker. Saved layouts and queued jobs retain it.',
  )
}
</script>
<template>
  <section class="panel form-stack">
    <h2>Upload a font</h2>
    <p class="help">
      Static TTF and OTF files, up to 5 MB. Upload regular, bold and italic faces separately.
      Variable fonts, font collections and color fonts are not supported yet.
    </p>
    <label
      >Font file<input
        ref="input"
        type="file"
        accept=".ttf,.otf"
        :disabled="w.busy.value"
        @change="choose"
    /></label>
    <button class="primary" :disabled="!file || w.busy.value" @click="upload">Upload font</button>
  </section>
  <section class="panel">
    <h2>Font library</h2>
    <p class="help">
      Noto Sans regular and bold are bundled. Uploads are immutable: new files create separate
      entries. Hiding a font removes it from new selections while keeping saved labels printable.
    </p>
    <div class="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Family</th>
            <th>Face</th>
            <th>Size</th>
            <th>Status</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Noto Sans</td>
            <td>Regular / Bold</td>
            <td>Bundled</td>
            <td>Available</td>
            <td>—</td>
          </tr>
          <tr v-for="font in w.fonts.value" :key="font.id">
            <td>
              {{ font.family }}<small>{{ font.id.slice(0, 12) }}</small>
            </td>
            <td>{{ font.style }}</td>
            <td>{{ (font.size_bytes / 1024).toFixed(0) }} KB</td>
            <td>{{ font.archived ? 'Hidden' : 'Available' }}</td>
            <td>
              <button class="text-button" :disabled="w.busy.value" @click="visibility(font)">
                {{ font.archived ? 'Restore' : 'Hide' }}
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
