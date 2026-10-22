<script setup lang="ts">
import { computed, onBeforeUnmount, ref, useId, watch } from 'vue'
import { useAuthStore } from '../auth'
import { api, errorMessage } from '../api'
import { confirmAction } from '../confirmation'
import { useResourceStore } from '../stores/resources'
import { date, useWorkspaceStore } from '../workspace'
import type { Template, TemplateRevision } from '../types'
import { templateLength } from '../templateDimensions'
import AdminDialog from './AdminDialog.vue'
import MotionSurface from './MotionSurface.vue'

const props = defineProps<{
  open: boolean
  templateId: string
  templateName: string
  canRestore: boolean
  unsavedChanges?: boolean
}>()
const emit = defineEmits<{ close: []; restored: [template: Template] }>()
const auth = useAuthStore()
const resources = useResourceStore()
const workspace = useWorkspaceStore()
const previewId = useId()
const entries = ref<TemplateRevision[]>([])
const selectedNumber = ref(0)
const loading = ref(false)
const restoring = ref(false)
const historyError = ref('')
const previewError = ref('')
const restoreError = ref('')
interface RevisionPreview {
  png: string
  width_mm: number
  length_mm: number
  warnings: string[]
  missing_assets: Record<string, string>
}
const preview = ref<RevisionPreview | null>(null)
const previewLoading = ref(false)
const selected = computed(() =>
  entries.value.find((entry) => entry.revision === selectedNumber.value),
)
const currentRevision = computed(() => entries.value[0]?.revision ?? 0)
const path = computed(() => `/templates/${encodeURIComponent(props.templateId)}/revisions`)
let historyGeneration = 0
let previewGeneration = 0
let stopped = false

async function loadHistory() {
  const ticket = ++historyGeneration,
    actor = auth.user?.id,
    identifier = props.templateId
  loading.value = true
  historyError.value = ''
  restoreError.value = ''
  try {
    const result = await resources.get<TemplateRevision[]>(path.value, { force: true })
    if (
      stopped ||
      ticket !== historyGeneration ||
      !props.open ||
      actor !== auth.user?.id ||
      identifier !== props.templateId
    )
      return
    entries.value = result
    if (!result.some((entry) => entry.revision === selectedNumber.value))
      selectedNumber.value = result[0]?.revision ?? 0
  } catch (error) {
    if (!stopped && ticket === historyGeneration && props.open && actor === auth.user?.id)
      historyError.value = errorMessage(error)
  } finally {
    if (ticket === historyGeneration) loading.value = false
  }
}

async function loadPreview() {
  const number = selectedNumber.value,
    identifier = props.templateId,
    actor = auth.user?.id
  const ticket = ++previewGeneration
  preview.value = null
  previewError.value = ''
  previewLoading.value = false
  if (!props.open || !number) return
  previewLoading.value = true
  try {
    const result = await resources.get<RevisionPreview>(`${path.value}/${number}/preview`)
    if (
      !stopped &&
      props.open &&
      ticket === previewGeneration &&
      actor === auth.user?.id &&
      identifier === props.templateId
    )
      preview.value = result
  } catch (error) {
    if (!stopped && ticket === previewGeneration && props.open && actor === auth.user?.id)
      previewError.value = errorMessage(error)
  } finally {
    if (ticket === previewGeneration) previewLoading.value = false
  }
}

async function restoreSelected() {
  const entry = selected.value
  if (
    !entry ||
    !props.canRestore ||
    restoring.value ||
    workspace.busy ||
    entry.revision === currentRevision.value
  )
    return
  restoring.value = true
  restoreError.value = ''
  const identifier = props.templateId,
    expected = currentRevision.value,
    actor = auth.user?.id
  try {
    const accepted = await confirmAction(
      `Restore revision ${entry.revision} as a new revision?${props.unsavedChanges ? ' Unsaved editor changes will be discarded.' : ''}`,
      'Restore revision',
    )
    if (!accepted || !props.open || identifier !== props.templateId || actor !== auth.user?.id)
      return
    let result: Template | undefined
    const ok = await workspace.action(async () => {
      try {
        result = await api<Template>(`${path.value}/${entry.revision}/restore`, 'POST', {
          expected_revision: expected,
          destination_id: workspace.selectedPrinter || undefined,
        })
      } catch (error) {
        restoreError.value = errorMessage(error)
        throw error
      }
    }, `Revision ${entry.revision} restored as a new revision.`)
    if (
      !stopped &&
      ok &&
      result &&
      props.open &&
      identifier === props.templateId &&
      actor === auth.user?.id
    ) {
      emit('restored', result)
      emit('close')
    }
  } finally {
    restoring.value = false
  }
}

watch(
  [() => props.open, () => props.templateId],
  () => {
    historyGeneration++
    previewGeneration++
    if (!props.open) return
    entries.value = []
    selectedNumber.value = 0
    preview.value = null
    void loadHistory()
  },
  { immediate: true },
)
watch([selectedNumber, () => props.open, () => props.templateId], () => void loadPreview())
onBeforeUnmount(() => {
  stopped = true
  historyGeneration++
  previewGeneration++
})
</script>

