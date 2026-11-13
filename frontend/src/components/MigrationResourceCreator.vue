<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, errorMessage } from '../shared/api'

interface Field {
  key: string
  label: string
  type: string
  required?: boolean
  default?: string | number | boolean
  minlength?: number
  maxlength?: number
  min?: number
  max?: number
  step?: number
  resource?: string
  options?: { id: string; name: string }[]
}
interface Resource {
  label: string
  note?: string
  fields: Field[]
}
interface Draft {
  kind: string
  values: Record<string, string | number | boolean>
  reason: string
  returnField?: string
}
const props = defineProps<{
  relationship: string
  token: string
  parent: string
  resources: Record<string, Resource>
}>()
const emit = defineEmits<{
  created: [value: { id: string; name: string }]
  cancel: []
  busy: [value: boolean]
}>()
const drafts = ref<Draft[]>([])
const draft = computed(() => drafts.value[drafts.value.length - 1]!)
const spec = computed(() => props.resources[draft.value.kind]!)
const choices = ref<Record<string, { id: string; name: string }[]>>({})
const searches = ref<Record<string, string>>({})
const busy = ref(false)
const transitioning = ref(false)
const error = ref('')
const receipt = ref<{ confirmation_token: string; name: string }>()
function start(kind: string, returnField?: string) {
  const values: Draft['values'] = {}
  for (const field of props.resources[kind]!.fields) values[field.key] = field.default ?? ''
  drafts.value.push({ kind, values, reason: '', returnField })
  receipt.value = undefined
  error.value = ''
  choices.value = {}
  searches.value = {}
}
start(props.parent)
async function action(fn: () => Promise<void>) {
  if (busy.value) return
  busy.value = true
  emit('busy', true)
  error.value = ''
  try {
    await fn()
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    busy.value = false
    emit('busy', false)
  }
}
async function search(field: Field) {
  choices.value[field.key] = await api(
    `/migration/relationships/creation/targets?key=${encodeURIComponent(props.relationship)}&kind=${encodeURIComponent(field.resource!)}&search=${encodeURIComponent(searches.value[field.key] || '')}`,
  )
}
async function loadChoices() {
  for (const field of spec.value.fields) if (field.resource) await search(field)
}
function nested(field: Field) {
  start(field.resource!, field.key)
  void action(loadChoices)
}
function back() {
  if (busy.value) return
  receipt.value = undefined
  error.value = ''
  if (drafts.value.length === 1) emit('cancel')
  else {
    drafts.value.pop()
    void action(loadChoices)
  }
}
function payload() {
  const values = Object.fromEntries(
    Object.entries(draft.value.values).filter(([, value]) => value !== ''),
  )
  return {
    key: props.relationship,
    token: props.token,
    kind: draft.value.kind,
    values,
    reason: draft.value.reason.trim(),
  }
}
async function submit() {
  let created: { id: string; name: string } | undefined
  await action(async () => {
    if (!receipt.value) {
      receipt.value = await api('/migration/relationships/creation/preview', 'POST', payload())
      return
    }
    const result = await api<{ id: string; name: string }>(
      '/migration/relationships/creation',
      'POST',
      payload(),
      { 'X-Access-Confirmation': receipt.value.confirmation_token },
    )
    if (drafts.value.length === 1) created = result
    else {
      const field = draft.value.returnField!
      drafts.value.pop()
      draft.value.values[field] = result.id
      receipt.value = undefined
      await loadChoices()
      if (!choices.value[field]?.some((item) => item.id === result.id))
        (choices.value[field] ??= []).push(result)
    }
  })
  // Finish the busy notification before the parent unmounts this form.
  if (created) emit('created', created)
}
onMounted(() => action(loadChoices))
function entered(element: Element) {
  transitioning.value = false
  element
    .querySelector<HTMLElement>(
      'input:not(:disabled), select:not(:disabled), textarea:not(:disabled)',
    )
    ?.focus()
}
</script>

