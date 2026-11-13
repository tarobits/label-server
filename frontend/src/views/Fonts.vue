<script setup lang="ts">
import { t } from '../shared/i18n'
import { api } from '../shared/api'
import { useAuthStore } from '../auth/auth'
import { confirmAction } from '../shared/confirmation'
import { useWorkspaceStore } from '../shared/workspace'
import type { FontAsset } from '../shared/types'
import AssetUpload from '../components/AssetUpload.vue'
import AssetSharingEditor from '../components/AssetSharingEditor.vue'
const w = useWorkspaceStore()
const auth = useAuthStore()
async function visibility(font: FontAsset) {
  await w.action(
    () =>
      api(
        `/font-assets/${font.id}${font.archived ? '/restore' : ''}`,
        font.archived ? 'POST' : 'DELETE',
      ),
    font.archived
      ? t('uiMessages.fontRestoredToThePicker')
      : t('uiMessages.fontHiddenFromThePickerSavedLayoutsAndQueuedJobsRetainIt'),
  )
}
async function remove(font: FontAsset) {
  if (await confirmAction(t('uiDetails.deleteFont', { value1: String(font.family) })))
    await w.action(
      () => api(`/font-assets/${font.id}/permanent`, 'DELETE'),
      t('uiMessages.fontDeletedAdministratorsCanRestoreItWithin30Days'),
    )
}
</script>
<template>
  <AssetUpload kind="fonts" />
  <section class="panel">
    <h2>{{ $t('fonts.fontLibrary') }}</h2>
    <p class="help">{{ $t('fonts.hiddenFontsRemainAvailableToSavedLabels') }}</p>
    <div class="table-scroll">
      <table>
        <thead>
          <tr>
            <th>{{ $t('fonts.family') }}</th>
            <th v-if="auth.user?.is_admin">{{ $t('common.owner') }}</th>
            <th>{{ $t('fonts.face') }}</th>
            <th>{{ $t('common.size') }}</th>
            <th>{{ $t('common.visibility') }}</th>
            <th>{{ $t('common.status') }}</th>
            <th>{{ $t('common.actions') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>{{ $t('common.notoSans') }}</td>
            <td v-if="auth.user?.is_admin">{{ $t('common.system') }}</td>
            <td>{{ $t('common.thinBlack100900') }}</td>
            <td>{{ $t('fonts.bundled') }}</td>
            <td>{{ $t('common.global') }}</td>
            <td>{{ $t('fonts.available') }}</td>
            <td>—</td>
          </tr>
          <tr v-for="font in w.fonts" :key="font.id">
            <td>
              {{ font.family }}<small>{{ font.id.slice(0, 12) }}</small>
            </td>
            <td v-if="auth.user?.is_admin" class="asset-owner">
              {{ font.owner_name ?? $t('uiMessages.unknownOwner') }}
            </td>
            <td>{{ font.variable ? $t('uiMessages.variable') : font.style }}</td>
            <td>{{ (font.size_bytes / 1024).toFixed(0) }} {{ $t('fonts.kb') }}</td>
            <td>
              {{
                font.scope === 'group'
                  ? font.group_name
                  : font.scope === 'global'
                    ? $t('common.global')
                    : $t('common.personal')
              }}
            </td>
            <td>{{ font.archived ? $t('uiMessages.hidden') : $t('fonts.available') }}</td>
            <td>
              <button
                v-if="font.archived ? font.can_edit : font.can_delete"
                class="text-button"
                :disabled="w.busy"
                @click="visibility(font)"
              >
                {{ font.archived ? $t('administration.restore') : $t('uiMessages.hide') }}
              </button>
              <button
                v-if="font.can_delete"
                class="text-button danger-text"
                :disabled="w.busy"
                @click="remove(font)"
              >
                {{ $t('fonts.deleteFont') }}
              </button>
              <AssetSharingEditor v-if="font.can_share" kind="fonts" :asset="font" />
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <RouterLink class="button secondary open-templates" to="/templates">{{
      $t('common.openTemplates')
    }}</RouterLink>
  </section>
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
</style>
