import { t } from './i18n'
import { printerPermissionLabel } from '../printing/printerPermissions'
export type ResourceKind = 'printer' | 'cartridge' | 'location'
export interface Grant {
  principal_kind: 'user' | 'role'
  principal_id: string
  permission: string
  effect?: 'allow' | 'deny'
}
export interface ResourceEntry {
  inherited_location?: boolean
  kind: ResourceKind
  id: string
  name: string
  owner_id: string | null
  location_id: string | null
  parent_id: string | null
  abilities: { transfer: boolean; locate: boolean; grants: boolean; roles: boolean }
  grants: Grant[]
}
export interface AccessCatalog {
  resources: ResourceEntry[]
  users: { id: string; name: string }[]
  roles: { id: string; name: string }[]
  locations: { id: string; name: string; parent_id: string | null }[]
  permissions: { printer: string[]; cartridge: string[] }
  manage_locations: boolean
}
export interface ResourceChange {
  kind: ResourceKind
  identifier: string
  name?: string
  parent_id?: string | null
  owner_id?: string | null
  location_id?: string | null
  grants?: Grant[]
  accept_owner_loss?: boolean
}
export interface AccessImpact {
  id: string
  name: string
  before: Record<string, string[]>
  after: Record<string, string[]>
}
export interface AccessPreview {
  confirmation_token: string
  affected_users: AccessImpact[]
  owner_loss_warning?: boolean
  claims_unassigned_debts?: boolean
}
export interface PairBalance {
  requester_id: string
  requester_name: string
  recipient_id: string | null
  recipient_name: string
  currency: string
  owed: string
  cartridge_id?: string
}

export interface PermissionRule {
  permission: string
  effect: 'allow' | 'deny'
  scope_kind: string
  scope_id: string
  scope_name: string
  principal_kind: string
  principal_id: string
  principal_name: string
  priority: number[]
  protected: boolean
  inherited_via?: string[]
  winning: boolean
}
export interface PermissionDecision {
  permission: string
  allowed: boolean
  superseded_by: string | null
  rules: PermissionRule[]
}
export interface AccessExplanation {
  user: { id: string; name: string }
  resources: { kind: ResourceKind; id: string; name: string; permissions: PermissionDecision[] }[]
}
export function permissionLabel(permission: string): string {
  if (permission.startsWith('printer.')) return printerPermissionLabel(permission)
  const labels: Record<string, string> = {
    'cartridge.view': t('sharedMessages.viewCartridge'),
    'cartridge.use': t('sharedMessages.useCartridge'),
    'cartridge.approve_use': t('sharedMessages.approveCartridge'),
    'cartridge.edit_notes': t('sharedMessages.editNotes'),
    'cartridge.edit_details': t('sharedMessages.editDetails'),
    'cartridge.manage_access': t('sharedMessages.manageAccess'),
    'cartridge.view_audit': t('sharedMessages.viewAudit'),
    'location.manage': t('sharedMessages.manageLocation'),
  }
  return labels[permission] ?? permission.replaceAll('_', ' ')
}
export function decisionSummary(decision: PermissionDecision): string {
  if (decision.superseded_by)
    return t('sharedMessages.usesPermission', {
      permission: permissionLabel(decision.superseded_by),
    })
  const winners = decision.rules.filter(
    (rule) => rule.winning && (decision.allowed || rule.effect === 'deny'),
  )
  if (!winners.length) return t('sharedMessages.noAccess')
  const sources = [
    ...new Set(
      winners.map(
        (rule) =>
          `${rule.scope_name}${rule.principal_kind === 'role' ? ` · ${rule.principal_name}` : ''}`,
      ),
    ),
  ].join(', ')
  return t(decision.allowed ? 'sharedMessages.allowedThrough' : 'sharedMessages.deniedThrough', {
    sources,
  })
}

export function exclusiveGrantModes(grants: Grant[]): Grant[] {
  return grants.filter(
    (grant) =>
      grant.permission !== 'printer.submit_requests' ||
      grant.effect === 'deny' ||
      !grants.some(
        (other) =>
          other.principal_kind === grant.principal_kind &&
          other.principal_id === grant.principal_id &&
          other.permission === 'printer.submit_directly' &&
          other.effect !== 'deny',
      ),
  )
}
