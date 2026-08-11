# Stable release notes

Every new stable PlaylistMuse version must include a curated, user-facing release note file before it can be published.

Create one file named:

```text
.github/release-notes/vX.Y.Z.md
```

where `X.Y.Z` matches `backend.version.APP_VERSION`.

The stable release workflow refuses to publish a new version when this file is missing or empty. Its contents are prepended to GitHub's automatically generated release notes, so the release page contains both a useful summary of the product changes and the complete PR/changelog information.

## Recommended structure

```markdown
## Highlights

- The most important user-visible change.
- Another major capability or improvement.

## New and improved

- New feature or meaningful enhancement.
- Workflow, integration or usability improvement.

## Fixes

- Relevant fixes that users are likely to notice.

## Upgrade notes

- Only include this section when an upgrade requires user action or has compatibility implications.
```

Keep the notes concise but substantive. Focus on what changed for users and why it matters. Avoid internal development details, temporary test environments, VPS references, implementation-only refactors, or routine CI information unless they materially affect installation or operation.
