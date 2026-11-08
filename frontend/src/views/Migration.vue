<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, errorMessage } from '../api'
import { useAuthStore } from '../auth'
import type {
  AccessCatalog,
  AccessPreview,
  Grant,
  PairBalance,
  ResourceChange,
  ResourceEntry,
} from '../resourceAccess'
import ResourceGrants from '../components/ResourceGrants.vue'
import ResourceImpact from '../components/ResourceImpact.vue'
import AnimatedDetails from '../components/AnimatedDetails.vue'
interface Adjustment {
  id: string
  username: string
  note: string
  amount_minor: number
  currency: string
  recipient_id: string | null
  user_id: string
  cartridge_allocations: Record<string, string>
}
interface Draft {
  resources: ResourceChange[]
  adjustment_recipients: Record<string, string>
  adjustment_allocations: Record<string, Record<string, number>>
  accept_owner_loss: boolean
}
const auth = useAuthStore(),
  router = useRouter()
const catalog = ref<AccessCatalog>()
const resources = ref<ResourceEntry[]>([]),
  adjustments = ref<Adjustment[]>([])
const draft = ref<Draft>({
  resources: [],
  adjustment_recipients: {},
  adjustment_allocations: {},
  accept_owner_loss: false,
})
const selected = ref<string[]>([]),
  bulkOwner = ref(''),
  bulkLocation = ref<string | null>(null),
  bulkRecipient = ref('')
const bulkGrants = ref<Grant[]>([])
type MigrationPreview = AccessPreview & {
  balances: PairBalance[]
  cartridge_balances: (PairBalance & { cartridge_id: string; cartridge_name: string })[]
  adjustments: Adjustment[]
}
const preview = ref<MigrationPreview>()
const allocationsChanged = ref(false)
function allocationOptions(adjustment: Adjustment) {
  return (
    preview.value?.cartridge_balances.filter(
      (row) =>
        row.requester_id === adjustment.user_id &&
        row.recipient_id === adjustment.recipient_id &&
        row.currency === adjustment.currency,
    ) ?? []
  )
}
function editAllocation(adjustment: Adjustment, cartridge: string, event: Event) {
  const selected =
    draft.value.adjustment_allocations[adjustment.id] ??
    Object.fromEntries(
      Object.entries(adjustment.cartridge_allocations).map(([key, value]) => [key, Number(value)]),
    )
  const amount = Number((event.target as HTMLInputElement).value)
  if (!Number.isFinite(amount) || amount < 0) return
  if (amount)
    selected[cartridge] = Math.round(amount * 1000000) * Math.sign(adjustment.amount_minor)
  else delete selected[cartridge]
  draft.value.adjustment_allocations[adjustment.id] = selected
  allocationsChanged.value = true
}
const busy = ref(false),
  error = ref(''),
  saved = ref(false),
  required = ref(true)
const lossWarning = computed(() =>
  draft.value.resources.some((item) =>
    item.grants?.some((grant) => grant.permission === 'cartridge.approve_use'),
  ),
)
const key = (resource: { kind: string; id: string }) => `${resource.kind}:${resource.id}`
const change = (item: ResourceEntry) =>
  draft.value.resources.find((row) => row.kind === item.kind && row.identifier === item.id)!
