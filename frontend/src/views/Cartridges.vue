<script setup lang="ts">
import { reactive, ref } from 'vue'
import { api } from '../api'
import { workspace as w, metres } from '../workspace'
import type { Cartridge } from '../types'
const { profiles, cartridges, activeCartridge, locked, busy } = w
const showForm = ref(false),
  correcting = ref<string | null>(null),
  correction = ref(0)
const form = reactive({
  profile_id: profiles.value[0]?.id ?? '',
  name: '',
  nominal: 8,
  remaining: 8,
})
async function save() {
  if (
    await w.action(
      () =>
        api('/cartridges', 'POST', {
          profile_id: form.profile_id,
          name: form.name,
          nominal_length_mm: form.nominal * 1000,
          remaining_mm: form.remaining * 1000,
        }),
      'Cartridge registered. Install it when it is in the printer.',
    )
  ) {
    showForm.value = false
    form.name = ''
  }
}
async function install(id: string | null) {
  await w.action(
    () => api('/printer/active-tape', 'PUT', { cartridge_id: id }),
    id
      ? 'Installed cartridge updated. Eligible queued labels may now print.'
      : 'No cartridge selected.',
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
    <p class="muted">Select the cassette physically installed in the printer.</p>
    <button class="secondary" :disabled="!profiles.length" @click="showForm = !showForm">
      Register cartridge
    </button>
  </div>
  <p v-if="locked" class="alert warning">
    Finish printing or resolve the pending review before swapping cartridges or correcting
    estimates.
  </p>
  <form v-if="showForm" class="panel form-stack" @submit.prevent="save">
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
    <div class="row">
      <button class="primary" :disabled="busy">Register cartridge</button
      ><button type="button" @click="showForm = false">Cancel</button>
    </div>
  </form>
  <div v-if="!cartridges.length" class="panel empty">
    <h2>No cartridges registered yet.</h2>
    <p>Each cassette keeps its own remaining-tape estimate when you swap it out.</p>
    <RouterLink v-if="!profiles.length" class="button primary" to="/profiles"
      >Create a tape profile first</RouterLink
    >
  </div>
  <div class="card-grid">
    <article v-for="cartridge in cartridges" :key="cartridge.id" class="panel">
      <div class="section-heading">
        <span class="eyebrow">{{ w.profileName(cartridge.profile_id) }}</span
        ><span v-if="activeCartridge?.id === cartridge.id" class="badge printed">Installed</span>
      </div>
      <h2>{{ cartridge.name }}</h2>
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
      <p v-else class="help">An estimate, including labels and batch overhead.</p>
      <form
        v-if="correcting === cartridge.id"
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
          <button :disabled="busy || locked" class="secondary">Save estimate</button
          ><button type="button" @click="correcting = null">Cancel</button>
        </div>
      </form>
      <div class="card-actions">
        <button
          v-if="activeCartridge?.id !== cartridge.id"
          class="secondary"
          :disabled="busy || locked"
          @click="install(cartridge.id)"
        >
          Install cartridge</button
        ><button v-else :disabled="busy || locked" @click="install(null)">
          Remove from printer</button
        ><button class="text-button" :disabled="busy || locked" @click="startCorrection(cartridge)">
          Correct estimate
        </button>
      </div>
    </article>
  </div>
</template>
