<script setup lang="ts">
import { t } from '../shared/i18n'
import { computed } from 'vue'
import type { Element } from '../templates/editor'
import type { FontAsset } from '../shared/types'

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
const names = computed<[number, string][]>(() => [
  [100, t('uiMessages.thin')],
  [200, t('uiMessages.extraLight')],
  [300, t('uiMessages.light')],
  [400, t('uiMessages.regular')],
  [500, t('uiMessages.medium')],
  [600, t('uiMessages.semiBold')],
  [700, t('uiMessages.bold')],
  [800, t('uiMessages.extraBold')],
  [900, t('uiMessages.black')],
])
const options = computed(() =>
  names.value.filter(([value]) =>
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
      >{{ $t('common.weight')
      }}<select
        :value="weight"
        :disabled="disabled || !axis"
        @change="emit('change', Number(($event.target as HTMLSelectElement).value))"
      >
        <option v-if="!options.some(([value]) => value === weight)" :value="weight">
          {{ $t('common.custom') }}
        </option>
        <option v-for="[value, name] in options" :key="value" :value="value">
          {{ name }}
        </option>
      </select></label
    >
    <label
      >{{ $t('fontWeightControl.numericWeight')
      }}<input
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
