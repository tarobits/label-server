import { printerPermissionLabel } from './printerPermissions'
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
    'cartridge.view': 'View cartridge',
    'cartridge.use': 'Use cartridge',
    'cartridge.approve_use': 'Approve cartridge use',
    'cartridge.edit_notes': 'Edit cartridge notes',
    'cartridge.edit_details': 'Edit cartridge details',
    'cartridge.manage_access': 'Manage cartridge access',
    'cartridge.view_audit': 'View cartridge audit log',
    'location.manage': 'Manage location',
  }
  return labels[permission] ?? permission.replaceAll('_', ' ')
}
export function decisionSummary(decision: PermissionDecision): string {
  if (decision.superseded_by) return `Uses ${permissionLabel(decision.superseded_by)}`
  const winners = decision.rules.filter(
    (rule) => rule.winning && (decision.allowed || rule.effect === 'deny'),
  )
  if (!winners.length) return 'No access granted'
  return `${decision.allowed ? 'Has access' : 'Denied'} through ${[
    ...new Set(
      winners.map(
        (rule) =>
          `${rule.scope_name}${rule.principal_kind === 'role' ? ` · ${rule.principal_name}` : ''}`,
      ),
    ),
  ].join(', ')}`
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
