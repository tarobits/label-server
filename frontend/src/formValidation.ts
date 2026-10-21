import type { ObjectDirective } from 'vue'
import { ApiError } from './api'

export type FieldErrors = Record<string, string>
type Control = HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement
let nextId = 0
const forms = new WeakMap<HTMLFormElement, ReturnType<typeof createValidation>>()

export function apiFieldErrors(error: unknown, prefix = ['body']): FieldErrors {
  if (!(error instanceof ApiError) || !Array.isArray(error.detail)) return {}
  return Object.fromEntries(
    error.detail
      .filter(
        (issue) =>
          issue &&
          Array.isArray(issue.loc) &&
          typeof issue.msg === 'string' &&
          prefix.every((part, index) => issue.loc[index] === part),
      )
      .map((issue) => [issue.loc.slice(prefix.length).join('.'), issue.msg]),
  )
}

export function focusFormErrors(form: HTMLFormElement | null) {
  if (form) forms.get(form)?.focusErrors()
}

function createValidation(form: HTMLFormElement) {
  const prefix = `validation-${++nextId}`
  const entries = new Map<
    Control,
    {
      message: HTMLSpanElement
      invalid: string | null
      description: string | null
      label: string | null
      customMessage: string
    }
  >()
  let external: FieldErrors = {}
  let submitted = false
  let summary: HTMLDivElement | undefined
  let summaryKey = ''
  let focusPending = false
  let disposed = false
  const controls = () =>
    [...form.querySelectorAll<Control>('input, select, textarea')].filter(
      (control) => control.form === form,
    )

  function clear(control: Control) {
    const entry = entries.get(control)
    if (!entry) return
    entry.message.remove()
    for (const [attribute, value] of [
      ['aria-invalid', entry.invalid],
      ['aria-describedby', entry.description],
      ['aria-label', entry.label],
    ]) {
      if (value === null) control.removeAttribute(attribute!)
      else control.setAttribute(attribute!, value!)
    }
    if (entry.customMessage) control.setCustomValidity('')
    entries.delete(control)
  }

  function render() {
    const fields = controls()
    for (const control of entries.keys()) if (!fields.includes(control)) clear(control)
    for (const control of fields) {
      const previous = entries.get(control)
      const customMessage = external[control.name] ?? ''
      if (previous?.customMessage) control.setCustomValidity('')
      if (customMessage) control.setCustomValidity(customMessage)
      const message =
        control.willValidate && (submitted || customMessage) ? control.validationMessage : ''
      if (!message) {
        clear(control)
        continue
      }
      let entry = previous
      if (!entry) {
        const element = document.createElement('span')
        element.id = `${prefix}-error-${++nextId}`
        element.className = 'field-error'
        element.setAttribute('aria-live', 'polite')
        entry = {
          message: element,
          invalid: control.getAttribute('aria-invalid'),
          description: control.getAttribute('aria-describedby'),
          label: control.getAttribute('aria-label'),
          customMessage,
        }
        // Keep the error out of the field's accessible name when its label wraps it.
        if (!control.hasAttribute('aria-label') && !control.hasAttribute('aria-labelledby')) {
          const label = control.labels?.[0]
          if (label) control.setAttribute('aria-label', label.textContent?.trim() ?? '')
        }
        if (!control.id) control.id = `${prefix}-field-${++nextId}`
        const label = control.closest('label')
        if (label) label.append(element)
        else control.after(element)
        entries.set(control, entry)
      }
      entry.customMessage = customMessage
      entry.message.textContent = message
      control.setAttribute('aria-invalid', 'true')
      control.setAttribute(
        'aria-describedby',
        [entry.description, entry.message.id].filter(Boolean).join(' '),
      )
    }
    const key =
      submitted && entries.size > 1
        ? JSON.stringify(
            [...entries].map(([control, entry]) => [control.id, entry.message.textContent]),
          )
        : ''
    if (key === summaryKey) return
    summaryKey = key
    summary?.remove()
    summary = undefined
    if (submitted && entries.size > 1) {
      summary = document.createElement('div')
      summary.className = 'alert danger validation-summary'
      summary.tabIndex = -1
      summary.setAttribute('role', 'alert')
      summary.setAttribute('aria-labelledby', `${prefix}-heading`)
      const heading = document.createElement('strong')
      heading.id = `${prefix}-heading`
      heading.textContent = `${entries.size} fields need attention`
      const list = document.createElement('ul')
      for (const [control, entry] of entries) {
        const item = document.createElement('li')
        const link = document.createElement('a')
        link.href = `#${control.id}`
        const label =
          control.getAttribute('aria-label') ||
          control.labels?.[0]?.textContent?.trim() ||
          control.name
        link.textContent = `${label}: ${entry.message.textContent}`
        link.addEventListener('click', (event) => {
          event.preventDefault()
          control.focus()
        })
        item.append(link)
        list.append(item)
      }
      summary.append(heading, list)
      form.prepend(summary)
    }
  }

  function focusErrors() {
    submitted = true
    render()
    const target = summary ?? entries.keys().next().value
    target?.focus()
  }
  function invalid(event: Event) {
    event.preventDefault()
    submitted = true
    if (focusPending) return
    focusPending = true
    queueMicrotask(() => {
      focusPending = false
      if (!disposed) focusErrors()
    })
  }
  function submit() {
    submitted = true
    render()
  }
  function input(event: Event) {
    const control = event.target as Control
    if (!entries.has(control)) return
    // A server error belongs to the submitted value, not the next edit.
    if (control.name in external) {
      external = { ...external }
      delete external[control.name]
    }
    render()
  }
  form.addEventListener('invalid', invalid, true)
  form.addEventListener('submit', submit, true)
  form.addEventListener('input', input)
  form.addEventListener('change', input)
  return {
    update(errors: FieldErrors = {}) {
      external = errors
      render()
    },
    focusErrors,
    dispose() {
      disposed = true
      form.removeEventListener('invalid', invalid, true)
      form.removeEventListener('submit', submit, true)
      form.removeEventListener('input', input)
      form.removeEventListener('change', input)
      for (const control of entries.keys()) clear(control)
      summary?.remove()
    },
  }
}

export const vValidateForm: ObjectDirective<HTMLFormElement, FieldErrors | undefined> = {
  mounted(form, binding) {
    const validation = createValidation(form)
    forms.set(form, validation)
    validation.update(binding.value)
  },
  updated(form, binding) {
    forms.get(form)?.update(binding.value)
  },
  beforeUnmount(form) {
    forms.get(form)?.dispose()
    forms.delete(form)
  },
}
