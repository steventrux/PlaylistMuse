# PlaylistMuse support and feedback

GitHub Issues is the official place for PlaylistMuse support reports and playlist-result feedback.

This guide explains which report to open, what information to include, how to collect diagnostics safely, and what to check before submitting an issue.

## Choose the right report

| Situation | Use |
|---|---|
| PlaylistMuse crashes, shows an error, fails to load, or a function is broken | **Bug report** |
| Generation, refinement or publishing fails technically | **Bug report** |
| PlaylistMuse works, but the generated/refined playlist does not follow the musical request as expected | **Playlist result feedback** |
| A prompt constraint, artist count, ordering instruction or recording preference was interpreted incorrectly | **Playlist result feedback** |
| You are unsure whether the problem is technical or related to playlist quality | Start with a **Bug report** if an error or failed operation occurred; otherwise use **Playlist result feedback** |

Open a bug report:

https://github.com/steventrux/PlaylistMuse/issues/new?template=bug_report.yml

Open playlist-result feedback:

https://github.com/steventrux/PlaylistMuse/issues/new?template=playlist_feedback.yml

You can also start playlist-result feedback directly from the PlaylistMuse playlist page with **Give feedback**. This is preferred because relevant playlist context is prepared automatically.

## Before asking for support

Before opening a technical issue, check the following:

1. Reload PlaylistMuse and retry the operation once.
2. Confirm that the container is running.
3. Confirm that you are opening the correct host and port.
4. If the problem concerns an external service, verify that the relevant integration is configured and connected.
5. Record the exact sequence of actions that leads to the problem.
6. Keep any visible error message and any reference beginning with `PM-`.
7. Note whether the problem occurs every time or only intermittently.
8. Open **Settings → Diagnostics** and download a diagnostic report when the application is reachable.
9. Review the diagnostic archive before attaching it to a public issue.
10. Remove personal or sensitive information from screenshots, prompts and copied text.

Do not reset the application, delete the `data` directory, disconnect accounts, or overwrite configuration files only to see whether the problem disappears unless you already have a backup and understand the consequences.

## Bug reports

Use the **Bug report** form for reproducible technical failures, including:

- application startup failures;
- pages or controls that do not work;
- crashes or server errors;
- failed playlist generation caused by a technical error;
- failed Playlist Studio operations caused by a technical error;
- persistent storage or library problems;
- configuration failures;
- AI provider connection errors;
- Last.fm integration failures;
- YouTube Music connection or publishing failures;
- unexpected application behavior that is not simply a disagreement about the musical result.

### What to include

A useful bug report should include all information that is relevant to the problem:

- **PlaylistMuse version/build** shown in **Settings → Diagnostics**;
- **installation method**: `latest` Docker image, versioned Docker image, source/Docker Compose, or another setup;
- **browser and browser version**;
- **operating system**;
- **exact steps to reproduce** the problem;
- **expected behavior**;
- **actual behavior**;
- whether the problem occurs **every time, often, sometimes, or only once**;
- **AI provider and model** if generation, refinement, prompt analysis or AI settings are involved;
- whether **Last.fm** or **YouTube Music** was involved;
- the exact visible error message when useful;
- any **`PM-...` error reference** shown by PlaylistMuse;
- screenshots when they help explain the visible problem;
- the **diagnostic ZIP** when available and safe to share.

If a technical generation failure depends on a particular prompt or reference song, include that input when possible. Remove personal or sensitive information first.

### Minimal reproducible steps

Try to reduce the problem to the shortest reliable sequence. For example:

```text
1. Open PlaylistMuse.
2. Open a saved draft.
3. Enter the following Playlist Studio instruction: ...
4. Apply the refinement.
5. PlaylistMuse shows PM-... and the change is not applied.
```

A short reproducible sequence is more useful than a long description of everything done before the failure.

## Playlist result feedback

Use **Playlist result feedback** when PlaylistMuse completes the operation but the musical result does not match the request.

Typical examples include:

- a requested artist or style is missing;
- an exclusion was not respected;
- an artist count is wrong;
- a request for a specific recording type was not respected;
- ordering or progression does not follow the instruction;
- a Playlist Studio refinement changes something that should have remained unchanged;
- the result technically succeeds but clearly misunderstands the prompt.

Do **not** use playlist-result feedback for crashes, connection failures, timeouts or other technical errors.

### Preferred reporting method

From the playlist page, select **Give feedback**. PlaylistMuse prepares a GitHub report with relevant request and playlist context already included.

Before submitting:

1. Describe exactly what part of the request was not respected.
2. Explain what you expected instead.
3. Review the captured prompt or Playlist Studio instruction.
4. Review any previous refinement context included in the report.
5. Review the playlist result or relevant tracks.
6. Remove personal or sensitive information.

A diagnostic ZIP is normally unnecessary for playlist-result feedback unless a technical failure also occurred.

