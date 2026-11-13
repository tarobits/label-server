<script setup lang="ts">
import { computed } from 'vue'
import { t, number } from '../shared/i18n'
import type { PrintPlan } from '../shared/types'

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
      ? t(padding > 0 ? 'printPlanMessages.shortStrip' : 'printPlanMessages.trim', {
          minimum: plan.minimum_cut_length_mm ?? 0,
          extra: number(extra, { minimumFractionDigits: 1, maximumFractionDigits: 1 }),
        })
      : ''
  }
  const short = (plan.label_output ?? []).filter((label) => label.minimum_padding_mm > 0)
  const count = short.length * copies
  const extra =
    short.reduce((sum, label) => sum + label.minimum_padding_mm, 0) * copies + templateExtra
  if (!extra) return ''
  return t(count ? 'printPlanMessages.shortLabels' : 'printPlanMessages.trim', {
    count,
    minimum: plan.minimum_cut_length_mm ?? 0,
    extra: number(extra, { minimumFractionDigits: 1, maximumFractionDigits: 1 }),
  })
})
</script>

<template>
  <Transition name="notice">
    <p v-if="message" class="alert warning" role="status">{{ message }}</p>
  </Transition>
</template>
