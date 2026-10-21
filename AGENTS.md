# Taro's Label Room

## Hard Rules

- Never let printer-specific protocol concerns leak into the queue/domain layer.
- Always use conventional commits unless otherwise instructed.

## UI Copy and Minimalism

- Do not add redundant, self-evident, or unnecessary explanatory text to the UI.
- Assume users understand common UI conventions and standard editor behavior.
- Do not explain behavior that is already obvious from the interface or its immediate feedback.
- Avoid unsolicited helper text, instructional subtitles, tooltips, and descriptive paragraphs.
- Prefer intuitive design over explaining how the interface works.
- Every piece of UI text must serve a clear purpose. If removing it does not reduce usability or understanding, omit it.
- Only add explanations when behavior is genuinely non-obvious, potentially destructive, safety-critical, or requires important context.
- Do not add text merely to fill empty space or make the interface appear more informative.

When in doubt, leave unnecessary text out.

## Release Notes and Changelogs

Follow the "Keep a Changelog" 1.1.0 convention.

When preparing a release, always generate a Markdown
changelog summarizing the changes since the previous release.

### Format

## [VERSION] - YYYY-MM-DD

### Added
- New features and functionality.

### Changed
- Modifications to existing functionality.

### Fixed
- Resolved bugs and incorrect behavior.

### Removed
- Removed features and functionality.

### Security
- Security improvements and vulnerability fixes.

### Rules

- Only include categories containing actual changes.
- Use concise, descriptive bullet points.
- Write from the user's perspective, not the developer's.
- Group related changes into one entry.
- Avoid implementation details unless relevant to users.
- Do not include trivial refactoring or formatting changes.
- Never invent changes.
- Determine changes from the Git history and actual code diff.
- Compare against the previous release tag when available.
- Highlight breaking changes and migration requirements.
- Use Semantic Versioning where applicable.
- Default to English.
- Output release notes as copyable Markdown.
- Maintain CHANGELOG.md when explicitly preparing a release.
