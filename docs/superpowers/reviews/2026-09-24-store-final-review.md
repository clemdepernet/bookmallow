# Bookmallow `feat/store` — final whole-branch review (v1.1.0 candidate)

Range: `4646782` (main) → `21b6cc0` (feat/store). 292 tests pass in ~3 s. Image `bookmallow:dev` (ffmpeg 7.1.5, yt-dlp 2026.08.19) used for read-only probes. Live, read-only calls were made to the LibriVox and Internet Archive APIs and to one LibriVox chapter URL (3 s of audio) to validate the parsers and the ffmpeg command; no torrent, Prowlarr or qBittorrent was touched.

## Strengths

- Clean layering that matches spec §4 almost table-for-table: `store/http.py` (stdlib only), providers, `search.py`, `assemble.py`, `torrent.py`, `qbittorrent.py`, with clocks, sleeps, probers, transports and factories all injectable. The tests are fast and deterministic because of it.
- Security posture is right: magnet/.torrent links never reach the browser (`SearchResult.public()` pops `download`, jobs carry only a sha1-prefixed `source_id`), fabricated `prowlarr:*` keys 404, `safe_filename`/`safe_tag` strip separators and leading dots for M4B names, `resolve_file` accepts `.m4b` with the same hardening as `.mp3`, every new route is behind `login_required`, the CSP additions are the minimum the spec asked for, and no secret ever appears in a log line (the Prowlarr key travels in a header, qBittorrent errors log path + status only).
- `_process_book` lock discipline is careful: `_current` is set under the lock before any blocking step, every early `return` inside `with self._lock` still passes through `finally` (which clears `_current` and runs `acq.cleanup()`), and cancel has reach during `start()`, `wait()` and `run()`. The `_results` leak for queued-then-cancelled books was fixed in `9473204`.
- The ffmpeg assembly command is valid on the shipped ffmpeg 7.1.5. I ran the exact command shape in the image: chapters from the ffmetadata input land correctly (`-map_chapters 1`), the cover becomes `disposition:attached_pic=1` in the ipod container, `-c:a copy` from AAC inputs through the concat demuxer works with chapters, and concat over `https://www.archive.org/download/...` follows redirects under the `-protocol_whitelist`.
- `escape_lucene` (incl. `&&`/`||`), the ffconcat single-quote escaping, `parse_runtime`, `natural_key`, `map_path` prefix matching (no `/downloadsX` false positive) are all correct.
- Startup recovery covers the new failure modes (work dir wipe, orphan torrent deletion, queued Prowlarr jobs failed with a clear reason).
- Frontend: all text goes through `textContent`, cover images are limited to the CSP hosts, Prowlarr results deliberately show no image, `app.js` parses (deno), FR/EN parity is tested.

## Issues

### Critical (Must Fix)

