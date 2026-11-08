export type ResourceKind = 'printer' | 'cartridge' | 'location'
export interface Grant {
  principal_kind: 'user' | 'role'
  principal_id: string
  permission: string
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
