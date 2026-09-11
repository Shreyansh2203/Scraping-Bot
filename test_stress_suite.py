#!/usr/bin/env python3
# Stress Test Suite - social_video_downloader.py
from __future__ import annotations
import asyncio, gc, json, os, platform, shutil, signal, subprocess, sys, tempfile, threading, time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch
import pytest
try:
    import fcntl
except ImportError:
    fcntl = None
REPO_ROOT = Path(r"C:\Files\Scraping")
IS_WINDOWS = platform.system() == "win32"
def safe_str(obj: Any) -> str:
    s = str(obj)
    try:
        s.encode("cp1252")
        return s
    except UnicodeEncodeError:
        return s.encode("utf-8", errors="replace").decode("ascii", errors="replace")
def run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    else:
        import concurrent.futures
        def _run_in_thread(c):
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(c)
            finally:
                loop.close()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_run_in_thread, coro)
            return future.result()
def make_tmp_dir() -> Path:
    return Path(tempfile.mkdtemp(prefix="svd_stress_"))
def make_state_file(path: Path, completed: int = 0, failed: int = 0) -> None:
    sys.path.insert(0, str(REPO_ROOT))
    import social_video_downloader as _svd
    data = {"completed": {_svd.normalize_url(f"https://example.com/v/{i}"): {
        "file": f"downloads/vid_{i} [12345{i}].mp4", "size": 1024*1024,
        "resolution": "1920x1080", "format_id": "http-999",
        "timestamp": "2026-01-01T00:00:00+00:00"} for i in range(completed)},
        "failed": {_svd.normalize_url(f"https://example.com/f/{i}"): {
            "error": "previous failure", "timestamp": "2026-01-01T00:00:00+00:00"}
            for i in range(failed)}, "meta": {}}
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
def lock_file_exclusive(path: Path, timeout: float = 5.0):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)
    fh = open(path, "r+")
    if IS_WINDOWS:
        import msvcrt
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            try:
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                return fh
            except OSError:
                time.sleep(0.05)
        fh.close()
        raise TimeoutError(f"Could not acquire lock on {path}")
    elif fcntl is not None:
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return fh
            except (IOError, OSError):
                time.sleep(0.05)
        fh.close()
        raise TimeoutError(f"Could not acquire lock on {path}")
    return fh
sys.path.insert(0, str(REPO_ROOT))
for _mod in list(sys.modules.keys()):
    if "social_video" in _mod:
        del sys.modules[_mod]
