# Label Printer Server

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