**C1. LibriVox search is broken for virtually every real query — the API answers HTTP 404 for "no match", which becomes `provider_error`.**
`bookmallow/store/http.py:31-32` turns every `HTTPError` into `StoreError("provider_error")`; `bookmallow/store/providers/librivox.py:70-71` issues *two* queries (`title=^q`, then `author=q`) and lets the first exception escape. LibriVox returns `404 {"error":"Audiobooks could not be found"}` whenever one of them has no hit, so a title hit + author miss (the normal case) fails the whole provider. Verified live: `librivox.search("candide","fr")`, `("Maupassant","fr")`, `("dickens","en")` all raise `provider_error: librivox.org: HTTP 404`; `curl 'title=^zzzzqqq'` → 404. In production the store's main catalogue would show "Source indisponible : librivox" on every search. The tests did not catch it because the fake fetcher (`tests/test_store_librivox.py:31-32`) models "no results" as a 200 with the error JSON, which is not what the API does.
Fix: let `_open`/`get_json` distinguish 404 (e.g. `StoreError("not_found", ..., status=404)` or a `ok_404=True` parameter that returns the body); in `librivox.search` treat 404 as `[]` for each query; in `librivox.plan` map 404 to `not_found` (today an unknown id answers 502 instead of the spec's 404). Add a test whose fetcher raises the 404 error for one of the two queries and asserts results from the other are still returned.

**C2. Internet Archive chapters come out in the wrong order when the `track` field is only partially present — the M4B is wrong.**
`bookmallow/store/providers/archive.py:77-82`: `order()` sorts files carrying a numeric `track` first and everything else after (`10**9`), then by name. On real items the `track` field is inherited from ID3 on only some derivatives. Verified live on `candide_ou_loptimisme_b_librivox` (the first FR result for "candide"): picked order is `candide_26`, `candide_27`, `candide_01`, `candide_02`, … → the book would start at chapter 26. This is a defective deliverable, silently.
Fix: use `track` only when *every* picked file has a numeric one; otherwise (and as tiebreak) natural-sort on `_track_key(name)` (reuse `torrent.natural_key`). While there, take the chapter title from the file's `title` field (`"Chapitre 26"`) instead of the stem `candide_26_voltaire_64kb` (`archive.py:100`). Add a fixture with partial `track` values.

**C3. Book progress is stuck at 0 % for the whole assembly whenever a cover is embedded (i.e. every LibriVox/Archive book).**
`bookmallow/store/assemble.py:86-87` maps the cover as a video stream in the same ffmpeg run. On ffmpeg 7.1 `-progress` reports the *minimum* `last_mux_dts` across output streams, and the single-frame cover stream sits at 40 ms. Verified in the image: with cover the final progress line is `out_time_us=40000` (file is otherwise perfect, 5.1 s, 2 chapters, attached pic); without cover it is `out_time_us=5106485`. `progress_percent(40000, dur)` → 0.0 → the UI shows an indeterminate bar for the entire (possibly hours-long) assembly, contrary to spec §6.3 ("Progression = out_time_us / duration"). Not data loss, but a shipped feature visibly not working on every free book.
Fix: two passes in `Assembly.run` — encode audio + metadata + chapters without the cover (progress correct), then if a cover exists a fast remux `ffmpeg -i part.m4b -i cover -map 0 -map 1:v -c copy -disposition:v attached_pic -movflags +faststart -f ipod part2.m4b` and `os.replace`. Keep `ffmpeg_command()` tests asserting the first pass has no `-map 2:v`.

### Important (Should Fix)

**I1. `tests/test_store_assemble.py:53` — invalid escape `\;` raises `SyntaxWarning` on a fresh compile** (visible in the Docker test stage; with `-W error` it is a `SyntaxError`). Replace `\;` with `\\;` (the assertion value is otherwise right).

**I2. Free acquisition has no protection against a stalled or flaky HTTP source — ffmpeg can hang forever or die on a transient 503.**
`bookmallow/store/assemble.py:45-49` writes bare `file 'https://…'` lines. ffmpeg's http protocol has no read timeout by default, so a half-open connection mid-concat blocks `for raw in proc.stdout` indefinitely and the single worker is wedged until someone cancels; a transient IA `503`/`429` on chapter 17 of 30 kills the run with `ffmpeg` and no retry (I hit a 503 from archive.org during probing). On a Pi over home Wi-Fi with 10-hour books this will happen.
Fix (verified: the ffconcat `option` directive works on the shipped ffmpeg 7.1.5, and the https protocol exposes these options): after each `file` line for an `http(s)` track emit `option rw_timeout 30000000`, `option reconnect 1`, `option reconnect_on_network_error 1`, `option reconnect_on_http_error 429,5xx`, `option reconnect_delay_max 60`. Optionally add a progress watchdog in `Assembly.run` (no progress line for N minutes → terminate → `ConversionError("ffmpeg", "no progress for …")`). Update `test_concat_list_escapes_quotes`.

**I3. A lost qBittorrent session mid-download fails the job *and* leaves an orphan torrent that recovery will never clean.**
`bookmallow/store/qbittorrent.py:63-64` raises `qbt_auth` on any 401/403 and there is no re-login. Torrent waits last up to `TORRENT_STALL_HOURS` (12 h); a qBittorrent restart (update, host reboot) invalidates the SID cookie → `wait()` raises `qbt_auth` → `_fail` → `finally: acq.cleanup()` also gets 403 and only logs → torrent + files stay in qBittorrent, and since the job is FAILED (not interrupted) `recover()` will not revisit it.
Fix: in `_call`, on 401/403 for any path other than `/auth/login`, call `login()` once and retry the request; `cleanup()` benefits automatically. Add a transport test that answers 403 then 200.

**I4. `wait()` accepts a torrent in the `moving` state as finished.**
`bookmallow/store/torrent.py:116`: `info.progress >= 1.0` short-circuits before the state check. If qBittorrent uses an incomplete/temp directory, at 100 % the state is `moving` and `content_path` still points at the temp path for a few seconds to minutes → `plan()` scans a directory that is vanishing (`no_audio`, or half-moved files probed/assembled). Fix: keep polling while `info.state in {"moving", "checkingResumeData", "allocating", "metaDL"}`; the 5 s poll makes this free.

**I5. README embeds `docs/screenshot-store.png`, which does not exist** (`README.md:49`; only `docs/screenshot.png` is in the tree). The GitHub README will show a broken image the day v1.1.0 is tagged, and spec §12 lists the store screenshot as a deliverable. The plan's `?tab=store&q=` deep link (meant to help capture it) was not shipped either — dropping the deep link is fine, but either add the screenshot or remove the `<img>` before tagging.

**I6. Test/mocks vs reality.** C1–C3 were all reachable by the tests but invisible because the fixtures encode assumptions rather than recorded behaviour: LibriVox no-match as 200 JSON, IA `track` present on every file, ffmpeg progress simulated by a fake `Popen`. For a release: (a) make the provider fixtures reproduce the HTTP semantics (status codes) and partial metadata; (b) add one opt-in integration test (`@pytest.mark.slow`, real ffmpeg with `lavfi` sine inputs and a generated JPEG) asserting chapters, attached pic and that the last `out_time_us` ≥ 90 % of the duration — it would have caught C3 in 2 s.

### Minor (Nice to Have)

- `bookmallow/store/providers/archive.py:101-103`: cover = first `.jpg/.png` that is not `__ia_thumb`; real items contain `*_spectrogram.png` and per-chapter images, so this is right by luck. Prefer names containing `itemimage`/`cover`/`front`, exclude `spectrogram`, else fall back to `services/img/<id>` (always valid). Do it together with C2.
- `archive.py:86,100,103`: `identifier` is interpolated unquoted into URLs. A crafted `key` (`archive:foo?x=`/`archive:a b`) injects into the archive.org path/query (host is fixed, so no SSRF), and a control character raises `http.client.InvalidURL`, which `_open` does not catch → HTTP 500 from `/api/store/jobs`. Validate `^[A-Za-z0-9._-]{1,100}$` and `quote(identifier, safe="")`.
- `bookmallow/store/torrent.py:35`: a `content_path` outside `QBT_PATH_MAP` is returned unchanged and then scanned on Bookmallow's own filesystem. Not exploitable (qBittorrent's save path is operator-controlled) but a misconfiguration should fail loudly: log a warning and raise `no_audio` ("content path … is outside QBT_PATH_MAP"). Pair with the deferred `QBT_PATH_MAP` without `:` → `ConfigError`.
- `torrent.py:92-101`: when `add()` succeeds but the tag never shows up within 30 s, the torrent stays in qBittorrent with no hash for `cleanup()`. Let `cleanup()` fall back to `find_by_tag(f"job-{job_id}")` when `self.hash` is None.
- `bookmallow/jobqueue.py:369-378` `_copy_single`: an `OSError` during `copyfile` leaves `Title.part.m4b` until the next restart and surfaces as `internal`; wrap in try/except → `unlink_quietly(part)` and `StoreError("ffmpeg"|"no_space")`. Cancel during a large copy is honoured only afterwards (acceptable, but untested — the deferred "no test for cancel mid-copy").
- `jobqueue.py:358`: with `copy_audio` the disk guard estimates from `BOOK_BITRATE` while the actual output is the sources' size; use `sum(st_size)` of the tracks when copying.
- `librivox.py:70`: deviation from spec §6.1 (author query always issued, without `^`). Verified `^Maupassant` and `Maupassant` return the same set, and always issuing it gives better results — fine, but update the spec line. Also two sequential calls of `timeout` each can exceed the `wait()` budget in `unified_search` (`timeout + 15 s`) → reported as "timed out" while still running; give the second call the remaining budget.
- `jobqueue.py:29`: `DuplicateJob` message reads "video librivox:761 is already queued".
- `app.js`: `store_seeders` renders "0 sources" when `seeders` is null (hide instead); `render()` calls `setTab()` → `localStorage.set` on every poll; result `url` is not scheme-checked server-side (CSP blocks `javascript:` today — cheap to whitelist `http(s)` in the providers).
- API deviation: unknown `source` in `POST /api/store/jobs` answers 404 instead of the spec's 400 (harmless; document or adjust).
- `procutil.py`/`converter.py`: `close_quietly(...) if ff is not None else None` — statement-ternary (deferred); unused `field` import in `assemble.py`, unused `LANG_NAMES` in `librivox.py`, stale `PART_SUFFIX` comment in `retention.py`.

