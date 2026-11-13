<script setup lang="ts">
import { t } from '../shared/i18n'
import { computed, ref, watch } from 'vue'
import { referenceEntries } from '../templates/logicReference'
import type { TemplateDocument } from '../templates/editor'
import type { LogicCatalog } from '../templates/logicGraph'
import MotionSurface from './MotionSurface.vue'
const props = defineProps<{
  catalog: LogicCatalog
  document: TemplateDocument
  entry?: string
  request?: number
}>()
const query = ref(''),
  selection = ref(props.entry ?? 'source'),
  copied = ref('')
const entries = computed(() => referenceEntries(props.catalog, props.document))
const filtered = computed(() =>
  entries.value.filter((entry) =>
    `${entry.title} ${entry.group} ${entry.summary} ${entry.details.join(' ')}`
      .toLowerCase()
      .includes(query.value.toLowerCase()),
  ),
)
const selected = computed(
  () => entries.value.find((entry) => entry.id === selection.value) ?? filtered.value[0],
)
watch(
  () => [props.entry, props.request] as const,
  ([entry]) => {
    if (entry) {
      query.value = ''
      selection.value = entry
    }
  },
)
watch(filtered, (results) => {
  if (!results.some((entry) => entry.id === selection.value)) selection.value = results[0]?.id ?? ''
})
watch(selection, () => {
  copied.value = ''
})
async function copy() {
  try {
    await navigator.clipboard.writeText(selected.value?.example ?? '')
    copied.value = t('uiMessages.exampleCopied')
  } catch {
    copied.value = t('uiMessages.selectTheExampleTextToCopyIt')
  }
}
</script>
<template>
  <section class="logic-reference" :aria-label="$t('logicReference.logicReference')">
    <label>{{ $t('common.searchReference') }}<input v-model="query" type="search" /></label>
    <div class="reference-layout">
      <nav :aria-label="$t('logicReference.referenceEntries')">
        <button
          v-for="entry in filtered"
          :key="entry.id"
          :aria-current="selection === entry.id ? 'true' : undefined"
          @click="selection = entry.id"
        >
          <span>{{ entry.title }}</span
          ><small>{{ entry.group }}</small>
        </button>
        <p v-if="!filtered.length" class="help">{{ $t('logicReference.noMatchingEntries') }}</p>
      </nav>
      <MotionSurface :identity="selection" class="reference-entry">
        <article v-if="selected && filtered.length">
          <h3>{{ selected.title }}</h3>
          <p>{{ selected.summary }}</p>
          <p v-for="detail in selected.details" :key="detail">{{ detail }}</p>
          <template v-if="selected.example">
            <pre><code>{{ selected.example }}</code></pre>
            <button class="small" @click="copy">{{ $t('logicReference.copyExample') }}</button>
            <p v-if="copied" role="status">{{ copied }}</p></template
          >
        </article>
      </MotionSurface>
    </div>
  </section>
</template>
<style scoped>
.logic-reference {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--line);
}
.reference-layout {
  display: grid;
  grid-template-columns: minmax(180px, 240px) minmax(0, 1fr);
  gap: 24px;
  margin-top: 16px;
}
nav {
  display: grid;
  align-content: start;
  gap: 4px;
  max-height: 440px;
  overflow: auto;
}
nav button {
  display: grid;
  text-align: left;
  justify-content: stretch;
  background: transparent;
  border-color: transparent;
}
nav button[aria-current] {
  background: var(--surface-deepest);
  border-color: var(--accent-hover);
}
nav small {
  color: var(--muted);
  font-weight: 400;
}
.reference-entry {
  min-width: 0;
  max-height: 440px;
  overflow: auto;
  padding-right: 8px;
}
.reference-entry p {
  max-width: 70ch;
}
h3 {
  margin-top: 0;
}
pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  padding: 16px;
  background: var(--surface-deepest);
  border-radius: 12px;
}
@media (max-width: 760px) {
  .reference-layout {
    grid-template-columns: minmax(0, 1fr);
    gap: 16px;
  }
  nav {
    max-height: 180px;
  }
  .reference-entry {
    max-height: 420px;
  }
}
</style>
