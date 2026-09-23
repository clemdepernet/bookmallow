# Bookmallow v1 — final whole-branch review (94d62d4..44e2adc)

Reviewed: spec, deferred list, every file under `bookmallow/`, `tests/`, packaging (Dockerfile, entrypoint, compose, both workflows, dependabot), README/CHANGELOG/CONTRIBUTING/LICENSE. Diff read via `git diff` per file rather than the 200 KB dump (the original project's deletions were skimmed only). Test suite run (`135 passed`, ~1 s) and under `-W error`. Probes run against real `yt-dlp` (network) and the local `bookmallow:dev` image; no tree mutation.

### Strengths

- Module boundaries follow spec §4 exactly; `converter` and `metadata` are the only process launchers and both take an injected runner/popen, which the tests exploit well.
- The streaming pipeline (`converter.py`) is careful where it matters: yt-dlp's read end closed in the parent so EPIPE propagates, stderr drained by tail threads, `Broken pipe` noise suppressed so ffmpeg's real error wins, `.part.mp3` unlinked on every failure path, `.ffmeta` removed in `finally`, SIGTERM→SIGKILL on process groups, and a real `sleep 30` kill test.
- `JobQueue` lock discipline is right: `cancel()` releases the lock before `conv.cancel()`, every stage re-checks `CANCELLED`, the late-cancel-after-successful-run race is guarded and tested, `_fail` never overwrites a cancel, and progress updates never touch disk.
- Security fundamentals are solid for a shared-password app: file names resolved by exact `os.listdir` membership (no client-supplied path ever joined), `.part`/dotfile/non-`.mp3` refused, JSON-only mutation API (`get_json(silent=True)` refuses form/text bodies) + `SameSite=Lax` + `HttpOnly` + 64 KB body limit make CSRF a non-issue including the plain-form logout, constant-time password compare, `session.clear()` before login, open-redirect guard covers `//` and `\\`, `/healthz` leaks nothing.
- Frontend: no `innerHTML` anywhere (all `textContent`/`setAttribute`), FR/EN key parity enforced by a test, no external script/style/font, `prefers-reduced-motion` honoured, focus rings, `<dialog>` with fallback.
- Packaging: multi-stage image with the test suite runnable inside the real image, `PUID/PGID` via gosu with `HOME` handled, healthcheck, scoped GHA caches, weekly rebuild, tzdata present (verified `TZ=Europe/Paris` → CEST in the image), README variables match code (checked every row).
- Real-hardware e2e on arm64 already done; recovery, retention and Range downloads observed live.

### Issues

#### Critical (Must Fix)

1. **Any watch URL carrying a YouTube mix/radio `list=RD…` parameter is refused with 502 and there is no way forward in the UI.**
   `bookmallow/urls.py:77-79` treats every `list=` as a playlist; `bookmallow/app.py:101-106` then calls `fetch_playlist("…/playlist?list=RD…")`, which yt-dlp cannot read ("This playlist type is unviewable"). Verified end to end through the Flask client with the real fetcher: `POST /api/jobs {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=RDdQw4w9WgXcQ&start_radio=1"}` → `502 {"error":"metadata","code":"ytdlp",…}`. The UI (`app.js:339-340`) shows "Impossible de lire cette playlist. Erreur yt-dlp" and the "Seulement cette vidéo" button never appears because it lives inside the playlist dialog that only opens on a 200. YouTube appends `&list=RD…` to a large share of links copied from autoplay/mixes, so this is a common-input functional break for the target users.
   Fix (both parts):
   - `urls.parse`: ignore `list=` values that are mixes (`RD*`, `UL*`) — they are never convertible as playlists; keep the video id. One-line guard before line 78.
   - `app._submit`: when `fetch_playlist` raises `MetadataError` **and** `parsed.video_id` is set, log a warning and fall through to the single-video path (return 201 with an extra `"playlist_error": code` so the UI can toast "playlist illisible, vidéo ajoutée seule"). Keep the 502 only for playlist-only URLs.
   - Tests: `watch?v=X&list=RDX` → 201 single job without calling `fetch_playlist`; playlist fetcher raising with a video id → 201.

#### Important (Should Fix)

2. **ffmpeg failure detail is the whole 20-line stderr tail, stored in `job.error`, rendered raw in the UI, and nothing is logged server-side.**
   `bookmallow/converter.py:208` passes `ff_err.text()` (up to 20 lines, including `/data/<title>.part.mp3` paths) as `ConversionError.detail`; `bookmallow/jobqueue.py:143,152,171,209-214` `_fail` stores it without any `log.*` call. Spec §5 says `error` is a short readable message and §11 says the last 20 stderr lines go to the *logs*. Today the operator has no server-side trace of why a job failed.
   Fix: in `_fail` add `log.warning("job %s failed [%s]: %s", job.id, code, detail)`; in `converter.run` use `classify_error`/`last_line` for the ffmpeg detail too and emit the full tail via `log.warning` (or carry it on the exception as `.tail` and log it in `_fail`). Same for the `internal` path (already `log.exception`).

3. **`/api/state` can 500 when a file disappears between listing and stat.**
   `bookmallow/app.py:52` `st = path.stat()` is unguarded; `retention.list_mp3` skips vanished files but `build_state` re-stats outside the queue lock, and prune (worker) or `DELETE /api/files` (another user) can run in between. The UI polls this endpoint every 2 s while conversions finish, exactly when prune runs.
   Fix: `try: st = path.stat() except FileNotFoundError: continue` — or make `list_mp3` return `(path, st)` pairs and reuse them (also removes the double stat noted in the deferred list).

4. **`classify_error` misses yt-dlp's real "This video is unavailable" and over-matches "not available"** (known item, confirmed by probe).
   `bookmallow/metadata.py:16`: `"This video is unavailable"` → `ytdlp`; `"Requested format is not available"` → `unavailable` (wrong bucket). Also the most common self-hosting failure, `"Sign in to confirm you're not a bot"`, lands in the generic `ytdlp` bucket with a message about `--cookies-from-browser` that users cannot act on.
   Fix: needles for `unavailable` → `("unavailable", "has been removed", "no longer available", "does not exist", "video is not available")` (drop bare `"not available"`); add `("bot", ("confirm you're not a bot", "confirm you’re not a bot", "sign in to confirm"))` before `unavailable`, with `e_bot` in both I18N tables (FR: « YouTube demande une vérification anti-robot depuis ce serveur », EN: "YouTube is asking this server for a bot check") and a README line under "YouTube change souvent". Add the real messages to `test_classify_error`.

5. **Playlist preview work is unbounded.**
   `bookmallow/metadata.py:115` runs `--flat-playlist` over the whole playlist; a several-thousand-item playlist just burns the 90 s timeout in a request thread, and the response is truncated to `PLAYLIST_PREVIEW_LIMIT=200` anyway. This is the cheapest DoS lever when the instance is exposed without a password, and it makes big playlists unusable.
   Fix: pass the limit down and add `"--playlist-items", f":{limit}"` (yt-dlp `-I :200`) to the args; drop the redundant `[:PLAYLIST_PREVIEW_LIMIT]` slice or keep it as belt-and-braces. Test the arg is present.

6. **Test gaps that would have caught #1 and #3** (fold into the fixes above): no test for a watch URL with a mix `list=`; no test for `build_state` when a listed file vanishes; no test for `default_runner` when yt-dlp prints `null`/errors (mock `subprocess.run` returning `stdout="null\n"`).

#### Minor (Nice to Have)

7. `bookmallow/converter.py:197-199` — `ff.stdout`, `ff.stderr`, `yt.stderr` never closed → `ResourceWarning` under `-W error` (known). CPython refcounting closes them when the `Conversion` is dropped, so no runtime leak, but fix now since it is one line: after the joins, `for s in (ff.stdout, ff.stderr, yt.stderr): s.close()` inside the `finally` (or `with yt, ff:`).
8. Test hygiene under `-W error`: `tests/test_app.py:151-155` and `tests/test_frontend.py:29` leave `send_file` responses open (`r.close()` / `c.get(asset).close()`). Not app bugs, but they hide #7 if anyone adds `-W error` to CI.
9. `bookmallow/static/app.js:161` `fmtDuration`: `Math.round` on minutes yields "1 h 60" / "60 min" for e.g. 7170 s. Use `Math.floor` or carry over.
10. `bookmallow/templates/index.html:47` `aria-live="polite"` on `#jobs` while `render()` does `replaceChildren` every 2 s → screen readers re-announce the whole queue continuously. Move the live region to a single status line (e.g. "1 conversion en cours, 42 %") or drop it from the list.
11. `bookmallow/auth.py:28-30`: an expired session clicking a `<a href="/api/files/…">` download gets raw `{"error":"unauthorized"}` JSON in the browser. Redirect to `/login?next=` for `GET /api/files/*` (or when the client accepts `text/html`).
12. `bookmallow/converter.py:180` writes `<name>.part.ffmeta` next to the MP3 but `retention.remove_partials` (`retention.py:53`) only globs `*.part.mp3`; a crash mid-conversion leaves a stray metadata file in `/data`. Glob `*.part.*`.
13. No security headers. Add an `after_request` hook with `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, and `Content-Security-Policy: default-src 'self'; img-src 'self' https://i.ytimg.com https://*.ggpht.com; frame-ancestors 'none'` — trivial since there is no inline script/style. Also clarifies the README's "aucune ressource externe" claim: thumbnails *are* fetched by the browser from YouTube's CDN (spec §5 allows it, but say "no CDN scripts/fonts" rather than "none").
14. README (both languages): spec §8 says the absence of login rate-limiting is documented — it is not. Add one sentence in "Partager avec ses amies" recommending Cloudflare Access / NPM access list / fail2ban, and set `FORCE_HTTPS=1` behind TLS. Also list `LOG_LEVEL` (read in `wsgi.py:10`) and `DATA_DIR`.
15. `requirements.txt:3` `yt-dlp[default]>=2026.1.1` is a floor, not the pin spec §13 describes; Dependabot pip will not open PRs for a satisfied range, so the dependabot `pip` entry is inert for yt-dlp. The weekly rebuild makes the floor a defensible choice — record the deviation in the spec/README rather than change it.
16. `.github/workflows/release.yml:5-6`: the Monday rebuild checks out `main` HEAD and republishes `latest`, so `latest` can carry unreleased commits while `1.0`/`1.0.0` stay frozen. Acceptable; if you want `latest` == last release, resolve the newest `v*` tag in a step and pass `ref:` to checkout.
17. `Dockerfile:18` deno from `releases/latest` (deferred): one `ARG DENO_VERSION=2.9.7` line makes weekly builds reproducible and lets a breaking deno release be bisected. Recommended now, not blocking.
18. `.dockerignore`: add `.superpowers/` (untracked but present locally, sent in the build context).
19. `bookmallow/jobqueue.py:83` job ids are 8 hex with no uniqueness loop; negligible at ≤50 jobs but a `while any(j.id == job.id …)` regen is one line.
20. `bookmallow/jobqueue.py:141` a cancel during `FETCHING` cannot interrupt `yt-dlp -J` (up to 60 s), so the queue stalls that long. Acceptable for v1; note it in the code.
21. `style.css:13,123` contrast (deferred): `--muted #8A6F7D` on cream ≈ 4.3:1 and `.pill.cancelled` ≈ 3.9:1 miss AA for small text; `--muted: #7A5F6D` and a darker cancelled pill fix both.

### Deferred-minors triage

Must be fixed before merge (cheap, in this wave): `classify_error` "This video is unavailable" (#4); converter pipe close (#7); deno version pin (#17, one line); contrast tokens (#21, two values).

Can wait / post-1.0: `_int/_float` duplication; `ensure_secret` whitespace regeneration + missing direct test; dead `?` branch in `_PATH_ID`; uppercase-host/userinfo tests; `www.youtu.be` permissiveness; `typing.Iterable` vs `collections.abc`; `safe_filename` boundary test; `created_at` tie-break; single `.tmp` name (serialised by the queue lock); `remove_partials` `is_file` guard; mtime tie-break test; case-sensitive glob; double stat (goes away with #3's fix if `list_mp3` returns stats); `_int_or_none` 0→None; `live_status` detection; non-dict JSON test (covered by #6's `null` test); redundant `OSError` subclasses; `part_path` on non-`.mp3`; `_target_path` relying on `save()` having created `data_dir`; `resolve_file` leading-dot doc; `video_ids` `str()` coercion; extra `detail` on `invalid_url`; playlist checkboxes not visually capped; logout-button test; unconditional `chown -R`. Image size: resolved (267 MB content, 994 MB was the uncompressed local view) — no action.

### Recommendations

- Add `-W error::ResourceWarning` to `addopts` once #7/#8 land so the pipe hygiene stays enforced in CI.
- Consider surfacing `playlist_error` in the UI as a toast (see #1) so users understand why only one video was queued.
- Spec updates to record: two process groups instead of one (`start_new_session=True` on each Popen — cancel still kills both, and yt-dlp's deno child too), yt-dlp floor instead of pin, preview returns up to 200 entries for the user to pick rather than `[:MAX_FILES]`, `--no-part` dropped (meaningless with `-o -`), `default_lang`/`auth_enabled` in `/api/state.config`.
- Before tagging: run one manual conversion of a URL with `&list=RD…` after the fix, and one deliberate ffmpeg failure to see the new log line.

### Assessment

**Ready to merge?** With fixes

**Reasoning:** The architecture, concurrency handling and security posture are sound and well tested, but a very common URL shape (`&list=RD…`) is currently rejected outright, failures leave no server-side trace while dumping raw ffmpeg output in the UI, and the main poll endpoint can 500 during retention — all small, well-localised fixes that should land before v1.0.0 is published.