## Deferred-minors triage

Fix before merge (cheap, each prevents a silent misbehaviour):
- `QBT_PATH_MAP` without `:` silently maps to `/` → raise `ConfigError` (Task 1).
- `_infos` does not guard a non-list JSON top level → `AttributeError` in the worker → `internal` (Task 5): one `isinstance(items, list)` check.
- Unused `field` import, unused `LANG_NAMES`, stale `PART_SUFFIX` comment (Tasks 1/3/7): fold into the C1/C2 commits.
- No test for cancel during `acq.start()` / mid-copy (Task 9): add with the `_copy_single` hardening above.

Fine after release:
- Accept header uniform for images; `h/mn` naming (Task 2). Unknown-language books dropped when `lang != all` (design, Task 3). Cover picks first jpg (Task 4) — superseded by the Minor above; missing docstrings, `_first` untyped. Cached provider statuses frozen for the TTL, `SearchResult` instances shared with the cache, `unified_search` relying on the route for `store_enabled` (Task 6). Ternary-as-statement in `converter` (Task 7). Partial-config warning per `create_app`, quality validated before key shape (Task 10). `estimate_book_bytes` on malformed bitrate (validated upstream, Task 9). Provider note cleared on language toggle, `addBook` collapsing generic 400s (Task 11).
- Rulings accepted as-is: Task 6 files landing in `44c32f6`; attribution trailers (out of scope here).

