<script setup lang="ts">
import { t } from '../shared/i18n'
import { computed, onUnmounted, ref, watch } from 'vue'
import { api, errorMessage } from '../shared/api'
import { useAuthStore } from '../auth/auth'
import { permissionLabel, decisionSummary } from '../shared/resourceAccess'
import type { AccessCatalog, AccessExplanation, PermissionRule } from '../shared/resourceAccess'
import ExpandableContent from './ExpandableContent.vue'
const props = defineProps<{
  catalog: AccessCatalog
  initialResource?: string
  initialUser?: string
}>()
const auth = useAuthStore()
const user = ref(props.initialUser ?? auth.user?.id ?? '')
const resource = ref(props.initialResource ?? '')
const permission = ref('')
const result = ref<AccessExplanation>()
const error = ref('')
const busy = ref(false)
let generation = 0
const choices = computed(() => [
  ...new Set(
    result.value?.resources.flatMap((item) => item.permissions.map((p) => p.permission)) ?? [],
  ),
])
const rows = computed(() =>
  (result.value?.resources ?? []).flatMap((item) => {
    const decision = item.permissions.find((p) => p.permission === permission.value)
    return decision ? [{ ...item, decision }] : []
  }),
)
watch(
  [user, resource],
  async () => {
    const ticket = ++generation
    result.value = undefined
    error.value = ''
    if (!user.value) return
    busy.value = true
    try {
      const query = new URLSearchParams({ user_id: user.value })
      if (resource.value) {
        const split = resource.value.indexOf(':')
        if (resource.value.slice(0, split) === 'location')
          query.set('location_id', resource.value.slice(split + 1))
        else {
          query.set('kind', resource.value.slice(0, split))
          query.set('identifier', resource.value.slice(split + 1))
        }
      }
      const response = await api<AccessExplanation>(`/resource-access/explain?${query}`)
      if (ticket !== generation) return
      result.value = response
      if (!choices.value.includes(permission.value))
        permission.value = choices.value.includes('cartridge.use')
          ? 'cartridge.use'
          : choices.value.includes('printer.view')
            ? 'printer.view'
            : (choices.value[0] ?? '')
    } catch (issue) {
      if (ticket === generation) error.value = errorMessage(issue)
    } finally {
      if (ticket === generation) busy.value = false
    }
  },
  { immediate: true },
)
onUnmounted(() => {
  generation++
})
function steps(rule: PermissionRule, name: string) {
  return [
    result.value?.user.name ?? '',
    ...(rule.principal_kind === 'role'
      ? [t('uiDetails.role', { value1: String(rule.principal_name) })]
      : []),
    rule.protected
      ? rule.scope_name
      : rule.scope_kind === 'location'
        ? t('uiDetails.location', { value1: String(rule.scope_name) })
        : rule.scope_kind === 'application'
          ? rule.scope_name
          : t('uiMessages.directRule'),
    ...(rule.inherited_via ?? []).map((location) =>
      t('uiDetails.location', { value1: String(location) }),
    ),
    name,
  ]
}
</script>
<template>
  <div class="form-stack access-graph" :aria-busy="busy">
    <div class="graph-filters">
      <label
        >{{ $t('common.user')
        }}<select v-model="user">
          <option v-for="person in catalog.users" :key="person.id" :value="person.id">
            {{ person.name }}
          </option>
        </select></label
      >
      <label
        >{{ $t('common.resource')
        }}<select v-model="resource">
          <option value="">{{ $t('accessGraph.allInspectableResources') }}</option>
          <option
            v-for="item in catalog.resources"
            :key="`${item.kind}:${item.id}`"
            :value="`${item.kind}:${item.id}`"
          >
            {{ item.name }} · {{ item.kind }}
          </option>
        </select></label
      >
      <label
        >{{ $t('common.permission')
        }}<select v-model="permission" :disabled="busy || !choices.length">
          <option v-for="choice in choices" :key="choice" :value="choice">
            {{ permissionLabel(choice) }}
          </option>
        </select></label
      >
    </div>
    <ExpandableContent :open="!!error"
      ><p class="alert danger" role="alert">{{ error }}</p></ExpandableContent
    >
    <p v-if="busy" role="status">{{ $t('accessGraph.loadingAccessPaths') }}</p>
    <template v-else-if="result">
      <p class="muted">
        {{ $t('accessGraph.moreSpecificResourceRulesWinThenUserRulesOver') }}
      </p>
      <section v-for="row in rows" :key="`${row.kind}:${row.id}`" class="graph-resource">
        <div class="section-heading wrap">
          <h3>{{ row.name }}</h3>
          <span class="badge" :class="row.decision.allowed ? 'printed' : 'failed'">{{
            row.decision.allowed ? $t('uiMessages.allowed') : $t('uiMessages.denied')
          }}</span>
        </div>
        <p>{{ decisionSummary(row.decision) }}</p>
        <ol
          class="access-paths"
          :aria-label="$t('uiDetails.accessPaths', { value1: String(row.name) })"
        >
          <li
            v-for="(rule, index) in row.decision.rules"
            :key="index"
            :class="{ overridden: !rule.winning }"
          >
            <div class="path-steps">
              <template v-for="(step, stepIndex) in steps(rule, row.name)" :key="stepIndex">
                <svg v-if="stepIndex" class="path-arrow" viewBox="0 0 24 24" aria-hidden="true">
                  <path
                    d="M3 12h17m-6-6 6 6-6 6"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.5"
                  />
                </svg>
                <span class="path-node">{{ step }}</span>
              </template>
            </div>
            <p class="path-outcome">
              {{ rule.effect === 'allow' ? $t('common.allow') : $t('common.deny') }} ·
              {{ rule.winning ? $t('uiMessages.applies') : $t('uiMessages.overridden')
              }}{{ rule.protected ? ' · Protected' : '' }}
            </p>
          </li>
        </ol>
      </section>
      <p v-if="!rows.length" class="empty">
        {{ $t('accessGraph.noResourcesMatchThisPermission') }}
      </p>
    </template>
  </div>
</template>
<style scoped>
.graph-filters {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 180px), 1fr));
  gap: 16px;
}
.graph-resource {
  padding-block: 20px;
  border-top: 1px solid var(--line);
}
.graph-resource h3,
.graph-resource p {
  margin: 0;
}
.graph-resource > p {
  margin-block: 12px;
}
.access-paths {
  list-style: none;
  padding: 0;
  margin: 0;
  display: grid;
  gap: 20px;
}
.path-steps {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.path-node {
  border: 1px solid var(--line-strong);
  border-radius: 8px;
  padding: 10px 12px;
  background: var(--surface-dense);
  overflow-wrap: anywhere;
  max-width: 100%;
}
.path-arrow {
  width: 24px;
  height: 24px;
  flex: none;
  color: var(--muted);
}
.access-paths .path-outcome {
  margin-top: 8px;
  font-size: 0.85rem;
}
.overridden .path-node {
  border-style: dashed;
}
@media (max-width: 600px) {
  .path-steps {
    flex-direction: column;
    align-items: stretch;
  }
  .path-arrow {
    align-self: center;
    transform: rotate(90deg);
  }
}
</style>
