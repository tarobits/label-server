# License and attribution

Taro's Label Room

Copyright (C) 2026 tarobits and contributors

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU Affero General Public License as published by the Free
Software Foundation, either version 3 of the License, or (at your option) any
later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE. See the GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License along
with this program. If not, see <https://www.gnu.org/licenses/>.

The project-owned source code, companion, frontend, scripts and documentation
are licensed under **AGPL-3.0-or-later**, unless a file states otherwise. See
[LICENSE](LICENSE) for the full license text. This notice does not relicense
third-party material or content supplied by users.

## Third-party material

- Bundled Noto Sans fonts retain their SIL Open Font License and copyright
  notices in [app/fonts/OFL.txt](app/fonts/OFL.txt).
- Python and JavaScript dependencies retain their own licenses and attribution
  requirements. Their versions are recorded in [requirements.lock](requirements.lock)
  and [frontend/package-lock.json](frontend/package-lock.json). Keep their license
  files and notices when redistributing them; this notice does not replace those
  terms. Heroicons, Vue and CodeMirror are among the MIT-licensed frontend dependencies.
- resvg-py is MIT-licensed; its upstream license is available in the
  [resvg-py repository](https://github.com/baseplate-admin/resvg-py/blob/master/LICENSE).
  Native libraries bundled by dependencies also retain their upstream licenses.

## Source availability

Source and release tags are available at
<https://github.com/tarobits/label-server>. Installation and build instructions are
in [README.md](README.md) and [docs/COMPANION.md](docs/COMPANION.md).

Both interfaces expose a **Source** link and a downloadable copy of the license.
For modified deployments, update `frontend/src/components/SourceLink.vue` to point
to the corresponding source of the version actually running, including your
modifications and the scripts needed to build and install it. Rebuild the relevant
frontend. An unchanged link to upstream is not a source offer for unpublished
modifications. Keep the source offer available to remote users as required by
AGPL section 13, and follow the distribution requirements when supplying copies.

This license permits commercial use and self-hosting. It does not require
publishing users' private labels, uploads, credentials or production databases
merely because they are processed by the application.
