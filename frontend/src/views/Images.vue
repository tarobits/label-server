<script setup lang="ts">
import { vValidateForm } from '../formValidation'
import { nextTick, ref } from 'vue'
import { api } from '../api'
import { useAuthStore } from '../auth'
import { confirmAction } from '../confirmation'
import { useWorkspaceStore } from '../workspace'
import type { ImageAsset } from '../types'
import AssetUpload from '../components/AssetUpload.vue'
import AssetSharingEditor from '../components/AssetSharingEditor.vue'
const w = useWorkspaceStore()
const auth = useAuthStore()
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
      `Delete “${asset.name}”? It becomes unavailable immediately. Administrators can restore it for 30 days before permanent purging. ${auth.user?.is_admin || (asset.scope === 'global' && auth.can('images.delete_global')) ? 'Templates using it will show a missing-image placeholder, and affected queued work is paused.' : 'Images used by saved labels cannot be deleted.'}`,
    ))
  )
    return
  if (
    await w.action(
      () => api(`/image-assets/${asset.id}/permanent`, 'DELETE'),
      'Image deleted. Administrators can restore it within 30 days.',
    )
  ) {
    if (editing.value === asset.id) editing.value = null
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
  <AssetUpload kind="images" />
  <section class="panel">
    <h2>Image library</h2>
    <p class="help">Hidden images remain available to saved labels.</p>
    <p v-if="!w.images.length" class="empty">No images uploaded.</p>
    <div v-else class="table-scroll">
      <table class="image-library-table">
        <thead>
          <tr>
            <th>Preview</th>
            <th>Name</th>
            <th v-if="auth.user?.is_admin">Owner</th>
            <th>Format</th>
            <th>Dimensions</th>
            <th>Visibility</th>
            <th>Status</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="asset in w.images" :key="asset.id">
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
                v-validate-form
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
                    :disabled="w.busy"
                /></label>
                <div class="row wrap">
                  <button class="small primary" :disabled="w.busy || !imageName.trim()">
                    Save name
                  </button>
                  <button
                    type="button"
                    class="small secondary"
                    :disabled="w.busy"
                    @click="editing = null"
                  >
                    Cancel
                  </button>
                </div>
              </form>
              <template v-else>{{ asset.name }}</template>
              <small>{{ asset.id.slice(0, 12) }}</small>
            </td>
            <td v-if="auth.user?.is_admin" class="asset-owner">
              {{ asset.owner_name ?? 'Unknown owner' }}
            </td>
            <td>{{ asset.kind === 'svg' ? 'SVG' : 'Bitmap' }}</td>
            <td>{{ asset.width }} × {{ asset.height }}</td>
            <td>
              {{
                asset.scope === 'group'
                  ? asset.group_name
                  : asset.scope === 'global'
                    ? 'Global'
                    : 'Personal'
              }}
            </td>
            <td>{{ asset.archived ? 'Hidden' : 'Available' }}</td>
            <td>
              <div class="image-library-actions">
                <button
                  v-if="asset.can_edit"
                  class="small secondary"
                  :disabled="w.busy || editing === asset.id"
                  @click="startRename(asset)"
                >
                  Rename
                </button>
                <button
                  v-if="asset.archived ? asset.can_edit : asset.can_delete"
                  class="small secondary"
                  :disabled="w.busy"
                  @click="visibility(asset)"
                >
                  {{ asset.archived ? 'Restore' : 'Hide' }}
                </button>
                <button
                  v-if="asset.can_delete"
                  class="small secondary danger-text"
                  :disabled="w.busy"
                  @click="remove(asset)"
                >
                  Delete
                </button>
              </div>
              <AssetSharingEditor v-if="asset.can_share" kind="images" :asset="asset" />
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
        <p class="help">{{ preview.width }} × {{ preview.height }} px</p>
      </template>
    </dialog>
  </Teleport>
</template>
<style scoped>
.asset-owner {
  min-width: 100px;
  max-width: 180px;
  overflow-wrap: anywhere;
}
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
