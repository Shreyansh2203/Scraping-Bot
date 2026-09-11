# Stress Test Suite — `social_video_downloader.py`

**Target:** `C:\Files\Scraping\social_video_downloader.py`  
**Implementation file:** `C:\Files\Scraping\test_stress_suite.py` (21 tests, 17 fast / 4 slow)  
**Date:** 2026-09-12

---

## Architecture Summary (What We Are Testing)

| Component | Mechanism | Risk |
|---|---|---|
| Subprocess execution | `asyncio.to_thread(subprocess.run)` per URL | Thread-pool saturation, stdout/stderr interleaving |
| Concurrency control | `asyncio.Semaphore(max_concurrent)` | Semaphore leak, over-subscription |
| Resume support | JSON state file (`.download_state.json`) with atomic `os.replace` write | Corruption under concurrent writes, locked-file crash |
| Output discovery | `_parse_yt_dlp_output` parses `--print` lines from combined stdout+stderr | Cross-talk between tasks, format-change fragility |
| Terminal UI | `ProgressDisplay` with `asyncio.Lock` per render | Race on internal dict under 50+ concurrent updaters |
| Retry/timeout | Exponential back-off + `asyncio.wait_for(subprocess_timeout)` | Timeout vs. retry double-trip, hung worker threads |
| Cookie extraction | `browser_cookie3` → temp Netscape file | Missing module, empty cookie jar, unsupported browser |

---

## Running the Suite

```powershell
# Fast tests only (17 tests)
python C:\Files\Scraping\test_stress_suite.py --verbose

# All tests including slow ones (21 tests, ~60–120 s)
python C:\Files\Scraping\test_stress_suite.py --all --slow --verbose

# Run a single test by name filter
python C:\Files\Scraping\test_stress_suite.py test_004_timeout_kills_process_and_triggers_retry
```

---

## Test Catalog

### 1. `test_001_parse_output_no_cross_talk`

**Area:** Concurrent subprocess output parsing races

**Setup:**
1. Create a temp directory.
2. Pre-create four files on disk: `file.mp4`, a Japanese/Greek filename, and `multiline_file.mp4`.
3. Construct four `(output_string, returncode)` pairs — three successful (ASCII, Unicode, multiline title) and one failure (empty output, rc=1).
4. Call `_parse_yt_dlp_output` sequentially for each pair.

**Exact command:**
```powershell
python C:\Files\Scraping\test_stress_suite.py test_001_parse_output_no_cross_talk --verbose
```

**Expected behavior:** Each call returns an independent dict. Successful calls return `{"success": True, "file": ..., "format_id": ..., "size": ...}`. The failure call returns `{"success": False}`. No keys from one call leak into another.

**Bug exposed:** If `_parse_yt_dlp_output` used a shared mutable default argument (e.g., `result = {}` at class level) or a class-level cache, concurrent or sequential calls would contaminate each other's results.

**Severity if it fails:** HIGH — silently wrong file attribution causes data loss and incorrect state file entries.

---

### 2. `test_002_state_file_no_corruption_under_concurrent_writes`

**Area:** State file corruption under concurrent writes

**Setup:**
1. Create a temp directory.
2. Instantiate a single `StateManager(state_path)`.
3. Launch 5 async coroutines (`asyncio.gather`), each calling `sm.mark_completed()` 50 times with unique URLs (250 total writes), yielding control with `await asyncio.sleep(0)` between writes.

**Exact command:**
```powershell
python C:\Files\Scraping\test_stress_suite.py test_002_state_file_no_corruption_under_concurrent_writes --verbose
```

**Expected behavior:** After all writers complete, `state.json` contains valid JSON. The `completed` dict has at least one entry. No partial writes, no truncated JSON.

**Bug exposed:** `StateManager.save()` uses `tempfile.mkstemp` + `os.replace` for atomic writes, but if two coroutines write simultaneously the temp files can clobber each other, or the rename can interleave with a read, producing a corrupt or empty file.

**Severity if it fails:** HIGH — corrupt state file makes resume impossible; user must delete it and re-download everything.

---

### 3. `test_003_unicode_filename_parsing`

**Area:** Unicode filenames from yt-dlp

