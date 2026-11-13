<script setup lang="ts">
import type { LabelInformation, PrintAttribution } from '../shared/types'
import PrintAttributionDisplay from './PrintAttribution.vue'
defineProps<{ label: LabelInformation; attribution?: PrintAttribution | null }>()
</script>

<template>
  <div class="label-details">
    <dl>
      <div>
        <dt>{{ $t('common.template') }}</dt>
        <dd>
          {{ label.template_name
          }}<span v-if="label.template_revision != null">
            {{ $t('common.revision3') }} {{ label.template_revision }}</span
          >
        </dd>
      </div>
      <div>
        <dt>{{ $t('common.printer') }}</dt>
        <dd>{{ label.printer_name ?? $t('uiMessages.notAssigned') }}</dd>
      </div>
      <div v-if="label.destination_name !== label.printer_name">
        <dt>{{ $t('common.destination') }}</dt>
        <dd>{{ label.destination_name }}</dd>
      </div>
      <div>
        <dt>{{ $t('common.tapeProfile') }}</dt>
        <dd>{{ label.profile_name }}</dd>
      </div>
    </dl>
    <dl v-if="label.fields.length" class="label-fields">
      <div v-for="field in label.fields" :key="field.name">
        <dt>{{ field.label }}</dt>
        <dd>{{ field.value || '—' }}</dd>
      </div>
    </dl>
    <PrintAttributionDisplay v-if="attribution" :attribution="attribution" queue />
  </div>
</template>

<style scoped>
.label-details {
  display: grid;
  gap: 16px;
  padding-block: 12px;
  white-space: normal;
}
dl {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(180px, 100%), 1fr));
  gap: 10px;
  margin: 0;
  font-size: 13px;
}
dl > div {
  display: block;
  padding: 0;
  border: 0;
  min-width: 0;
}
dt {
  color: var(--text-secondary);
  font-size: 12px;
  margin-bottom: 3px;
}
dd {
  margin: 0;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}
.label-fields {
  border-top: 1px solid var(--line);
  padding-top: 12px;
}
</style>
