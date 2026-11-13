<script setup lang="ts">
import { t } from '../shared/i18n'

import { computed, nextTick, reactive, ref, watch } from 'vue'
import type { Template } from '../shared/types'
import { useAuthStore } from '../auth/auth'
import {
  compareTemplateNames,
  matchesTemplateSearch,
  recentTemplates,
  rememberTemplate,
} from '../templates/templateBrowser'
import { templateLength } from '../templates/templateDimensions'
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
    ? (item.group_name ?? t('assetScopeFields.group'))
    : item.scope === 'personal'
      ? t('common.personal')
      : t('common.global')
</script>

<template>
  <div class="template-choice">
    <span class="template-choice-label">{{ $t('common.template') }}</span>
    <div class="template-choice-summary">
      <TemplatePreview v-if="selected" :template="selected" />
      <div class="template-choice-description">
        <strong>{{ selected?.name ?? $t('uiMessages.chooseATemplate') }}</strong>
        <span v-if="selected?.owner_id && selected.owner_id !== auth.user?.id" class="muted">{{
          selected.owner_username || $t('uiMessages.unavailableUser')
        }}</span>
        <span v-if="selected" class="muted"
          >{{ selected.document.width_mm }} {{ $t('common.mm2') }} {{ templateLength(selected) }}
          {{ $t('common.revision3') }} {{ selected.revision }}</span
        >
        <button
          type="button"
          :value="modelValue"
          class="secondary"
          aria-haspopup="dialog"
          @click="show"
        >
          {{ $t('templatePicker.changeTemplate') }}
        </button>
      </div>
    </div>
  </div>
  <Teleport to="body">
    <AdminDialog
      :open="open"
      :title="$t('templatePicker.chooseTemplate')"
      wide
      class="template-picker"
      @close="open = false"
    >
      <div class="picker-body">
        <div class="picker-filters">
          <label class="picker-search"
            >{{ $t('common.searchTemplates')
            }}<input
              v-model="filters.search"
              type="search"
              :placeholder="$t('common.nameFieldOrGroup')"
              @keydown.esc.prevent.stop="open = false"
          /></label>
          <label
            >{{ $t('common.visibility')
            }}<select v-model="filters.scope">
              <option value="">{{ $t('common.all') }}</option>
              <option value="personal">{{ $t('common.personal') }}</option>
              <option value="group">{{ $t('templatePicker.groups') }}</option>
              <option value="global">{{ $t('common.global') }}</option>
            </select></label
          >
          <label
            >{{ $t('common.tapeWidth')
            }}<select v-model="filters.width">
              <option value="">{{ $t('common.allWidths') }}</option>
              <option v-for="width in widths" :key="width" :value="String(width)">
                {{ width }} {{ $t('common.mm') }}
              </option>
            </select></label
          >
          <label
            >{{ $t('common.media')
            }}<select v-model="filters.media">
              <option value="">{{ $t('common.allMedia') }}</option>
              <option value="tze">{{ $t('common.continuousTze') }}</option>
              <option value="fixed_label">{{ $t('common.fixedLabels') }}</option>
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
            {{ $t('common.showOthersPersonalTemplates') }}
          </button>
          <label class="checkbox"
            ><input v-model="filters.compatible" type="checkbox" />{{
              $t('templatePicker.compatibleWithDestination')
            }}</label
          >
          <button
            type="button"
            class="text-button"
            :disabled="!activeFilters"
            @click="clearFilters"
          >
            {{ $t('common.clearFilters') }}
          </button>
        </div>
        <div class="picker-meta" role="status" aria-live="polite" aria-atomic="true">
          {{ filtered.length }} {{ filtered.length === 1 ? 'template' : 'templates' }}
        </div>
        <div
          ref="results"
          class="picker-results"
          role="region"
          :aria-label="$t('common.templateResults')"
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
                  :aria-label="$t('uiDetails.use', { value1: String(item.name) })"
                  :aria-pressed="modelValue === item.id"
                  @click="choose(item)"
                >
                  {{ item.name }}
                </button>
                <span v-if="item.owner_id && item.owner_id !== auth.user?.id" class="muted">{{
                  item.owner_username || $t('uiMessages.unavailableUser')
                }}</span>
                <span class="muted"
                  >{{ item.document.width_mm }} {{ $t('common.mm2') }}
                  {{ templateLength(item) }}</span
                >
                <div class="picker-card-meta">
                  <span
                    >{{ scopeName(item) }} ·
                    {{
                      item.document.media?.media_family === 'fixed_label'
                        ? $t('common.fixedLabels')
                        : 'TZe'
                    }}</span
                  ><span v-if="recent.includes(item.id)" class="picker-recent">{{
                    $t('templatePicker.recent')
                  }}</span>
                </div>
              </article>
            </div>
            <p v-else class="picker-empty">{{ $t('templatePicker.noMatchingTemplates') }}</p>
          </MotionSurface>
        </div>
        <nav class="picker-pagination" :aria-label="$t('common.templatePages')">
          <button type="button" class="secondary" :disabled="page === 0" @click="page--">
            {{ $t('common.previous') }}
          </button>
          <span>{{ $t('common.page') }} {{ page + 1 }} {{ $t('common.of') }} {{ pages }}</span>
          <button type="button" class="secondary" :disabled="page + 1 >= pages" @click="page++">
            {{ $t('common.next') }}
          </button>
        </nav>
      </div>
    </AdminDialog>
  </Teleport>
</template>

<style scoped src="./picker.css"></style>