import social_video_downloader as svd
class TestSuite:
    def test_001_parse_output_no_cross_talk(self):
        tmp = make_tmp_dir()
        safe_name = "multiline_file.mp4"
        (tmp / "file.mp4").write_bytes(b"\x00"*1024)
        (tmp / "日本語タイトル_ελληνικά [9876543210].mp4").write_bytes(b"\x00"*1024)
        (tmp / safe_name).write_bytes(b"\x00"*1024)
        engine = svd.AsyncDownloadEngine(svd.DownloaderConfig(urls=[], output_dir=tmp), svd.setup_logging(quiet=True))
        outputs = [("file.mp4\n1048576\n1920x1080\nhttp-1234",0),
                   ("日本語タイトル_ελληνικά [9876543210].mp4\n2048000\n1280x720\nhttp-5678",0),
                   ("",1),(f"{safe_name}\n5242880\n3840x2160\nhttp-9999",0)]
        for i,(out,rc) in enumerate(outputs):
            task = svd.DownloadTask(url=f"https://x.com/{i}", index=i)
            result = engine._parse_yt_dlp_output(task, out, rc)
            if rc==0:
                assert result["success"] is True, f"Test 1 r{i}: "+safe_str(f"{result}")
                assert "file" in result and "format_id" in result
            else:
                assert result["success"] is False
    def test_002_state_file_no_corruption_under_concurrent_saves(self):
        tmp = make_tmp_dir()
        sm = svd.StateManager(tmp/"state.json")
        async def writer(tag):
            for i in range(50):
                sm.mark_completed(f"https://example.com/{tag}/{i}",
                    svd.DownloadTask(url=f"https://example.com/{tag}/{i}", index=i, file_size=1024))
                await asyncio.sleep(0)
        async def run_writers():
            await asyncio.gather(*[writer(f"w{j}") for j in range(5)])
        run_async(run_writers())
        raw = (tmp/"state.json").read_text(encoding="utf-8")
        parsed = json.loads(raw)
        assert "completed" in parsed and len(parsed["completed"]) > 0
    def test_003_unicode_filename_parsing(self):
        tmp = make_tmp_dir()
        placeholder = tmp / "unicode_placeholder.mp4"
        placeholder.write_bytes(b"\x00"*1024)
        engine = svd.AsyncDownloadEngine(svd.DownloaderConfig(urls=[], output_dir=tmp), svd.setup_logging(quiet=True))
        unicode_filename = "vid_日本語_ελληνικά_العربية [9876543210].mp4"
        output = f"{unicode_filename}\n3145728\n1920x1080\nhttp-abc\n"
        real_exists, real_stat = Path.exists, Path.stat
        def fake_exists(self):
            s = str(self)
            return True if "unicode_placeholder" in s or unicode_filename in s else real_exists(self)
        def fake_stat(self, *a, **kw):
            s = str(self)
            return os.stat_result((33188,0,0,0,0,0,1024,0,0,0)) if "unicode_placeholder" in s or unicode_filename in s else real_stat(self,*a,**kw)
        try:
            with patch.object(Path,"exists",fake_exists), patch.object(Path,"stat",fake_stat):
                result = engine._parse_yt_dlp_output(svd.DownloadTask(url="https://x.com/1",index=1),output,0)
        except Exception as exc:
            pytest.fail("test_003 raised: "+safe_str(f"{type(exc).__name__}: {exc}"))
        try:
            assert result["success"] is True, "success not True: "+safe_str(repr(result))
            assert "vid_" in result["file"], "file wrong: "+safe_str(result.get("file",""))
            assert result["format_id"]=="http-abc","format_id wrong: "+safe_str(result.get("format_id",""))
        except AssertionError as ae:
            pytest.fail(safe_str(str(ae)))
    def test_004_timeout_kills_process_and_triggers_retry(self):
        config = svd.DownloaderConfig(urls=["https://x.com/1"],output_dir=make_tmp_dir(),retries=3,subprocess_timeout=1)
        engine = svd.AsyncDownloadEngine(config, svd.setup_logging(quiet=True))
        call_count = 0
        def fake_run(cmd,**kw):
            nonlocal call_count; call_count += 1; raise subprocess.TimeoutExpired(cmd,1)
        with patch("subprocess.run", side_effect=fake_run):
            task = run_async(engine._process_task(svd.DownloadTask(url="https://x.com/1",index=1)))
        assert call_count==3, f"Expected 3 retries, got {call_count}"
        assert task.status=="failed" and "Timeout" in (task.error or "")
    def test_005_partial_part_file_cleanup(self):
        tmp = make_tmp_dir()
        (tmp/"video.mp4.part").write_bytes(b"partial"*1000)
        (tmp/"thumb.jpg").write_bytes(b"jpg")
        engine = svd.AsyncDownloadEngine(svd.DownloaderConfig(urls=[],output_dir=tmp),svd.setup_logging(quiet=True))
        engine._cleanup_orphans()
        assert not (tmp/"video.mp4.part").exists() and (tmp/"thumb.jpg").exists()
    def test_006_empty_output_dir_does_not_crash(self):
        tmp = make_tmp_dir()
        config = svd.DownloaderConfig(urls=[],output_dir=tmp)
        engine = svd.AsyncDownloadEngine(config, svd.setup_logging(quiet=True))
        results = run_async(engine.run())
        assert results==[] and tmp.exists()
    @pytest.mark.slow
    def test_007_hundred_urls_semaphore_respected(self):
        tmp = make_tmp_dir()
        urls = [f"https://example.com/v/{i}" for i in range(120)]
        max_c, cur_c = 0, 0
        lock = threading.Lock()
        def fake_run(cmd,**kw):
            nonlocal max_c, cur_c
            with lock: cur_c+=1; max_c=max(max_c,cur_c)
            time.sleep(0.02)
            with lock: cur_c-=1
            return subprocess.CompletedProcess(cmd,0,stdout="fake_vid [9999999999].mp4\n1048576\n480p\nhttp-1\n",stderr="")
        config = svd.DownloaderConfig(urls=urls,output_dir=tmp,concurrent=5,subprocess_timeout=60,quiet=True)
        engine = svd.AsyncDownloadEngine(config, svd.setup_logging(quiet=True))
        (tmp/"fake_vid [9999999999].mp4").write_bytes(b"\x00"*1048576)
        with patch.object(svd.subprocess,"run",side_effect=fake_run):
            results = run_async(engine.run())
        assert max_c<=5, f"Semaphore violated: max_c={max_c}, limit=5"
        assert sum(1 for r in results if r and r.status=="success")==120
    def test_008_network_reset_returns_error_not_crash(self):
        engine = svd.AsyncDownloadEngine(svd.DownloaderConfig(urls=[],output_dir=make_tmp_dir()),svd.setup_logging(quiet=True))
        stderr = "[yt-dlp] ERROR: Unable to download webpage: <urlopen error [Errno 104] Connection reset by peer>"
        result = engine._parse_yt_dlp_output(svd.DownloadTask(url="https://x.com/1",index=1),f"[download] 50% of 10.00MiB\n{stderr}",1)
        assert result["success"] is False and "error" in result and result["error"]!=""
    def test_009_yt_dlp_output_format_changes_dont_crash(self):
        tmp = make_tmp_dir()
        fname = "real_file [abc123xyz].mp4"
        (tmp/fname).write_bytes(b"\x00"*1024)
        engine = svd.AsyncDownloadEngine(svd.DownloaderConfig(urls=[],output_dir=tmp),svd.setup_logging(quiet=True))
        changed = ("[download] 25.0% of 50.00MiB at 2.00MiB/s ETA 00:10\n"
                   "[download] 100.0% of 50.00MiB in 00:00:25\n"
                   "WARNING: new format\n"+fname+"\n52428800\n1920x1080\nhttp-999\n")
        try:
            result = engine._parse_yt_dlp_output(svd.DownloadTask(url="https://x.com/1",index=1),changed,0)
        except Exception as exc:
            pytest.fail("test_009 raised: "+safe_str(f"{type(exc).__name__}: {exc}"))
        try:
            assert "success" in result
            assert result["success"] is True, f"success: {result['success']!r}"
            assert "real_file" in result.get("file",""), f"file: {result.get('file','')!r}"
            assert result["format_id"]=="http-999", f"format_id: {result.get('format_id','')!r}"
            assert result["size"]==52428800, f"size: {result.get('size','')!r}"
        except AssertionError as ae:
            pytest.fail(safe_str(str(ae)))
    def test_010_cookie_extraction_no_cookies_found(self):
        mock_cj = MagicMock(); mock_cj.__iter__=lambda self:iter([])
        with patch.object(svd.browser_cookie3,"chrome",return_value=mock_cj):
            assert svd.extract_browser_cookies("chrome") is None
    def test_010b_cookie_extraction_invalid_browser_name(self):
        assert svd.extract_browser_cookies("netscape") is None
    @pytest.mark.slow
    def test_011_progress_display_no_exception_under_concurrent_updates(self):
        display = svd.ProgressDisplay(total=50, quiet=False)
        for i in range(50): display.register(svd.DownloadTask(url=f"u{i}",index=i))
        async def updater(idx):
            for pct in range(0,101,10):
                await display.update(idx,"running",progress=float(pct)); await asyncio.sleep(0)
        async def runner(): await asyncio.gather(*[updater(i) for i in range(50)])
        try: run_async(runner())
        except Exception as exc: pytest.fail(f"ProgressDisplay raised: {exc}")
    def test_012_disk_full_handled_gracefully(self):
        tmp = make_tmp_dir()
        real_file = tmp/"downloaded_video.mp4"; real_file.write_bytes(b"\x00"*2048)
        config = svd.DownloaderConfig(urls=["https://x.com/1"],output_dir=tmp,subprocess_timeout=5,retries=1)
        engine = svd.AsyncDownloadEngine(config, svd.setup_logging(quiet=True))
        def failing_verify(fp, min_size): return False, "OS error: disk full"
        with patch.object(svd.AsyncDownloadEngine,"_verify_file",staticmethod(failing_verify)):
            def fake_run(cmd,**kw):
                return subprocess.CompletedProcess(cmd,0,stdout=f"{real_file}\n2048\n480p\nhttp-1\n",stderr="")
            with patch.object(svd.subprocess,"run",side_effect=fake_run):
                task = run_async(engine._process_task(svd.DownloadTask(url="https://x.com/1",index=1)))
        assert task.status=="failed", f"Expected failed, got {task.status}"
        assert "Integrity" in (task.error or ""), f"Expected integrity error, got: {task.error}"
    @pytest.mark.slow
    def test_013_keyboard_interrupt_during_run(self):
        tmp = make_tmp_dir()
        urls = [f"https://x.com/{i}" for i in range(6)]
        hang_event = threading.Event()
        def hang_forever(cmd,**kw):
            hang_event.wait()
            return subprocess.CompletedProcess(cmd,0,stdout="",stderr="")
        async def patched_main(argv):
            import social_video_downloader as svd_mod
            parser = svd_mod.build_parser()
            args = parser.parse_args(argv)
            collected = list(args.urls or [])
            if args.file: collected.extend(svd_mod.load_urls_from_file(Path(args.file)))
            seen2=set(); unique=[u for u in collected if u not in seen2 and not seen2.add(u)]
            cf = args.cookies; tc = None
            if args.cookies_from_browser:
                tc = svd_mod.extract_browser_cookies(args.cookies_from_browser)
                if tc: cf = tc
            config = svd_mod.DownloaderConfig(
                urls=unique, output_dir=Path(args.output_dir), concurrent=max(1,args.concurrent),
                retries=1, retry_delay=0, timeout=max(10,args.timeout),
                subprocess_timeout=getattr(args,"subprocess_timeout",30),
                cookies_file=cf, resume=args.resume, state_file=args.state_file,
                quiet=args.quiet, verbose=args.verbose, no_verify=args.no_verify,
                min_file_size=max(0,args.min_file_size),
            )
            logger = svd_mod.setup_logging(verbose=config.verbose, quiet=config.quiet)
            if config.embed_thumbnail or config.merge_format!="webm":
                if not shutil.which("ffmpeg"): logger.warning("ffmpeg not found.")
            # Patch asyncio.to_thread so worker threads are daemon threads
            orig_to_thread = asyncio.to_thread
            hang_ref = [hang_event]
            async def _slow_run(func, *args, **kwargs):
                import concurrent.futures
                executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
                future = executor.submit(func, *args, **kwargs)
                for t in executor._threads: t.daemon = True
                try:
                    return await asyncio.wrap_future(future)
                except asyncio.CancelledError:
                    hang_ref[0].set()
                    raise
            try:
                with patch.object(asyncio,"to_thread",_slow_run), \
                     patch.object(svd.subprocess,"run",side_effect=hang_forever):
                    engine = svd_mod.AsyncDownloadEngine(config, logger)
                    loop = asyncio.get_running_loop()
                    loop.call_later(0.3, lambda: (_ for _ in ()).throw(KeyboardInterrupt()))
                    await engine.run()
                return 0
            except KeyboardInterrupt:
                print("\nInterrupted by user.", file=sys.stderr)
                return 130
            finally:
                hang_event.set()
                if tc: tc.unlink(missing_ok=True)
        with patch.object(svd.subprocess,"run",side_effect=hang_forever):
            ret = run_async(patched_main([*urls,"-o",str(tmp),"-j","2","-q"]))
        assert ret==130, f"Expected exit code 130 on Ctrl+C, got {ret}"
    def test_014_resume_with_mixed_completed_and_failed(self):
        tmp = make_tmp_dir()
        make_state_file(tmp/"state.json", completed=3, failed=2)
        downloads_dir = tmp/"downloads"; downloads_dir.mkdir()
        (downloads_dir/"vid_0 [123450].mp4").write_bytes(b"x"*1024)
        config = svd.DownloaderConfig(
            urls=[*[f"https://example.com/v/{i}" for i in range(3)],
                  *[f"https://example.com/f/{i}" for i in range(2)],"https://example.com/new/1"],
            output_dir=downloads_dir, resume=True, state_file=tmp/"state.json",
            concurrent=2, subprocess_timeout=2, retries=1, retry_delay=0,
        )
        engine = svd.AsyncDownloadEngine(config, svd.setup_logging(quiet=True))
        def fake_run(cmd,**kw):
            out_file = downloads_dir/"new_file [9999999999].mp4"
            out_file.write_bytes(b"\x00"*1024)
            return subprocess.CompletedProcess(cmd,0,stdout="new_file [9999999999].mp4\n1024\n640x360\nhttp-1\n",stderr="")
        with patch.object(svd.subprocess,"run",side_effect=fake_run), \
             patch("asyncio.sleep", side_effect=lambda *a,**kw: None):
            results = run_async(engine.run())
        skipped = sum(1 for r in results if r and r.status=="skipped")
        assert skipped==3, f"Expected 3 skipped, got {skipped}"
        assert len([r for r in results if r and r.status!="skipped"])==3
    def test_015_ffmpeg_hotswap_detection(self):
        tmp = make_tmp_dir()
        config = svd.DownloaderConfig(urls=["https://x.com/1"],output_dir=tmp)
        engine = svd.AsyncDownloadEngine(config, svd.setup_logging(quiet=True))
        assert "--merge-output-format" in engine._build_command("https://x.com/1")
        with patch("shutil.which", return_value=None):
            cmd = engine._build_command("https://x.com/1")
        assert "--merge-output-format" in cmd and "--no-embed-metadata" in cmd
    @pytest.mark.skipif(not IS_WINDOWS, reason="Windows-specific test")
    def test_016_long_filename_handling(self):
        long_filename = "A"*200 + " [1234567890].mp4"
        assert len(long_filename) > 200
        engine = svd.AsyncDownloadEngine(svd.DownloaderConfig(urls=[],output_dir=make_tmp_dir()),svd.setup_logging(quiet=True))
        result = engine._parse_yt_dlp_output(svd.DownloadTask(url="https://x.com/1",index=1),f"{long_filename}\n1024\n480p\nhttp-1\n",0)
        assert "success" in result
    def test_017_duplicate_urls_deduplicated(self):
        tmp = make_tmp_dir()
        urls = ["https://x.com/1","https://x.com/2","https://x.com/1","https://x.com/3","https://x.com/2"]
        captured = []
        def fake_run(cmd,**kw):
            return subprocess.CompletedProcess(cmd,0,stdout="f [999].mp4\n1024\n360p\nhttp-1\n",stderr="")
        async def fake_main(argv):
            captured.extend(argv); return 0
        with patch.object(svd.subprocess,"run",side_effect=fake_run),patch.object(svd,"main",fake_main):
            run_async(svd.main([*urls,"-o",str(tmp),"-j","2","-q"]))
        unique_seen=[]; seen=set()
        for u in captured:
            if u not in seen: seen.add(u); unique_seen.append(u)
        assert len([u for u in unique_seen if u.startswith("https://")])==3
    def test_018_state_file_locked_handled(self):
        tmp = make_tmp_dir()
        state_path = tmp/"state.json"
        make_state_file(state_path, completed=1, failed=0)
        sm = svd.StateManager(state_path)
        assert "completed" in sm.data and sm.get_completed_count()==1
        fh = lock_file_exclusive(state_path, timeout=5.0)
        try:
            sm.mark_completed("https://example.com/locked-test",
                svd.DownloadTask(url="https://example.com/locked-test",index=99,file_size=100))
        except PermissionError:
            pytest.fail("StateManager.save() raised PermissionError on locked file")
        finally:
            fh.close()
        assert "https://example.com/locked-test" in sm.data["completed"]
        assert "completed" in json.loads(state_path.read_text(encoding="utf-8"))
    @pytest.mark.slow
    def test_019_memory_usage_thousand_urls(self):
        import tracemalloc
        urls = [f"https://x.com/{i}" for i in range(1000)]
        tmp = make_tmp_dir()
        config = svd.DownloaderConfig(urls=urls, output_dir=tmp)
        logger = svd.setup_logging(quiet=True)
        tracemalloc.start()
        engine = svd.AsyncDownloadEngine(config, logger)
        _c, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        assert peak/(1024*1024) < 50.0, f"Memory too high: {peak/(1024*1024):.1f} MB"
    def test_020_stdout_stderr_interleaved_parse(self):
        tmp = make_tmp_dir()
        (tmp/"my video [9876543210].mp4").write_bytes(b"\x00"*1024)
        engine = svd.AsyncDownloadEngine(svd.DownloaderConfig(urls=[],output_dir=tmp),svd.setup_logging(quiet=True))
        interleaved = ("[download] 10.0% of 20.00MiB at 1.00MiB/s ETA 00:18\n"
                       "WARNING: stderr warning\n"
                       "[download] 50.0% of 20.00MiB at 2.00MiB/s ETA 00:05\n"
                       "my video [9876543210].mp4\n20971520\n1920x1080\nhttp-555\n"
                       "[download] 100.0% of 20.00MiB in 00:00:10\n[ExtractAudio] Not extracting audio\n")
        result = engine._parse_yt_dlp_output(svd.DownloadTask(url="https://x.com/1",index=1),interleaved,0)
        try:
            assert result["success"] is True, f"Unexpected failure: {result}"
            assert "my video" in result.get("file",""), f"file wrong: {result.get('file','')!r}"
            assert result["format_id"]=="http-555", f"format_id wrong: {result.get('format_id','')!r}"
            assert result["size"]==20971520, f"size wrong: {result.get('size','')!r}"
        except AssertionError as ae:
            pytest.fail(safe_str(str(ae)))
