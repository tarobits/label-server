<script setup lang="ts">
import { t } from '../shared/i18n'
import { vValidateForm } from '../shared/formValidation'
import { nextTick, ref } from 'vue'
import { api } from '../shared/api'
import { useAuthStore } from '../auth/auth'
import { confirmAction } from '../shared/confirmation'
import { useWorkspaceStore } from '../shared/workspace'
import type { ImageAsset } from '../shared/types'
import AssetUpload from '../components/AssetUpload.vue'
import AssetSharingEditor from '../components/AssetSharingEditor.vue'
import ImageAssetPreview from '../components/ImageAssetPreview.vue'
const w = useWorkspaceStore()
const auth = useAuthStore()
const editing = ref<string | null>(null),
  imageName = ref(''),
  renameInput = ref<HTMLInputElement[]>([]),
  preview = ref<ImageAsset | null>(null),
  previewDialog = ref<HTMLDialogElement | null>(null)

async function showPreview(asset: ImageAsset) {
  preview.value = asset
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
      t('uiMessages.imageRenamed'),
    )
  )
    editing.value = null
}
async function remove(asset: ImageAsset) {
  if (
    !(await confirmAction(
      t('uiDetails.deleteImage', {
        value1: String(asset.name),
        value2: String(
          auth.user?.is_admin || (asset.scope === 'global' && auth.can('images.delete_global'))
            ? t(
                'uiMessages.templatesUsingItWillShowAMissingImagePlaceholderAndAffectedQueuedWorkIsPaused',
              )
            : t('uiMessages.imagesUsedBySavedLabelsCannotBeDeleted'),
        ),
      }),
    ))
  )
    return
  if (
    await w.action(
      () => api(`/image-assets/${asset.id}/permanent`, 'DELETE'),
      t('uiMessages.imageDeletedAdministratorsCanRestoreItWithin30Days'),
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
      ? t('uiMessages.imageRestoredToThePicker')
      : t('uiMessages.imageHiddenSavedLayoutsAndQueuedJobsRetainIt'),
  )
}
</script>
<template>
  <AssetUpload kind="images" />
  <section class="panel">
    <h2>{{ $t('images.imageLibrary') }}</h2>
    <p class="help">{{ $t('images.hiddenImagesRemainAvailableToSavedLabels') }}</p>
    <p v-if="!w.images.length" class="empty">{{ $t('images.noImagesUploaded') }}</p>
    <div v-else class="table-scroll">
      <table class="image-library-table">
        <thead>
          <tr>
            <th>{{ $t('common.preview') }}</th>
            <th>{{ $t('common.name') }}</th>
            <th v-if="auth.user?.is_admin">{{ $t('common.owner') }}</th>
            <th>{{ $t('images.format') }}</th>
            <th>{{ $t('images.dimensions') }}</th>
            <th>{{ $t('common.visibility') }}</th>
            <th>{{ $t('common.status') }}</th>
            <th>{{ $t('common.actions') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="asset in w.images" :key="asset.id">
            <td>
              <ImageAssetPreview :asset="asset" @enlarge="showPreview(asset)" />
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
                  >{{ $t('images.imageName')
                  }}<input
                    ref="renameInput"
                    v-model="imageName"
                    maxlength="120"
                    required
                    :disabled="w.busy"
                /></label>
                <div class="row wrap">
                  <button class="small primary" :disabled="w.busy || !imageName.trim()">
                    {{ $t('common.saveName') }}
                  </button>
                  <button
                    type="button"
                    class="small secondary"
                    :disabled="w.busy"
                    @click="editing = null"
                  >
                    {{ $t('common.cancel') }}
                  </button>
                </div>
              </form>
              <template v-else>{{ asset.name }}</template>
              <small>{{ asset.id.slice(0, 12) }}</small>
            </td>
            <td v-if="auth.user?.is_admin" class="asset-owner">
              {{ asset.owner_name ?? $t('uiMessages.unknownOwner') }}
            </td>
            <td>{{ asset.kind === 'svg' ? 'SVG' : $t('uiMessages.bitmap') }}</td>
            <td>{{ asset.width }} × {{ asset.height }}</td>
            <td>
              {{
                asset.scope === 'group'
                  ? asset.group_name
                  : asset.scope === 'global'
                    ? $t('common.global')
                    : $t('common.personal')
              }}
            </td>
            <td>{{ asset.archived ? $t('uiMessages.hidden') : $t('fonts.available') }}</td>
            <td>
              <div class="image-library-actions">
                <button
                  v-if="asset.can_edit"
                  class="small secondary"
                  :disabled="w.busy || editing === asset.id"
                  @click="startRename(asset)"
                >
                  {{ $t('common.rename') }}
                </button>
                <button
                  v-if="asset.archived ? asset.can_edit : asset.can_delete"
                  class="small secondary"
                  :disabled="w.busy"
                  @click="visibility(asset)"
                >
                  {{ asset.archived ? $t('administration.restore') : $t('uiMessages.hide') }}
                </button>
                <button
                  v-if="asset.can_delete"
                  class="small secondary danger-text"
                  :disabled="w.busy"
                  @click="remove(asset)"
                >
                  {{ $t('common.delete') }}
                </button>
              </div>
              <AssetSharingEditor v-if="asset.can_share" kind="images" :asset="asset" />
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <RouterLink class="button secondary open-templates" to="/templates">{{
      $t('common.openTemplates')
    }}</RouterLink>
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
          <button class="secondary" autofocus @click="previewDialog?.close()">
            {{ $t('common.close') }}
          </button>
        </div>
        <ImageAssetPreview :asset="preview" large />
        <p class="help">{{ preview.width }} × {{ preview.height }} {{ $t('common.px') }}</p>
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
.image-preview-dialog .help {
  margin-top: 16px;
}
</style>
