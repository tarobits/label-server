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
const filters = reactive({
  search: '',
  scope: '',
  width: '',
  media: '',
  compatible: false,
  others: false,
})
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
        (!auth.user?.is_admin ||
          filters.others ||
          item.scope !== 'personal' ||
          item.owner_id === auth.user.id) &&
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
    filters.others = false
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
  Object.assign(filters, {
    search: '',
    scope: '',
    width: '',
    media: '',
    compatible: false,
    others: false,
  })
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
        <span v-if="selected?.owner_id && selected.owner_id !== auth.user?.id" class="muted">{{
          selected.owner_username || 'Unavailable user'
        }}</span>
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
          <button
            v-if="auth.user?.is_admin"
            type="button"
            class="secondary"
            :aria-pressed="filters.others"
            @click="filters.others = !filters.others"
          >
            Show others’ personal templates
          </button>
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
                <span v-if="item.owner_id && item.owner_id !== auth.user?.id" class="muted">{{
                  item.owner_username || 'Unavailable user'
                }}</span>
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

<style scoped src="./picker.css"></style>
