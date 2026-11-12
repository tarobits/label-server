<script setup lang="ts">
import { computed } from 'vue'
import type { Element } from '../editor'
import type { FontAsset } from '../types'

const props = defineProps<{ element: Element; fonts: FontAsset[]; disabled?: boolean }>()
const emit = defineEmits<{ change: [number] }>()
const asset = computed(() => props.fonts.find((font) => font.id === props.element.font))
const axis = computed(() =>
  props.element.font === 'Noto Sans'
    ? { min: 100, max: 900, default: props.element.bold ? 700 : 400 }
    : asset.value?.weight_axis,
)
const weight = computed(
  () => props.element.font_weight ?? axis.value?.default ?? asset.value?.weight ?? 400,
)
const names: [number, string][] = [
  [100, 'Thin'],
  [200, 'Extra Light'],
  [300, 'Light'],
  [400, 'Regular'],
  [500, 'Medium'],
  [600, 'Semi Bold'],
  [700, 'Bold'],
  [800, 'Extra Bold'],
  [900, 'Black'],
]
const options = computed(() =>
  names.filter(([value]) =>
    axis.value ? value >= axis.value.min && value <= axis.value.max : value === weight.value,
  ),
)
function numeric(event: Event) {
  const input = event.target as HTMLInputElement
  if (input.reportValidity() && Number.isFinite(input.valueAsNumber))
    emit('change', input.valueAsNumber)
}
</script>

<template>
  <div class="field-row">
    <label
      >Weight<select
        :value="weight"
        :disabled="disabled || !axis"
        @change="emit('change', Number(($event.target as HTMLSelectElement).value))"
      >
        <option v-if="!options.some(([value]) => value === weight)" :value="weight">Custom</option>
        <option v-for="[value, name] in options" :key="value" :value="value">
          {{ name }}
        </option>
      </select></label
    >
    <label
      >Numeric weight<input
        type="number"
        :value="weight"
        :min="axis?.min"
        :max="axis?.max"
        step="any"
        required
        :disabled="disabled || !axis"
        @change="numeric"
    /></label>
  </div>
</template>