## Recommendations

1. Land C1, C2, C3 and I1 as small focused commits with tests that reproduce the *real* provider behaviour (404 no-match, partial `track`, ffmpeg min-stream progress).
2. Add the ffconcat `option` lines (I2) — a two-line change in `concat_list` that turns "one hiccup kills a 10-hour job" into a retry.
3. Re-login on 401/403 (I3) and the `moving` state (I4) before the first real torrent test; then do the spec §11 manual run (one FR LibriVox, one EN, one torrent) — nothing in this branch has exercised `torrents/add` against a real qBittorrent yet, and `find_by_tag`/`content_path` mapping are only tested against fakes.
4. Either commit `docs/screenshot-store.png` or drop the `<img>` from the README (I5) before tagging.
5. Consider one opt-in integration test with real ffmpeg (I6); it costs ~2 s and covers the one component no unit test can.
6. Spec notes: §6.1 should say the author query is always issued; §6.3 should mention the two-pass cover remux once C3 is fixed; §6.4 should list `moving` as a non-finished state.

## Assessment

**Ready to merge?** With fixes

**Reasoning:** The architecture, security and concurrency work is solid and the ffmpeg pipeline is verified to produce correct chaptered M4Bs with covers — but as it stands the LibriVox provider fails on every realistic query (C1), Internet Archive books can be assembled with chapters out of order (C2) and book progress never moves when a cover is embedded (C3); all three are small, localized fixes that must land (with reality-based tests) before v1.1.0 is tagged.
