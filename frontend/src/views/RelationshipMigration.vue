<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, errorMessage } from '../shared/api'
import AdminDialog from '../components/AdminDialog.vue'
import MigrationResourceCreator from '../components/MigrationResourceCreator.vue'

interface Relationship {
  table: string
  column: string
  parent: string
  count: number
}
interface BrokenRow {
  token: string
  name: string
  missing: string
  nullable: boolean
  revoke_only: boolean
}
interface Target {
  id: string
  name: string
}
const state = ref<{ ready: boolean; relationships: Relationship[] }>()
const selected = ref('')
const rows = ref<BrokenRow[]>([])
const offset = ref(0)
const editing = ref<BrokenRow>()
const targets = ref<Target[]>([])
const search = ref('')
const target = ref('')
const reason = ref('')
const busy = ref(false)
const error = ref('')
const modalError = ref('')
const creating = ref(false)
const creation = ref<{
  parent: string
  resources: InstanceType<typeof MigrationResourceCreator>['$props']['resources']
}>()
function created(value: Target) {
  targets.value.push(value)
  target.value = value.id
  creating.value = false
}
function focusPanel(element: Element) {
  element.querySelector<HTMLElement>('input, select, button')?.focus()
}
const total = computed(
  () => state.value?.relationships.reduce((sum, item) => sum + item.count, 0) ?? 0,
)
const count = computed(
  () => state.value?.relationships.find((item) => key(item) === selected.value)?.count ?? 0,
)
const key = (item: Relationship) => `${item.table}.${item.column}`
const label = (value: string) => value.replaceAll('_', ' ')
async function loadRows() {
  rows.value = selected.value
    ? await api(
        `/migration/relationships/rows?key=${encodeURIComponent(selected.value)}&offset=${offset.value}`,
      )
    : []
}
function changeRelationship() {
  offset.value = 0
  void action(loadRows)
}
function changePage(delta: number) {
  if (busy.value) return
  offset.value += delta
  void action(loadRows)
}
async function load() {
  state.value = await api('/migration/relationships')
  if (!state.value?.relationships.some((item) => key(item) === selected.value)) {
    selected.value = state.value?.relationships[0] ? key(state.value.relationships[0]) : ''
    offset.value = 0
  }
  if (offset.value >= count.value) offset.value = Math.max(0, offset.value - 50)
  await loadRows()
}
async function action(fn: () => Promise<void>) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    await fn()
  } catch (e) {
    if (editing.value) modalError.value = errorMessage(e)
    else error.value = errorMessage(e)
  } finally {
    busy.value = false
  }
}
async function findTargets() {
  targets.value = await api(
    `/migration/relationships/targets?key=${encodeURIComponent(selected.value)}&search=${encodeURIComponent(search.value)}`,
  )
}
async function open(row: BrokenRow) {
  creating.value = false
  creation.value = undefined
  search.value = ''
  target.value = ''
  reason.value = ''
  modalError.value = ''
  targets.value = []
  if (!row.revoke_only) {
    await findTargets()
    creation.value = await api(
      `/migration/relationships/creation?key=${encodeURIComponent(selected.value)}`,
    )
  }
  editing.value = row
}
async function save() {
  if (!editing.value) return
  busy.value = true
  modalError.value = ''
  try {
    await api('/migration/relationships/repair', 'POST', {
      key: selected.value,
      token: editing.value.token,
      target: target.value === '__clear__' ? null : target.value || null,
      revoke: editing.value.revoke_only,
      reason: reason.value.trim(),
    })
    editing.value = undefined
    await load()
  } catch (e) {
    if (editing.value) modalError.value = errorMessage(e)
    else error.value = errorMessage(e)
  } finally {
    busy.value = false
  }
}
async function finish() {
  await api('/migration/relationships/complete', 'POST', {})
  await load()
}
onMounted(() => action(load))
</script>

