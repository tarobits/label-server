<script setup lang="ts">
import { freezeLeavingItem } from '../collectionMotion'
import { vValidateForm } from '../formValidation'
import { storeToRefs } from 'pinia'
import { confirmAction } from '../confirmation'
import { reactive, ref } from 'vue'
import ExpandableContent from '../components/ExpandableContent.vue'
import { api } from '../api'
import { useWorkspaceStore, date } from '../workspace'
import type { Profile, ProfileInput } from '../types'
import { mediaLabel } from '../media'
const w = useWorkspaceStore()
const { profiles, busy, status } = storeToRefs(w)
const editing = ref<string | null>(null),
  formOpen = ref(false)
const defaults = (): ProfileInput => ({
  name: '',
  width_mm: 24,
  media_family: 'tze',
  label_length_mm: null,
  foreground: '#000000',
  background: '#ffffff',
  auto_print_threshold: 10,
  waiting_notification_enabled: false,
  waiting_notification_interval_seconds: 86400,
})
const form = reactive(defaults()),
  intervalHours = ref(24)
const snoozeProfile = ref<string | null>(null),
  snoozeUntil = ref('')
let snoozeButton: HTMLElement | null = null
function openSnooze(id: string, event: MouseEvent) {
  snoozeButton = event.currentTarget as HTMLElement
  snoozeProfile.value = id
}
function closeSnooze() {
  snoozeProfile.value = null
  snoozeButton?.focus()
}
function edit(profile?: Profile) {
  editing.value = profile?.id ?? null
  Object.assign(
    form,
    defaults(),
    profile
      ? Object.fromEntries(
          Object.keys(defaults()).map((key) => [key, profile[key as keyof Profile]]),
        )
      : {},
  )
  intervalHours.value = form.waiting_notification_interval_seconds / 3600
  formOpen.value = true
}
async function save() {
  const intervalSeconds = Math.round(intervalHours.value * 3600)
  const body = {
    ...form,
    label_length_mm: form.media_family === 'fixed_label' ? form.label_length_mm : null,
    waiting_notification_interval_seconds:
      !form.waiting_notification_enabled &&
      (!Number.isFinite(intervalSeconds) || intervalSeconds < 60)
        ? form.waiting_notification_interval_seconds
        : intervalSeconds,
  }
  if (
    await w.action(
      () =>
        api(
          `/tape-profiles${editing.value ? `/${editing.value}` : ''}`,
          editing.value ? 'PUT' : 'POST',
          body,
        ),
      'Tape profile saved. Its threshold is effective immediately.',
    )
  )
    formOpen.value = false
}
async function remove(profile: Profile) {
  if (
    await confirmAction(
      `Delete unused profile “${profile.name}”? Profiles with history cannot be deleted.`,
    )
  )
    await w.action(() => api(`/tape-profiles/${profile.id}`, 'DELETE'), 'Tape profile deleted.')
}
async function setAvailability(profile: Profile) {
  const available = profile.available === false
  await w.action(
    () => api(`/tape-profiles/${profile.id}/availability`, 'PUT', { available }),
    available ? 'Tape profile available.' : 'Tape profile unavailable for new labels.',
  )
}
async function reminder(id: string, action: 'silence' | 'resume' | 'snooze') {
  const body = {
    action,
    ...(action === 'snooze' ? { until: new Date(snoozeUntil.value).getTime() / 1000 } : {}),
  }
  if (
    await w.action(
      () => api(`/tape-profiles/${id}/reminder`, 'PUT', body),
      `Reminder setting updated.`,
    )
  )
    if (snoozeProfile.value) closeSnooze()
}
</script>
<template>
  <div class="section-heading">
    <button class="secondary" @click="edit()">Add tape profile</button>
  </div>
  <Transition name="panel-expand">
    <form v-validate-form v-if="formOpen" class="panel form-stack" @submit.prevent="save">
      <div class="section-heading">
        <h2>{{ editing ? 'Edit tape profile' : 'New tape profile' }}</h2>
        <button type="button" class="text-button" @click="formOpen = false">Close</button>
      </div>
      <div class="field-row">
        <label
          >Profile name<input
            v-model="form.name"
            required
            maxlength="100"
            placeholder="Black on Yellow 24 mm" /></label
        ><label
          >Media family<select v-model="form.media_family">
            <option value="tze">TZe · Continuous tape</option>
            <option value="fixed_label">Fixed-size labels</option>
          </select></label
        ><label v-if="form.media_family !== 'fixed_label'"
          >Tape width<select v-model.number="form.width_mm">
            <option v-for="width in [3.5, 6, 9, 12, 18, 24]" :key="width" :value="width">
              {{ width }} mm
            </option>
          </select></label
        >
        <label v-else
          >Label width (mm)<input
            v-model.number="form.width_mm"
            type="number"
            min="0.1"
            max="100"
            step="any"
            required
        /></label>
      </div>
      <ExpandableContent :open="form.media_family === 'fixed_label'">
        <label
          >Stock label length (mm)<input
            v-model.number="form.label_length_mm"
            type="number"
            min="10"
            max="300"
            step="any"
            :required="form.media_family === 'fixed_label'"
            :disabled="form.media_family !== 'fixed_label'"
        /></label>
      </ExpandableContent>
      <div class="field-row">
        <label>Text color<input type="color" v-model="form.foreground" /></label
        ><label>Tape color<input type="color" v-model="form.background" /></label
        ><label
          >Automatic batch threshold<input
            v-model.number="form.auto_print_threshold"
            type="number"
            min="1"
            max="10000"
            required
        /></label>
      </div>
      <label class="checkbox"
        ><input v-model="form.waiting_notification_enabled" type="checkbox" />Remind me when this
        tape is waiting above its threshold</label
      >
      <ExpandableContent :open="form.waiting_notification_enabled">
        <label
          >Repeat reminder every (hours)<input
            v-model.number="intervalHours"
            type="number"
            min="0.017"
            step="any"
            required
            :disabled="!form.waiting_notification_enabled"
        /></label>
      </ExpandableContent>
      <p class="help">
        Thresholds count physical copies. Lowering an installed tape’s threshold may start a batch
        immediately. Media family and dimensions cannot change after a profile has been used.
      </p>
      <button class="primary" :disabled="busy" type="submit">Save tape profile</button>
    </form>
  </Transition>
  <div v-if="!profiles.length && !formOpen" class="panel empty">
    <h2>No tape profiles</h2>
    <button class="primary" @click="edit()">Create first tape profile</button>
  </div>
  <TransitionGroup
    v-if="profiles.length"
    tag="div"
    class="card-grid"
    name="collection"
    @before-leave="freezeLeavingItem"
  >
    <article v-for="profile in profiles" :key="profile.id" class="panel profile-card">
      <div class="section-heading">
        <span
          class="swatch large"
          :style="{ background: profile.background, color: profile.foreground }"
          >Aa</span
        ><span class="badge">{{ mediaLabel(profile) }}</span>
      </div>
      <h2>{{ profile.name }}</h2>
      <ExpandableContent :open="profile.available === false">
        <span class="badge">Unavailable</span>
      </ExpandableContent>
      <p>
        {{ status?.queues.find((q) => q.profile_id === profile.id)?.queued_copies ?? 0 }} queued ·
        Prints at {{ profile.auto_print_threshold }} copies
      </p>
      <div class="profile-meta">
        <span>Waiting reminders</span
        ><strong>{{
          profile.waiting_notification_enabled
            ? `Every ${+(profile.waiting_notification_interval_seconds / 3600).toFixed(2)} h`
            : 'Off'
        }}</strong>
      </div>
      <p v-if="profile.reminder_silenced" class="inline-warning">
        Silenced for this waiting episode.
      </p>
      <p
        v-else-if="
          profile.reminder_snoozed_until && profile.reminder_snoozed_until > Date.now() / 1000
        "
        class="help"
      >
        Snoozed until {{ date(profile.reminder_snoozed_until) }}
      </p>
      <div v-if="profile.waiting_notification_enabled" class="row wrap">
        <button class="small" :disabled="busy" @click="reminder(profile.id, 'silence')">
          Silence episode</button
        ><button class="small" @click="openSnooze(profile.id, $event)">Snooze</button
        ><button class="small" :disabled="busy" @click="reminder(profile.id, 'resume')">
          Resume
        </button>
      </div>
      <Transition name="panel-expand">
        <form
          v-if="snoozeProfile === profile.id"
          v-validate-form
          class="form-stack inset"
          @submit.prevent="reminder(profile.id, 'snooze')"
        >
          <label
            >Snooze until (local time)<input v-model="snoozeUntil" type="datetime-local" required
          /></label>
          <div class="row wrap">
            <button class="secondary" :disabled="busy">Set snooze</button>
            <button type="button" :disabled="busy" @click="closeSnooze">Cancel</button>
          </div>
        </form>
      </Transition>
      <div class="card-actions">
        <button class="text-button" :disabled="busy" @click="setAvailability(profile)">
          {{ profile.available === false ? 'Make available' : 'Mark unavailable' }}
        </button>
        <button class="text-button" @click="edit(profile)">Edit profile</button
        ><button class="text-button danger-text" :disabled="busy" @click="remove(profile)">
          Delete
        </button>
      </div>
    </article>
  </TransitionGroup>
</template>
