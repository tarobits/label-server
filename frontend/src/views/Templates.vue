<script setup lang="ts">
import { freezeLeavingItem } from '../collectionMotion'
import { confirmAction } from '../confirmation'
import { computed, reactive, watch } from 'vue'
import { useRoute, useRouter, type LocationQuery } from 'vue-router'
import { api } from '../api'
import { useAuthStore } from '../auth'
import type { Template } from '../types'
import { useWorkspaceStore } from '../workspace'
import TemplatePreview from '../components/TemplatePreview.vue'
import MotionTrack from '../components/MotionTrack.vue'
import MotionSurface from '../components/MotionSurface.vue'
import ExpandableContent from '../components/ExpandableContent.vue'
const w = useWorkspaceStore()
const auth = useAuthStore()
const router = useRouter()
const route = useRoute()
const scopes = [
  { id: 'all', label: 'All' },
  { id: 'personal', label: 'Personal', heading: 'Personal templates' },
  { id: 'group', label: 'Groups', heading: 'Group templates' },
  { id: 'global', label: 'Global', heading: 'Global templates' },
] as const
type Scope = (typeof scopes)[number]['id']
function readFilters(query: LocationQuery) {
  const text = (key: string) => (typeof query[key] === 'string' ? query[key] : '')
  const scope = scopes.some((item) => item.id === text('scope')) ? (text('scope') as Scope) : 'all'
  return {
    scope,
    search: text('q'),
    width: /^\d+(?:\.\d+)?$/.test(text('width')) && Number(text('width')) > 0 ? text('width') : '',
    group: scope === 'group' ? text('group') : '',
  }
}
const filters = reactive(readFilters(route.query))
watch(
  () => route.query,
  (query) => Object.assign(filters, readFilters(query)),
)
watch(filters, () => {
  const query = {
    ...route.query,
    q: filters.search || undefined,
    scope: filters.scope === 'all' ? undefined : filters.scope,
    width: filters.width || undefined,
    group: filters.scope === 'group' ? filters.group || undefined : undefined,
  }
  if (
    ['q', 'scope', 'width', 'group'].some(
      (key) => (route.query[key] || undefined) !== query[key as keyof typeof query],
    )
  )
    void router.replace({ query })
})
function selectScope(scope: Scope) {
  filters.scope = scope
  filters.group = ''
}
function clearFilters() {
  Object.assign(filters, { scope: 'all', search: '', width: '', group: '' })
}
const activeFilters = computed(
  () => filters.scope !== 'all' || !!filters.search || !!filters.width || !!filters.group,
)
const normalize = (value: string) =>
  value.normalize('NFKD').replace(/\p{M}/gu, '').toLocaleLowerCase()
const sorted = computed(() =>
  [...w.templates].sort(
    (a, b) =>
      a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' }) ||
      a.id.localeCompare(b.id),
  ),
)
const widths = computed(() =>
  [...new Set(w.templates.map((template) => template.document.width_mm))].sort((a, b) => a - b),
)
const groups = computed(() => {
  const names = new Map<string, string>()
  for (const template of sorted.value)
    if (template.scope === 'group' && template.group_id)
      names.set(template.group_id, template.group_name || 'Unnamed group')
  return [...names].map(([id, name]) => ({ id, name })).sort((a, b) => a.name.localeCompare(b.name))
})
const matching = computed(() => {
  const terms = normalize(filters.search).split(/\s+/).filter(Boolean)
  return sorted.value.filter((template) => {
    if (filters.width && template.document.width_mm !== Number(filters.width)) return false
    const text = normalize(
      [
        template.name,
        template.group_name ?? '',
        ...template.fields,
        ...template.document.fields.map((field) => field.label),
      ].join(' '),
    )
    return terms.every((term) => text.includes(term))
  })
})
const scopeCount = (scope: Scope) =>
  matching.value.filter((template) => scope === 'all' || (template.scope ?? 'global') === scope)
    .length
