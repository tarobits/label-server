import type { Profile, Printer } from '../shared/types'
import type { TemplateDocument } from '../templates/editor'

export interface MediaProperties {
  media_family: 'tze' | 'fixed_label'
  label_length_mm: number | null
}
export function mediaProperties(
  profile: Pick<Profile, 'media_family' | 'label_length_mm'>,
): MediaProperties {
  return {
    media_family: profile.media_family ?? 'tze',
    label_length_mm: profile.label_length_mm ?? null,
  }
}
export function mediaLabel(profile: Profile | undefined) {
  if (!profile) return ''
  return profile.media_family === 'fixed_label'
    ? `Fixed labels · ${profile.width_mm} × ${profile.label_length_mm} mm`
    : `TZe · Continuous · ${profile.width_mm} mm`
}
export function compatibleProfile(
  profile: Profile | undefined,
  capabilities?: Printer['capabilities'],
  document?: TemplateDocument,
) {
  if (!profile) return false
  const media = mediaProperties(profile)
  if (
    document &&
    (document.width_mm !== profile.width_mm ||
      (document.media?.media_family ?? 'tze') !== media.media_family ||
      (document.media?.label_length_mm ?? null) !== media.label_length_mm)
  )
    return false
  if (!capabilities) return true
  return (
    media.media_family === (capabilities.media_family ?? 'tze') &&
    (media.media_family === 'tze' ? 'continuous' : 'fixed_label') ===
      (capabilities.media_kind ?? 'continuous') &&
    capabilities.supported_widths_mm.includes(profile.width_mm) &&
    (media.media_family !== 'fixed_label' ||
      !!capabilities.fixed_label_sizes_mm?.some(
        ([width, length]) => width === profile.width_mm && length === media.label_length_mm,
      ))
  )
}