**Setup:**
1. Create a temp directory with an ASCII placeholder file.
2. Mock `Path.exists` and `Path.stat` to return `True` / a stat result for a Unicode filename string containing Japanese, Greek, and Arabic characters, avoiding actual filesystem creation.
3. Call `_parse_yt_dlp_output` with output containing that Unicode filename followed by size, resolution, and format_id on separate lines.

**Exact command:**
```powershell
python C:\Files\Scraping\test_stress_suite.py test_003_unicode_filename_parsing --verbose
```

**Expected behavior:** `result["success"] is True`, `result["file"]` contains the Unicode characters, `result["format_id"] == "http-abc"`.

**Bug exposed:** yt-dlp frequently outputs titles in CJK, emoji, or RTL scripts. If `_parse_yt_dlp_output` uses a regex with an incorrect byte-width assumption or splits on `\t` instead of `\n`, the multi-byte characters get truncated or raise `UnicodeDecodeError`.

**Severity if it fails:** MEDIUM — non-ASCII social media titles (common on X/Twitter, Instagram, TikTok) would be misattributed or crash the batch.

---

### 4. `test_004_timeout_kills_process_and_triggers_retry`

**Area:** Subprocess timeout killing vs. retry interaction

**Setup:**
1. Create a `DownloaderConfig` with `retries=3`, `subprocess_timeout=1`.
2. Mock `subprocess.run` to always raise `subprocess.TimeoutExpired`.
3. Call `_process_task` on a single `DownloadTask`.

**Exact command:**
```powershell
python C:\Files\Scraping\test_stress_suite.py test_004_timeout_kills_process_and_triggers_retry --verbose
```

**Expected behavior:** `subprocess.run` is called exactly 3 times. Final task status is `"failed"` and `task.error` contains `"Timeout"`.

**Bug exposed:** A double-trip race where `asyncio.wait_for` cancels the task but the underlying thread (`asyncio.to_thread`) keeps running. On the next retry, the stale thread's subprocess might still be alive, causing port/resource exhaustion or a second yt-dlp writing to the same output file concurrently.

**Severity if it fails:** HIGH — a hung yt-dlp process never gets killed; after N retries you have N+1 live subprocesses all writing to the same directory.

---

### 5. `test_005_partial_part_file_cleanup`

**Area:** Partial `.part` files from interrupted downloads

**Setup:**
1. Create a temp directory.
2. Place a `video.mp4.part` file (simulating an interrupted yt-dlp download) and a `thumb.jpg` file (simulating an orphan thumbnail).
3. Instantiate the engine with an empty URL list.
4. Call `engine._cleanup_orphans()`.

**Exact command:**
```powershell
python C:\Files\Scraping\test_stress_suite.py test_005_partial_part_file_cleanup --verbose
```

**Expected behavior:** `video.mp4.part` is deleted. `thumb.jpg` remains (it is a non-`.part` file without a matching final video, so the cleanup policy preserves it).

**Bug exposed:** If `_cleanup_orphans` only checks for `.part` files but does not verify the corresponding final `.mp4` exists, it may delete a `.part` that is actively being written to by a still-running subprocess from a previous batch. Conversely, if it deletes thumbnails too aggressively, users lose cover art.

**Severity if it fails:** MEDIUM — leftover `.part` files waste disk space; premature deletion corrupts in-progress downloads.

---

### 6. `test_006_empty_output_dir_does_not_crash`

**Area:** Empty output directory

**Setup:**
1. Create a temp directory.
2. Instantiate engine with `urls=[]`.
3. Call `engine.run()`.

**Exact command:**
```powershell
python C:\Files\Scraping\test_stress_suite.py test_006_empty_output_dir_does_not_crash --verbose
```

**Expected behavior:** Returns `[]` immediately. No exceptions. No files created in the output directory.

**Bug exposed:** If `run()` does not short-circuit on an empty URL list, it may try to acquire the semaphore, call `_log_banner` which assumes at least one task, or attempt to write an empty state file.

**Severity if it fails:** LOW — crash on empty input is a usability bug, not a data-risk bug.

---

### 7. `test_007_hundred_urls_semaphore_respected` *(SLOW)*

