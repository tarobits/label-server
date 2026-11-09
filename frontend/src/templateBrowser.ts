import type { Template } from './types'

export const normalizeTemplateSearch = (value: string) =>
  value.normalize('NFKD').replace(/\p{M}/gu, '').toLocaleLowerCase()

export function matchesTemplateSearch(template: Template, query: string) {
  const text = normalizeTemplateSearch(
    [
      template.name,
      template.group_name ?? '',
      ...template.fields,
      ...template.document.fields.map((field) => field.label),
    ].join(' '),
  )
  return normalizeTemplateSearch(query)
    .split(/\s+/)
    .filter(Boolean)
    .every((term) => text.includes(term))
}

export const compareTemplateNames = (a: Template, b: Template) =>
  a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' }) ||
  a.id.localeCompare(b.id)

const recentKey = (user: string) => `label-room:recent-templates:${user}`
export function recentTemplates(user: string | undefined): string[] {
  if (!user) return []
  try {
    const value: unknown = JSON.parse(localStorage.getItem(recentKey(user)) ?? '[]')
    return Array.isArray(value)
      ? [...new Set(value.filter((id): id is string => typeof id === 'string'))].slice(0, 6)
      : []
  } catch {
    return []
  }
}

export function rememberTemplate(user: string | undefined, template: string) {
  if (!user || !template) return
  try {
    localStorage.setItem(
      recentKey(user),
      JSON.stringify(
        [template, ...recentTemplates(user).filter((id) => id !== template)].slice(0, 6),
      ),
    )
  } catch {
    // Browser storage is optional; choosing and printing labels must still work.
  }
}
