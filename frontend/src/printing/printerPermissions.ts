import type { AccessLevel } from '../auth/auth'
import { t } from '../shared/i18n'

export const printerPermissionOptions = [
  ['view', 'view'],
  ['submit_requests', 'submitRequests'],
  ['submit_directly', 'submitDirectly'],
  ['start_own', 'startOwn'],
  ['view_queue', 'viewQueue'],
  ['start_any', 'startAny'],
  ['manage_queue', 'manageQueue'],
  ['approve_requests', 'approveRequests'],
  ['view_activity', 'viewActivity'],
  ['view_audit', 'viewAudit'],
  ['review', 'review'],
  ['swap_cartridges', 'swapCartridges'],
  ['hold_resume', 'holdResume'],
  ['stop_after_label', 'stopAfterLabel'],
  ['emergency_stop', 'emergencyStop'],
  ['configure', 'configure'],
].map(([name, key]) => ({
  id: `printer.${name}`,
  get label() {
    return t(`printerPermissionLabels.${key}`)
  },
}))

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
