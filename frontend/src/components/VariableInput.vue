<script setup lang="ts">
import type { TemplateField, VariableValue } from '../editor'
import ImageValueInput from './ImageValueInput.vue'

defineProps<{
  field: TemplateField
  modelValue: VariableValue | undefined
  label: string
  name?: string
  required?: boolean
  nullable?: boolean
  multiline?: boolean
  disabled?: boolean
}>()
const emit = defineEmits<{ 'update:modelValue': [value: VariableValue]; change: [] }>()
function numberChanged(event: Event) {
  const value = (event.target as HTMLInputElement).valueAsNumber
  emit('update:modelValue', Number.isFinite(value) ? value : null)
}
function checkboxChanged(event: Event) {
  emit('update:modelValue', (event.target as HTMLInputElement).checked)
  emit('change')
}
function booleanChanged(event: Event) {
  const value = (event.target as HTMLSelectElement).value
  emit('update:modelValue', value === '' ? null : value === 'true')
  emit('change')
}
</script>

<template>
  <ImageValueInput
    v-if="field.type === 'image'"
    :context="field"
    :model-value="typeof modelValue === 'object' ? (modelValue ?? null) : null"
    :label="label"
    :name="name"
    :required="required"
    :disabled="disabled"
    @update:model-value="emit('update:modelValue', $event)"
    @change="emit('change')"
  />
  <label v-else-if="field.type === 'number'"
    >{{ label
    }}<input
      type="number"
      step="any"
      :value="typeof modelValue === 'number' ? modelValue : ''"
      :min="field.minimum ?? -1e12"
      :max="field.maximum ?? 1e12"
      :name="name"
      :required="required"
      :disabled="disabled"
      @input="numberChanged"
      @change="emit('change')"
  /></label>
  <label v-else-if="field.type === 'boolean' && nullable"
    >{{ label
    }}<select
      :value="modelValue == null ? '' : String(modelValue)"
      :name="name"
      :disabled="disabled"
      @change="booleanChanged"
    >
      <option value="">Not set</option>
      <option value="false">False</option>
      <option value="true">True</option>
    </select></label
  >
  <label v-else-if="field.type === 'boolean'" class="checkbox"
    ><input
      type="checkbox"
      :checked="modelValue === true"
      :name="name"
      :disabled="disabled"
      @change="checkboxChanged"
    />{{ label }}</label
  >
  <label v-else
    >{{ label
    }}<textarea
      v-if="multiline"
      :value="typeof modelValue === 'string' ? modelValue : ''"
      :name="name"
      :required="required"
      :disabled="disabled"
      maxlength="2000"
      rows="2"
      @input="emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)"
      @change="emit('change')" /><input
      v-else
      :value="typeof modelValue === 'string' ? modelValue : ''"
      :name="name"
      :required="required"
      :disabled="disabled"
      maxlength="2000"
      @input="emit('update:modelValue', ($event.target as HTMLInputElement).value)"
      @change="emit('change')"
  /></label>
</template>
