<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, errorMessage } from '../shared/api'
import { useAuthStore } from '../auth/auth'
import type {
  AccessCatalog,
  AccessPreview,
  ResourceChange,
  ResourceEntry,
} from '../shared/resourceAccess'
import { exclusiveGrantModes } from '../shared/resourceAccess'
import AdminDialog from '../components/AdminDialog.vue'
import ResourceGrants from '../components/ResourceGrants.vue'
import ResourceImpact from '../components/ResourceImpact.vue'
import AccessGraph from '../components/AccessGraph.vue'
import { useRoute } from 'vue-router'
const auth = useAuthStore()
const route = useRoute()
const graphOpen = ref(false)
const graphResource = ref('')
const graphUser = ref('')
function openGraph(item?: ResourceEntry) {
  graphResource.value = item ? `${item.kind}:${item.id}` : ''
  graphOpen.value = true
}
const catalog = ref<AccessCatalog>()
const error = ref(''),
  busy = ref(false),
  saved = ref('')
const selected = ref<ResourceEntry>()
const form = ref<ResourceChange>()
const preview = ref<AccessPreview>()
const accepted = ref(false)
const filter = ref('')
const locationFilter = ref('')
const ownerFilter = ref('')
const resources = computed(
  () =>
    catalog.value?.resources.filter((item) => {
      const location = item.kind === 'location' ? item.parent_id : item.location_id
      return (
        (!filter.value || item.kind === filter.value) &&
        (!locationFilter.value ||
          (locationFilter.value === 'unassigned'
            ? !location
            : location === locationFilter.value)) &&
        (!ownerFilter.value ||
          (ownerFilter.value === 'unowned' ? !item.owner_id : item.owner_id === ownerFilter.value))
      )
    }) ?? [],
)
async function load() {
  catalog.value = await api<AccessCatalog>('/resource-access')
}
onMounted(async () => {
  try {
    await load()
    if (typeof route.query.user === 'string') {
      graphUser.value = route.query.user
      openGraph()
    }
  } catch (e) {
    error.value = errorMessage(e)
  }
})
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
    ...(item.abilities.transfer && (item.owner_id || item.kind === 'location')
      ? { owner_id: item.owner_id }
      : {}),
    ...(item.kind !== 'location' && item.abilities.locate ? { location_id: item.location_id } : {}),
    ...(item.abilities.grants
      ? {
          grants: exclusiveGrantModes(item.grants)
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
    abilities: { transfer: true, locate: true, grants: true, roles: true },
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
      <h2>{{ $t('resourceAccess.resources') }}</h2>
      <div class="row wrap">
        <button class="secondary" @click="openGraph()">{{ $t('common.permissionsGraph') }}</button
        ><button v-if="catalog?.manage_locations" @click="createLocation">
          {{ $t('resourceAccess.newLocation') }}
        </button>
      </div>
    </div>
    <p v-if="error && !form" class="alert danger" role="alert">{{ error }}</p>
    <p v-if="saved" class="alert success" role="status">{{ saved }}</p>
    <div class="resource-filters">
      <label
        >{{ $t('common.show')
        }}<select v-model="filter">
          <option value="">{{ $t('resourceAccess.allResources') }}</option>
          <option value="location">{{ $t('common.locations') }}</option>
          <option value="printer">{{ $t('common.printers') }}</option>
          <option value="cartridge">{{ $t('resourceAccess.cartridges') }}</option>
        </select></label
      >
      <label
        >{{ $t('resourceAccess.filterByLocation')
        }}<select v-model="locationFilter">
          <option value="">{{ $t('resourceAccess.allLocations') }}</option>
          <option value="unassigned">{{ $t('common.unassigned') }}</option>
          <option v-for="location in catalog?.locations" :key="location.id" :value="location.id">
            {{ location.name }}
          </option>
        </select></label
      >
      <label
        >{{ $t('resourceAccess.filterByOwner')
        }}<select v-model="ownerFilter">
          <option value="">{{ $t('resourceAccess.allOwners') }}</option>
          <option value="unowned">{{ $t('common.noOwner') }}</option>
          <option v-for="user in catalog?.users" :key="user.id" :value="user.id">
            {{ user.name }}
          </option>
        </select></label
      >
    </div>
    <div class="table-scroll">
      <table>
        <thead>
          <tr>
            <th>{{ $t('common.name') }}</th>
            <th>{{ $t('common.type') }}</th>
            <th>{{ $t('common.owner') }}</th>
            <th>{{ $t('common.location') }}</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in resources" :key="`${item.kind}:${item.id}`">
            <td>{{ item.name }}</td>
            <td>{{ item.kind }}</td>
            <td>
              {{
                catalog?.users.find((user) => user.id === item.owner_id)?.name ??
                $t('common.noOwner')
              }}
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
              <div class="row wrap">
                <button class="secondary" :aria-label="`Manage ${item.name}`" @click="edit(item)">
                  {{ $t('resourceAccess.manage') }}</button
                ><button
                  class="secondary"
                  :aria-label="`Permissions graph for ${item.name}`"
                  @click="openGraph(item)"
                >
                  {{ $t('common.permissionsGraph') }}
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-if="catalog && !resources.length" class="empty">
      {{ $t('resourceAccess.noResourcesToManage') }}
    </p>
  </section>
  <AdminDialog
    :open="graphOpen"
    :title="$t('common.permissionsGraph')"
    wide
    @close="graphOpen = false"
  >
    <AccessGraph
      v-if="graphOpen && catalog"
      :catalog="catalog"
      :initial-resource="graphResource"
      :initial-user="graphUser || undefined"
    />
  </AdminDialog>
  <AdminDialog
    :open="!!form"
    :title="preview ? 'Review access changes' : selected?.name || $t('resourceAccess.newLocation')"
    :busy="busy"
    @close="form = undefined"
  >
    <template v-if="form && selected && catalog">
      <p v-if="error" class="alert danger" role="alert">{{ error }}</p>
      <form v-if="!preview" class="form-stack" @submit.prevent="review">
        <template v-if="form.kind === 'location'"
          ><label
            >{{ $t('resourceAccess.locationName')
            }}<input v-model="form.name" required maxlength="100" /></label
          ><label
            >{{ $t('resourceAccess.parentLocation')
            }}<select v-model="form.parent_id">
              <option :value="null">{{ $t('resourceAccess.none') }}</option>
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
          >{{ $t('common.owner')
          }}<select v-model="form.owner_id">
            <option
              :value="form.kind === 'location' ? null : undefined"
              :disabled="form.kind !== 'location'"
            >
              {{ $t('common.noOwner') }}
            </option>
            <option v-for="user in catalog.users" :key="user.id" :value="user.id">
              {{ user.name }}
            </option>
          </select></label
        >
        <p v-if="selected.inherited_location" class="muted">
          {{ $t('resourceAccess.locationIsInheritedFromTheCompanion') }}
        </p>
        <label v-if="selected.abilities.locate && form.kind !== 'location'"
          >{{ $t('common.location')
          }}<select v-model="form.location_id">
            <option :value="null">{{ $t('common.unassigned') }}</option>
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
          :identifier="form.identifier"
          :roles="selected.abilities.roles"
        />
        <button :disabled="busy">{{ $t('resourceAccess.reviewChanges') }}</button>
      </form>
      <template v-else>
        <p v-if="preview.claims_unassigned_debts" class="alert warning">
          {{ $t('common.unassignedDebtsForThisCartridgeWillBelongToThe') }}
        </p>
        <ResourceImpact :changes="preview.affected_users" :resources="catalog.resources" />
        <label v-if="preview.owner_loss_warning" class="checkbox alert warning"
          ><input v-model="accepted" type="checkbox" />{{
            $t('resourceAccess.approveUseCanReduceTheCartridgeOwnerSIncome')
          }}</label
        >
        <div class="row wrap">
          <button :disabled="busy || (preview.owner_loss_warning && !accepted)" @click="confirm">
            {{ $t('resourceAccess.confirmAccessChanges') }}</button
          ><button class="secondary" :disabled="busy" @click="preview = undefined">
            {{ $t('common.back') }}
          </button>
        </div>
      </template>
    </template>
  </AdminDialog>
</template>

<style scoped>
.resource-filters {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 180px), 1fr));
  gap: 16px;
  margin-block: 20px;
}
</style>
