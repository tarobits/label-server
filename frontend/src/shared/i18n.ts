import { computed, ref, watch } from 'vue'
import { createI18n } from 'vue-i18n'
import english from '../../../lang/en.json' with { type: 'json' }
import german from '../../../lang/de.json' with { type: 'json' }

export type Language = 'en' | 'de'
export type LanguagePreference = Language | 'browser'
type Parameters = Record<string, string | number>
const storageKey = 'label-room.language'
export const validPreference = (value: unknown): LanguagePreference =>
  value === 'en' || value === 'de' ? value : 'browser'
export function detectLanguage(languages: readonly string[]): Language {
  for (const language of languages) {
    const base = language.toLowerCase().split('-')[0]
    if (base === 'en' || base === 'de') return base
  }
  return 'en'
}
function readPreference(): LanguagePreference {
  try {
    return validPreference(localStorage.getItem(storageKey))
  } catch {
    return 'browser'
  }
}
export const deviceLanguage = ref<LanguagePreference>(readPreference())
export const accountLanguage = ref<LanguagePreference | null>(null)
export const deploymentLanguage = ref<Language | null>(null)
export const browserLanguage = ref(
  detectLanguage(typeof navigator === 'undefined' ? [] : (navigator.languages ?? [])),
)
export const locale = computed<Language>(() => {
  const preference =
    accountLanguage.value ??
    (deviceLanguage.value === 'browser'
      ? (deploymentLanguage.value ?? 'browser')
      : deviceLanguage.value)
  return preference === 'browser' ? browserLanguage.value : preference
})
export const i18n = createI18n({
  legacy: false,
  globalInjection: true,
  locale: locale.value,
  fallbackLocale: 'en',
  messages: { en: english, de: german },
})
export function t(key: string, parameters: Parameters = {}): string {
  return i18n.global.t(key, parameters)
}
export function number(value: number, options?: Intl.NumberFormatOptions) {
  return new Intl.NumberFormat(locale.value, options).format(value)
}
export function date(
  value: Date | number,
  options: Intl.DateTimeFormatOptions = { dateStyle: 'medium', timeStyle: 'short' },
) {
  return new Intl.DateTimeFormat(locale.value, options).format(value)
}
watch(
  locale,
  (value) => {
    i18n.global.locale.value = value
    if (typeof document !== 'undefined') document.documentElement.lang = value
  },
  { immediate: true, flush: 'sync' },
)
watch(
  deviceLanguage,
  (value) => {
    try {
      localStorage.setItem(storageKey, value)
    } catch {
      /* Session-only preference. */
    }
  },
  { flush: 'sync' },
)
if (typeof window !== 'undefined')
  window.addEventListener('storage', (event) => {
    if (event.key === storageKey || event.key === null) deviceLanguage.value = readPreference()
  })
if (typeof window !== 'undefined')
  window.addEventListener('languagechange', () => {
    browserLanguage.value = detectLanguage(navigator.languages)
  })