<template>
  <form class="form-stack" @submit.prevent="submit">
    <h3>{{ $t('migrationResourceCreator.create') }} {{ spec.label.toLowerCase() }}</h3>
    <p v-if="spec.note" class="alert warning">{{ spec.note }}</p>
    <Transition
      name="panel-expand"
      mode="out-in"
      @before-leave="transitioning = true"
      @after-enter="entered"
    >
      <div v-if="receipt" key="review" class="form-stack">
        <p>
          {{ $t('migrationResourceCreator.create') }} <strong>{{ receipt.name }}</strong
          >?
        </p>
        <dl>
          <template
            v-for="field in spec.fields.filter((entry) => entry.type !== 'password')"
            :key="field.key"
          >
            <dt>{{ field.label }}</dt>
            <dd>
              {{
                choices[field.key]?.find((item) => item.id === draft.values[field.key])?.name ??
                field.options?.find((item) => item.id === draft.values[field.key])?.name ??
                (draft.values[field.key] === '' ? '—' : draft.values[field.key])
              }}
            </dd>
          </template>
          <dt>{{ $t('common.reason') }}</dt>
          <dd>{{ draft.reason }}</dd>
        </dl>
      </div>
      <div v-else :key="draft.kind" class="form-stack">
        <div v-for="field in spec.fields" :key="field.key" class="form-stack">
          <label v-if="field.type === 'checkbox'" class="checkbox"
            ><input v-model="draft.values[field.key]" type="checkbox" :disabled="busy" />{{
              field.label
            }}</label
          >
          <template v-else-if="field.resource">
            <div class="row wrap">
              <label
                >{{ $t('migrationResourceCreator.find') }} {{ field.label.toLowerCase()
                }}<input v-model="searches[field.key]" maxlength="128" :disabled="busy"
              /></label>
              <button
                type="button"
                class="secondary"
                :disabled="busy"
                @click="action(() => search(field))"
              >
                {{ $t('common.search') }}
              </button>
            </div>
            <label
              >{{ field.label
              }}<select
                v-model="draft.values[field.key]"
                :required="field.required"
                :disabled="busy"
              >
                <option value="" disabled>
                  {{ $t('common.choose') }} {{ field.label.toLowerCase() }}
                </option>
                <option v-for="item in choices[field.key] || []" :key="item.id" :value="item.id">
                  {{ item.name }} · {{ item.id }}
                </option>
              </select></label
            >
            <p v-if="choices[field.key]?.length === 50">
              {{ $t('common.showing50MatchesRefineTheSearchToFindAnother') }}
            </p>
            <button type="button" class="secondary" :disabled="busy" @click="nested(field)">
              {{ $t('migrationResourceCreator.create') }} {{ field.label.toLowerCase() }}
            </button>
          </template>
          <label v-else-if="field.type === 'select'"
            >{{ field.label
            }}<select v-model="draft.values[field.key]" :disabled="busy">
              <option v-for="item in field.options" :key="item.id" :value="item.id">
                {{ item.name }}
              </option>
            </select></label
          >
          <label v-else
            >{{ field.label }}
            <input
              v-if="field.type === 'number'"
              v-model.number="draft.values[field.key]"
              type="number"
              :min="field.min"
              :max="field.max"
              :step="field.step ?? 'any'"
              :required="field.required"
              :disabled="busy"
            />
            <input
              v-else
              v-model="draft.values[field.key]"
              :type="field.type"
              :minlength="field.minlength"
              :maxlength="field.maxlength"
              :required="field.required"
              :disabled="busy"
              :autocomplete="field.type === 'password' ? 'new-password' : 'off'"
            />
          </label>
        </div>
        <label
          >{{ $t('migrationResourceCreator.creationReason')
          }}<textarea v-model="draft.reason" required maxlength="500" :disabled="busy" />
        </label>
      </div>
    </Transition>
    <Transition name="notice"
      ><p v-if="error" class="alert danger" role="alert">{{ error }}</p></Transition
    >
    <div class="row wrap">
      <button type="submit" :disabled="busy || transitioning || !draft.reason.trim()">
        {{ receipt ? $t('uiMessages.confirmCreation') : $t('uiMessages.reviewReplacement') }}
      </button>
      <button
        v-if="receipt"
        type="button"
        class="secondary"
        :disabled="busy || transitioning"
        @click="receipt = undefined"
      >
        {{ $t('migrationResourceCreator.editDetails') }}
      </button>
      <button type="button" class="secondary" :disabled="busy || transitioning" @click="back">
        {{ $t('common.back') }}
      </button>
    </div>
  </form>
</template>

<style scoped>
dl {
  margin: 0;
}
dt {
  color: var(--muted);
}
dd {
  margin: 0 0 12px;
  overflow-wrap: anywhere;
}
.row {
  align-items: end;
}
.row label {
  flex: 1;
  min-width: 180px;
}
</style>
