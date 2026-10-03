<script setup lang="ts">
import { workspace as w, date, metres } from '../workspace'
import { api } from '../api'
import Badge from '../components/Badge.vue'
import Icon from '../components/Icon.vue'
const {
  status,
  activeCartridge,
  activeProfile,
  activeCount,
  totalQueued,
  profiles,
  batches,
  canPrint,
  busy,
} = w
</script>
<template>
  <div class="panel row spread wrap">
    <div>
      <strong>{{
        status?.automatic_printing_held
          ? 'Building a larger batch'
          : 'Automatic printing is enabled'
      }}</strong>
      <p class="help">Hold automatic printing to accumulate labels beyond their tape thresholds.</p>
    </div>
    <button
      :disabled="busy"
      @click="
        w.action(
          () =>
            api('/printer/automatic-printing', 'PUT', { held: !status?.automatic_printing_held }),
          status?.automatic_printing_held
            ? 'Automatic printing resumed. Eligible batches may now print.'
            : 'Automatic printing held until you resume it.',
        )
      "
    >
      {{
        status?.automatic_printing_held ? 'Resume automatic printing' : 'Hold automatic printing'
      }}
    </button>
  </div>
  <div class="stats-grid">
    <article class="stat">
      <span>QUEUED LABELS</span><strong>{{ totalQueued }}<small>copies</small></strong>
      <p>
        Waiting across {{ status?.queues.filter((q) => q.queued_copies > 0).length }} tape profiles
      </p>
    </article>
    <article class="stat">
      <span>READY ON THIS TAPE</span
      ><strong
        >{{ activeCount }}<small>/ {{ activeProfile?.auto_print_threshold ?? '—' }}</small></strong
      >
      <p>
        {{ activeProfile ? 'Automatic batch threshold' : 'Install a cartridge to get started' }}
      </p>
    </article>
    <article class="stat">
      <span>TAPE REMAINING</span
      ><strong>{{ activeCartridge ? metres(activeCartridge.remaining_mm) : '—' }}</strong>
      <p>
        {{
          activeCartridge?.consumption_uncertain
            ? 'Uncertain · review the interrupted batch'
            : 'Approximate remaining on installed cartridge'
        }}
      </p>
    </article>
  </div>
  <div class="dashboard-grid">
    <section class="panel printer-card">
      <div class="section-heading">
        <h2>At the printer</h2>
        <span class="badge" :class="status?.connected ? 'printed' : 'failed'">{{
          status?.connected ? 'Connected' : 'Disconnected'
        }}</span>
      </div>
      <div class="printer-illustration" aria-hidden="true">
        <div class="printer-body">
          <div class="printer-slot"></div>
          <div class="printer-paper">
            <span>MAKE IT<br />FINDABLE.</span>
            <div class="fake-code"></div>
          </div>
          <span class="printer-light"></span>
        </div>
      </div>
      <div class="printer-caption">
        <strong>Brother PT-P710BT</strong
        ><span
          >{{ status?.printer_name }} · {{ status?.detected_width_mm ?? 'Unknown' }} mm
          detected</span
        >
      </div>
      <div class="installed-tape">
        <span
          class="swatch"
          :style="{
            background: activeProfile?.background ?? 'var(--surface-secondary)',
            color: activeProfile?.foreground ?? 'var(--text-secondary)',
          }"
          >Aa</span
        >
        <div>
          <small>INSTALLED TAPE</small
          ><strong>{{ activeProfile?.name ?? 'No cartridge selected' }}</strong
          ><span>{{ activeCartridge?.name ?? 'Choose a cartridge from your collection' }}</span>
        </div>
        <RouterLink to="/cartridges" class="text-link">Change</RouterLink>
      </div>
      <p
        v-if="activeProfile && status?.detected_width_mm !== activeProfile.width_mm"
        class="inline-warning"
      >
        Tape width does not match. Printing is blocked until the detected width matches
        {{ activeProfile.width_mm }} mm.
      </p>
      <p v-else-if="status?.blocker" class="inline-warning">{{ status.blocker }}</p>
      <button class="primary full" :disabled="!canPrint || busy" @click="w.printNow">
        <Icon name="printer" />{{
          status?.printing
            ? 'Printing batch…'
            : status?.pending_flush
              ? 'Manual batch pending…'
              : 'Print compatible queue now'
        }}
      </button>
      <p class="help centered">Only labels for the installed tape will be printed.</p>
    </section>
    <section class="panel">
      <div class="section-heading">
        <h2>Waiting by tape</h2>
        <RouterLink to="/profiles" class="text-link">Manage tapes →</RouterLink>
      </div>
      <div v-if="!profiles.length" class="empty">
        <Icon name="tape" />
        <h3>Your first tape starts here.</h3>
        <p>Create a tape profile, then register a cartridge.</p>
        <RouterLink class="button secondary" to="/profiles">Add a tape profile</RouterLink>
      </div>
      <div v-for="profile in profiles" :key="profile.id" class="tape-row">
        <span class="swatch" :style="{ background: profile.background, color: profile.foreground }"
          >Aa</span
        >
        <div class="grow">
          <div class="row spread">
            <strong>{{ profile.name }}</strong
            ><span class="count"
              >{{ status?.queues.find((q) => q.profile_id === profile.id)?.queued_copies ?? 0 }}
              <span>/ {{ profile.auto_print_threshold }}</span></span
            >
          </div>
          <progress
            :value="status?.queues.find((q) => q.profile_id === profile.id)?.queued_copies ?? 0"
            :max="profile.auto_print_threshold"
            :aria-label="`${profile.name} queue progress`"
          ></progress
          ><small
            >{{ profile.id === activeProfile?.id ? 'Installed' : 'Waiting for this tape' }} ·
            {{ profile.width_mm }} mm<span v-if="profile.reminder_silenced">
              · Reminders silenced</span
            ></small
          >
        </div>
      </div>
      <div class="note">
        <strong>A batch for every tape.</strong>
        <p>
          Each tape has its own threshold. Matching copies print automatically when that tape is
          installed.
        </p>
      </div>
    </section>
  </div>
  <section class="panel">
    <div class="section-heading">
      <h2>Recent batches</h2>
      <RouterLink class="text-link" to="/activity">All activity →</RouterLink>
    </div>
    <div v-if="!batches.length" class="empty compact">
      Nothing printed yet. Your first batch will appear here.
    </div>
    <div v-for="batch in batches.slice(0, 4)" :key="batch.id" class="list-row">
      <div>
        <strong>{{ w.cartridgeName(batch.cartridge_id) }}</strong
        ><small>{{ date(batch.created_at) }}</small>
      </div>
      <Badge :state="batch.state" /><RouterLink :to="`/batches/${batch.id}`">{{
        batch.state === 'needs_review' ? 'Review →' : 'Details →'
      }}</RouterLink>
    </div>
  </section>
</template>
