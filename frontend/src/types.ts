import type { TemplateDocument } from './editor'
export type CopyState = 'queued' | 'printing' | 'printed' | 'needs_review' | 'cancelled' | 'failed'
export interface Profile {
  id: string
  name: string
  width_mm: number
  foreground: string
  background: string
  auto_print_threshold: number
  waiting_notification_enabled: boolean
  waiting_notification_interval_seconds: number
  reminder_silenced: boolean
  reminder_snoozed_until: number | null
  reminder_last_at: number | null
}
export type ProfileInput = Pick<
  Profile,
  | 'name'
  | 'width_mm'
  | 'foreground'
  | 'background'
  | 'auto_print_threshold'
  | 'waiting_notification_enabled'
  | 'waiting_notification_interval_seconds'
>
export interface Cartridge {
  id: string
  profile_id: string
  name: string
  nominal_length_mm: number
  remaining_mm: number
  consumption_uncertain: boolean
}
export interface Status {
  automatic_printing_held: boolean
  active_cartridge_id: string | null
  blocker: string | null
  backend: string
  renderer: string
  connected: boolean
  detected_width_mm: number | null
  needs_review: string[]
  notifications_enabled: boolean
  printing: string | null
  pending_flush: string | null
  queues: { profile_id: string; queued_copies: number; threshold: number }[]
}
export interface Job {
  run_id: string | null
  source_row: number | null
  id: string
  profile_id: string
  template_id: string
  payload: Record<string, string>
  width_mm: number
  length_mm: number
  copies: number
  created_at: number
  status: CopyState | 'mixed'
  labels: { id: string; ordinal: number; state: CopyState }[]
}
export interface Batch {
  id: string
  cartridge_id: string
  state: CopyState
  created_at: number
  finished_at: number | null
  error: string | null
  estimated_mm: number
  consumed_mm: number | null
  shortage_warning: boolean
}
export interface BatchDetail extends Batch {
  items: {
    copy_id: string
    position: number
    outcome: CopyState
    job_id: string
    copy_number: number
    text: string
  }[]
}
export interface Notice {
  id: string
  title: string
  message: string
  created_at: number
  delivered_at: number | null
  cancelled: boolean
  attempts: number
  last_error: string | null
  path: string
}
export interface MockSettings {
  connected: boolean
  tape_width_mm: number | null
  fail_after: number | null
}
export interface Template {
  name: string
  document: TemplateDocument
  archived: boolean
  id: string
  revision: number
  fields: string[]
  renderer: string
}

export interface FontAsset {
  id: string
  family: string
  style: string
  size_bytes: number
  archived: boolean
}

export interface ImageAsset {
  id: string
  name: string
  kind: 'bitmap' | 'svg'
  width: number
  height: number
  size_bytes: number
  archived: boolean
}
