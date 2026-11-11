<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import { ChevronLeftIcon, ChevronRightIcon } from '@heroicons/vue/24/outline'
import type { PreviewExample, TemplateDocument, TemplateField, VariableValue } from '../editor'
import { randomUUID } from '../uuid'
import VariableInput from './VariableInput.vue'
import ExpandableContent from './ExpandableContent.vue'
import MotionSurface from './MotionSurface.vue'
import PropertySection from './PropertySection.vue'

const props = defineProps<{
  document: TemplateDocument
  modelValue: string
  disabled: boolean
}>()
const emit = defineEmits<{ 'update:modelValue': [id: string]; change: [] }>()
const examples = computed(() => props.document.preview_examples ?? [])
const index = computed(() => examples.value.findIndex((item) => item.id === props.modelValue))
const selected = computed(() => examples.value[index.value])
const displayed = shallowRef<PreviewExample>()
watch(
  selected,
  (example) => {
    if (example) displayed.value = example
  },
  { immediate: true },
)
function select(offset: number) {
  const next =
    index.value < 0
      ? offset < 0
        ? examples.value.length - 1
        : 0
      : (index.value + offset + examples.value.length) % examples.value.length
  if (examples.value[next]) emit('update:modelValue', examples.value[next]!.id)
}
function add(duplicate = false) {
  if (props.disabled || examples.value.length >= 50) return
  const data: Record<string, VariableValue> = Object.fromEntries(
    props.document.fields.map((field) => [field.name, sample(field)]),
  )
  const example = {
    id: randomUUID(),
    name:
      duplicate && selected.value
        ? `${selected.value.name.slice(0, 95)} copy`
        : `Example ${examples.value.length + 1}`,
    data: JSON.parse(JSON.stringify(duplicate && selected.value ? selected.value.data : data)),
  }
  props.document.preview_examples = [...examples.value, example]
  emit('update:modelValue', example.id)
  emit('change')
}
function remove() {
  if (props.disabled || !selected.value) return
  const position = index.value
  props.document.preview_examples = examples.value.filter((item) => item.id !== props.modelValue)
  emit('update:modelValue', examples.value[Math.min(position, examples.value.length - 1)]?.id ?? '')
  emit('change')
}
function value(name: string, value: VariableValue) {
  if (props.disabled || !selected.value) return
  selected.value.data[name] = value
}
function sample(field: TemplateField) {
  return props.document.version === 1
    ? field.sample || field.default
    : (field.sample ?? field.default)
}
</script>

<template>
  <section
    v-if="document.fields.length || examples.length"
    class="panel preview-inputs"
    aria-label="Preview inputs"
  >
    <PropertySection title="Preview inputs" initially-open>
      <div class="section-heading preview-actions">
        <div class="row wrap">
          <button
            type="button"
            class="secondary"
            :disabled="disabled || examples.length >= 50"
            @click="add()"
          >
            Add example
          </button>
          <button
            type="button"
            class="secondary"
            :disabled="disabled || !selected || examples.length >= 50"
            @click="add(true)"
          >
            Duplicate
          </button>
          <button
            type="button"
            class="danger-text"
            :disabled="disabled || !selected"
            @click="remove"
          >
            Delete example
          </button>
        </div>
      </div>
      <div class="row wrap preview-picker">
        <label class="grow"
          >Example<select
            :value="selected?.id ?? ''"
            @change="emit('update:modelValue', ($event.target as HTMLSelectElement).value)"
          >
            <option value="">Sample values</option>
            <option v-for="example in examples" :key="example.id" :value="example.id">
              {{ example.name }}
            </option>
          </select></label
        >
        <div class="row" role="group" aria-label="Browse preview examples">
          <button
            type="button"
            class="secondary"
            aria-label="Previous example"
            :disabled="!examples.length"
            @click="select(-1)"
          >
            <ChevronLeftIcon />
          </button>
          <span class="count" role="status">{{
            selected ? `${index + 1} / ${examples.length}` : 'Samples'
          }}</span>
          <button
            type="button"
            class="secondary"
            aria-label="Next example"
            :disabled="!examples.length"
            @click="select(1)"
          >
            <ChevronRightIcon />
          </button>
        </div>
      </div>
      <ExpandableContent :open="!!selected" @closed="displayed = undefined">
        <MotionSurface :identity="selected?.id ?? ''" :order="index">
          <div v-if="displayed" class="example-fields">
            <label
              >Example name<input
                v-model="displayed.name"
                maxlength="100"
                required
                :disabled="disabled"
                @change="emit('change')"
            /></label>
            <VariableInput
              v-for="field in document.fields"
              :key="`${displayed.id}:${field.name}:${field.type}`"
              :field="field"
              :model-value="
                Object.hasOwn(displayed.data, field.name)
                  ? displayed.data[field.name]
                  : sample(field)
              "
              :label="field.label"
              :disabled="disabled"
              nullable
              multiline
              @update:model-value="value(field.name, $event)"
              @change="emit('change')"
            />
          </div>
        </MotionSurface>
      </ExpandableContent>
    </PropertySection>
  </section>
</template>

<style scoped>
.preview-inputs :deep(.property-section) {
  border-top: 0;
}
.preview-inputs :deep(.property-section h3 button) {
  padding-top: 0;
  font-size: 17px;
}
.preview-inputs :deep(.property-section-content) {
  padding-bottom: 0;
}
.preview-actions {
  justify-content: flex-end;
}
.preview-picker {
  align-items: flex-end;
}
.preview-picker > label {
  min-width: min(220px, 100%);
}
.preview-picker button {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  padding: 10px;
}
.preview-picker button svg {
  width: 20px;
  height: 20px;
}
.example-fields {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(220px, 100%), 1fr));
  gap: 16px;
  margin-top: 20px;
  max-height: 300px;
  overflow: auto;
  padding: 6px;
}
.count {
  min-width: 64px;
  text-align: center;
}
</style>
