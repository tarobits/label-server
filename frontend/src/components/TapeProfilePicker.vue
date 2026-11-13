<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from 'vue'
import type { Profile } from '../shared/types'
import { mediaLabel } from '../printing/media'
import AdminDialog from './AdminDialog.vue'
import MotionSurface from './MotionSurface.vue'

const props = defineProps<{
  modelValue: string
  profiles: Profile[]
  compatible?: (profile: Profile) => boolean
  disabled?: boolean
  compact?: boolean
  controlId?: string
  savedName?: string
}>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const open = ref(false)
const selected = computed(() => props.profiles.find((item) => item.id === props.modelValue))
const filters = reactive({ search: '', width: '', media: '', compatible: false })
const page = ref(0)
const results = ref<HTMLElement | null>(null)
const normalize = (value: string) =>
  value
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
    .toLocaleLowerCase()
const widths = computed(() =>
  [...new Set(props.profiles.map((item) => item.width_mm))].sort((a, b) => a - b),
)
const filtered = computed(() =>
  props.profiles
    .filter(
      (item) =>
        normalize(`${item.name} ${mediaLabel(item)}`).includes(normalize(filters.search.trim())) &&
        (!filters.width || item.width_mm === Number(filters.width)) &&
        (!filters.media || (item.media_family ?? 'tze') === filters.media) &&
        (!filters.compatible || !props.compatible || props.compatible(item)),
    )
    .sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true })),
)
const pages = computed(() => Math.max(1, Math.ceil(filtered.value.length / 12)))
const visible = computed(() => filtered.value.slice(page.value * 12, (page.value + 1) * 12))
const identity = computed(() => JSON.stringify([filters, page.value]))
const activeFilters = computed(() => Object.values(filters).some(Boolean))
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
  () => props.disabled,
  (disabled) => {
    if (disabled) open.value = false
  },
)
function show(event: MouseEvent) {
  ;(event.currentTarget as HTMLElement).focus()
  if (!props.disabled) open.value = true
}
function blocked(item: Profile) {
  return item.available === false || (props.compatible && !props.compatible(item))
}
function choose(item: Profile) {
  if (props.disabled || blocked(item)) return
  emit('update:modelValue', item.id)
  open.value = false
}
function clearFilters() {
  Object.assign(filters, { search: '', width: '', media: '', compatible: false })
}
</script>

<template>
  <div class="template-choice">
    <slot name="label"
      ><span class="template-choice-label">{{ $t('common.tapeProfile') }}</span></slot
    >
    <button
      v-if="compact"
      :id="controlId"
      type="button"
      class="secondary compact-profile"
      :value="modelValue"
      :disabled="disabled"
      :aria-label="$t('tapeProfilePicker.changeTapeProfile')"
      aria-haspopup="dialog"
      @click="show"
    >
      <span
        v-if="selected"
        class="swatch"
        :style="{ background: selected.background, color: selected.foreground }"
        aria-hidden="true"
        >{{ $t('common.aa') }}</span
      >
      <span
        >{{ selected?.name ?? savedName ?? $t('uiMessages.chooseATapeProfile')
        }}{{ selected?.available === false ? ' — Unavailable' : '' }}</span
      >
    </button>
    <div v-else class="template-choice-summary">
      <div
        v-if="selected"
        class="tape-swatch"
        :style="{ background: selected.background, color: selected.foreground }"
        aria-hidden="true"
      >
        {{ $t('common.aa') }}
      </div>
      <div class="template-choice-description">
        <strong>{{ selected?.name ?? $t('uiMessages.chooseATapeProfile') }}</strong>
        <span v-if="selected" class="muted">{{ mediaLabel(selected) }}</span>
        <span v-if="selected?.available === false" class="badge">{{
          $t('common.unavailable')
        }}</span>
        <button
          :id="controlId"
          type="button"
          :value="modelValue"
          class="secondary"
          :disabled="disabled"
          aria-haspopup="dialog"
          @click="show"
        >
          {{ $t('tapeProfilePicker.changeTapeProfile') }}
        </button>
      </div>
    </div>
  </div>
  <Teleport to="body">
    <AdminDialog
      :open="open"
      :title="$t('tapeProfilePicker.chooseTapeProfile')"
      wide
      class="template-picker"
      @close="open = false"
    >
      <div class="picker-body">
        <div class="picker-filters profile-filters">
          <label class="picker-search"
            >{{ $t('common.searchTapeProfiles')
            }}<input
              v-model="filters.search"
              type="search"
              :placeholder="$t('tapeProfilePicker.nameOrMedia')"
              @keydown.esc.prevent.stop="open = false"
          /></label>
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
          <label v-if="compatible" class="checkbox"
            ><input v-model="filters.compatible" type="checkbox" />{{
              $t('tapeProfilePicker.compatibleWithSelection')
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
          {{ filtered.length }} {{ filtered.length === 1 ? 'profile' : 'profiles' }}
        </div>
        <div
          ref="results"
          class="picker-results"
          role="region"
          :aria-label="$t('common.tapeProfileResults')"
          tabindex="0"
        >
          <MotionSurface :identity="identity" :order="page">
            <div v-if="visible.length" class="picker-grid">
              <article
                v-for="item in visible"
                :key="item.id"
                class="picker-card"
                :class="{ selected: modelValue === item.id }"
                :data-profile-id="item.id"
              >
                <div
                  class="tape-swatch"
                  :style="{ background: item.background, color: item.foreground }"
                  aria-hidden="true"
                >
                  {{ $t('common.aa') }}
                </div>
                <button
                  type="button"
                  class="picker-select"
                  :disabled="blocked(item)"
                  :aria-label="$t('uiDetails.use', { value1: String(item.name) })"
                  :aria-pressed="modelValue === item.id"
                  @click="choose(item)"
                >
                  {{ item.name }}
                </button>
                <span class="muted">{{ mediaLabel(item) }}</span>
                <span v-if="item.available === false" class="picker-card-meta">{{
                  $t('common.unavailable')
                }}</span>
                <span v-else-if="compatible && !compatible(item)" class="picker-card-meta">{{
                  $t('tapeProfilePicker.incompatibleWithSelection')
                }}</span>
              </article>
            </div>
            <p v-else class="picker-empty">{{ $t('tapeProfilePicker.noMatchingTapeProfiles') }}</p>
          </MotionSurface>
        </div>
        <nav class="picker-pagination" :aria-label="$t('common.tapeProfilePages')">
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
<style scoped>
.tape-swatch {
  display: grid;
  place-items: center;
  min-height: 64px;
  border-radius: 4px;
  border: 1px solid var(--line);
  font-size: 28px;
  font-weight: 600;
}
.template-choice-summary > .tape-swatch {
  width: 88px;
  flex-shrink: 0;
}
.compact-profile {
  display: flex;
  align-items: center;
  gap: 8px;
  text-align: left;
  width: 100%;
  min-height: 44px;
  overflow-wrap: anywhere;
}
.compact-profile .swatch {
  flex-shrink: 0;
}
.profile-filters {
  grid-template-columns: 2fr 1fr 1fr;
}
@media (max-width: 700px) {
  .profile-filters {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .profile-filters > label:last-child {
    grid-column: auto;
  }
}
</style>
