<script setup lang="ts">
import { computed } from 'vue'
import type { PrintPlan } from '../types'

const props = withDefaults(defineProps<{ plan?: PrintPlan | null; copies?: number }>(), {
  copies: 1,
})
const message = computed(() => {
  const plan = props.plan
  if (!plan) return ''
  const copies = Number.isFinite(props.copies) ? Math.max(1, Math.floor(props.copies)) : 1
  const templateExtra =
    (plan.label_output ?? []).reduce((sum, label) => sum + (label.template_padding_mm ?? 0), 0) *
    copies
  if (!plan.cut_each) {
    const padding = plan.label_output?.length
      ? Math.max(
          0,
          (plan.minimum_cut_length_mm ?? 0) -
            plan.label_output.reduce((sum, label) => sum + label.output_length_mm, 0) * copies,
        )
      : (plan.strip_padding_mm ?? 0)
    const extra = padding + templateExtra
    return extra > 0
      ? `${padding > 0 ? `This strip is below the ${plan.minimum_cut_length_mm} mm minimum cut length. ` : ''}Hand trimming required; ${extra.toFixed(1)} mm of extra unused tape estimated, beyond normal feed and leader.`
      : ''
  }
  const short = (plan.label_output ?? []).filter((label) => label.minimum_padding_mm > 0)
  const count = short.length * copies
  const extra =
    short.reduce((sum, label) => sum + label.minimum_padding_mm, 0) * copies + templateExtra
  if (!extra) return ''
  const reason = count
    ? `${count === 1 ? '1 label is' : `${count} labels are`} below the ${plan.minimum_cut_length_mm} mm minimum cut length. `
    : ''
  return `${reason}Hand trimming required; ${extra.toFixed(1)} mm of extra unused tape estimated, beyond normal feed and leader.`
})
</script>

<template>
  <Transition name="notice">
    <p v-if="message" class="alert warning" role="status">{{ message }}</p>
  </Transition>
</template>
