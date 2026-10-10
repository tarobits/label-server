<script setup lang="ts">
import { nextTick, ref } from 'vue'
import { api } from '../api'
import { auth } from '../auth'
import { confirmAction } from '../confirmation'
import { workspace as w } from '../workspace'
import type { ImageAsset } from '../types'
const file = ref<File | null>(null),
  input = ref<HTMLInputElement | null>(null)
const editing = ref<string | null>(null),
  imageName = ref(''),
  renameInput = ref<HTMLInputElement[]>([]),
  preview = ref<ImageAsset | null>(null),
  previewDialog = ref<HTMLDialogElement | null>(null),
  previewFailed = ref(false)

async function showPreview(asset: ImageAsset) {
  preview.value = asset
  previewFailed.value = false
  await nextTick()
  previewDialog.value?.showModal()
}
async function startRename(asset: ImageAsset) {
  editing.value = asset.id
  imageName.value = asset.name
  await nextTick()
  renameInput.value[0]?.focus()
  renameInput.value[0]?.select()
}
async function rename(asset: ImageAsset) {
  if (!imageName.value.trim()) return
  if (
    await w.action(
      () => api(`/image-assets/${asset.id}`, 'PUT', { name: imageName.value.trim() }),
      'Image renamed.',
    )
  )
    editing.value = null
}
async function remove(asset: ImageAsset) {
  if (
    !(await confirmAction(
      `Permanently delete “${asset.name}”? This removes its files and cannot be undone. Images used by saved labels cannot be deleted.`,
    ))
  )
    return
  if (
    await w.action(
      () => api(`/image-assets/${asset.id}/permanent`, 'DELETE'),
      'Image permanently deleted.',
    )
  ) {
    if (editing.value === asset.id) editing.value = null
  }
}
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
  <section v-if="auth.can('assets.write')" class="panel form-stack">
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
      original artwork and their own brightness and contrast settings. Unused images can be
      permanently deleted. Click a preview to enlarge it.
    </p>
    <p v-if="!w.images.value.length" class="empty">Upload your first image to get started.</p>
    <div v-else class="table-scroll">
      <table class="image-library-table">
        <thead>
          <tr>
            <th>Preview</th>
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
              <button
                class="image-thumbnail"
                :aria-label="`Preview ${asset.name}`"
                @click="showPreview(asset)"
              >
                <img
                  :src="`/api/image-assets/${asset.id}/preview`"
                  alt=""
                  loading="lazy"
                  width="120"
                  height="80"
                />
              </button>
            </td>
            <td>
              <form
                v-if="editing === asset.id"
                class="image-rename"
                @submit.prevent="rename(asset)"
                @keydown.esc.prevent="editing = null"
              >
                <label
                  >Image name<input
                    ref="renameInput"
                    v-model="imageName"
                    maxlength="120"
                    required
                    :disabled="w.busy.value"
                /></label>
                <div class="row wrap">
                  <button class="small primary" :disabled="w.busy.value || !imageName.trim()">
                    Save name
                  </button>
                  <button
                    type="button"
                    class="small secondary"
                    :disabled="w.busy.value"
                    @click="editing = null"
                  >
                    Cancel
                  </button>
                </div>
              </form>
              <template v-else>{{ asset.name }}</template>
              <small>{{ asset.id.slice(0, 12) }}</small>
            </td>
            <td>{{ asset.kind === 'svg' ? 'SVG' : 'Bitmap' }}</td>
            <td>{{ asset.width }} × {{ asset.height }}</td>
            <td>{{ asset.archived ? 'Hidden' : 'Available' }}</td>
            <td>
              <div
                v-if="
                  auth.can('assets.write') &&
                  (asset.can_edit ??
                    (auth.user.value?.is_admin || asset.owner_id === auth.user.value?.id))
                "
                class="image-library-actions"
              >
                <button
                  class="small secondary"
                  :disabled="w.busy.value || editing === asset.id"
                  @click="startRename(asset)"
                >
                  Rename
                </button>
                <button class="small secondary" :disabled="w.busy.value" @click="visibility(asset)">
                  {{ asset.archived ? 'Restore' : 'Hide' }}
                </button>
                <button
                  class="small secondary danger-text"
                  :disabled="w.busy.value"
                  @click="remove(asset)"
                >
                  Delete
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <RouterLink class="button secondary open-templates" to="/templates">Open templates</RouterLink>
  </section>
  <Teleport to="body">
    <dialog
      ref="previewDialog"
      class="image-preview-dialog"
      aria-labelledby="image-preview-title"
      @close="preview = null"
    >
      <template v-if="preview">
        <div class="section-heading">
          <h2 id="image-preview-title">{{ preview.name }}</h2>
          <button class="secondary" autofocus @click="previewDialog?.close()">Close</button>
        </div>
        <p v-if="previewFailed" class="alert danger" role="alert">
          Could not load this image preview.
        </p>
        <img
          v-else
          class="image-enlarged-preview"
          :src="`/api/image-assets/${preview.id}/preview?size=large`"
          :alt="preview.name"
          @error="previewFailed = true"
        />
        <p class="help">
          {{ preview.width }} × {{ preview.height }} px · Original artwork. Print conversion is set
          per template.
        </p>
      </template>
    </dialog>
  </Teleport>
</template>
<style scoped>
.open-templates {
  margin-top: 18px;
}
.image-library-table {
  min-width: 680px;
}
.image-library-table td:nth-child(2) {
  min-width: 180px;
  max-width: 300px;
  overflow-wrap: anywhere;
}
.image-thumbnail,
.image-enlarged-preview {
  background-color: #fff;
  background-image: conic-gradient(#e5e7eb 25%, #fff 0 50%, #e5e7eb 0 75%, #fff 0);
  background-size: 16px 16px;
}
.image-thumbnail {
  display: block;
  padding: 0;
  overflow: hidden;
}
.image-thumbnail img {
  display: block;
  object-fit: contain;
}
.image-library-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.image-rename {
  display: grid;
  gap: 10px;
}
.image-preview-dialog {
  width: min(1000px, calc(100vw - 40px));
  max-height: calc(100vh - 40px);
  padding: 24px;
  border: 1px solid var(--border-strong);
  border-radius: 12px;
  background: var(--surface);
  color: var(--ink);
  box-shadow: 0 24px 80px #0008;
}
.image-preview-dialog::backdrop {
  background: #030712b3;
  backdrop-filter: blur(3px);
}
.image-preview-dialog h2 {
  overflow-wrap: anywhere;
  min-width: 0;
}
.image-enlarged-preview {
  display: block;
  width: 100%;
  height: min(60vh, 600px);
  object-fit: contain;
  border-radius: 6px;
}
.image-preview-dialog .help {
  margin-top: 16px;
}
</style>