<template>
  <section class="panel relationship-migration">
    <div class="row wrap spread">
      <h1>{{ $t('relationshipMigration.repairDatabaseRelationships') }}</h1>
      <button class="secondary" :disabled="busy" @click="action(load)">
        {{ $t('common.refresh') }}
      </button>
    </div>
    <p class="alert warning">
      {{ $t('relationshipMigration.printingAndNormalOperationsArePausedReviewEachMissing') }}
    </p>
    <Transition name="notice"
      ><p v-if="error" class="alert danger" role="alert">{{ error }}</p></Transition
    >
    <Transition name="panel-expand" mode="out-in">
      <p v-if="!state" key="loading" role="status">
        {{ $t('relationshipMigration.checkingRelationships') }}
      </p>
      <p v-else-if="state.ready" key="ready" class="alert success" role="status">
        {{ $t('relationshipMigration.readyForAMaintenanceRestartRestartTheServerService') }}
      </p>
      <div v-else-if="total" key="repairs" class="form-stack">
        <label
          >{{ $t('relationshipMigration.relationship')
          }}<select v-model="selected" :disabled="busy" @change="changeRelationship">
            <option v-for="item in state.relationships" :key="key(item)" :value="key(item)">
              {{ label(item.table) }} · {{ label(item.column) }} → {{ label(item.parent) }} ({{
                item.count
              }})
            </option>
          </select></label
        >
        <div class="table-scroll">
          <table>
            <thead>
              <tr>
                <th>{{ $t('common.record') }}</th>
                <th>{{ $t('relationshipMigration.missingReference') }}</th>
                <th>
                  <span class="sr-only">{{ $t('relationshipMigration.action') }}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in rows" :key="row.token">
                <td>{{ row.name }}</td>
                <td>{{ row.missing }}</td>
                <td>
                  <button class="secondary" :aria-disabled="busy" @click="action(() => open(row))">
                    {{
                      row.revoke_only
                        ? $t('uiMessages.reviewRevocation')
                        : $t('uiMessages.reassign')
                    }}
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="row wrap spread">
          <span
            >{{ total }} {{ total === 1 ? 'reference' : 'references' }}
            {{ $t('common.remaining') }}</span
          >
          <div class="row wrap">
            <button class="secondary" :disabled="busy || !offset" @click="changePage(-50)">
              {{ $t('common.previous') }}</button
            ><span
              >{{ offset + 1 }}–{{ Math.min(offset + 50, count) }} {{ $t('common.of') }}
              {{ count }}</span
            ><button
              class="secondary"
              :disabled="busy || offset + 50 >= count"
              @click="changePage(50)"
            >
              {{ $t('common.next') }}
            </button>
          </div>
        </div>
      </div>
      <div v-else key="valid" class="form-stack">
        <p>{{ $t('relationshipMigration.allReferencesHaveValidTargets') }}</p>
        <button class="primary" :disabled="busy" @click="action(finish)">
          {{ $t('relationshipMigration.prepareMaintenanceRestart') }}
        </button>
      </div>
    </Transition>
    <AdminDialog
      :open="!!editing"
      :title="
        editing?.revoke_only
          ? $t('uiMessages.revokeInvalidCredential')
          : $t('uiMessages.reassignReference')
      "
      :busy="busy"
      @close="editing = undefined"
    >
      <Transition name="panel-expand" mode="out-in" @after-enter="focusPanel">
        <MigrationResourceCreator
          v-if="editing && creating && creation"
          :relationship="selected"
          :token="editing.token"
          :parent="creation.parent"
          :resources="creation.resources"
          @created="created"
          @cancel="creating = false"
          @busy="busy = $event"
        />
        <form v-else-if="editing" class="form-stack" @submit.prevent="save">
          <p>
            <strong>{{ editing.name }}</strong> · {{ selected }}<br />{{
              $t('relationshipMigration.missing')
            }}
            {{ editing.missing }}
          </p>
          <p v-if="editing.revoke_only" class="alert warning">
            {{ $t('common.thisCredentialOrConsentWillBeRevokedItCannot') }}
          </p>
          <template v-else>
            <div class="row wrap">
              <label
                >{{ $t('relationshipMigration.findReplacement')
                }}<input v-model="search" maxlength="128" :disabled="busy" /></label
              ><button
                type="button"
                class="secondary"
                :disabled="busy"
                @click="action(findTargets)"
              >
                {{ $t('common.search') }}
              </button>
            </div>
            <label
              >{{ $t('relationshipMigration.replacement')
              }}<select v-model="target" :disabled="busy" required>
                <option value="" disabled>
                  {{ $t('relationshipMigration.chooseAReplacement') }}
                </option>
                <option v-if="editing.nullable" value="__clear__">
                  {{ $t('relationshipMigration.clearReference') }}
                </option>
                <option v-for="item in targets" :key="item.id" :value="item.id">
                  {{ item.name }} · {{ item.id }}
                </option>
              </select></label
            >
            <p v-if="targets.length === 50">
              {{ $t('common.showing50MatchesRefineTheSearchToFindAnother') }}
            </p>
            <button
              v-if="creation?.resources?.[creation.parent]"
              type="button"
              class="secondary"
              :disabled="busy"
              @click="creating = true"
            >
              {{ $t('relationshipMigration.createReplacement') }}
            </button>
            <p v-else class="help">
              {{ $t('relationshipMigration.chooseAnExistingRecordOrRestoreTheMissingHistory') }}
            </p>
            <p class="alert warning">
              {{ $t('common.thisChangesTheRecordSAssignmentCheckTheReplacement') }}
            </p>
          </template>
          <label
            >{{ $t('common.reason')
            }}<textarea v-model="reason" required maxlength="500" :disabled="busy" />
          </label>
          <Transition name="notice"
            ><p v-if="modalError" class="alert danger" role="alert">{{ modalError }}</p></Transition
          >
          <div class="row wrap">
            <button
              type="submit"
              :disabled="busy || !reason.trim() || (!editing.revoke_only && !target)"
            >
              {{
                editing.revoke_only
                  ? $t('uiMessages.revokeCredential')
                  : $t('uiMessages.saveAssignment')
              }}</button
            ><button type="button" class="secondary" :disabled="busy" @click="editing = undefined">
              {{ $t('common.cancel') }}
            </button>
          </div>
        </form>
      </Transition>
    </AdminDialog>
  </section>
</template>

<style scoped>
.relationship-migration {
  display: grid;
  gap: 20px;
  min-width: 0;
}
.relationship-migration h1 {
  margin: 0;
}
td {
  overflow-wrap: anywhere;
}
td:last-child {
  text-align: right;
}
td button {
  white-space: nowrap;
}
form .row {
  align-items: end;
}
form .row label {
  flex: 1;
  min-width: 180px;
}
</style>