**Area:** 100+ concurrent URLs

**Setup:**
1. Generate 120 fake URLs (`https://example.com/v/0` … `v/119`).
2. Mock `subprocess.run` with a thread-safe counter that tracks `current_concurrent` depth (increments on entry, decrements on exit via `threading.Lock`). Each call sleeps 20 ms and returns a successful result.
3. Pre-create the expected output file on disk so no retries occur.
4. Instantiate engine with `concurrent=5`.

**Exact command:**
```powershell
python C:\Files\Scraping\test_stress_suite.py test_007_hundred_urls_semaphore_respected --all --slow --verbose
```

**Expected behavior:** `max_concurrent <= 5` at all times. All 120 tasks report `status == "success"`.

**Bug exposed:** If the `asyncio.Semaphore` is acquired inside the coroutine *after* `asyncio.to_thread` has already been called (i.e., the thread is spawned before the semaphore is held), then 120 threads can be spawned simultaneously, overwhelming the process pool and causing `RuntimeError: cannot schedule new futures after shutdown`.

**Severity if it fails:** HIGH — resource exhaustion, zombie yt-dlp processes, eventual `OSError: [WinError 10055]` (no buffer space).

---

### 8. `test_008_network_reset_returns_error_not_crash`

**Area:** Network reset mid-download

**Setup:**
1. Instantiate engine with a temp output dir.
2. Call `_parse_yt_dlp_output` with combined output: a `[download] 50%` progress line followed by yt-dlp's `[Errno 104] Connection reset by peer` error on stderr, `returncode=1`.

**Exact command:**
```powershell
python C:\Files\Scraping\test_stress_suite.py test_008_network_reset_returns_error_not_crash --verbose
```

**Expected behavior:** `result["success"] is False`, `result["error"]` is a non-empty string containing the error message.

**Bug exposed:** If `_parse_yt_dlp_output` only looks at `returncode` and ignores stderr content, or if it tries to parse file/size lines that don't exist after a network error, it may raise `IndexError` or return a partially-filled dict that crashes `_download_subprocess`.

**Severity if it fails:** MEDIUM — network errors should be retried, not crash the engine.

---

### 9. `test_009_yt_dlp_output_format_changes_dont_crash`

**Area:** yt-dlp output format changes

**Setup:**
1. Create a temp directory and pre-create `real_file [abc123xyz].mp4`.
2. Construct output with *extra* progress lines, a `WARNING:` line, and the standard `--print` fields (filepath, size, resolution, format_id) — simulating a hypothetical new yt-dlp version that emits additional stderr lines.
3. Call `_parse_yt_dlp_output`.

**Exact command:**
```powershell
python C:\Files\Scraping\test_stress_suite.py test_009_yt_dlp_output_format_changes_dont_crash --verbose
```

**Expected behavior:** `result["success"] is True`, `result["file"]` contains `"real_file"`, `result["size"] == 52428800`, `result["format_id"] == "http-999"`.

**Bug exposed:** The current parser uses a heuristic: *last non-bracket line = format_id, second-to-last = resolution, third-to-last = filesize, everything before = filepath*. If yt-dlp adds a new `[info]` line or changes field order, the heuristic misassigns values (e.g., treats the resolution as the format_id).

**Severity if it fails:** HIGH — silent data corruption in the state file (wrong format_id, wrong file size) causes resume to skip re-downloads of videos that were actually incomplete.

---

### 10. `test_010_cookie_extraction_no_cookies_found` + `test_010b_cookie_extraction_invalid_browser_name`

**Area:** Browser cookie extraction edge cases

**Setup (010):** Mock `browser_cookie3.chrome` to return an empty cookie jar. Call `extract_browser_cookies("chrome")`.

**Setup (010b):** Call `extract_browser_cookies("netscape")` with no mock.

**Exact command:**
```powershell
python C:\Files\Scraping\test_stress_suite.py test_010_cookie_extraction_no_cookies_found --verbose
python C:\Files\Scraping\test_stress_suite.py test_010b_cookie_extraction_invalid_browser_name --verbose
```

**Expected behavior:** Both return `None`. No exception is raised. A warning is printed to stderr for the unsupported browser.

