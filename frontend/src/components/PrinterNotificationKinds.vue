<script setup lang="ts">
import type { Destination } from '../shared/types'
import {
  printerEventKinds,
  priorityOptions,
  type PrinterKinds,
  type PrinterPriorities,
} from '../notifications/notificationPreferences'
import ExpandableContent from './ExpandableContent.vue'

const props = defineProps<{
  printers: Destination[]
  defaults: string[]
  disabled?: boolean
  showPriorities?: boolean
  defaultPriorities?: Record<string, number>
}>()
const rules = defineModel<PrinterKinds>({ required: true })
const priorities = defineModel<PrinterPriorities>('priorities', { default: () => ({}) })

function setPriority(id: string, kind: string, event: Event) {
  const value = (event.target as HTMLSelectElement).value
  const events = { ...priorities.value[id] }
  if (value) events[kind] = Number(value)
  else delete events[kind]
  const next = { ...priorities.value }
  if (Object.keys(events).length) next[id] = events
  else delete next[id]
  priorities.value = next
}

function defaultPriority(kind: string) {
  return priorityOptions.find((option) => option.value === (props.defaultPriorities?.[kind] ?? 3))
    ?.label
}

function customize(id: string, event: Event) {
  const next = { ...rules.value }
  if ((event.target as HTMLInputElement).checked) {
    next[id] = props.defaults.filter((kind) =>
      printerEventKinds.some((event) => event.value === kind),
    )
  } else {
    delete next[id]
    const nextPriorities = { ...priorities.value }
    delete nextPriorities[id]
    priorities.value = nextPriorities
  }
  rules.value = next
}
</script>

<template>
  <ExpandableContent :open="printers.length > 0">
    <fieldset class="printer-event-settings choice-list">
      <legend>{{ $t('printerNotificationKinds.perPrinterEventTypes') }}</legend>
      <p class="help">
        {{ $t('printerNotificationKinds.printersUseTheDefaultsUnlessCustomizedClearEveryEvent') }}
      </p>
      <div v-for="printer in printers" :key="printer.id" class="printer-event-row">
        <label class="checkbox">
          <input
            type="checkbox"
            :checked="printer.id in rules"
            :disabled="disabled"
            :aria-label="$t('uiDetails.customizeEvents', { value1: String(printer.name) })"
            @change="customize(printer.id, $event)"
          />{{ $t('printerNotificationKinds.customizeEventsFor') }} {{ printer.name }}
        </label>
        <ExpandableContent :open="printer.id in rules">
          <fieldset
            class="printer-events notification-event-grid"
            :aria-label="$t('uiDetails.eventTypes', { value1: String(printer.name) })"
          >
            <div
              v-for="kind in printerEventKinds"
              :key="kind.value"
              class="notification-event-row"
              :class="{ 'without-priority': !showPriorities }"
            >
              <label class="checkbox">
                <input
                  v-model="rules[printer.id]"
                  type="checkbox"
                  :value="kind.value"
                  :disabled="disabled"
                />{{ kind.label }}
              </label>
              <ExpandableContent :open="!!showPriorities">
                <label class="event-priority"
                  >{{ $t('common.priority') }}
                  <select
                    :value="priorities[printer.id]?.[kind.value] ?? ''"
                    :aria-label="
                      $t('uiDetails.printerEventPriority', {
                        value1: String(kind.label),
                        value2: String(printer.name),
                      })
                    "
                    :disabled="disabled || !rules[printer.id]?.includes(kind.value)"
                    @change="setPriority(printer.id, kind.value, $event)"
                  >
                    <option value="">
                      {{ $t('printerNotificationKinds.default') }}{{ defaultPriority(kind.value) }})
                    </option>
                    <option
                      v-for="priority in priorityOptions"
                      :key="priority.value"
                      :value="priority.value"
                    >
                      {{ priority.label }}
                    </option>
                  </select>
                </label>
              </ExpandableContent>
            </div>
          </fieldset>
        </ExpandableContent>
      </div>
    </fieldset>
  </ExpandableContent>
</template>

<style scoped>
.printer-event-settings {
  margin-top: 16px;
}
.printer-event-row {
  min-width: 0;
}
.printer-event-row > label {
  overflow-wrap: anywhere;
}
.printer-events {
  margin-top: 8px;
}
</style>
