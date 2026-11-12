import { expect, type Page } from '@playwright/test'

export function tapeProfileControl(page: Page) {
  return page.getByRole('button', { name: 'Change tape profile', exact: true })
}

export async function chooseTapeProfile(page: Page, id: string) {
  await tapeProfileControl(page).click()
  const dialog = page.getByRole('dialog', { name: 'Choose tape profile', exact: true })
  const response = await page.request.get('/api/tape-profiles')
  expect(response.ok()).toBeTruthy()
  const profiles = await response.json()
  const profile = profiles.find((item: { id: string }) => item.id === id)
  await dialog
    .getByRole('searchbox', { name: 'Search tape profiles', exact: true })
    .fill(profile.name)
  await dialog
    .locator(`[data-profile-id="${id}"]`)
    .getByRole('button', { name: `Use ${profile.name}`, exact: true })
    .click()
  await expect(dialog).toBeHidden()
  await expect(tapeProfileControl(page)).toHaveJSProperty('value', id)
}