**Bug exposed:** If `extract_browser_cookies` does not handle an empty cookie jar (e.g., iterating over `None`), or if `BROWSER_MAP.get(browser_name.lower())` returns `None` and the code tries to call `.lower()` on `None`, it raises `AttributeError`.

**Severity if it fails:** LOW — cookie extraction is best-effort; a crash here prevents all downloads for users who rely on browser cookies.

---

### 11. `test_011_progress_display_no_exception_under_concurrent_updates` *(SLOW)*

**Area:** Progress display under heavy concurrency

**Setup:**
1. Create a `ProgressDisplay(total=50, quiet=False)`.
2. Register 50 `DownloadTask` objects.
3. Launch 50 coroutines concurrently. Each calls `display.update(idx, "running", progress=pct)` for pct in 0, 10, …, 100, yielding with `await asyncio.sleep(0)` between updates.

**Exact command:**
```powershell
python C:\Files\Scraping\test_stress_suite.py test_011_progress_display_no_exception_under_concurrent_updates --all --slow --verbose
```

**Expected behavior:** No exception raised. All 50 coroutines complete. The final display state is consistent (no missing or duplicate entries).

**Bug exposed:** `ProgressDisplay._tasks` is a plain `dict` protected by an `asyncio.Lock`. If any path updates the dict without holding the lock (e.g., `register` called from `__init__` without locking, or `update` releases the lock before writing), concurrent writes can cause `RuntimeError: dictionary changed size during iteration` or `KeyError`.

**Severity if it fails:** MEDIUM — terminal UI corruption under high concurrency; in the worst case the crash propagates up and aborts the entire batch.

---

### 12. `test_012_disk_full_handled_gracefully`

**Area:** Disk full / permission errors

**Setup:**
1. Create a temp directory and a 2048-byte dummy video file.
2. Mock `AsyncDownloadEngine._verify_file` to return `(False, "OS error: disk full")`.
3. Mock `subprocess.run` to report the dummy file as the download output.
4. Call `_process_task`.

**Exact command:**
```powershell
python C:\Files\Scraping\test_stress_suite.py test_012_disk_full_handled_gracefully --verbose
```

**Expected behavior:** `task.status == "failed"`. `task.error` contains `"Integrity"`. The bad file is deleted from disk.

**Bug exposed:** If `_verify_file` propagates `OSError` from `Path.stat()` or `open()` instead of catching it, the exception bubbles up through `_download_subprocess` → `_process_task` and crashes the `asyncio.gather` in `run()`, aborting all in-flight downloads.

**Severity if it fails:** HIGH — a single disk-full error kills the entire batch; no retry, no graceful degradation.

---

### 13. `test_013_keyboard_interrupt_during_run` *(SLOW)*

**Area:** Ctrl+C during active downloads

**Setup:**
1. Create 6 fake URLs.
2. Mock `subprocess.run` to block forever on a `threading.Event` (simulating a long yt-dlp subprocess).
3. Patch `asyncio.to_thread` so worker threads are daemon threads (do not block event-loop shutdown).
4. Schedule `KeyboardInterrupt` via `loop.call_later(0.3, ...)` while `engine.run()` is in progress.

**Exact command:**
```powershell
python C:\Files\Scraping\test_stress_suite.py test_013_keyboard_interrupt_during_run --all --slow --verbose
```

**Expected behavior:** `patched_main` returns `130`. Worker threads are unblocked via `hang_event.set()`. No zombie threads remain.

**Bug exposed:** If `asyncio.to_thread` uses non-daemon threads, the `KeyboardInterrupt` cancels the `asyncio.Task` but the underlying `ThreadPoolExecutor` worker is blocked on `subprocess.run`. Python waits for the thread to finish on event-loop close, causing the test (and real Ctrl+C) to hang for minutes.

**Severity if it fails:** HIGH — Ctrl+C appears to do nothing; user must kill the process with Task Manager.

---

### 14. `test_014_resume_with_mixed_completed_and_failed`

**Area:** Resume after crash with mixed state

