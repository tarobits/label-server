<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from 'vue'
import type { Template } from '../types'
import { useAuthStore } from '../auth'
import {
  compareTemplateNames,
  matchesTemplateSearch,
  recentTemplates,
  rememberTemplate,
} from '../templateBrowser'
import { templateLength } from '../templateDimensions'
import AdminDialog from './AdminDialog.vue'
import TemplatePreview from './TemplatePreview.vue'
import MotionSurface from './MotionSurface.vue'

const props = defineProps<{
  modelValue: string
  templates: Template[]
  compatible: (template: Template) => boolean
}>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const auth = useAuthStore()
const open = ref(false)
const selected = computed(() => props.templates.find((item) => item.id === props.modelValue))
const filters = reactive({ search: '', scope: '', width: '', media: '', compatible: false })
const recent = ref<string[]>([])
const page = ref(0)
const pageSize = 12
const results = ref<HTMLElement | null>(null)
const widths = computed(() =>
  [...new Set(props.templates.map((item) => item.document.width_mm))].sort((a, b) => a - b),
)
const filtered = computed(() =>
  props.templates
    .filter(
      (item) =>
        matchesTemplateSearch(item, filters.search) &&
        (!filters.scope || (item.scope ?? 'global') === filters.scope) &&
        (!filters.width || item.document.width_mm === Number(filters.width)) &&
        (!filters.media || (item.document.media?.media_family ?? 'tze') === filters.media) &&
        (!filters.compatible || props.compatible(item)),
    )
    .sort((a, b) => {
      const rank = (item: Template) => {
        const index = recent.value.indexOf(item.id)
        return index < 0 ? recent.value.length : index
      }
      return rank(a) - rank(b) || compareTemplateNames(a, b)
    }),
)
const pages = computed(() => Math.max(1, Math.ceil(filtered.value.length / pageSize)))
const visible = computed(() =>
  filtered.value.slice(page.value * pageSize, (page.value + 1) * pageSize),
)
const activeFilters = computed(() => Object.values(filters).some(Boolean))
const identity = computed(() => JSON.stringify([filters, page.value]))
watch(filters, () => {
  page.value = 0
})
watch(pages, (count) => {
  page.value = Math.min(page.value, count - 1)
})
watch(identity, async () => {
  await nextTick()
  results.value?.scrollTo({ top: 0 })
})
watch(
  () => auth.user?.id,
  () => {
    recent.value = recentTemplates(auth.user?.id)
  },
)
function show(event: MouseEvent) {
  ;(event.currentTarget as HTMLElement).focus()
  recent.value = recentTemplates(auth.user?.id)
  open.value = true
}
function choose(item: Template) {
  rememberTemplate(auth.user?.id, item.id)
  emit('update:modelValue', item.id)
  open.value = false
}
function clearFilters() {
  Object.assign(filters, { search: '', scope: '', width: '', media: '', compatible: false })
}
const scopeName = (item: Template) =>
  item.scope === 'group'
    ? (item.group_name ?? 'Group')
    : item.scope === 'personal'
      ? 'Personal'
      : 'Global'
</script>

<template>
  <div class="template-choice">
    <span class="template-choice-label">Template</span>
    <div class="template-choice-summary">
      <TemplatePreview v-if="selected" :template="selected" />
      <div class="template-choice-description">
        <strong>{{ selected?.name ?? 'Choose a template' }}</strong>
        <span v-if="selected" class="muted"
          >{{ selected.document.width_mm }} mm · {{ templateLength(selected) }} · revision
          {{ selected.revision }}</span
        >
        <button
          type="button"
          :value="modelValue"
          class="secondary"
          aria-haspopup="dialog"
          @click="show"
        >
          Change template
        </button>
      </div>
    </div>
  </div>
  <Teleport to="body">
    <AdminDialog
      :open="open"
      title="Choose template"
      wide
      class="template-picker"
      @close="open = false"
    >
      <div class="picker-body">
        <div class="picker-filters">
          <label class="picker-search"
            >Search templates<input
              v-model="filters.search"
              type="search"
              placeholder="Name, field, or group"
              @keydown.esc.prevent.stop="open = false"
          /></label>
          <label
            >Visibility<select v-model="filters.scope">
              <option value="">All</option>
              <option value="personal">Personal</option>
              <option value="group">Groups</option>
              <option value="global">Global</option>
            </select></label
          >
          <label
            >Tape width<select v-model="filters.width">
              <option value="">All widths</option>
              <option v-for="width in widths" :key="width" :value="String(width)">
                {{ width }} mm
              </option>
            </select></label
          >
          <label
            >Media<select v-model="filters.media">
              <option value="">All media</option>
              <option value="tze">Continuous TZe</option>
              <option value="fixed_label">Fixed labels</option>
            </select></label
          >
        </div>
        <div class="picker-options">
          <label class="checkbox"
            ><input v-model="filters.compatible" type="checkbox" />Compatible with
            destination</label
          >
          <button
            type="button"
            class="text-button"
            :disabled="!activeFilters"
            @click="clearFilters"
          >
            Clear filters
          </button>
        </div>
        <div class="picker-meta" role="status" aria-live="polite" aria-atomic="true">
          {{ filtered.length }} {{ filtered.length === 1 ? 'template' : 'templates' }}
        </div>
        <div
          ref="results"
          class="picker-results"
          role="region"
          aria-label="Template results"
          tabindex="0"
        >
          <MotionSurface :identity="identity" :order="page">
            <div v-if="visible.length" class="picker-grid">
              <article
                v-for="item in visible"
                :key="item.id"
                class="picker-card"
                :class="{ selected: modelValue === item.id }"
                :data-template-id="item.id"
              >
                <TemplatePreview :template="item" />
                <button
                  type="button"
                  class="picker-select"
                  :aria-label="`Use ${item.name}`"
                  :aria-pressed="modelValue === item.id"
                  @click="choose(item)"
                >
                  {{ item.name }}
                </button>
                <span class="muted"
                  >{{ item.document.width_mm }} mm · {{ templateLength(item) }}</span
                >
                <div class="picker-card-meta">
                  <span
                    >{{ scopeName(item) }} ·
                    {{
                      item.document.media?.media_family === 'fixed_label' ? 'Fixed labels' : 'TZe'
                    }}</span
                  ><span v-if="recent.includes(item.id)" class="picker-recent">Recent</span>
                </div>
              </article>
            </div>
            <p v-else class="picker-empty">No matching templates.</p>
          </MotionSurface>
        </div>
        <nav class="picker-pagination" aria-label="Template pages">
          <button type="button" class="secondary" :disabled="page === 0" @click="page--">
            Previous
          </button>
          <span>Page {{ page + 1 }} of {{ pages }}</span>
          <button type="button" class="secondary" :disabled="page + 1 >= pages" @click="page++">
            Next
          </button>
        </nav>
      </div>
    </AdminDialog>
  </Teleport>
