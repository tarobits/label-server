import type { AccessLevel } from './auth'

export const printerPermissionOptions = [
  ['view', 'View printer'],
  ['submit_requests', 'Submit requests'],
  ['submit_directly', 'Submit directly'],
  ['start_own', 'Start own prints'],
  ['view_queue', 'View everyone’s queue'],
  ['start_any', 'Start anyone’s prints'],
  ['manage_queue', 'Manage everyone’s queue'],
  ['approve_requests', 'Approve print requests'],
  ['view_activity', 'View everyone’s print activity'],
  ['view_audit', 'View audit log'],
  ['review', 'Review interrupted batches'],
  ['swap_cartridges', 'Swap cartridges'],
  ['hold_resume', 'Hold/resume printing'],
  ['stop_after_label', 'Stop after current label'],
  ['emergency_stop', 'Emergency stop'],
  ['configure', 'Configure printer'],
].map(([name, label]) => ({ id: `printer.${name}`, label: label! }))

const physical = new Set(
  ['review', 'swap_cartridges', 'stop_after_label', 'emergency_stop', 'view_audit'].map(
    (name) => `printer.${name}`,
  ),
)
export const permissionOptions = (group = false) =>
  printerPermissionOptions.filter((option) => !group || !physical.has(option.id))

export function legacyPrinterPermissions(level: AccessLevel, group = false): string[] {
  const result: string[] = []
  if (level !== 'none') result.push('view', 'submit_requests')
  if (['print', 'moderator', 'full'].includes(level)) result.push('submit_directly', 'start_own')
  if (['moderator', 'full'].includes(level))
    result.push(
      'view_queue',
      'start_any',
      'manage_queue',
      'approve_requests',
      'view_activity',
      'review',
      'hold_resume',
      'stop_after_label',
    )
  if (level === 'full') result.push('configure', 'swap_cartridges', 'emergency_stop')
  return exclusiveSubmissionPermissions(
    result.map((name) => `printer.${name}`).filter((name) => !group || !physical.has(name)),
  )
}

export const printerPreset = (level: AccessLevel, group = false) =>
  level === 'full'
    ? exclusiveSubmissionPermissions(permissionOptions(group).map((option) => option.id))
    : legacyPrinterPermissions(level, group)

export const printerPermissionLabel = (permission: string) =>
  printerPermissionOptions.find((option) => option.id === permission)?.label ?? permission

export const oppositeSubmissionPermission = (permission: string) =>
  permission === 'printer.submit_requests'
    ? 'printer.submit_directly'
    : permission === 'printer.submit_directly'
      ? 'printer.submit_requests'
      : undefined
export const exclusiveSubmissionPermissions = (permissions: string[]) =>
  permissions.includes('printer.submit_directly')
    ? permissions.filter((p) => p !== 'printer.submit_requests')
    : permissions
