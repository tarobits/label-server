import { expect, type Page } from '@playwright/test'

export function templateControl(page: Page) {
  return page.getByRole('button', { name: 'Change template', exact: true })
}

export async function chooseTemplate(page: Page, id: string) {
  const control = templateControl(page)
  const response = await page.request.get(`/api/templates/${encodeURIComponent(id)}`)
  expect(response.ok()).toBeTruthy()
  const template = await response.json()
  await control.click()
  const dialog = page.getByRole('dialog', { name: 'Choose template', exact: true })
  await dialog.getByRole('searchbox', { name: 'Search templates', exact: true }).fill(template.name)
  await dialog
    .locator(`[data-template-id="${id}"]`)
    .getByRole('button', { name: `Use ${template.name}`, exact: true })
    .click()
  await expect(dialog).not.toBeVisible()
  await expect(control).toHaveJSProperty('value', id)
}