**Setup:**
1. Create a temp directory.
2. Write a state file with 3 completed entries (normalized URL keys) and 2 failed entries.
3. Create the output directory and pre-create one of the completed video files.
4. Instantiate engine with `resume=True`, `retries=1`, `retry_delay=0`.
5. Mock `subprocess.run` to return a successful result with a pre-created output file.

**Exact command:**
```powershell
python C:\Files\Scraping\test_stress_suite.py test_014_resume_with_mixed_completed_and_failed --verbose
```

**Expected behavior:** 3 tasks have `status == "skipped"` (already in state file). The 2 previously-failed tasks and 1 new task are processed. Total processed = 3.

**Bug exposed:** If `StateManager.is_completed()` uses raw URLs instead of `normalize_url()` keys, resume fails to skip URLs that differ only in scheme case, trailing slash, or query parameters. If the state file is keyed by raw URL but `run()` passes `normalize_url(url)` to `is_completed()`, every URL appears uncompleted and the batch re-downloads everything.

**Severity if it fails:** HIGH — resume is the primary feature for large batches; a broken resume forces full re-downloads.

---

### 15. `test_015_ffmpeg_hotswap_detection`

**Area:** ffmpeg appearing/disappearing mid-batch

**Setup:**
1. Instantiate engine with default config.
2. Call `engine._build_command("https://x.com/1")` — assert `--merge-output-format` is present.
3. Patch `shutil.which` to return `None` and call `_build_command` again.

**Exact command:**
```powershell
python C:\Files\Scraping\test_stress_suite.py test_015_ffmpeg_hotswap_detection --verbose
```

**Expected behavior:** Both commands succeed. Without ffmpeg, `--merge-output-format` is still present (yt-dlp can merge without ffmpeg for some formats) and `--no-embed-metadata` / `--no-embed-thumbnail` are added to avoid embedding failures.

**Bug exposed:** `_build_command` calls `shutil.which("ffmpeg")` at command-build time. If ffmpeg is uninstalled between two subprocess launches in the same batch, the second batch's command still includes `--embed-metadata` / `--embed-thumbnail` flags, causing yt-dlp to exit with a non-zero code and marking the download as failed even though the video was downloaded correctly.

**Severity if it fails:** MEDIUM — transient ffmpeg unavailability during a long batch causes spurious failures for all subsequent URLs.

---

### 16. `test_016_long_filename_handling` *(Windows-only)*

**Area:** Very long filenames (Windows path limits)

**Setup:**
1. Generate a filename of 200 `'A'` characters + ` [1234567890].mp4` (total > 220 chars).
2. Call `_parse_yt_dlp_output` with that filename as the reported filepath, `returncode=0`.

**Exact command:**
```powershell
python C:\Files\Scraping\test_stress_suite.py test_016_long_filename_handling --verbose
```

**Expected behavior:** `result["success"] is True`. No `OSError` or `UnicodeEncodeError` is raised.

**Bug exposed:** Windows `MAX_PATH` is 260 characters. If the output directory is `C:\Users\<user>\AppData\Local\Temp\svd_stress_XXXXXX\` (~50 chars) and the filename is 220+ chars, the full path exceeds 260. If the code uses `os.path` (ANSI) instead of `Path` (wide-char) or does not call `pathlib.Path(path).resolve()` with `\\?\` prefix, `Path.exists()` returns `False`, causing the engine to enter `_find_output_file` and fail with "Download completed but no output file found".

**Severity if it fails:** HIGH — long social media titles (common on X/Twitter) silently fail on Windows.

---

### 17. `test_017_duplicate_urls_deduplicated`

**Area:** Duplicate URLs in input list

**Setup:**
1. Create a list of 5 URLs where `https://x.com/1` appears twice and `https://x.com/2` appears twice (3 unique URLs).
2. Mock `svd.main` to capture the argv list it receives.
3. Call `svd.main(urls + ["-o", tmp, "-j", "2", "-q"])`.

**Exact command:**
```powershell
python C:\Files\Scraping\test_stress_suite.py test_017_duplicate_urls_deduplicated --verbose
```

**Expected behavior:** The captured argv list contains exactly 3 unique `https://` URLs. The deduplication log message "Removed N duplicate URLs" is emitted.

