import type { TemplateDocument } from './editor'
export type CopyState = 'queued' | 'printing' | 'printed' | 'needs_review' | 'cancelled' | 'failed'
export interface PrinterConfig {
  usb_serial?: string | null
  resolution?: string
  feed_mm?: number
  leader_mm?: number
  cut_each?: boolean
  timeout_seconds?: number
}
export interface Printer {
  configuration_error?: string | null
  config: PrinterConfig
  id: string
  name: string
  driver: string
  capabilities: {
    supported_widths_mm: number[]
    dpi_x: number
    dpi_y: number
    resolution_modes?: Record<string, [number, number]> | null
    printable_margin_mm: number
    printable_widths_mm?: Record<string, number> | null
    supports_stop_after_current?: boolean
    supports_emergency_stop?: boolean
    supports_manual_cut?: boolean
  } | null
}
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
  installed?: boolean
  estimate_locked?: boolean
  id: string
  profile_id: string
  name: string
  nominal_length_mm: number
  remaining_mm: number
  consumption_uncertain: boolean
}
export interface Destination {
  available?: boolean
  member_names?: Record<string, string>
  capabilities?: Printer['capabilities'] | null
  access_level?: import('./auth').AccessLevel
  queues: { profile_id: string; queued_copies: number; threshold: number }[]
  id: string
  name: string
  kind: 'printer' | 'group'
  printer_ids: string[]
  automatic_printing_held: boolean
}
export interface Status {
  total_queued: number
  printer_id: string
  backend: string
  printer_name: string
  printer_error: string | null
  automatic_printing_held: boolean
  active_cartridge_id: string | null
  blocker: string | null
  renderer: string
  connected: boolean
  detected_width_mm: number | null
  needs_review: string[]
  notifications_enabled: boolean
  printing: string | null
  stop_requested?: 'after_current' | 'emergency' | null
  pending_flush: string | null
  queues: { profile_id: string; queued_copies: number; threshold: number }[]
}
export interface Job {
  attribution: PrintAttribution
  owner_id: string
  can_print?: boolean
  can_cancel?: boolean
  access_hold?: {
    reason: string
    held_at: number
    status: 'held' | 'released' | 'cancelled'
  } | null
  assigned_printer_id: string | null
  destination_id: string
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
export interface AuditActor {
  id: string
  name: string
}
export interface PrintAttribution {
  requested_by: AuditActor | null
  submitted_by?: AuditActor | null
  requested_at: number | null
  authorization: {
    kind: 'direct' | 'approval' | 'override' | 'unknown'
    actor: AuditActor | null
    at: number | null
    request_id: string | null
  }
  release: { actor: AuditActor | null; at: number } | null
}
export interface BatchTrigger {
  kind: 'automatic' | 'manual' | 'unknown'
  actor: AuditActor | null
  at: number | null
  flush_request_id: string | null
  stop_request?: {
    mode: 'after_current' | 'emergency'
    actor: AuditActor | null
    at: number
  }
}
export interface Batch {
  trigger: BatchTrigger
  attribution_summary: { attribution: PrintAttribution; copies: number }[]
  printer_id: string
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
    attribution: PrintAttribution
    copy_id: string
    position: number
    outcome: CopyState
    job_id: string
    copy_number: number
    text: string
    width_mm: number
    length_mm: number
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
  deliveries?: {
    endpoint_name: string
    attempts: number
    next_attempt_at: number
    delivered_at: number | null
    cancelled: boolean
    last_error: string | null
  }[]
}

export interface Template {
  can_delete?: boolean
  scope?: 'personal' | 'group' | 'global'
  group_id?: string | null
  owner_id?: string | null
  can_edit?: boolean
  name: string
  document: TemplateDocument
  archived: boolean
  id: string
  revision: number
  fields: string[]
  renderer: string
}
export interface AccessHold {
  job_id: string
  reason: string
  held_at: number
  status: 'held' | 'released' | 'cancelled'
  owner_name: string
  job: Job
}

export interface FontAsset {
  can_edit?: boolean
  owner_id?: string | null
  id: string
  family: string
  style: string
  size_bytes: number
  archived: boolean
}

export interface ImageAsset {
  can_edit?: boolean
  owner_id?: string | null
  id: string
  name: string
  kind: 'bitmap' | 'svg'
  width: number
  height: number
  size_bytes: number
  archived: boolean
}
