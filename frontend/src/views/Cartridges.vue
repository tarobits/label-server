<script setup lang="ts">
import CartridgePrice from '../components/CartridgePrice.vue'
import CartridgeDetection from '../components/CartridgeDetection.vue'
import { installCartridge } from '../cartridges'
import { freezeLeavingItem } from '../collectionMotion'
import { vValidateForm } from '../formValidation'
import { storeToRefs } from 'pinia'
import { computed, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../api'
import { confirmAction } from '../confirmation'
import { useAuthStore } from '../auth'
import { useWorkspaceStore, metres } from '../workspace'
import type { Cartridge, Status } from '../types'
const w = useWorkspaceStore()
const auth = useAuthStore()
const route = useRoute()
const { profiles, cartridges, busy } = storeToRefs(w)
const inventoryView = ref('active')
const editing = ref<string | null>(null),
  cartridgeName = ref(''),
  nameInput = ref<HTMLInputElement[]>([])
const visibleCartridges = computed(() =>
  cartridges.value.filter(
    (cartridge) => !!cartridge.archived === (inventoryView.value === 'archived'),
  ),
)
const printerId = ref('')
watch(
  () =>
    [
      typeof route.query.printer === 'string' ? route.query.printer : w.selectedPrinter,
      w.printers,
    ] as const,
  ([selected, printers], previous) => {
    if (
      (!previous ||
        selected !== previous[0] ||
        !printers.some((printer) => printer.id === printerId.value)) &&
      printers.some((printer) => printer.id === selected)
    )
      printerId.value = selected
    else if (!printers.some((printer) => printer.id === printerId.value))
      printerId.value =
        printers.find((printer) => auth.atLeast(printer.id, 'full'))?.id ?? printers[0]?.id ?? ''
  },
  { immediate: true },
)
const selectedPrinter = computed(() => w.printers.find((printer) => printer.id === printerId.value))
const selectedStatus = computed(() =>
  w.printerStatuses.find((printer) => printer.printer_id === printerId.value),
)
function isLocked(status: Status | undefined) {
  return !!status && (!!status.printing || !!status.needs_review.length)
}
const locked = computed(
  () => isLocked(selectedStatus.value) || !!selectedStatus.value?.pending_flush,
)
const canSwap = computed(() => !!selectedStatus.value && auth.atLeast(printerId.value, 'full'))
function installedIn(id: string) {
  return w.printerStatuses.find((printer) => printer.active_cartridge_id === id)
}
function correctionLocked(id: string) {
  return (
    cartridges.value.find((cartridge) => cartridge.id === id)?.estimate_locked ||
    isLocked(installedIn(id))
  )
}
function isInstalled(cartridge: Cartridge) {
  return cartridge.installed || !!installedIn(cartridge.id)
}
function removalReason(cartridge: Cartridge) {
  if (cartridge.archive_blocked_reason)
    return cartridge.archive_blocked_reason.replace('archiving', 'archiving or deleting')
  if (cartridge.delete_blocked_reason)
    return cartridge.archived
      ? 'Cartridges with print or queue history cannot be permanently deleted.'
      : cartridge.delete_blocked_reason
  return ''
}
const showForm = ref(false),
  correcting = ref<string | null>(null),
  correction = ref(0)
const form = reactive({
  profile_id: profiles.value[0]?.id ?? '',
  name: '',
  nominal: 8,
  remaining: 8,
  price: '',
  currency: 'EUR',
})
async function save() {
  if (
    await w.action(
      () =>
        api('/cartridges', 'POST', {
          profile_id: form.profile_id,
          name: form.name,
          price_minor: form.price === '' ? null : Math.round(Number(form.price) * 100),
          currency: form.currency,
          nominal_length_mm: form.nominal * 1000,
          remaining_mm: form.remaining * 1000,
        }),
      'Cartridge registered. Install it when it is in the printer.',
    )
  ) {
    showForm.value = false
    inventoryView.value = 'active'
    form.name = ''
  }
}
async function archive(cartridge: Cartridge) {
  if (
    !(await confirmAction(
      `Archive “${cartridge.name}”? It will no longer appear in active inventory or printing choices. Its history, usage and costs remain available.`,
      'Archive cartridge',
    ))
  )
    return
  if (await w.action(() => api(`/cartridges/${cartridge.id}`, 'DELETE'), 'Cartridge archived.'))
    correcting.value = null
}
function startRename(cartridge: Cartridge) {
  editing.value = cartridge.id
  cartridgeName.value = cartridge.name
}
function focusName() {
  if (editing.value) {
    nameInput.value[0]?.focus()
    nameInput.value[0]?.select()
  }
}
async function rename(cartridge: Cartridge) {
  if (!cartridgeName.value.trim()) return
  if (
    await w.action(
      () => api(`/cartridges/${cartridge.id}`, 'PUT', { name: cartridgeName.value.trim() }),
      'Cartridge renamed.',
    )
  )
    editing.value = null
}
async function restore(cartridge: Cartridge) {
  await w.action(
    () => api(`/cartridges/${cartridge.id}/restore`, 'POST'),
    'Cartridge restored to inventory.',
  )
}
async function remove(cartridge: Cartridge) {
  if (
    !(await confirmAction(
      `Permanently delete “${cartridge.name}”? This removes its inventory record and cannot be undone.`,
      'Delete permanently',
    ))
  )
    return
  if (
    await w.action(
      () => api(`/cartridges/${cartridge.id}/permanent`, 'DELETE'),
      'Cartridge permanently deleted.',
    )
  )
    correcting.value = null
}
async function install(id: string | null) {
  const target = printerId.value
  const name = selectedPrinter.value?.name ?? 'printer'
  await w.action(
    () => installCartridge(target, id),
    id
      ? `Cartridge installed in ${name}. Eligible queued labels may now print.`
      : `Cartridge removed from ${name}.`,
  )
}
function startCorrection(cartridge: Cartridge) {
  correcting.value = cartridge.id
  correction.value = cartridge.remaining_mm / 1000
}
async function correct(id: string) {
  if (
    await w.action(
      () => api(`/cartridges/${id}/remaining`, 'PUT', { remaining_mm: correction.value * 1000 }),
      'Remaining tape estimate updated.',
    )
  )
    correcting.value = null
}
</script>
<template>
  <div class="section-heading">
    <div class="row wrap cartridge-filters">
      <label v-if="w.printers.length" class="cartridge-printer"
        >Printer<select v-model="printerId" :disabled="busy">
          <option v-for="printer in w.printers" :key="printer.id" :value="printer.id">
            {{ printer.name }}
          </option>
        </select></label
      >
      <label class="cartridge-view"
        >Inventory<select v-model="inventoryView" :disabled="busy">
          <option value="active">Active</option>
          <option value="archived">Archived</option>
        </select></label
      >
    </div>
    <button class="secondary" :disabled="!profiles.length" @click="showForm = !showForm">
      Register cartridge
    </button>
  </div>
  <p class="muted">
    {{
      selectedPrinter
        ? `Select the cassette physically installed in ${selectedPrinter.name}.`
        : 'No physical printers are assigned. Cartridges can be registered for later installation.'
    }}
  </p>
  <p v-if="locked" class="alert warning">
    Finish printing, resolve the pending review, or cancel the pending flush on
    {{ selectedPrinter?.name }} before swapping cartridges.
  </p>
  <Transition name="panel-expand">
    <form v-validate-form v-if="showForm" class="panel form-stack" @submit.prevent="save">
      <h2>Register a cartridge</h2>
      <div class="field-row">
        <label
          >Cartridge name<input
            v-model="form.name"
            required
            maxlength="100"
            placeholder="Yellow cassette 1" /></label
        ><label
          >Tape profile<select v-model="form.profile_id" required>
            <option disabled value="">Select a tape</option>
            <option v-for="profile in profiles" :key="profile.id" :value="profile.id">
              {{ profile.name }}
            </option>
          </select></label
        >
      </div>
      <div class="field-row">
        <label
          >Length on packaging (m)<input
            v-model.number="form.nominal"
            type="number"
            min="0.001"
            max="1000"
            step="0.001"
            required /></label
        ><label
          >Estimated remaining (m)<input
            v-model.number="form.remaining"
            type="number"
            min="0"
            :max="form.nominal"
            step="0.001"
            required
        /></label>
      </div>
      <div class="field-row">
        <label
          >Cartridge price<input
            v-model="form.price"
            type="number"
            min="0"
            max="10000000"
            step="0.01"
        /></label>
        <label
          >Currency<input v-model="form.currency" required pattern="[A-Z]{3}" maxlength="3"
        /></label>
      </div>
      <div class="row">
        <button class="primary" :disabled="busy">Register cartridge</button
        ><button type="button" @click="showForm = false">Cancel</button>
      </div>
    </form>
  </Transition>
  <CartridgeDetection :status="selectedStatus" />
  <Transition name="notice"
    ><div v-if="!visibleCartridges.length" class="panel empty motion-reveal">
      <h2>
        {{ inventoryView === 'archived' ? 'No archived cartridges.' : 'No active cartridges.' }}
      </h2>
      <RouterLink
        v-if="!profiles.length && inventoryView === 'active'"
        class="button primary"
        to="/profiles"
        >Create a tape profile first</RouterLink
      >
    </div></Transition
  >
  <TransitionGroup
    tag="div"
    class="cartridge-grid"
    name="collection"
    @before-leave="freezeLeavingItem"
  >
    <article
      v-for="cartridge in visibleCartridges"
      :key="cartridge.id"
      class="panel cartridge-card"
    >
      <div class="section-heading">
        <span class="eyebrow">{{ w.profileName(cartridge.profile_id) }}</span
        ><span v-if="cartridge.archived" class="badge">Archived</span
        ><span v-else-if="isInstalled(cartridge)" class="badge printed">{{
          installedIn(cartridge.id)
            ? `Installed in ${installedIn(cartridge.id)?.printer_name}`
            : 'Installed in another printer'
        }}</span>
      </div>
      <Transition name="notice" mode="out-in" @after-enter="focusName"
        ><form
          v-if="editing === cartridge.id"
          v-validate-form
          class="form-stack motion-reveal"
          @submit.prevent="rename(cartridge)"
          @keydown.esc.prevent="editing = null"
        >
          <label
            >Cartridge name<input
              ref="nameInput"
              v-model="cartridgeName"
              required
              maxlength="100"
              :disabled="busy"
          /></label>
          <div class="row wrap">
            <button class="small primary" :disabled="busy || !cartridgeName.trim()">
              Save name
            </button>
            <button type="button" class="small secondary" :disabled="busy" @click="editing = null">
              Cancel
            </button>
          </div>
        </form>
        <div v-else class="row spread cartridge-name motion-reveal">
          <h2>{{ cartridge.name }}</h2>
          <button class="text-button" :disabled="busy" @click="startRename(cartridge)">
            Rename
          </button>
        </div></Transition
      >
      <p class="remaining">
        ≈ {{ metres(cartridge.remaining_mm)
        }}<small>of {{ metres(cartridge.nominal_length_mm) }}</small>
      </p>
      <progress
        :value="cartridge.remaining_mm"
        :max="cartridge.nominal_length_mm"
        :aria-label="`${cartridge.name} remaining tape`"
      ></progress>
      <p v-if="cartridge.consumption_uncertain" class="inline-warning">
        Consumption uncertain. Reconcile it during batch review.
      </p>
      <form
        v-validate-form
        v-if="correcting === cartridge.id && !cartridge.archived"
        class="form-stack inset"
        @submit.prevent="correct(cartridge.id)"
      >
        <label
          >Remaining tape (m)<input
            v-model.number="correction"
            type="number"
            min="0"
            :max="cartridge.nominal_length_mm / 1000"
            step="0.001"
            required
        /></label>
        <div class="row">
          <button :disabled="busy || correctionLocked(cartridge.id)" class="secondary">
            Save estimate</button
          ><button type="button" @click="correcting = null">Cancel</button>
        </div>
      </form>
      <div v-else aria-hidden="true"></div>
      <CartridgePrice v-if="!cartridge.archived" :cartridge="cartridge" />
      <p v-else class="help">
        Price:
        {{
          cartridge.price_minor === null
            ? 'Not set'
            : `${(cartridge.price_minor / 100).toFixed(2)} ${cartridge.currency}`
        }}
      </p>
      <div class="card-actions">
        <template v-if="!cartridge.archived">
          <button
            v-if="!isInstalled(cartridge) && canSwap"
            class="secondary"
            :disabled="busy || locked"
            @click="install(cartridge.id)"
          >
            Install cartridge</button
          ><button
            v-else-if="installedIn(cartridge.id)?.printer_id === printerId && canSwap"
            :disabled="busy || locked"
            @click="install(null)"
          >
            Remove from printer</button
          ><button
            class="text-button"
            :disabled="busy || correctionLocked(cartridge.id)"
            @click="startCorrection(cartridge)"
          >
            Correct estimate
          </button>
          <button
            class="text-button"
            :disabled="busy || !!cartridge.archive_blocked_reason"
            :title="cartridge.archive_blocked_reason ?? undefined"
            :aria-describedby="
              cartridge.archive_blocked_reason ? `removal-${cartridge.id}` : undefined
            "
            @click="archive(cartridge)"
          >
            Archive cartridge
          </button>
        </template>
        <button v-else class="secondary" :disabled="busy" @click="restore(cartridge)">
          Restore cartridge
        </button>
        <button
          class="text-button danger-text"
          :disabled="busy || !!cartridge.delete_blocked_reason"
          :title="cartridge.delete_blocked_reason ?? undefined"
          :aria-describedby="
            cartridge.delete_blocked_reason ? `removal-${cartridge.id}` : undefined
          "
          @click="remove(cartridge)"
        >
          Delete permanently
        </button>
      </div>
      <div>
        <Transition name="notice" mode="out-in">
          <p
            v-if="removalReason(cartridge)"
            :id="`removal-${cartridge.id}`"
            :key="removalReason(cartridge)"
            class="help motion-reveal"
          >
            {{ removalReason(cartridge) }}
          </p>
        </Transition>
      </div>
    </article>
  </TransitionGroup>
</template>

<style scoped>
.cartridge-filters {
  align-items: end;
  flex: 1;
  min-width: 0;
}
.cartridge-view {
  width: min(160px, 100%);
}
.cartridge-name h2 {
  min-width: 0;
}
.cartridge-name {
  align-items: start;
}
.cartridge-name button {
  flex-shrink: 0;
}
.cartridge-printer {
  width: min(320px, 100%);
}
.cartridge-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(300px, 100%), 1fr));
  gap: 20px;
  align-items: stretch;
}
.cartridge-card {
  display: grid;
  grid-template-rows: auto auto auto auto 1fr auto auto auto auto;
  grid-row: span 9;
  row-gap: 12px;
  min-width: 0;
  margin-bottom: 0;
}
@supports (grid-template-rows: subgrid) {
  .cartridge-card {
    grid-template-rows: subgrid;
  }
}
.cartridge-card .section-heading {
  align-items: start;
  flex-wrap: nowrap;
  gap: 10px;
  margin: 0;
}
.cartridge-card .eyebrow {
  min-width: 0;
  overflow-wrap: anywhere;
}
.cartridge-card .badge {
  flex-shrink: 1;
  text-align: right;
  overflow-wrap: anywhere;
  white-space: normal;
}
.cartridge-card h2,
.cartridge-card p,
.cartridge-card progress,
.cartridge-card .inset {
  margin: 0;
}
.cartridge-card h2 {
  overflow-wrap: anywhere;
}
.cartridge-card .remaining {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 8px;
  margin: 0 !important;
}
.cartridge-card .remaining small {
  margin-left: 0;
}
.cartridge-card .inline-warning {
  font-size: 12px;
}
.cartridge-card .card-actions {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  align-items: stretch;
  margin: 0;
  padding-top: 16px;
}
.cartridge-card .card-actions button {
  min-width: 0;
  white-space: normal;
}
.cartridge-card .inset .row {
  flex-wrap: wrap;
}
@media (max-width: 600px) {
  .cartridge-grid {
    gap: 16px;
  }
}
</style>