**Bug exposed:** If `main()` passes the raw URL list directly to `DownloaderConfig` without deduplication, the engine spawns 5 tasks for 3 unique videos. Two tasks write to the same output file concurrently, causing the second write to overwrite the first, or the semaphore to waste slots on redundant work.

**Severity if it fails:** MEDIUM — duplicate URLs waste bandwidth and disk I/O; concurrent writes to the same filepath cause silent data loss.

---

### 18. `test_018_state_file_locked_handled`

**Area:** State file locked by another process

**Setup:**
1. Create a temp directory and a valid state file (1 completed entry) using `make_state_file`.
2. Instantiate `StateManager(state_path)`.
3. Acquire an exclusive OS-level lock on the state file using `msvcrt.locking` (Windows) or `fcntl.flock` (POSIX).
4. Call `sm.mark_completed("https://example.com/locked-test", task)` while the lock is held.
5. Release the lock.
6. Verify the state file is still valid JSON and the in-memory state contains the new entry.

**Exact command:**
```powershell
python C:\Files\Scraping\test_stress_suite.py test_018_state_file_locked_handled --verbose
```

**Expected behavior:** `mark_completed` does not raise `PermissionError`. The in-memory `sm.data["completed"]` contains `"https://example.com/locked-test"`. After releasing the lock, `state.json` is still valid JSON.

**Bug exposed:** `StateManager.save()` uses `tempfile.mkstemp` + `os.replace`. On Windows, `os.replace` to a destination that is locked by another process raises `PermissionError` (WinError 5). The current implementation catches `Exception` but re-raises it, propagating the `PermissionError` up through `mark_completed` → `_process_task` → `run()` and crashing the batch.

**Fix already applied:** `save()` now catches `PermissionError` specifically, logs a warning, and preserves in-memory state.

**Severity if it fails:** HIGH — antivirus scanners or backup tools that briefly lock `.json` files crash the entire download batch.

---

### 19. `test_019_memory_usage_thousand_urls` *(SLOW)*

**Area:** Memory usage with 1000+ URLs

**Setup:**
1. Generate 1000 fake URLs.
2. Start `tracemalloc`.
3. Instantiate `DownloaderConfig(urls=1000_urls, output_dir=tmp)` and `AsyncDownloadEngine(config, logger)`.
4. Read peak memory.

**Exact command:**
```powershell
python C:\Files\Scraping\test_stress_suite.py test_019_memory_usage_thousand_urls --all --slow --verbose
```

**Expected behavior:** Peak traced memory < 50 MB.

**Bug exposed:** If `ProgressDisplay.register` stores a full copy of each `DownloadTask` (including the URL string) in an internal dict, and `AsyncDownloadEngine.__init__` eagerly creates all 1000 `DownloadTask` objects at once, memory scales linearly. For 10,000 URLs this becomes ~500 MB. If `asyncio.Semaphore` is also holding references to all tasks, GC cannot collect them until `run()` completes.

**Severity if it fails:** MEDIUM — users running large batches (1000+ URLs) on machines with < 4 GB RAM see the process killed by the OOM killer.

---

### 20. `test_020_stdout_stderr_interleaved_parse`

**Area:** Subprocess stdout/stderr interleaving

**Setup:**
1. Create a temp directory and pre-create `my video [9876543210].mp4`.
2. Construct a combined output string mixing:
   - `[download]` progress lines (stdout)
   - `WARNING: stderr warning` (stderr)
   - More `[download]` progress lines
   - The `--print` output: filepath, size, resolution, format_id (each on its own line)
   - `[ExtractAudio]` line (yt-dlp post-processing log)
3. Call `_parse_yt_dlp_output` with `returncode=0`.

**Exact command:**
```powershell
python C:\Files\Scraping\test_stress_suite.py test_020_stdout_stderr_interleaved_parse --verbose
```

**Expected behavior:** `result["success"] is True`. `result["file"]` contains `"my video"`. `result["size"] == 20971520`. `result["resolution"] == "1920x1080"`. `result["format_id"] == "http-555"`.

