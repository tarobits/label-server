<script setup lang="ts">
import { api } from '../api'
import { useAuthStore } from '../auth'
import { confirmAction } from '../confirmation'
import { useWorkspaceStore } from '../workspace'
import type { FontAsset } from '../types'
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
      ? 'Font restored to the picker.'
      : 'Font hidden from the picker. Saved layouts and queued jobs retain it.',
  )
}
async function remove(font: FontAsset) {
  if (
    await confirmAction(
      `Delete “${font.family}”? It becomes unavailable immediately, including in saved templates. Administrators can restore it for 30 days before permanent purging. Fonts used by saved labels require administrator or global deletion permission.`,
    )
  )
    await w.action(
      () => api(`/font-assets/${font.id}/permanent`, 'DELETE'),
      'Font deleted. Administrators can restore it within 30 days.',
    )
}
</script>
<template>
  <AssetUpload kind="fonts" />
  <section class="panel">
    <h2>Font library</h2>
    <p class="help">Hidden fonts remain available to saved labels.</p>
    <div class="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Family</th>
            <th v-if="auth.user?.is_admin">Owner</th>
            <th>Face</th>
            <th>Size</th>
            <th>Visibility</th>
            <th>Status</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Noto Sans</td>
            <td v-if="auth.user?.is_admin">System</td>
            <td>Regular / Bold</td>
            <td>Bundled</td>
            <td>Global</td>
            <td>Available</td>
            <td>—</td>
          </tr>
          <tr v-for="font in w.fonts" :key="font.id">
            <td>
              {{ font.family }}<small>{{ font.id.slice(0, 12) }}</small>
            </td>
            <td v-if="auth.user?.is_admin" class="asset-owner">
              {{ font.owner_name ?? 'Unknown owner' }}
            </td>
            <td>{{ font.style }}</td>
            <td>{{ (font.size_bytes / 1024).toFixed(0) }} KB</td>
            <td>
              {{
                font.scope === 'group'
                  ? font.group_name
                  : font.scope === 'global'
                    ? 'Global'
                    : 'Personal'
              }}
            </td>
            <td>{{ font.archived ? 'Hidden' : 'Available' }}</td>
            <td>
              <button
                v-if="font.archived ? font.can_edit : font.can_delete"
                class="text-button"
                :disabled="w.busy"
                @click="visibility(font)"
              >
                {{ font.archived ? 'Restore' : 'Hide' }}
              </button>
              <button
                v-if="font.can_delete"
                class="text-button danger-text"
                :disabled="w.busy"
                @click="remove(font)"
              >
                Delete font
              </button>
              <AssetSharingEditor v-if="font.can_share" kind="fonts" :asset="font" />
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <RouterLink class="button secondary open-templates" to="/templates">Open templates</RouterLink>
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
