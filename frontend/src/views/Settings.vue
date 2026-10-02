<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { api, errorMessage } from '../api'
import type { MockSettings } from '../types'
import { workspace as w } from '../workspace'
const { status, busy } = w
const form = reactive<MockSettings>({ connected: true, tape_width_mm: 24, fail_after: null })
const error = ref(''),
  ready = ref(false),
  interrupt = ref(false),
  after = ref(1)
onMounted(async () => {
  try {
    const data = await api<MockSettings>('/printer/mock')
    Object.assign(form, data)
    interrupt.value = data.fail_after !== null
    after.value = data.fail_after ?? 1
    ready.value = true
  } catch (e) {
    error.value = errorMessage(e)
  }
})
async function save() {
  await w.action(
    () =>
      api('/printer/mock', 'PUT', { ...form, fail_after: interrupt.value ? after.value : null }),
    interrupt.value
      ? 'Mock settings saved. The next batch will be interrupted once.'
      : 'Mock printer settings saved.',
  )
}
</script>
<template>
  <div class="two-column">
    <form class="panel form-stack" @submit.prevent="save">
      <div class="section-heading">
        <h2>Mock printer controls</h2>
        <span class="badge queued">Development mode</span>
      </div>
      <p class="help">
        These controls simulate the printer. No USB device is accessed. Changes last until the
        server restarts.
      </p>
      <p v-if="error" class="alert danger">{{ error }}</p>
      <fieldset :disabled="!ready || busy">
        <label class="checkbox"
          ><input v-model="form.connected" type="checkbox" />Printer connected</label
        ><label
          >Detected tape width<select v-model="form.tape_width_mm">
            <option :value="null">Unknown / no tape</option>
            <option v-for="width in [4, 6, 9, 12, 18, 24]" :key="width" :value="width">
              {{ width }} mm
            </option>
          </select></label
        ><label class="checkbox"
          ><input v-model="interrupt" type="checkbox" />Interrupt the next print batch</label
        ><label v-if="interrupt"
          >Confirmed copies before interruption<input
            v-model.number="after"
            type="number"
            min="0"
            max="1000"
            required
        /></label>
        <p v-if="interrupt" class="help">
          The fault is consumed once. The batch pauses for review, including tape consumption, even
          if every copy was confirmed.
        </p>
        <button class="primary" type="submit">Apply mock settings</button>
      </fieldset>
    </form>
    <div class="stack">
      <section class="panel">
        <h2>Printer status</h2>
        <dl>
          <div>
            <dt>Connection</dt>
            <dd>{{ status?.connected ? 'Connected' : 'Disconnected' }}</dd>
          </div>
          <div>
            <dt>Detected width</dt>
            <dd>
              {{
                status?.detected_width_mm === null ? 'Unknown' : `${status?.detected_width_mm} mm`
              }}
            </dd>
          </div>
          <div>
            <dt>Printing</dt>
            <dd>
              {{
                status?.printing
                  ? 'In progress'
                  : status?.needs_review.length
                    ? 'Paused for review'
                    : 'Idle'
              }}
            </dd>
          </div>
        </dl>
      </section>
      <section class="panel">
        <h2>Notifications</h2>
        <p>
          {{
            status?.notifications_enabled
              ? 'ntfy delivery is enabled.'
              : 'ntfy delivery is not configured.'
          }}
        </p>
        <p class="help">
          Set the ntfy server URL, topic, optional token, and public application URL in the server
          environment. Tokens are never sent to the browser. Manage reminder intervals and silence
          per tape profile.
        </p>
        <RouterLink class="text-link" to="/profiles">Manage tape reminders →</RouterLink>
      </section>
    </div>
  </div>
</template>
