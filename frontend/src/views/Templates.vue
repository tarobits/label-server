<script setup lang="ts">
import { confirmAction } from '../confirmation'
import { useRouter } from 'vue-router'
import { api } from '../api'
import { useAuthStore } from '../auth'
import type { Template } from '../types'
import { useWorkspaceStore } from '../workspace'
const w = useWorkspaceStore()
const auth = useAuthStore()
const router = useRouter()
async function duplicate(template: Template) {
  let result: Template | undefined
  if (
    await w.action(async () => {
      result = await api<Template>('/templates', 'POST', {
        name: `${template.name} copy`,
        document: template.document,
        destination_id: w.selectedPrinter || undefined,
        scope: 'personal',
      })
    }, 'Template duplicated.')
  )
    await router.push(`/templates/${result!.id}/edit`)
}
async function archive(template: Template) {
  if (await confirmAction(`Archive “${template.name}”? Queued labels keep their saved revision.`))
    await w.action(
      () => api(`/templates/${template.id}`, 'DELETE'),
      'Template archived. Existing queued labels are unchanged.',
    )
}
</script>
<template>
  <div class="section-heading">
    <RouterLink class="button primary" to="/templates/new">Create template</RouterLink>
  </div>
  <div class="card-grid">
    <article v-for="template in w.templates" :key="template.id" class="panel">
      <div class="template-placeholder" aria-hidden="true"><span>Aa</span><i></i></div>
      <div class="section-heading">
        <h2>{{ template.name }}</h2>
        <span class="badge">{{ template.document.width_mm }} mm</span>
      </div>
      <p>
        Revision {{ template.revision }} · {{ template.document.length_mm }} mm long ·
        {{ template.document.elements.length }} elements
      </p>
      <p class="help">Fields: {{ template.fields.join(', ') || 'No variable fields' }}</p>
      <p class="help">
        {{
          template.scope === 'personal'
            ? 'Personal template'
            : template.scope === 'group'
              ? 'Shared with a user group'
              : 'Global template'
        }}
      </p>
      <div class="row wrap">
        <RouterLink
          v-if="template.can_edit ?? (auth.user?.is_admin || template.owner_id === auth.user?.id)"
          class="button primary"
          :to="`/templates/${template.id}/edit`"
          >Edit visually</RouterLink
        ><RouterLink
          v-if="auth.any('request')"
          class="button secondary"
          :to="{ path: '/new', query: { template: template.id } }"
          >Use template</RouterLink
        >
        <RouterLink
          v-if="auth.any('request')"
          class="button secondary"
          :to="{ path: '/runs', query: { template: template.id } }"
          >Use with CSV</RouterLink
        >
      </div>
      <div class="card-actions">
        <button :disabled="w.busy" class="text-button" @click="duplicate(template)">
          Duplicate template</button
        ><button
          v-if="template.can_delete ?? (auth.user?.is_admin || template.owner_id === auth.user?.id)"
          :disabled="w.busy"
          class="text-button danger-text"
          @click="archive(template)"
        >
          Archive
        </button>
      </div>
    </article>
  </div>
</template>