async function load() {
  const [inventory, state] = await Promise.all([
    api<AccessCatalog>('/resource-access'),
    api<{ required: boolean; draft: Partial<Draft>; adjustments: Adjustment[] }>('/migration'),
  ])
  catalog.value = inventory
  resources.value = inventory.resources.filter((item) => item.kind !== 'location')
  required.value = state.required
  adjustments.value = state.adjustments
  draft.value = {
    resources: resources.value.map(
      (item) =>
        state.draft.resources?.find(
          (row) => row.kind === item.kind && row.identifier === item.id,
        ) ?? {
          kind: item.kind,
          identifier: item.id,
          owner_id: item.owner_id,
          location_id: item.location_id,
          grants: item.grants,
        },
    ),
    adjustment_recipients: state.draft.adjustment_recipients ?? {},
    adjustment_allocations: state.draft.adjustment_allocations ?? {},
    accept_owner_loss: state.draft.accept_owner_loss ?? false,
  }
  for (const adjustment of adjustments.value)
    if (adjustment.recipient_id && !draft.value.adjustment_recipients[adjustment.id])
      draft.value.adjustment_recipients[adjustment.id] = adjustment.recipient_id
}
onMounted(() => load().catch((e) => (error.value = errorMessage(e))))
function assignOwners() {
  for (const item of resources.value)
    if (selected.value.includes(key(item))) change(item).owner_id = bulkOwner.value
}
function assignLocations() {
  for (const item of resources.value)
    if (selected.value.includes(key(item))) change(item).location_id = bulkLocation.value
}
function assignGrants() {
  for (const item of resources.value)
    if (item.kind === 'cartridge' && selected.value.includes(key(item))) {
      const existing = change(item).grants ?? []
      change(item).grants = [
        ...existing,
        ...bulkGrants.value.filter(
          (grant) => !existing.some((current) => JSON.stringify(current) === JSON.stringify(grant)),
        ),
      ]
    }
}
async function save() {
  await api('/migration/draft', 'PUT', draft.value)
  saved.value = true
}
async function act(action: 'save' | 'review' | 'complete') {
  busy.value = true
  error.value = ''
  try {
    if (action === 'complete' && preview.value) {
      await api(
        '/migration/complete',
        'POST',
        {},
        { 'X-Access-Confirmation': preview.value.confirmation_token },
      )
      await auth.refresh(true)
      await router.replace('/')
    } else {
      await save()
      if (action === 'review') {
        preview.value = await api<MigrationPreview>('/migration/preview', 'POST', {})
        allocationsChanged.value = false
      }
    }
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    busy.value = false
  }
}
</script>
<template>
  <section class="panel migration">
    <h2>Set up ownership</h2>
    <p v-if="required" class="alert warning">
      Printing is paused until these assignments are confirmed. Existing printer holds remain in
      place.
    </p>
    <p v-else>The ownership migration is complete.</p>
    <p v-if="error" class="alert danger" role="alert">{{ error }}</p>
    <template v-if="catalog && required">
      <template v-if="!preview">
        <div class="row wrap spread">
          <h3>Printers & cartridges</h3>
          <RouterLink to="/resource-access">Manage locations</RouterLink>
        </div>
        <div class="row wrap migration-bulk">
          <label
            >Owner for selected<select v-model="bulkOwner">
              <option value="" disabled>Choose an owner</option>
              <option v-for="user in catalog.users" :key="user.id" :value="user.id">
                {{ user.name }}
              </option>
            </select></label
          ><button
            class="secondary"
            :disabled="!selected.length || !bulkOwner"
            @click="assignOwners"
          >
            Assign owner
          </button>
          <label
            >Location for selected<select v-model="bulkLocation">
              <option :value="null">Unassigned</option>
              <option v-for="location in catalog.locations" :key="location.id" :value="location.id">
                {{ location.name }}
              </option>
            </select></label
          ><button class="secondary" :disabled="!selected.length" @click="assignLocations">
            Assign location
          </button>
        </div>
        <div class="table-scroll">
          <table>
            <thead>
              <tr>
                <th>
                  <input
                    type="checkbox"
                    aria-label="Select all inventory"
                    :checked="!!resources.length && selected.length === resources.length"
                    @change="
                      selected = ($event.target as HTMLInputElement).checked
                        ? resources.map(key)
                        : []
                    "
                  />
                </th>
                <th>Name</th>
                <th>Owner</th>
                <th>Location</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in resources" :key="key(item)">
                <td>
                  <input
                    v-model="selected"
                    type="checkbox"
                    :value="key(item)"
                    :aria-label="`Select ${item.name}`"
                  />
                </td>
                <td>
                  {{ item.name }}<small>{{ item.kind }}</small>
                </td>
                <td>
                  <select v-model="change(item).owner_id" :aria-label="`Owner of ${item.name}`">
                    <option :value="null" disabled>Choose an owner</option>
                    <option v-for="user in catalog.users" :key="user.id" :value="user.id">
                      {{ user.name }}
                    </option>
                  </select>
                </td>
                <td>
                  <select
                    v-model="change(item).location_id"
                    :aria-label="`Location of ${item.name}`"
                  >
                    <option :value="null">Unassigned</option>
                    <option
                      v-for="location in catalog.locations"
                      :key="location.id"
                      :value="location.id"
                    >
                      {{ location.name }}
                    </option>
                  </select>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <AnimatedDetails class="settings-details"
          ><template #summary>Initial cartridge permissions</template>
          <ResourceGrants v-model="bulkGrants" :catalog="catalog" kind="cartridge" :roles="true" />
          <button
            class="secondary"
            :disabled="!selected.some((id) => id.startsWith('cartridge:')) || !bulkGrants.length"
            @click="assignGrants"
          >
            Grant to selected cartridges
          </button>
        </AnimatedDetails>
        <AnimatedDetails
          v-for="item in resources.filter((item) => item.kind === 'cartridge')"
          :key="item.id"
          class="settings-details"
          ><template #summary>{{ item.name }} permissions</template
          ><ResourceGrants
            v-model="change(item).grants!"
            :catalog="catalog"
            kind="cartridge"
            :roles="true"
        /></AnimatedDetails>
        <template v-if="adjustments.length">
          <h3>Historical repayments & adjustments</h3>
          <p>
            Choose who received each payment or adjustment. The recording operator is shown
            separately in the existing ledger.
          </p>
          <div class="row wrap migration-bulk">
            <label
              >Recipient for all<select v-model="bulkRecipient">
                <option value="" disabled>Choose a recipient</option>
                <option v-for="user in catalog.users" :key="user.id" :value="user.id">
                  {{ user.name }}
                </option>
              </select></label
            ><button
              class="secondary"
              :disabled="!bulkRecipient"
              @click="
                adjustments.forEach(
                  (item) => (draft.adjustment_recipients[item.id] = bulkRecipient),
                )
              "
            >
              Assign recipient
            </button>
          </div>
          <div class="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Payer</th>
                  <th>Amount</th>
                  <th>Reason</th>
                  <th>Recipient</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in adjustments" :key="item.id">
                  <td>{{ item.username }}</td>
                  <td>{{ (item.amount_minor / 100).toFixed(2) }} {{ item.currency }}</td>
                  <td>{{ item.note }}</td>
                  <td>
                    <select
                      v-model="draft.adjustment_recipients[item.id]"
                      :aria-label="`Recipient for ${item.note}`"
                    >
                      <option :value="undefined" disabled>Choose a recipient</option>
                      <option v-for="user in catalog.users" :key="user.id" :value="user.id">
                        {{ user.name }}
                      </option>
                    </select>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>
        <label v-if="lossWarning" class="checkbox alert warning"
          ><input v-model="draft.accept_owner_loss" type="checkbox" />Approve use can reduce
          cartridge owners' income. I accept this permission's effect.</label
        >
        <div class="row wrap">
          <button class="secondary" :disabled="busy" @click="act('save')">Save progress</button
          ><button
            :disabled="busy || (lossWarning && !draft.accept_owner_loss)"
            @click="act('review')"
          >
            Review migration</button
          ><span v-if="saved" role="status">Progress saved.</span>
        </div>
      </template>
      <template v-else>
        <h3>Resulting balances</h3>
        <div class="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Payer</th>
                <th>Recipient</th>
                <th>Owed</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="balance in preview.balances"
                :key="`${balance.requester_id}:${balance.recipient_id}:${balance.currency}`"
              >
                <td>{{ balance.requester_name }}</td>
                <td>{{ balance.recipient_name }}</td>
                <td>{{ balance.owed }} {{ balance.currency }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-if="!preview.balances.length">No debts between users.</p>
        <AnimatedDetails v-for="adjustment in preview.adjustments" :key="adjustment.id">
          <template #summary
            >{{ adjustment.note }} · {{ (adjustment.amount_minor / 100).toFixed(2) }}
            {{ adjustment.currency }}</template
          >
          <label v-for="row in allocationOptions(adjustment)" :key="row.cartridge_id">
            {{ row.cartridge_name }}
            <input
              type="number"
              min="0"
              step="0.000001"
              :aria-label="`Allocation of ${adjustment.note} to ${row.cartridge_name}`"
              :value="
                Math.abs(
                  (draft.adjustment_allocations[adjustment.id] ?? adjustment.cartridge_allocations)[
                    row.cartridge_id
                  ] ?? 0,
                ) / 1000000
              "
              @input="editAllocation(adjustment, row.cartridge_id, $event)"
            />
          </label>
          <p v-if="!allocationOptions(adjustment).length">
            No matching cartridge debts. This adjustment remains unallocated.
          </p>
        </AnimatedDetails>
        <h3>Permission changes</h3>
        <ResourceImpact :changes="preview.affected_users" :resources="catalog.resources" />
        <div class="row wrap">
          <button v-if="allocationsChanged" :disabled="busy" @click="act('review')">
            Review allocations
          </button>
          <button :disabled="busy || allocationsChanged" @click="act('complete')">
            Complete migration</button
          ><button class="secondary" :disabled="busy" @click="preview = undefined">Back</button>
        </div>
      </template>
    </template>
  </section>
</template>
<style scoped>
.migration-bulk {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr) auto;
  align-items: end;
  margin: 1rem 0;
}
@media (max-width: 700px) {
  .migration-bulk {
    grid-template-columns: minmax(0, 1fr) auto;
  }
}
.migration small {
  display: block;
}
.migration h3 {
  margin-top: 1.5rem;
}
.migration td select {
  min-width: 10rem;
}
</style>
