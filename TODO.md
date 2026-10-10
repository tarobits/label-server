# ToDo

- Create a way to hold off on automatic printing (in case you want to create a really big batch and don't want to waste anything on separate print jobs)

Implemented: persistent automatic-print hold on the Overview screen and via
`PUT /api/printer/automatic-printing`. Manual flush remains available; resuming
re-evaluates thresholds. See PLAN.md for the full behavior and scope.

- Add a way to ignore out of bounds objects

Implemented: saved clipping option in the editor. Partial objects are clipped to
the printable area; fully outside objects are omitted but remain editable.

- Implement automatic label resizing (toggleable)

Implemented: automatic continuous-label length, plus optional text-box width fitted
to each field value. Resolved dimensions are frozen when queued. Tape width is fixed.

- Implement chain printing (with csv to populate fields) (Like the database printing in the p touch editor)

CSV authoring implemented: import, field mapping, selected/reordered records, copy
counts, durable frozen drafts and atomic, retry-safe submission. Brother USB
multi-page and final-feed commands are implemented. The user validated physical
printer testing on 2026-10-04; measured consumption calibration values have not
been recorded.

- Implement print previews for the chain printing as well

Implemented: per-record smooth/raster previews and an ordered run overview with
dimensions, copies and adapter-based tape estimate. Drafts also retain a planned
feed/cut sequence. Physical printer testing was validated by the user on 2026-10-04.

- Make fonts addable through the web UI

Implemented: Fonts page accepts static TTF/OTF uploads and the editor selects each
face. Hiding/restoring fonts preserves references in saved templates and queued jobs.

- Make images addable like bitmaps, svgs etc. It automatically adjusts the image to the color you're printing with additional settings to adjust the brightness and contrast.

Implemented: Images library and editor image elements with aspect fitting,
brightness, contrast, threshold and monochrome dithering. Still PNG/JPEG/WebP/BMP/GIF
and a constrained SVG shapes/paths subset are supported. Preview uses the tape's
colors; hidden assets remain available to frozen templates, jobs and CSV runs.

- The PT-P710BT can print in grayscale so be sure to implement that too especially for images

Native grayscale is still pending Brother hardware verification. Dithered shading
is available now as explicitly monochrome output, not native grayscale.

- Add user authentication with administrators being able to create roles with permissions. And issue registration codes with which you can register. Make registration by code toggleable so if it is set to false you can freely register.

- Requests should also be added which means it is placed in a separate queue which the administrator has to approve first. Also make notifications to the administrator when something is added to the queue. But also make a debounce on notifications which is configurable because we do not need 50 notifications coming in because someone added 50 to the request queue.

- Make global, group and user specific templates. The administrator can see all of them. Global templates can only be created by the administrator.

- Groups can be created by the administrator and users can be added to it to share templates among themselves.

- For the multi printer support make the admin able to assign access to each individual printer for each user/group.

- All user/group/role and permissions todos are low priority. They should be appended to the end of the implementation plan into a different phase which requires approval before proceeding with implementation. Although implement the vague archetectural structure so the future implementation does not require a full rewrite.

Phase 8 implemented and verified on 2026-10-04. The agreed model uses
roles assigned directly to users, per-member template-group rights, and five
role-defined printer/distribution-group access levels. The protected Administrator
role covers all existing and future resources, including all group templates.
Access changes require an administrator preview/confirmation; lost access pauses
queued jobs for an administrator decision. See PLAN.md and docs/ACCESS_CONTROL.md
for the full specification and acceptance checks. Verification passed 269 backend
tests and 28 browser tests, with independent backend/UI review. Existing
installations require migrations, a frontend rebuild and a server restart.
