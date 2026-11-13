import { t } from '../shared/i18n'
import type { Destination } from '../shared/types'

export type PrinterKinds = Record<string, string[]>
export type PrinterPriorities = Record<string, Record<string, number>>

export const priorityOptions = [
  {
    value: 1,
    get label() {
      return t('notificationPriorities.minimum')
    },
  },
  {
    value: 2,
    get label() {
      return t('notificationPriorities.low')
    },
  },
  {
    value: 3,
    get label() {
      return t('companionApp.normal')
    },
  },
  {
    value: 4,
    get label() {
      return t('companionApp.high')
    },
  },
  {
    value: 5,
    get label() {
      return t('notificationPriorities.urgent')
    },
  },
]

export const printerEventKinds = [
  {
    value: 'empty_tape',
    get label() {
      return t('uiMessages.emptyCartridges')
    },
  },
  {
    value: 'printer_blocked',
    get label() {
      return t('uiMessages.blockedPrinters')
    },
  },
  {
    value: 'batch_review',
    get label() {
      return t('uiMessages.batchReviews')
    },
  },
  {
    value: 'batch_printed',
    get label() {
      return t('uiMessages.finishedBatches')
    },
  },
  {
    value: 'tape_waiting',
    get label() {
      return t('uiMessages.waitingTapeReminders')
    },
  },
]

export function scopedPrinters(destinations: Destination[], all: boolean, selected: string[]) {
  const covered = new Set(
    destinations
      .filter((destination) => selected.includes(destination.id))
      .flatMap((d) => d.printer_ids),
  )
  return destinations.filter((d) => d.kind === 'printer' && (all || covered.has(d.id)))
}

export function selectedPrinterKinds(rules: PrinterKinds, printers: Destination[]): PrinterKinds {
  return Object.fromEntries(
    Object.entries(rules).filter(([id]) => printers.some((printer) => printer.id === id)),
  )
}