const sections = computed(() =>
  scopes
    .filter((scope) => scope.id !== 'all')
    .map((scope) => ({
      ...scope,
      templates: matching.value.filter(
        (template) =>
          (template.scope ?? 'global') === scope.id &&
          (filters.scope === 'all' || filters.scope === scope.id) &&
          (filters.scope !== 'group' || !filters.group || template.group_id === filters.group),
      ),
    }))
    .filter((section) => section.templates.length),
)
const resultCount = computed(() =>
  sections.value.reduce((count, section) => count + section.templates.length, 0),
)
const entries = computed(() =>
  sections.value.flatMap((section) => [
    {
      id: `heading:${section.id}`,
      heading: section.heading,
      count: section.templates.length,
      template: null as Template | null,
    },
    ...section.templates.map((template) => ({ id: template.id, heading: '', count: 0, template })),
  ]),
)
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
async function remove(template: Template) {
  if (
    await confirmAction(
      `Delete “${template.name}”? It becomes unavailable immediately. Administrators can restore it for 30 days before permanent purging. Queued work using it is paused.`,
    )
  )
    await w.action(
      () => api(`/templates/${template.id}/permanent`, 'DELETE'),
      'Template deleted. Administrators can restore it within 30 days.',
    )
}
</script>
<template>
  <div class="template-browser">
    <div class="template-toolbar">
      <MotionTrack
        class="template-scopes"
        :identity="filters.scope"
        selector="[aria-pressed='true']"
        underline
        role="group"
        aria-label="Template visibility"
      >
        <button
          v-for="scope in scopes"
          :key="scope.id"
          type="button"
          :aria-pressed="filters.scope === scope.id"
          @click="selectScope(scope.id)"
        >
          {{ scope.label
          }}<span class="template-count" aria-hidden="true">{{ scopeCount(scope.id) }}</span>
        </button>
      </MotionTrack>
      <RouterLink v-if="auth.canCreateTemplates" class="button primary" to="/templates/new"
        >Create template</RouterLink
      >
    </div>
    <div class="template-filters">
      <label
        >Search templates<input
          v-model="filters.search"
          type="search"
          placeholder="Name, field, or group"
      /></label>
      <label
        >Tape width<select v-model="filters.width">
          <option value="">All widths</option>
          <option v-for="width in widths" :key="width" :value="String(width)">
            {{ width }} mm
          </option>
        </select></label
      >
    </div>
    <ExpandableContent :open="filters.scope === 'group'">
      <label class="template-group-filter"
        >Template group<select v-model="filters.group">
          <option value="">All groups</option>
          <option v-for="group in groups" :key="group.id" :value="group.id">
            {{ group.name }}
          </option>
        </select></label
      >
    </ExpandableContent>
    <div class="template-results-meta">
      <span role="status" aria-live="polite" aria-atomic="true"
        >{{ resultCount }} {{ resultCount === 1 ? 'template' : 'templates' }}</span
      >
      <Transition name="notice"
        ><button
          v-if="activeFilters"
          type="button"
          class="text-button motion-reveal"
          @click="clearFilters"
        >
          Clear filters
        </button></Transition
      >
    </div>
  </div>
  <MotionSurface
    :identity="filters.scope"
    :order="scopes.findIndex((scope) => scope.id === filters.scope)"
  >
    <TransitionGroup
      tag="div"
      class="card-grid"
      name="collection"
      @before-leave="freezeLeavingItem"
    >
      <template v-for="{ id, heading, count, template } in entries" :key="id">
        <header v-if="!template" class="template-section-heading">
          <h2>{{ heading }}</h2>
          <span class="template-count">{{ count }}</span>
        </header>
        <article v-else class="panel template-card">
          <TemplatePreview :template="template" />
          <div class="section-heading">
            <h3>{{ template.name }}</h3>
            <span class="badge">{{ template.document.width_mm }} mm</span>
          </div>
          <p>
            Revision {{ template.revision }} · {{ template.document.length_mm }} mm long ·
            {{ template.document.elements.length }} elements
          </p>
          <p class="help">Fields: {{ template.fields.join(', ') || 'No variable fields' }}</p>
          <p
            v-for="notice in template.asset_notices ?? []"
            :key="notice.kind + notice.id"
            class="alert warning"
          >
            {{ notice.message }}
          </p>
          <p v-if="template.scope === 'group'" class="template-group-name">
            {{ template.group_name || 'Group template' }}
          </p>
          <div class="row wrap">
            <RouterLink
              v-if="
                template.can_edit ?? (auth.user?.is_admin || template.owner_id === auth.user?.id)
              "
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
            <button
              v-if="auth.can('templates.create_personal')"
              :disabled="w.busy"
              class="text-button"
              @click="duplicate(template)"
            >
              Duplicate template</button
            ><button
              v-if="
                template.can_delete ?? (auth.user?.is_admin || template.owner_id === auth.user?.id)
              "
              :disabled="w.busy"
              class="text-button danger-text"
              @click="archive(template)"
            >
              Archive
            </button>
            <button
              v-if="
                auth.user?.is_admin ||
                (template.scope === 'global' && auth.can('templates.delete_global'))
              "
              :disabled="w.busy"
              class="text-button danger-text"
              @click="remove(template)"
            >
              Delete template
            </button>
          </div>
        </article>
      </template>
      <div v-if="!resultCount" key="empty" class="panel template-empty">
        <p>{{ activeFilters ? 'No matching templates.' : 'No templates yet.' }}</p>
      </div>
    </TransitionGroup>
  </MotionSurface>
</template>

<style scoped>
.template-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 16px;
  margin-bottom: 24px;
}
.template-scopes {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.template-scopes button {
  min-height: 44px;
  padding: 10px 14px;
  border: 0;
  border-bottom: 2px solid transparent;
  border-radius: 0;
  background: transparent;
  color: var(--text-secondary);
}
.template-scopes button:hover {
  background: var(--overlay);
}
.template-scopes button[aria-pressed='true'] {
  color: var(--ink);
  border-bottom-color: var(--accent-hover);
}
.template-scopes.motion-track-ready button[aria-pressed='true'] {
  border-bottom-color: transparent;
}
.template-count {
  color: var(--muted);
  font-size: 12px;
  font-weight: 500;
  font-variant-numeric: tabular-nums;
}
.template-filters {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(140px, 200px);
  gap: 16px;
}
.template-group-filter {
  margin-top: 16px;
  max-width: 320px;
}
.template-results-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 36px;
  margin-top: 12px;
  margin-bottom: 20px;
  color: var(--muted);
  font-size: 13px;
}
.template-section-heading {
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  gap: 12px;
}
.template-section-heading:not(:first-child) {
  margin-top: 12px;
}
.template-section-heading.collection-leave-active {
  margin-top: 0;
}
.template-card h3 {
  font-size: 17px;
}
.template-card .template-group-name {
  color: var(--text-secondary);
}
.template-empty {
  grid-column: 1 / -1;
  text-align: center;
  padding: 36px 24px;
}
@media (max-width: 600px) {
  .template-toolbar {
    align-items: stretch;
  }
  .template-scopes {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    width: 100%;
  }
  .template-toolbar > .button {
    margin-left: auto;
  }
  .template-filters {
    grid-template-columns: minmax(0, 1fr);
  }
  .template-group-filter {
    max-width: none;
  }
}
</style>
