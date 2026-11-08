<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, errorMessage } from '../api'
import { useAuthStore } from '../auth'
import type { AccessCatalog, AccessPreview, ResourceChange, ResourceEntry } from '../resourceAccess'
import AdminDialog from '../components/AdminDialog.vue'
import ResourceGrants from '../components/ResourceGrants.vue'
import ResourceImpact from '../components/ResourceImpact.vue'
const auth = useAuthStore()
const catalog = ref<AccessCatalog>()
const error = ref(''),
  busy = ref(false),
  saved = ref('')
const selected = ref<ResourceEntry>()
const form = ref<ResourceChange>()
const preview = ref<AccessPreview>()
const accepted = ref(false)
const filter = ref('')
const resources = computed(
  () =>
    catalog.value?.resources.filter((item) => !filter.value || item.kind === filter.value) ?? [],
)
async function load() {
  catalog.value = await api<AccessCatalog>('/resource-access')
}
onMounted(() => load().catch((e) => (error.value = errorMessage(e))))
function edit(item: ResourceEntry) {
  selected.value = item
  preview.value = undefined
  accepted.value = false
  error.value = ''
  saved.value = ''
  form.value = {
    kind: item.kind,
    identifier: item.id,
    ...(item.kind === 'location' ? { name: item.name, parent_id: item.parent_id } : {}),
    ...(item.abilities.transfer && item.owner_id ? { owner_id: item.owner_id } : {}),
    ...(item.kind !== 'location' && item.abilities.locate ? { location_id: item.location_id } : {}),
    ...(item.abilities.grants
      ? {
          grants: item.grants
            .filter((g) => item.abilities.roles || g.principal_kind === 'user')
            .map((g) => ({ ...g })),
        }
      : {}),
  }
}
function createLocation() {
  edit({
    kind: 'location',
    id: crypto.randomUUID(),
    name: '',
    parent_id: null,
    owner_id: null,
    location_id: null,
    grants: [],
    abilities: { transfer: false, locate: true, grants: true, roles: true },
  })
}
async function review() {
  if (!form.value) return
  busy.value = true
  error.value = ''
  try {
    preview.value = await api<AccessPreview>('/resource-access/preview', 'POST', form.value)
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    busy.value = false
  }
}
async function confirm() {
  if (!form.value || !preview.value) return
  busy.value = true
  error.value = ''
  try {
    await api(
      '/resource-access/apply',
      'POST',
      { ...form.value, accept_owner_loss: accepted.value },
      { 'X-Access-Confirmation': preview.value.confirmation_token },
    )
    form.value = undefined
    preview.value = undefined
    saved.value = 'Access saved.'
    await auth.refresh(true)
    await load()
  } catch (e) {
    error.value = errorMessage(e)
    preview.value = undefined
  } finally {
    busy.value = false
  }
}
</script>
<template>
  <section class="panel">
    <div class="row wrap spread">
      <h2>Resources</h2>
      <button v-if="catalog?.manage_locations" @click="createLocation">New location</button>
    </div>
    <p v-if="error && !form" class="alert danger" role="alert">{{ error }}</p>
    <p v-if="saved" class="alert success" role="status">{{ saved }}</p>
    <label
      >Show<select v-model="filter">
        <option value="">All resources</option>
        <option value="location">Locations</option>
        <option value="printer">Printers</option>
        <option value="cartridge">Cartridges</option>
      </select></label
    >
    <div class="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Type</th>
            <th>Owner</th>
            <th>Location</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in resources" :key="`${item.kind}:${item.id}`">
            <td>{{ item.name }}</td>
            <td>{{ item.kind }}</td>
            <td>
              {{ catalog?.users.find((user) => user.id === item.owner_id)?.name ?? 'No owner' }}
            </td>
            <td>
              {{
                catalog?.locations.find(
                  (location) =>
                    location.id === (item.kind === 'location' ? item.parent_id : item.location_id),
                )?.name ?? '—'
              }}
            </td>
            <td>
              <button class="secondary" :aria-label="`Manage ${item.name}`" @click="edit(item)">
                Manage
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-if="catalog && !resources.length" class="empty">No resources to manage.</p>
  </section>
  <AdminDialog
    :open="!!form"
    :title="preview ? 'Review access changes' : selected?.name || 'New location'"
    :busy="busy"
    @close="form = undefined"
  >
    <template v-if="form && selected && catalog">
      <p v-if="error" class="alert danger" role="alert">{{ error }}</p>
      <form v-if="!preview" class="form-stack" @submit.prevent="review">
        <template v-if="form.kind === 'location'"
          ><label>Location name<input v-model="form.name" required maxlength="100" /></label
          ><label
            >Parent location<select v-model="form.parent_id">
              <option :value="null">None</option>
              <option
                v-for="location in catalog.locations.filter((item) => item.id !== form!.identifier)"
                :key="location.id"
                :value="location.id"
              >
                {{ location.name }}
              </option>
            </select></label
          ></template
        >
        <label v-if="selected.abilities.transfer"
          >Owner<select v-model="form.owner_id">
            <option :value="undefined" disabled>No owner</option>
            <option v-for="user in catalog.users" :key="user.id" :value="user.id">
              {{ user.name }}
            </option>
          </select></label
        >
        <p v-if="selected.inherited_location" class="muted">Location is inherited from the companion.</p>
        <label v-if="selected.abilities.locate && form.kind !== 'location'"
          >Location<select v-model="form.location_id">
            <option :value="null">Unassigned</option>
            <option v-for="location in catalog.locations" :key="location.id" :value="location.id">
              {{ location.name }}
            </option>
          </select></label
        >
        <ResourceGrants
          v-if="form.grants"
          v-model="form.grants"
          :catalog="catalog"
          :kind="form.kind"
          :roles="selected.abilities.roles"
        />
        <button :disabled="busy">Review changes</button>
      </form>
      <template v-else>
        <p v-if="preview.claims_unassigned_debts" class="alert warning">
          Unassigned debts for this cartridge will belong to the selected owner.
        </p>
        <ResourceImpact :changes="preview.affected_users" :resources="catalog.resources" />
        <label v-if="preview.owner_loss_warning" class="checkbox alert warning"
          ><input v-model="accepted" type="checkbox" />Approve use can reduce the cartridge owner's
          income. I accept this permission's effect.</label
        >
        <div class="row wrap">
          <button :disabled="busy || (preview.owner_loss_warning && !accepted)" @click="confirm">
            Confirm access changes</button
          ><button class="secondary" :disabled="busy" @click="preview = undefined">Back</button>
        </div>
      </template>
    </template>
  </AdminDialog>
</template>