### Good playlist feedback

Useful feedback is specific about the rule that was not respected.

Less useful:

```text
The playlist is bad.
```

More useful:

```text
I requested exactly two tracks by this artist, but the result contains four.
The rest of the playlist is acceptable. I expected the artist count to remain exactly two after refinement.
```

Musical taste alone is not necessarily a defect. Explain which explicit instruction, constraint or expected behavior was not followed whenever possible.

## Diagnostic report

PlaylistMuse can create a diagnostic ZIP from **Settings → Diagnostics**.

Use it for technical issues when the application is still reachable.

The archive is designed to provide troubleshooting context without requiring you to upload the complete application data directory. Depending on the running version and available information, it may include:

- PlaylistMuse version, release channel and source revision;
- basic runtime information;
- configured AI provider/model state without API keys;
- Last.fm configuration state without the API key;
- YouTube Music configuration/connection state without OAuth credentials;
- playlist-library schema metadata;
- recent PlaylistMuse application logs;
- recent browser-side JavaScript errors captured by PlaylistMuse when available.

PlaylistMuse keeps a limited set of rotating logs under the persistent application data directory so log files do not grow indefinitely.

### Error references

Server-side failures can receive an identifier such as:

```text
PM-20260811-ABC123
```

The same reference is written to the application log. Include it in the bug report exactly as displayed so the visible failure can be matched to the relevant diagnostic entry.

## Privacy and credentials

Treat the PlaylistMuse `data` directory as private. It contains application state and may contain service credentials or authorization data.

PlaylistMuse sanitizes diagnostic logging and sanitizes diagnostic archives before download. Known local credentials and common secret formats are redacted. This reduces risk but cannot guarantee that every possible sensitive value will always be detected.

**Always review a diagnostic archive before uploading it to a public issue.**

Never attach any of the following to a public issue:

- `.env`;
- `data/config.json`;
- `data/lastfm.json`;
- `data/youtube-settings.json`;
- `data/youtube-oauth.json`;
- OAuth pending-state files;
- API keys;
- passwords;
- access tokens or refresh tokens;
- cookies;
- authorization headers;
- private reverse-proxy or authentication configuration;
- a complete copy of the PlaylistMuse `data` directory.

Also review screenshots and prompts for names, account information, private playlist titles or other information you do not want to publish.

If a credential has already been exposed publicly, deleting or editing the issue is not sufficient. Revoke or rotate the affected credential immediately.

## Troubleshooting

The checks below cover the most common classes of technical problem without changing PlaylistMuse data.

### PlaylistMuse does not open

First confirm that the container exists and is running:

```bash
docker ps -a --filter name=playlistmuse
```

If it is stopped, inspect its recent output:

```bash
docker logs --tail 200 playlistmuse
```

Then check:

- that the expected host port is mapped to container port `5780`;
- that another application is not already using the selected host port;
- that the container has not entered a restart loop;
- that the mounted `data` directory exists and is accessible to Docker;
- that a firewall, reverse proxy or local network rule is not blocking access when connecting from another device.

If you used the standard installation command with port `5780`, the local URL is:

```text
http://localhost:5780
```

If you changed the host-side port, use that port instead.

### Container repeatedly restarts

Check:

```bash
docker ps -a --filter name=playlistmuse
docker logs --tail 200 playlistmuse
```

Do not delete the persistent `data` directory while troubleshooting. If the error appears related to stored data, make a backup before attempting any repair or restore.

Include the container logs or a diagnostic report in the bug report after removing sensitive information.

### AI provider is not configured or generation cannot start

Open the AI settings and verify:

- a provider is configured;
- the correct provider is active;
- a model is selected where required;
- the API key is present for providers that require one;
- the base URL is correct for Ollama or an OpenAI-compatible endpoint;
- the selected model is actually available to that account or endpoint.

Also verify that the container can reach the provider over the network and that the provider account has not reached a quota, billing or rate limit.

For Ollama or another locally hosted model endpoint, remember that `localhost` inside the PlaylistMuse container refers to the PlaylistMuse container itself, not automatically to the Docker host or another machine. Use a network-reachable endpoint appropriate for your Docker setup.

Never paste an API key into a public issue.

### Generation succeeds but the playlist is musically wrong

If there is no technical error and a playlist is returned, use **Playlist result feedback**, not a bug report.

Include:

- the exact request;
- what part was not respected;
- what you expected;
- the relevant result tracks;
- earlier Playlist Studio instructions when they affect the expected result.

### Last.fm does not work

Last.fm is optional. A Last.fm problem should not prevent the core application from working with a configured AI provider.

Check:

- that the Last.fm API key is saved;
- that the key is valid for the Last.fm API;
- that the container can reach Last.fm;
- that an unusually restrictive custom timeout has not been configured.

