import type { Page } from '@playwright/test'

export async function showEditorTab(page: Page, name: 'Content' | 'Style' | 'Layout') {
  const tab = page.getByRole('tab', { name, exact: true })
  if ((await tab.getAttribute('aria-selected')) !== 'true') await tab.click()
}

export async function showEditorSettings(page: Page, section: string) {
  await showEditorTab(
    page,
    ['Typography', 'Spacing & padding', 'Image adjustments', 'Appearance'].includes(section)
      ? 'Style'
      : 'Layout',
  )
  const toggle = page.getByRole('button', { name: section, exact: true })
  if ((await toggle.getAttribute('aria-expanded')) !== 'true') await toggle.click()
}