**Bug exposed:** `subprocess.run(capture_output=True)` returns `result.stdout` and `result.stderr` as separate strings. The current code concatenates them (`output = result.stdout + result.stderr`) before passing to `_parse_yt_dlp_output`. If yt-dlp emits `--print` fields on stderr (which it does when `--newline` is not used and progress bars are on stderr), the parser's heuristic (`prints = [l for l in lines if l and not l.startswith("[")]`) correctly filters bracket lines. But if a `WARNING:` line or `[ExtractAudio]` line does not start with `[`, it is included in `prints`, shifting the index and causing `format_id` to be assigned the wrong value.

**Severity if it fails:** HIGH — silent corruption of the state file's `format_id` field causes `_find_output_file` to fail on resume, marking all re-visited URLs as failed.

---

## Summary Table

| # | Test Name | Area | Severity | Slow |
|---|---|---|---|---|
| 1 | `test_001_parse_output_no_cross_talk` | Concurrent parsing races | HIGH | No |
| 2 | `test_002_state_file_no_corruption_under_concurrent_writes` | State file corruption | HIGH | No |
| 3 | `test_003_unicode_filename_parsing` | Unicode filenames | MEDIUM | No |
| 4 | `test_004_timeout_kills_process_and_triggers_retry` | Timeout vs. retry double-trip | HIGH | No |
| 5 | `test_005_partial_part_file_cleanup` | Partial `.part` files | MEDIUM | No |
| 6 | `test_006_empty_output_dir_does_not_crash` | Empty input | LOW | No |
| 7 | `test_007_hundred_urls_semaphore_respected` | 120-URL concurrency limit | HIGH | Yes |
| 8 | `test_008_network_reset_returns_error_not_crash` | Network reset | MEDIUM | No |
| 9 | `test_009_yt_dlp_output_format_changes_dont_crash` | yt-dlp format change fragility | HIGH | No |
| 10 | `test_010_cookie_extraction_no_cookies_found` | Cookie edge cases | LOW | No |
| 10b | `test_010b_cookie_extraction_invalid_browser_name` | Cookie edge cases | LOW | No |
| 11 | `test_011_progress_display_no_exception_under_concurrent_updates` | ProgressDisplay race | MEDIUM | Yes |
| 12 | `test_012_disk_full_handled_gracefully` | Disk full / permission | HIGH | No |
| 13 | `test_013_keyboard_interrupt_during_run` | Ctrl+C handling | HIGH | Yes |
| 14 | `test_014_resume_with_mixed_completed_and_failed` | Resume with mixed state | HIGH | No |
| 15 | `test_015_ffmpeg_hotswap_detection` | ffmpeg mid-batch swap | MEDIUM | No |
| 16 | `test_016_long_filename_handling` | Windows MAX_PATH | HIGH | No (Windows-only) |
| 17 | `test_017_duplicate_urls_deduplicated` | Duplicate URL deduplication | MEDIUM | No |
| 18 | `test_018_state_file_locked_handled` | State file locked by AV/backup | HIGH | No |
| 19 | `test_019_memory_usage_thousand_urls` | Memory at scale | MEDIUM | Yes |
| 20 | `test_020_stdout_stderr_interleaved_parse` | stdout/stderr interleaving | HIGH | No |

---

## Bug Fixes Applied to `social_video_downloader.py` During Test Development

| File | Line | Bug | Fix |
|---|---|---|---|
| `social_video_downloader.py` | ~954 | `re.search(pattern, flags, string)` — arguments swapped | Corrected to `re.search(pattern, string)` |
| `social_video_downloader.py` | ~193–208 | `StateManager.save()` re-raised `PermissionError` on locked file | Catch `PermissionError` specifically; log warning; keep in-memory state |
| `social_video_downloader.py` | ~998–1014 | `_verify_file` did not wrap `file_path.stat()` in try/except | Wrapped entire body in `try/except OSError` |
| `test_stress_suite.py` | — | `run_async` crashed with `RuntimeError: no running event loop` | Rewrote to use `asyncio.run` with ThreadPoolExecutor fallback |
| `test_stress_suite.py` | — | `make_state_file` used raw URLs but script now uses `normalize_url` keys | Updated helper to call `_svd.normalize_url()` |
| `test_stress_suite.py` | — | Windows console `cp1252` crashes on Unicode assertion messages | Added `safe_str()` helper that falls back to ASCII |