If Last.fm is unavailable, retry without relying on Last.fm-specific discovery behavior and include the integration status in a bug report if the failure persists.

### YouTube Music cannot connect

Verify the Google Cloud configuration:

- **YouTube Data API v3** is enabled for the project;
- the OAuth consent configuration permits the account you are using;
- the OAuth client type is **TVs and Limited Input devices**;
- the client ID and client secret saved in PlaylistMuse belong to the same OAuth client;
- you completed the device authorization with the intended Google/YouTube account.

If authorization was revoked or expired, reconnect the account from PlaylistMuse.

Changing the OAuth client ID or secret invalidates the previously stored authorization and requires a new connection.

### YouTube Music is connected but publishing fails

Check:

- whether PlaylistMuse still shows the account as connected;
- whether Google authorization needs to be renewed;
- whether the Google Cloud project has available YouTube API quota;
- whether the target account/channel can create playlists;
- whether the failure affects every playlist or only a specific one.

Include the `PM-...` reference and diagnostic report when available.

Do not attach the YouTube OAuth token file.

### Playlist library or settings appear to be missing after an update

The most important check is whether the new container is using the **same persistent `data` directory** as the previous container.

For the recommended Docker installation, the container should have a mount equivalent to:

```text
<host data directory>:/app/data
```

Inspect the container configuration if necessary:

```bash
docker inspect playlistmuse
```

If a new empty directory was mounted by mistake, stop the container before changing mounts. Do not copy, merge or overwrite database files blindly. Locate the previous complete `data` backup or directory first.

### Browser interface behaves incorrectly

Try:

1. Reloading the page.
2. Opening PlaylistMuse in a private/incognito window.
3. Testing with browser extensions disabled when an extension could affect scripts or requests.
4. Checking whether the same behavior occurs in another current browser.

Record the browser name and version in the issue. Include a screenshot when the problem is visual, after removing private information.

### Problem only occurs through remote access

If PlaylistMuse works locally but not through a reverse proxy, domain name or remote connection, compare local and remote behavior before opening a PlaylistMuse bug.

Check the surrounding network/access layer, including:

- HTTPS termination;
- proxy forwarding;
- authentication layer;
- firewall rules;
- WebSocket or HTTP request handling where applicable;
- request-size or timeout limits imposed by the proxy.

When reporting the issue, describe the access architecture but do not publish private credentials or sensitive configuration.

## Data recovery and backups

If the problem involves missing or corrupted data:

1. Stop making changes to the affected installation where possible.
2. Stop the container before taking a filesystem-level copy.
3. Copy the complete current `data` directory before attempting recovery.
4. Keep the most recent known-good backup unchanged.
5. Report what happened before replacing or editing database files.

The playlist library may use SQLite auxiliary files while PlaylistMuse is running. For this reason, a complete backup taken while the container is stopped is preferable to copying a single database file from a running application.

Do not upload a complete data backup to a public issue.

## Information that usually does not help

Avoid including large amounts of unrelated information. In particular, a report usually does not need:

- the complete Docker environment;
- all host logs;
- the complete contents of the `data` directory;
- full API responses containing credentials;
- repeated copies of the same error;
- screenshots of API keys or OAuth settings containing secrets.

Prefer the smallest amount of information that reliably explains and reproduces the problem.

## External-service limitations

PlaylistMuse depends on services that are operated independently of the project. Problems can sometimes originate from:

- AI-provider availability, model availability, quotas, billing or rate limits;
- Last.fm API availability;
- Google OAuth behavior;
- YouTube Data API availability or quota;
- changes in third-party APIs.

A PlaylistMuse issue is still useful when the application handles one of these situations incorrectly or presents an unclear error. If the external service itself is unavailable, the underlying outage may need to be resolved by that service provider.

## Security issues

Do not publish passwords, API keys, OAuth tokens, cookies or other secrets in a GitHub issue.

If you discover a possible security problem:

1. Do not include working credentials or personal data in a public report.
2. Revoke or rotate any credential that may already have been exposed.
3. Provide only the minimum non-sensitive information needed to describe the issue publicly.
4. If the repository offers GitHub private vulnerability reporting, use that mechanism when sensitive technical details are required.

## Support checklist

Before submitting a technical issue, confirm that you have:

- selected the correct report type;
- recorded the PlaylistMuse version/build;
- recorded the browser and operating system;
- written reproducible steps;
- explained expected and actual behavior;
- saved any `PM-...` reference;
- included the relevant AI provider/model or integration when applicable;
- downloaded diagnostics when useful;
- reviewed attachments for sensitive information;
- removed all credentials and private tokens.

For playlist-result feedback, confirm that you have:

- included the exact request or refinement instruction;
- explained the specific mismatch;
- described the expected result;
- included the relevant playlist result;
- included previous refinement context when it matters;
- removed personal and sensitive information.
