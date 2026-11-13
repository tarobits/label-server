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

The checks also reject duplicate catalog keys, verify literal server message keys,
and guard the migrated shared request-error modules, group-funding, retry,
cartridge-price and batch-review errors, and
approval-digest, review, retry and price-approval notification producers against
hardcoded text. Integration tests exercise German request-limit/CSRF
errors and notification delivery across language changes and retries. These guards
are scoped: they do not yet guarantee translation coverage of every screen or
server message. Extend them when migrating another feature; do not whitelist new
user-facing English to make a test pass.

Interface messages also cover conditional labels, confirmation dialogs, accessible
names, editor setting help, font weights, upload results and printer permissions.
Keep translated option labels reactive (computed values or getters); never replace
stored permission IDs, upload states or logic syntax with translated values.
Tests exercise locale changes without losing drafts or retrying completed uploads.

The logic reference, source diagnostics and operation descriptions use these
catalogs too. Some runtime printer reasons and framework-generated validation
messages still retain their original text.

Installer and updater messages use the separate nested `deployment.json` bundle.
They follow the terminal locale with an explicit `--language en|de` override,
preserving unattended updater behavior and the installer's interactive wizard.
The updater validates and backs up this bundle during self-update so translations
remain available before the application checkout is updated. Bootstrap errors
when the bundle cannot be read cannot use its translations.

Use `Message` for translated HTTP exception details. The main and companion HTTP
exception handlers render these in the request language, preserving status codes
and headers. Plain strings remain unchanged; do not infer translation keys from
user content. Personal notification endpoints use their owner's current language;
shared endpoints without an owner retain English.

Group-funding decisions, empty-cartridge alerts, print completions, batch-review
notices, retry offers and cartridge-price approvals also carry stored translation
descriptors. Label, printer and cartridge names remain literal parameters. Printer
faults and new block reasons carry optional translation descriptors in companion
status messages and stored printer state. Audit reasons keep the same access
restrictions when translated. Historical reasons without metadata retain their
recorded wording; malformed or mismatched metadata cannot replace that wording.
External driver diagnostics and other unconverted messages retain their original text.
