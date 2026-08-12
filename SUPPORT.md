# PlaylistMuse support and feedback

GitHub Issues is the official place for PlaylistMuse support reports.

Use the appropriate category:

- **Bug report** for reproducible technical failures, broken functions, errors, crashes, or unexpected application behavior.
- **Playlist result feedback** when PlaylistMuse works technically but a generated or refined playlist does not follow the musical request as expected.

## Playlist result feedback

From a generated playlist, select **Give feedback**. PlaylistMuse opens a GitHub issue with the relevant request context and current track list already prepared.

Before submitting it:

1. Describe what part of the request was not respected.
2. Explain what result you expected instead.
3. Review the captured prompt, refinement context, generation filters, and track list.
4. Remove personal or sensitive information if the prompt contains any.

Playlist result feedback does **not** need a diagnostic ZIP unless there is also a technical failure. These reports are reviewed separately from bugs and can be promoted into PlaylistMuse's prompt-quality regression corpus after the expected behavior has been validated.

If you open the issue directly from GitHub instead of from PlaylistMuse, choose **Playlist result feedback** and paste the relevant prompt or Playlist Studio instruction and playlist result.

## Before opening a bug report

1. Confirm the problem still occurs after reloading PlaylistMuse.
2. Note the exact steps needed to reproduce it.
3. If an error message contains an ID beginning with `PM-`, keep that **error reference**.
4. Open **Settings → Diagnostics** and select **Download diagnostic report**.
5. Review the downloaded ZIP before sharing it.
6. Open the GitHub **Bug report** form and attach the diagnostic ZIP when available.

## What to include in a bug report

A useful bug report should contain:

- PlaylistMuse version/build.
- Installation method: `latest`, a versioned Docker tag, Docker Compose/source, or another setup.
- Browser and operating system.
- Exact steps to reproduce the problem.
- Expected behavior and actual behavior.
- Whether the problem happens every time or intermittently.
- AI provider and model when the problem involves generation, refinement, prompt analysis, or AI configuration.
- Whether Last.fm or YouTube Music was involved.
- Any `PM-...` error reference shown by PlaylistMuse.
- A screenshot when it helps explain the visible problem.
- The diagnostic report when available.

If a playlist-generation problem is a technical failure and depends on a particular prompt or seed song, include it when you can. Remove personal information first if the request contains any.

## Diagnostic report

PlaylistMuse stores rotating application logs under `data/logs` and can package recent diagnostics into a ZIP from **Settings → Diagnostics**.

The archive contains:

- build version, release channel and source commit;
- basic runtime information;
- AI provider/model configuration state without API keys;
- Last.fm and YouTube Music connection/configuration state without credentials;
- local playlist-library schema metadata;
- recent PlaylistMuse application logs;
- frontend JavaScript errors captured by the browser when available.

Log files are rotated automatically so they do not grow indefinitely.

## Privacy and credentials

PlaylistMuse sanitizes diagnostic logs as they are written and sanitizes them again when the ZIP is created. Known local credentials and common secret formats are redacted.

No automatic redaction system can guarantee detection of every possible sensitive value. **Review the archive before uploading it.**

Never attach any of these files to a public issue:

- `.env`;
- `data/config.json`;
- `data/lastfm.json`;
- `data/youtube-settings.json`;
- `data/youtube-oauth.json`;
- API keys, passwords, cookies or authorization headers.

## Error references

Server-side failures receive an identifier such as:

```text
PM-20260811-ABC123
```

The same reference is written to the application log. Including it in the bug report makes it easier to match the visible failure to the relevant diagnostic entry.

## Security issues

Do not publish credentials, tokens or other secrets in a GitHub issue. If a suspected bug has already exposed a credential, revoke or rotate that credential before doing anything else.
