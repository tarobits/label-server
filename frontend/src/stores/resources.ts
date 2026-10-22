import { defineStore } from 'pinia'
import { shallowRef } from 'vue'
import { api, onApiMutation } from '../api'

interface Entry {
  value: unknown
  fetchedAt: number
}
export class SessionChanged extends Error {
  constructor() {
    super('The session changed while loading data.')
  }
}

// All readers share the same cache and pending requests. No persisted user data.
export const useResourceStore = defineStore('resources', () => {
  const entries = shallowRef<Record<string, Entry>>({})
  const pending = new Map<string, Promise<unknown>>()
  const revisions = new Map<string, number>()
  let generation = 0
  function invalidate(prefixes?: string[]) {
    const paths = new Set([...Object.keys(entries.value), ...pending.keys()])
    const updated = { ...entries.value }
    for (const path of paths) {
      if (
        prefixes &&
        !prefixes.some(
          (prefix) =>
            path === prefix ||
            path.startsWith(prefix + '/') ||
            path.startsWith(prefix + '?') ||
            path.startsWith(prefix + ':'),
        )
      )
        continue
      revisions.set(path, (revisions.get(path) ?? 0) + 1)
      pending.delete(path)
      if (updated[path]) updated[path] = { ...updated[path], fetchedAt: 0 }
    }
    entries.value = updated
  }
  function clear() {
    generation++
    entries.value = {}
    pending.clear()
    revisions.clear()
  }
  async function read<T>(
    path: string,
    loader: () => Promise<T>,
    options: { ttl?: number; force?: boolean } = {},
  ): Promise<T> {
    const cached = entries.value[path]
    if (!options.force && cached && Date.now() - cached.fetchedAt < (options.ttl ?? 60000))
      return cached.value as T
    const existing = pending.get(path)
    if (existing) return existing as Promise<T>
    const ticket = generation,
      revision = revisions.get(path) ?? 0
    const request = loader()
      .then(async (value) => {
        if (ticket !== generation) throw new SessionChanged()
        if (revision !== (revisions.get(path) ?? 0)) {
          if (pending.get(path) === request) pending.delete(path)
          const replacement = entries.value[path]
          if (replacement && replacement.fetchedAt > 0) return replacement.value as T
          return read<T>(path, loader, { ...options, force: true })
        }
        entries.value = { ...entries.value, [path]: { value, fetchedAt: Date.now() } }
        const keys = Object.keys(entries.value)
        if (keys.length > 100) {
          const updated = { ...entries.value }
          for (const key of keys
            .sort((a, b) => updated[a]!.fetchedAt - updated[b]!.fetchedAt)
            .slice(0, keys.length - 100))
            delete updated[key]
          entries.value = updated
        }
        return value
      })
      .finally(() => {
        if (pending.get(path) === request) pending.delete(path)
      })
    pending.set(path, request)
    return request
  }
  function get<T>(path: string, options: { ttl?: number; force?: boolean } = {}) {
    return read(path, () => api<T>(path), options)
  }
  function preview<T>(body: unknown, capabilities: unknown) {
    const snapshot = JSON.parse(JSON.stringify(body)) as unknown
    const key = '/preview:' + JSON.stringify([snapshot, capabilities])
    return read(key, () => api<T>('/preview', 'POST', snapshot), { ttl: 60000 })
  }
  onApiMutation((path) => {
    // Recording a release visit does not change any application resources.
    if (path === '/auth/changelog') return
    const printing = [
      '/workspace',
      '/printers/status',
      '/destinations',
      '/batches',
      '/cartridges',
      '/queue',
      '/jobs',
      '/runs',
      '/requests',
      '/access-holds',
      '/notifications',
    ]
    if (path.startsWith('/admin/')) {
      const collection = path.split('/').slice(0, 3).join('/')
      const affected = [collection]
      if (['/admin/users', '/admin/roles', '/admin/groups'].includes(collection))
        affected.push(...printing)
      if (collection === '/admin/roles' || collection === '/admin/groups')
        affected.push('/admin/users', '/admin/registration-codes')
      if (collection === '/admin/groups') affected.push('/templates', '/user-groups')
      if (collection === '/admin/users') affected.push('/admin/groups', '/admin/registration-codes')
      if (collection === '/admin/users' || collection === '/admin/trash')
        affected.push('/admin/trash', '/templates', '/image-assets', '/font-assets', ...printing)
      if (collection === '/admin/notification-endpoints')
        affected.push('/notifications', '/workspace')
      invalidate(affected)
    } else if (path.startsWith('/templates'))
      invalidate(['/templates', '/preview', '/admin/trash', ...printing])
    else if (path.startsWith('/image-assets') || path.startsWith('/font-assets'))
      invalidate([
        path.split('/').slice(0, 2).join('/'),
        '/templates',
        '/preview',
        '/admin/trash',
        ...printing,
      ])
    else if (path.startsWith('/tape-profiles')) invalidate(['/tape-profiles', ...printing])
    else if (
      path.startsWith('/printers') ||
      path.startsWith('/printer-groups') ||
      path.startsWith('/printer/') ||
      path.startsWith('/destinations/')
    )
      invalidate(['/printers', '/preview', ...printing])
    else if (
      path.startsWith('/cartridges') ||
      path.startsWith('/jobs') ||
      path.startsWith('/queue') ||
      path.startsWith('/runs') ||
      path.startsWith('/requests') ||
      path.startsWith('/access-holds') ||
      path.startsWith('/batches')
    )
      invalidate(printing)
    else invalidate()
  })
  window.addEventListener('session-ended', clear)
  window.addEventListener('access-changed', clear)
  return { entries, get, preview, invalidate, clear }
})