<template>
  <Teleport to="body">
    <AdminDialog
      :open="open"
      :title="`History: ${templateName}`"
      :busy="restoring"
      wide
      @close="emit('close')"
    >
      <p v-if="loading" role="status">Loading revisions…</p>
      <div v-if="historyError" class="alert danger" role="alert">
        {{ historyError }}
        <button type="button" class="small secondary" @click="loadHistory">Retry</button>
      </div>
      <p v-if="!loading && !historyError && !entries.length">No saved revisions.</p>
      <div v-if="entries.length" class="revision-history">
        <ol class="revision-list" aria-label="Saved revisions">
          <li v-for="entry in entries" :key="entry.revision">
            <button
              type="button"
              :aria-label="`View revision ${entry.revision}`"
              :aria-pressed="selectedNumber === entry.revision"
              :aria-controls="previewId"
              :aria-current="entry.revision === currentRevision ? 'true' : undefined"
              :aria-describedby="`${previewId}-${entry.revision}-metadata`"
              :disabled="restoring || loading"
              @click="selectedNumber = entry.revision"
            >
              <span class="revision-label"
                >Revision {{ entry.revision
                }}<span v-if="entry.revision === currentRevision" class="badge">Current</span></span
              >
              <span :id="`${previewId}-${entry.revision}-metadata`" class="revision-metadata">
                <span>{{ entry.edited_by?.name || 'Editor not recorded' }}</span>
                <time
                  v-if="entry.created_at"
                  :datetime="new Date(entry.created_at * 1000).toISOString()"
                  >{{ date(entry.created_at) }}</time
                >
                <span v-if="entry.restored_from_revision"
                  >Restored from revision {{ entry.restored_from_revision }}</span
                >
              </span>
            </button>
          </li>
        </ol>
        <MotionSurface
          v-if="selected"
          :id="previewId"
          :identity="String(selectedNumber)"
          :order="-selectedNumber"
          class="revision-detail"
        >
          <h3>{{ selected.name }}</h3>
          <div class="revision-preview" :aria-busy="previewLoading">
            <img
              v-if="preview"
              class="motion-reveal"
              :src="preview.png"
              :alt="`Preview of revision ${selected.revision}`"
              :style="{ aspectRatio: `${preview.length_mm} / ${preview.width_mm}` }"
            />
            <p v-else-if="previewLoading" role="status">Loading preview…</p>
            <div v-else-if="previewError" class="alert warning" role="alert">
              {{ previewError }}
              <button type="button" class="small secondary" @click="loadPreview">
                Retry preview
              </button>
            </div>
          </div>
          <p class="revision-dimensions">
            {{ selected.document.width_mm }} mm wide · {{ templateLength(selected) }} ·
            {{ selected.document.elements.length }}
            {{ selected.document.elements.length === 1 ? 'element' : 'elements' }}
          </p>
          <p v-for="warning in preview?.warnings ?? []" :key="warning" class="alert warning">
            {{ warning }}
          </p>
          <p v-if="preview && Object.keys(preview.missing_assets).length" class="alert warning">
            Restore the missing assets before restoring this revision.
          </p>
          <p v-if="selected.document.fields.length" class="help">
            Fields: {{ selected.document.fields.map((field) => field.label).join(', ') }}
          </p>
        </MotionSurface>
      </div>
      <div v-if="restoreError" class="alert danger" role="alert">
        {{ restoreError }}
        <button type="button" class="small secondary" :disabled="restoring" @click="loadHistory">
          Reload history
        </button>
      </div>
      <div v-if="entries.length && canRestore" class="admin-actions">
        <button
          type="button"
          class="primary"
          :disabled="
            restoring ||
            loading ||
            workspace.busy ||
            !selected ||
            selected.revision === currentRevision ||
            !preview ||
            !!Object.keys(preview.missing_assets).length
          "
          @click="restoreSelected"
        >
          Restore revision {{ selected?.revision }}
        </button>
      </div>
    </AdminDialog>
  </Teleport>
</template>

<style scoped>
.revision-history {
  display: grid;
  grid-template-columns: minmax(180px, 240px) minmax(0, 1fr);
  gap: 24px;
}
.revision-list {
  list-style: none;
  padding: 7px;
  margin: -7px;
  display: grid;
  align-content: start;
  gap: 8px;
  max-height: 55vh;
  overflow: auto;
}
.revision-list button {
  display: grid;
  gap: 6px;
  justify-content: stretch;
  width: 100%;
  padding: 14px;
  text-align: left;
  background: transparent;
}
.revision-list button[aria-pressed='true'] {
  background: var(--surface-secondary);
  border-color: var(--accent-hover);
}
.revision-list button > span:not(.revision-label),
.revision-list time {
  font-size: 12px;
  color: var(--text-secondary);
  font-weight: 400;
  overflow-wrap: anywhere;
}
.revision-label {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.revision-detail {
  min-width: 0;
}
.revision-metadata {
  display: grid;
  gap: 6px;
}
.revision-preview {
  min-height: 220px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  margin-top: 16px;
  background: var(--surface-deepest);
  border-radius: 6px;
}
.revision-preview img {
  display: block;
  max-width: 100%;
  max-height: 300px;
  object-fit: contain;
  image-rendering: pixelated;
}
.revision-dimensions {
  margin: 12px 0;
  font-size: 12px;
}
@media (max-width: 600px) {
  .revision-history {
    grid-template-columns: minmax(0, 1fr);
    gap: 20px;
  }
  .revision-list {
    max-height: 200px;
  }
  .revision-preview {
    min-height: 150px;
  }
}
</style>
