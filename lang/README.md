# Translations

`en.json` and `de.json` are the shared English and German message catalogs for
the main interface, companion and server. Keep the same nested keys in both files.
Group messages by feature and reference them by path, such as `account.language`.
Keys are stable identifiers, not English sentences.

Vue components use Vue I18n's `$t('account.language')`; scripts use `t` from
`frontend/src/shared/i18n.ts`. Use named parameters for complete sentences rather than
joining translated fragments. Use Vue I18n plural forms separated by ` | ` and
pass `count`. Escape literal reserved characters with Vue I18n literal syntax,
for example `{'@'}`. Never use translated strings as stored values or identifiers.

Server messages use `app.i18n.Message` and the same dot-separated keys. The shared
server subset supports named parameters, literal interpolation and English/German
plural forms. Do not use linked messages or positional parameters for messages
consumed by the server. Stored notification descriptors allow delivery in the
recipient's language; old notifications without descriptors retain their text.

User names, template content, filenames, logic source and other user-entered data
are not translated. English is the fallback language. Account language choices
override the device preference; `browser` selects English or German from browser
preferences, falling back to English.

Run `npm run test:i18n` from `frontend` to check catalogs and literal translation
references, and `pytest tests/test_i18n.py` for server catalog and preference checks.
