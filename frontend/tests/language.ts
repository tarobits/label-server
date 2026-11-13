import { expect, type Page } from '@playwright/test'

export const languagePicker = (page: Page) =>
  page.getByRole('button', { name: /^(Language|Sprache)$/ })
export async function selectLanguage(page: Page, language: 'en' | 'de') {
  const trigger = languagePicker(page)
  if ((await trigger.getAttribute('aria-expanded')) !== 'true') await trigger.click()
  await page
    .getByRole('menuitemradio', { name: language === 'de' ? 'Deutsch' : 'English', exact: true })
    .click()
}
export async function expectLanguage(page: Page, language: 'en' | 'de') {
  const trigger = languagePicker(page)
  const wasOpen = (await trigger.getAttribute('aria-expanded')) === 'true'
  if (!wasOpen) await trigger.click()
  await expect(
    page.getByRole('menuitemradio', {
      name: language === 'de' ? 'Deutsch' : 'English',
      exact: true,
    }),
  ).toHaveAttribute('aria-checked', 'true')
  await expect(page.getByRole('menuitemradio')).toHaveCount(2)
  if (!wasOpen) await trigger.press('Escape')
}