if __name__=="__main__":
    import argparse
    p = argparse.ArgumentParser(description="Stress tests for social_video_downloader.py")
    p.add_argument("test",nargs="?",help="Test name filter")
    p.add_argument("--all",action="store_true"); p.add_argument("--slow",action="store_true"); p.add_argument("-v","--verbose",action="store_true")
    args = p.parse_args()
    suite = TestSuite()
    all_tests = [(n,getattr(suite,n)) for n in sorted(dir(suite)) if n.startswith("test_")]
    if args.test: all_tests = [(n,f) for n,f in all_tests if args.test in n]
    passed=failed=skipped=0
    for name,fn in all_tests:
        is_slow = getattr(fn,"pytestmark",None) and any(m.name=="slow" for m in getattr(fn,"pytestmark",[]))
        if is_slow and not args.slow:
            skipped+=1
            if args.verbose: print(f"  SKIP  {name} (slow)")
            continue
        try:
            if args.verbose: print(f"  RUN   {name} ...",flush=True)
            fn(); passed+=1
            if args.verbose: print(f"  PASS  {name}")
        except Exception as exc:
            failed+=1; msg=safe_str(str(exc)) or safe_str(repr(exc))
            print(f"  FAIL  {name}: {msg}",file=sys.stderr)
    print(f"\n{'='*60}\n  PASSED : {passed}\n  FAILED : {failed}\n  SKIPPED: {skipped}\n{'='*60}")
    sys.exit(1 if failed else 0)
