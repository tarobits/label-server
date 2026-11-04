import type { Destination } from './types'

export type PrinterKinds = Record<string, string[]>
export type PrinterPriorities = Record<string, Record<string, number>>

export const priorityOptions = [
  { value: 1, label: 'Min' },
  { value: 2, label: 'Low' },
  { value: 3, label: 'Normal' },
  { value: 4, label: 'High' },
  { value: 5, label: 'Urgent' },
]

export const printerEventKinds = [
  { value: 'empty_tape', label: 'Empty cartridges' },
  { value: 'printer_blocked', label: 'Blocked printers' },
  { value: 'batch_review', label: 'Batch reviews' },
  { value: 'batch_printed', label: 'Finished batches' },
  { value: 'tape_waiting', label: 'Waiting tape reminders' },
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