</template>

<style scoped>
.template-choice {
  display: grid;
  gap: 8px;
}
.template-choice-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-label);
}
.template-choice-summary {
  display: flex;
  align-items: center;
  gap: 16px;
}
.template-choice-summary > .template-preview {
  width: 120px;
  height: 80px;
  flex-shrink: 0;
  margin: 0;
}
.template-choice-description {
  display: grid;
  justify-items: start;
  gap: 8px;
  min-width: 0;
}
.template-choice-description strong {
  overflow-wrap: anywhere;
}
.template-choice-description button {
  min-height: 44px;
  margin-top: 4px;
}
.template-picker :deep(.admin-dialog-body) {
  padding: 0;
}
.picker-body {
  display: flex;
  flex-direction: column;
  height: min(700px, calc(100dvh - 113px));
  padding: 20px 24px;
  gap: 12px;
}
.picker-filters {
  display: grid;
  grid-template-columns: 2fr repeat(3, 1fr);
  gap: 12px;
}
.picker-filters label {
  min-width: 0;
}
.picker-options,
.picker-card-meta,
.picker-pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.picker-options {
  flex-wrap: wrap;
}
.picker-meta {
  color: var(--muted);
  font-size: 12px;
}
.picker-results {
  min-height: 0;
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  overscroll-behavior: contain;
  padding: 4px;
}
.picker-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}
.picker-card {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 8px;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
}
.picker-card.selected {
  border-color: var(--accent-hover);
}
.picker-card:has(.picker-select:hover) {
  border-color: var(--border-strong);
}
.picker-card:has(.picker-select:focus-visible) {
  outline: 2px solid var(--accent-hover);
  outline-offset: 2px;
}
.picker-card > .template-preview {
  height: 84px;
  margin: 0 0 4px;
}
.picker-select {
  display: block;
  padding: 0;
  border: 0;
  background: transparent;
  text-align: left;
  font-weight: 600;
  color: var(--ink);
  overflow-wrap: anywhere;
}
.picker-select:not(:disabled):hover {
  background: transparent;
}
.picker-select::after {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: 8px;
}
.picker-select:focus-visible {
  outline: none;
}
.picker-card :deep(.preview-error button) {
  position: relative;
  z-index: 1;
}
.picker-card-meta {
  margin-top: auto;
  align-items: start;
  color: var(--muted);
  font-size: 12px;
  overflow-wrap: anywhere;
}
.picker-recent {
  flex-shrink: 0;
  color: var(--text-secondary);
}
.picker-empty {
  padding: 32px 16px;
  text-align: center;
}
.picker-pagination {
  flex-shrink: 0;
  border-top: 1px solid var(--line);
  padding-top: 12px;
}
.picker-pagination button {
  min-height: 44px;
}
.picker-pagination span {
  color: var(--muted);
  font-size: 12px;
}
@media (max-width: 700px) {
  .picker-body {
    padding: 16px;
  }
  .picker-filters {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
  .picker-search {
    grid-column: 1 / -1;
  }
  .picker-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (max-width: 450px) {
  .picker-filters {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .picker-filters > label:last-child {
    grid-column: 1 / -1;
  }
  .picker-grid {
    grid-template-columns: minmax(0, 1fr);
  }
  .template-choice-summary > .template-preview {
    width: 88px;
  }
}
</style>
