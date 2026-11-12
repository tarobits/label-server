<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, errorMessage } from '../shared/api'
import { useAuthStore } from '../auth/auth'
import { useWorkspaceStore, date } from '../shared/workspace'
import AnimatedDetails from '../components/AnimatedDetails.vue'
import HistoryPagination from '../components/HistoryPagination.vue'
import MotionSurface from '../components/MotionSurface.vue'
interface Entry {
  id: string
  action: string
  outcome: string
  occurred_at: number
  recorded_at: number
  printers: string[]
  cartridges: string[]
  fields: Record<string, string | number | boolean | string[] | null>
  restricted_details: boolean
}
const route = useRoute(),
  router = useRouter(),
  auth = useAuthStore(),
  workspace = useWorkspaceStore()
const items = ref<Entry[]>([]),
  total = ref(0),
  busy = ref(false),
  error = ref(''),
  options = ref<Record<string, { id: string; name: string }[]>>({})
const facets = ['printer', 'cartridge', 'action', 'actor', 'victim']
const page = computed(() => {
  const value = Number(route.query.page)
  return Number.isSafeInteger(value) && value > 0 && value <= 1000000 ? value : 1
})
const pages = computed(() => Math.max(1, Math.ceil(total.value / 50)))
let sequence = 0
function label(value: string) {
  return value
    .replaceAll('.', ' ')
    .replaceAll('_', ' ')
    .replace(/^./, (letter) => letter.toUpperCase())
}
function optionLabel(kind: string, value: { id: string; name: string }) {
  if (kind === 'printer')
    return workspace.printers.find((printer) => printer.id === value.id)?.name ?? value.name
  if (kind === 'cartridge')
    return workspace.cartridges.find((cartridge) => cartridge.id === value.id)?.name ?? value.name
  return kind === 'action' ? label(value.name) : value.name
}
async function load() {
  const ticket = ++sequence
  busy.value = true
  error.value = ''
  try {
    const query = new URLSearchParams({ offset: String((page.value - 1) * 50), limit: '50' })
    for (const key of facets)
      if (typeof route.query[key] === 'string' && route.query[key])
        query.set(key, route.query[key] as string)
    const result = await api<{ items: Entry[]; total: number; options: typeof options.value }>(
      `/audit?${query}`,
    )
    if (ticket !== sequence) return
    items.value = result.items
    total.value = result.total
    options.value = result.options
  } catch (cause) {
    if (ticket === sequence) {
      items.value = []
      options.value = {}
      total.value = 0
      error.value = errorMessage(cause)
    }
  } finally {
    if (ticket === sequence) busy.value = false
  }
}
function filter(key: string, event: Event) {
  void router.push({
    query: {
      ...route.query,
      [key]: (event.target as HTMLSelectElement).value || undefined,
      page: undefined,
    },
  })
}
function go(value: number) {
  void router.push({ query: { ...route.query, page: value > 1 ? value : undefined } })
}
watch(
  () => [route.fullPath, JSON.stringify(auth.user)],
  () => {
    items.value = []
    void load()
  },
  { immediate: true },
)
onUnmounted(() => {
  sequence++
})
const fields = (entry: Entry) =>
  Object.entries(entry.fields).filter(([key]) => !['actor_id', 'actor_name'].includes(key))
</script>
<template>
  <section class="panel form-stack">
    <div class="section-heading">
      <h2>{{ $t('common.auditLog') }}</h2>
      <button class="secondary" :disabled="busy" @click="load">{{ $t('common.refresh') }}</button>
    </div>
    <div class="field-row">
      <label v-for="kind in facets" :key="kind"
        >{{ label(kind)
        }}<select :value="route.query[kind] ?? ''" @change="filter(kind, $event)">
          <option value="">{{ $t('common.all') }}</option>
          <option v-for="option in options[kind] ?? []" :key="option.id" :value="option.id">
            {{ optionLabel(kind, option) }}
          </option>
        </select></label
      >
    </div>
    <Transition name="notice"
      ><p v-if="error" class="alert danger" role="alert">{{ error }}</p></Transition
    >
    <HistoryPagination
      :page="page"
      :pages="pages"
      :loading="busy"
      :label="$t('auditLog.auditLogPages')"
      @change="go"
    />
    <p v-if="!busy && !error && !items.length" class="empty compact">
      {{ $t('auditLog.noMatchingEvents') }}
    </p>
    <MotionSurface :identity="route.fullPath" :order="page">
      <article v-for="entry in items" :key="entry.id" class="audit-entry">
        <div class="row spread wrap">
          <strong>{{ label(entry.action) }}</strong
          ><span :class="{ 'danger-text': entry.outcome !== 'succeeded' }">{{
            label(entry.outcome)
          }}</span>
        </div>
        <small
          >{{ date(entry.occurred_at) }} ·
          {{
            entry.fields.actor_name ??
            entry.fields.actor_id ??
            (entry.fields.source === 'anonymous' ? 'Unauthenticated' : $t('common.system'))
          }}</small
        >
        <AnimatedDetails
          v-if="
            fields(entry).length ||
            entry.printers.length ||
            entry.cartridges.length ||
            entry.restricted_details
          "
        >
          <template #summary>{{ $t('common.details') }}</template>
          <dl>
            <template
              v-for="(value, key) in { printers: entry.printers, cartridges: entry.cartridges }"
              :key="key"
              ><template v-if="value.length"
                ><dt>{{ label(key) }}</dt>
                <dd>
                  {{
                    value
                      .map((id) =>
                        optionLabel(key === 'printers' ? 'printer' : 'cartridge', { id, name: id }),
                      )
                      .join(', ')
                  }}
                </dd></template
              ></template
            ><template v-for="[key, value] in fields(entry)" :key="key"
              ><dt>{{ label(key) }}</dt>
              <dd>
                {{ Array.isArray(value) ? value.join(', ') : (value ?? $t('resourceAccess.none')) }}
              </dd></template
            >
          </dl>
          <p v-if="entry.restricted_details" class="muted">
            {{ $t('common.someDetailsAreRestricted') }}
          </p>
        </AnimatedDetails>
      </article>
    </MotionSurface>
    <HistoryPagination
      v-if="items.length"
      :page="page"
      :pages="pages"
      :loading="busy"
      :label="$t('auditLog.auditLogPagesBottom')"
      @change="go"
    />
  </section>
</template>
<style scoped>
.audit-entry {
  padding-block: 20px;
  border-bottom: 1px solid var(--line);
  overflow-wrap: anywhere;
}
.audit-entry:last-child {
  border-bottom: 0;
}
.audit-entry small {
  display: block;
  margin-block: 8px;
  color: var(--text-secondary);
}
.audit-entry dl {
  display: grid;
  grid-template-columns: minmax(100px, 1fr) minmax(0, 3fr);
  gap: 12px;
}
.audit-entry dd {
  margin: 0;
}
</style>
