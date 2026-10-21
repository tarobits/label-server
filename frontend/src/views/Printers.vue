<script setup lang="ts">
import { vValidateForm } from '../formValidation'
import { useAuthStore } from '../auth'
import { computed, reactive, ref } from 'vue'
import { api } from '../api'
import { requestPrinting } from '../printing'
import { useWorkspaceStore, metres } from '../workspace'
import PropertySection from '../components/PropertySection.vue'
import type { Destination, Printer } from '../types'
const w = useWorkspaceStore()
const auth = useAuthStore()
const showPrinter = ref(false),
  showGroup = ref(false),
  editing = ref('')
const editingPrinter = ref('')
async function cancelFlush(id: string) {
  const pending = state(id)?.pending_flush
  if (pending)
    await w.action(
      () => api(`/queue/flush/${pending}`, 'DELETE'),
      'Pending flush cancelled. Copies remain queued.',
    )
}
const defaults = () => ({
  name: '',
  driver: 'brother-pt-p710bt',
  usb_serial: '',
  resolution: 'high',
  feed_mm: 2,
  leader_mm: 24.5,
  cut_each: true,
  timeout_seconds: 120,
})
const printer = reactive(defaults())
function editPrinter(device?: Printer) {
  editingPrinter.value = device?.id ?? ''
  Object.assign(
    printer,
    defaults(),
    device
      ? {
          ...device.config,
          name: device.name,
          driver: device.driver,
          usb_serial: device.config.usb_serial ?? '',
        }
      : {},
  )
  showPrinter.value = true
  window.scrollTo({ top: 0, behavior: 'smooth' })
}
const group = reactive({ name: '', printer_ids: [] as string[] })
const groups = computed(() => w.destinations.filter((d) => d.kind === 'group'))
const groupChoices = computed(() => {
  const existing = w.destinations.find((d) => d.id === editing.value)
  return [
    ...new Set([
      ...w.printers.filter((p) => auth.atLeast(p.id, 'full')).map((p) => p.id),
      ...(existing?.printer_ids ?? []),
    ]),
  ].map((id) => ({ id, name: existing?.member_names?.[id] ?? w.destinationName(id) }))
})
const state = (id: string) => w.printerStatuses.find((s) => s.printer_id === id)
const cartridge = (id: string) => w.cartridges.find((c) => c.id === state(id)?.active_cartridge_id)
function availableCartridges(id: string) {
  return w.cartridges.filter(
    (c) =>
      c.id === state(id)?.active_cartridge_id ||
      (!c.installed && !w.printerStatuses.some((s) => s.active_cartridge_id === c.id)),
  )
}
async function addPrinter() {
  if (
    await w.action(
      () =>
        api(
          `/printers${editingPrinter.value ? `/${editingPrinter.value}` : ''}`,
          editingPrinter.value ? 'PUT' : 'POST',
          {
            ...printer,
            usb_serial: printer.usb_serial.trim() || null,
          },
        ),
      editingPrinter.value
        ? 'Printer configuration saved.'
        : 'Printer registered. Install its cartridge to make matching labels eligible.',
    )
  ) {
    showPrinter.value = false
    printer.name = ''
    printer.usb_serial = ''
  }
}
function editGroup(target?: Destination) {
  editing.value = target?.id ?? ''
  group.name = target?.name ?? ''
  group.printer_ids = [...(target?.printer_ids ?? [])]
  showGroup.value = true
}
async function saveGroup() {
  if (
    await w.action(
      () =>
        api(
          `/printer-groups${editing.value ? `/${editing.value}` : ''}`,
          editing.value ? 'PUT' : 'POST',
          group,
        ),
      'Printer group saved.',
    )
  )
    showGroup.value = false
}
async function install(id: string, event: Event) {
  await w.action(
    () =>
      api(`/printer/active-tape?printer_id=${encodeURIComponent(id)}`, 'PUT', {
        cartridge_id: (event.target as HTMLSelectElement).value || null,
      }),
    'Installed cartridge updated.',
  )
}
async function hold(id: string, held: boolean) {
  await w.action(
    () => api(`/destinations/${id}/automatic-printing`, 'PUT', { held }),
    held ? 'Automatic printing held.' : 'Automatic printing resumed.',
  )
}
async function print(id: string) {
  await w.action(
    () => requestPrinting(`/destinations/${id}/print`),
    'Matching labels requested on available printers.',
  )
}
function move(index: number, offset: number) {
  const ids = [...group.printer_ids]
  const [id] = ids.splice(index, 1)
  ids.splice(index + offset, 0, id!)
  group.printer_ids = ids
}
</script>
<template>
  <div class="section-heading">
    <div class="row wrap">
      <button v-if="auth.can('printers.manage')" class="secondary" @click="editPrinter()">
        Add printer</button
      ><button v-if="auth.can('printers.manage')" class="primary" @click="editGroup()">
        Create group
      </button>
    </div>
  </div>
  <form v-validate-form v-if="showPrinter" class="panel form-stack" @submit.prevent="addPrinter">
    <h2>{{ editingPrinter ? 'Edit printer' : 'Add printer' }}</h2>
    <div class="field-row">
      <label>Printer name<input v-model="printer.name" required maxlength="100" /></label>
      <label
        >Driver<select v-model="printer.driver">
          <option value="brother-pt-p710bt">Brother PT-P710BT (USB)</option>
        </select></label
      >
      <label>USB serial number<input v-model="printer.usb_serial" maxlength="128" /></label>
      <label
        >Default print resolution<select v-model="printer.resolution">
          <option value="normal">180 × 180 dpi</option>
          <option value="high">180 × 360 dpi</option>
        </select></label
      >
    </div>
    <PropertySection title="Feed & cut settings">
      <div class="field-row">
        <label
          >Feed (mm)<input
            v-model.number="printer.feed_mm"
            type="number"
            min="2"
            max="127"
            step="0.1"
            required
        /></label>
        <label
          >Leader estimate (mm)<input
            v-model.number="printer.leader_mm"
            type="number"
            min="0"
            max="200"
            step="0.1"
            required
        /></label>
        <label
          >Page timeout (seconds)<input
            v-model.number="printer.timeout_seconds"
            type="number"
            min="5"
            max="600"
            required
        /></label>
      </div>
      <label class="checkbox"
        ><input v-model="printer.cut_each" type="checkbox" />Cut each label</label
      >
    </PropertySection>

    <p class="help">
      USB serial is optional for one printer. Multiple printers each need a distinct serial.
    </p>
    <div class="row">
      <button class="primary" :disabled="w.busy">
        {{ editingPrinter ? 'Save printer' : 'Register printer' }}</button
      ><button type="button" class="secondary" @click="showPrinter = false">Cancel</button>
    </div>
  </form>
  <p v-if="!w.printers.length && !showPrinter" class="panel empty">
    {{
      auth.can('printers.manage')
        ? 'No printers registered.'
        : 'No direct printer access. Available groups are listed below.'
    }}
  </p>
  <div class="printer-cards">
    <section v-for="device in w.printers" :key="device.id" class="panel form-stack printer-device">
      <div class="section-heading">
        <h2>{{ device.name }}</h2>
        <span class="badge" :class="state(device.id)?.connected ? 'printed' : 'failed'">{{
          state(device.id)?.connected ? 'Connected' : 'Disconnected'
        }}</span>
      </div>
      <p v-if="device.configuration_error" class="alert warning">
        Configuration error: {{ device.configuration_error }}. Edit this printer to repair it.
      </p>
      <p v-if="state(device.id)?.printer_error" class="alert warning">
        {{ state(device.id)?.printer_error }}
      </p>
      <p class="muted">Brother PT-P710BT · USB</p>
      <p class="help">
        {{ device.capabilities?.dpi_y }} × {{ device.capabilities?.dpi_x }} dpi · Detected tape:
        {{
          state(device.id)?.detected_width_mm
            ? `${state(device.id)?.detected_width_mm} mm`
            : 'Unknown'
        }}
      </p>
      <label
        >Installed cartridge<select
          :value="state(device.id)?.active_cartridge_id ?? ''"
          :disabled="
            !auth.atLeast(device.id, 'full') ||
            w.busy ||
            !!state(device.id)?.printing ||
            !!state(device.id)?.needs_review.length ||
            !!state(device.id)?.pending_flush
          "
          @change="install(device.id, $event)"
        >
          <option value="">No cartridge installed</option>
          <option v-for="item in availableCartridges(device.id)" :key="item.id" :value="item.id">
            {{ item.name }} · {{ w.profileName(item.profile_id) }}
          </option>
        </select></label
      >
      <p v-if="cartridge(device.id)" class="help">
        {{ w.profileName(cartridge(device.id)!.profile_id) }} · ≈
        {{ metres(cartridge(device.id)!.remaining_mm) }} remaining
      </p>
      <p v-if="state(device.id)?.printing">Printing…</p>
      <div v-if="state(device.id)?.pending_flush" class="row wrap">
        <span>A manual flush is waiting. Finish or cancel it before changing cartridges.</span>
        <button
          v-if="auth.atLeast(device.id, 'moderator')"
          class="secondary"
          :disabled="w.busy"
          @click="cancelFlush(device.id)"
        >
          Cancel pending flush
        </button>
      </div>
      <RouterLink
        v-for="batch in auth.atLeast(device.id, 'moderator')
          ? (state(device.id)?.needs_review ?? [])
          : []"
        :key="batch"
        class="button secondary"
        :to="`/batches/${batch}`"
        >Review interrupted batch</RouterLink
      >
      <div class="row wrap">
        <button
          v-if="auth.atLeast(device.id, 'moderator')"
          class="secondary"
          :disabled="w.busy"
          @click="hold(device.id, !state(device.id)?.automatic_printing_held)"
        >
          {{
            state(device.id)?.automatic_printing_held
              ? 'Resume automatic printing'
              : 'Hold automatic printing'
          }}
        </button>
        <button
          v-if="auth.atLeast(device.id, 'full')"
          class="secondary"
          :disabled="w.busy"
          @click="editPrinter(device)"
        >
          Configure
        </button>
      </div>
    </section>
  </div>
  <form v-validate-form v-if="showGroup" class="panel form-stack" @submit.prevent="saveGroup">
    <h2>{{ editing ? 'Edit group' : 'Create group' }}</h2>
    <label>Group name<input v-model="group.name" required maxlength="100" /></label>
    <fieldset>
      <legend>Member printers</legend>
      <label v-for="device in groupChoices" :key="device.id" class="checkbox"
        ><input v-model="group.printer_ids" type="checkbox" :value="device.id" />{{
          device.name
        }}</label
      >
    </fieldset>
    <ol class="preference-list">
      <li v-for="(id, index) in group.printer_ids" :key="id">
        <span>{{ groupChoices.find((p) => p.id === id)?.name ?? id }}</span
        ><button
          type="button"
          class="small secondary"
          :disabled="index === 0"
          :aria-label="`Prefer ${w.destinationName(id)} earlier`"
          @click="move(index, -1)"
        >
          ↑</button
        ><button
          type="button"
          class="small secondary"
          :disabled="index === group.printer_ids.length - 1"
          :aria-label="`Prefer ${w.destinationName(id)} later`"
          @click="move(index, 1)"
        >
          ↓
        </button>
      </li>
    </ol>
    <p class="help">
      The first ready member with matching tape is used. Members need matching geometry and
      resolution. CSV runs stay on one printer.
    </p>
    <div class="row">
      <button class="primary" :disabled="w.busy || !group.printer_ids.length">Save group</button
      ><button type="button" class="secondary" @click="showGroup = false">Cancel</button>
    </div>
  </form>
  <section v-if="groups.length" class="panel form-stack">
    <h2>Printer groups</h2>
    <article v-for="target in groups" :key="target.id" class="printer-group">
      <div class="section-heading">
        <h3>{{ target.name }}</h3>
        <button
          v-if="auth.atLeast(target.id, 'full')"
          class="small secondary"
          @click="editGroup(target)"
        >
          Edit group
        </button>
      </div>
      <p>
        {{
          target.printer_ids
            .map((id) => target.member_names?.[id] ?? w.destinationName(id))
            .join(' → ')
        }}
      </p>
      <p class="help">
        Labels wait for a member with the matching tape profile. Tape colors use your
        installed-cartridge selection; the printer verifies the width.
      </p>
      <div class="row wrap">
        <RouterLink
          v-if="auth.atLeast(target.id, 'request')"
          class="button primary"
          :to="`/new?destination=${target.id}`"
          >Print a label</RouterLink
        ><RouterLink
          v-if="auth.atLeast(target.id, 'request')"
          class="button secondary"
          :to="`/runs?destination=${target.id}`"
          >Use with CSV</RouterLink
        ><button
          v-if="auth.atLeast(target.id, 'moderator')"
          class="secondary"
          :disabled="w.busy"
          @click="print(target.id)"
        >
          Print matching queue</button
        ><button
          v-if="auth.atLeast(target.id, 'moderator')"
          class="secondary"
          :disabled="w.busy"
          @click="hold(target.id, !target.automatic_printing_held)"
        >
          {{ target.automatic_printing_held ? 'Resume group' : 'Hold group' }}
        </button>
      </div>
    </article>
  </section>
  <section class="panel">
    <h2>Notifications</h2>
    <p>
      {{
        w.overview.notifications_enabled
          ? 'ntfy delivery is enabled.'
          : 'ntfy delivery is not configured.'
      }}
    </p>
    <p class="help">Notification endpoints are configured in Administration.</p>
    <RouterLink v-if="auth.can('inventory.manage')" class="button secondary" to="/profiles"
      >Manage tape reminders</RouterLink
    >
  </section>
</template>
<style scoped>
.printer-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 340px), 1fr));
  gap: 20px;
  margin-bottom: 20px;
}
.printer-cards .panel {
  margin-bottom: 0;
}
.printer-group {
  border-top: 1px solid var(--line);
  padding-top: 18px;
}
.printer-group p {
  margin-bottom: 14px;
}
.preference-list {
  padding-left: 24px;
}
.preference-list li {
  margin: 8px 0;
}
.preference-list span {
  display: inline-block;
  min-width: 160px;
}
.preference-list button {
  margin-left: 8px;
}
</style>
