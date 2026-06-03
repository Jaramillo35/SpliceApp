"""
DTCR Engine — Streamlit-compatible wrapper around Playwright browser automation.

Runs the async Playwright workflow in a background thread, streams log lines
via a queue, and zips downloaded files for the Streamlit download button.
"""

from __future__ import annotations

import asyncio
import io
import logging
import queue
import threading
import zipfile
from pathlib import Path

from playwright.async_api import async_playwright

# ---------------------------------------------------------------------------
# Logging bridge — funnels all log output into the shared queue.
# ---------------------------------------------------------------------------

class _QueueHandler(logging.Handler):
    def __init__(self, log_queue: queue.Queue) -> None:
        super().__init__()
        self._q = log_queue

    def emit(self, record: logging.LogRecord) -> None:
        self._q.put(self.format(record))


def _attach_queue_handler(log_queue: queue.Queue) -> list[logging.Handler]:
    handler = _QueueHandler(log_queue)
    handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S"))
    root = logging.getLogger()
    root.addHandler(handler)
    return handler


def _detach_queue_handler(handler: logging.Handler) -> None:
    logging.getLogger().removeHandler(handler)


# ---------------------------------------------------------------------------
# Overlay helpers (copied from master_scraper logic)
# ---------------------------------------------------------------------------

_OVERLAY_SCRIPT = """
    () => {
        if (typeof window.__copilotDownloadClicked === 'undefined') {
            window.__copilotDownloadClicked = false;
        }

        let panel = document.getElementById('copilot-download-panel');
        if (!panel) {
            panel = document.createElement('div');
            panel.id = 'copilot-download-panel';
            panel.style.position = 'fixed';
            panel.style.top = '16px';
            panel.style.right = '16px';
            panel.style.zIndex = '2147483647';
            panel.style.maxWidth = '420px';
            panel.style.background = '#103b6d';
            panel.style.color = '#fff';
            panel.style.borderRadius = '10px';
            panel.style.padding = '14px 16px';
            panel.style.boxShadow = '0 6px 20px rgba(0,0,0,0.3)';
            panel.style.fontFamily = 'Arial, sans-serif';
            panel.style.fontSize = '14px';

            const title = document.createElement('div');
            title.style.fontWeight = '700';
            title.style.marginBottom = '8px';
            title.textContent = 'Steps Before Download';

            const list = document.createElement('ul');
            list.style.margin = '0 0 10px 0';
            list.style.paddingLeft = '18px';
            const steps = [
                'Sign in with your User ID and Password.',
                'Open the Change Requests tab.',
                'Input Program and Phase, then click Search.',
                'Wait for search results to appear.',
                'Click the Download button below.'
            ];
            steps.forEach(step => {
                const li = document.createElement('li');
                li.textContent = step;
                li.style.marginBottom = '4px';
                list.appendChild(li);
            });

            const btn = document.createElement('button');
            btn.id = 'copilot-download-button';
            btn.textContent = 'Download DTCRs';
            btn.style.background = '#f39c12';
            btn.style.border = '0';
            btn.style.borderRadius = '8px';
            btn.style.color = '#fff';
            btn.style.fontWeight = '700';
            btn.style.padding = '8px 14px';
            btn.style.cursor = 'pointer';
            btn.onclick = () => {
                window.__copilotDownloadClicked = true;
                btn.textContent = 'Starting...';
                btn.disabled = true;
                btn.style.opacity = '0.7';
            };

            panel.appendChild(title);
            panel.appendChild(list);
            panel.appendChild(btn);
            document.body.appendChild(panel);
        }

        return window.__copilotDownloadClicked === true;
    }
"""


def _get_active_page(context, current_page):
    try:
        if current_page and not current_page.is_closed():
            return current_page
    except Exception:
        pass
    live = [p for p in context.pages if not p.is_closed()]
    return live[-1] if live else current_page


async def _wait_for_download_click(context, page, log_queue: queue.Queue):
    """Inject overlay into every live page/frame; return when user clicks Download."""
    while True:
        for p in [pg for pg in context.pages if not pg.is_closed()]:
            for frame in [p.main_frame] + [f for f in p.frames if f != p.main_frame]:
                try:
                    clicked = await frame.evaluate(_OVERLAY_SCRIPT)
                    if clicked:
                        log_queue.put("✓ Download button clicked. Starting DTCR processing...")
                        # Remove panel
                        try:
                            await p.evaluate(
                                "() => { const el = document.getElementById('copilot-download-panel'); if (el) el.remove(); }"
                            )
                        except Exception:
                            pass
                        return p
                except Exception:
                    continue
        await asyncio.sleep(1)


# ---------------------------------------------------------------------------
# Main async workflow
# ---------------------------------------------------------------------------

CHRYSLER_LOGIN_URL = (
    "https://login.chrysler.com/siteminderagent/forms/chryslerlogin.fcc"
    "?TYPE=33554433&REALMOID=06-3f2a4016-f13a-0076-0000-31e7000031e7"
    "&GUID=&SMAUTHREASON=0&METHOD=GET"
    "&SMAGENTNAME=-SM-%2bWLpSgscRfpSwghGeXnNG1dvGOs%2bFyz1jzikB8V%2fvy"
    "%2bVofPVokIbhkuBaeIevVBwV5%2fnWaXHP4IzVfRYlCE7Gg3OqtvJTcVV"
    "&TARGET=-SM-https%3a%2f%2fispeed%2eextra%2echrysler%2ecom%2fispeed%2findex%2ehtml"
)
ISPEED_URL = "https://ispeed.extra.chrysler.com/ispeed/index.html"


async def _run_async(
    username: str,
    password: str,
    download_dir: Path,
    log_queue: queue.Queue,
    done_event: threading.Event,
    result_holder: dict,
) -> None:
    from dtcr_lib.dtcr_scraper import DTCRScraper

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context(accept_downloads=True)
            page = await context.new_page()

            log_queue.put("Browser launched. Opening Chrysler login page...")
            await page.goto(CHRYSLER_LOGIN_URL, wait_until="domcontentloaded", timeout=25000)

            # Pre-fill credentials if provided.
            if username and password:
                try:
                    await page.wait_for_selector("[name='USER']", timeout=8000)
                    await page.fill("[name='USER']", username)
                    await page.fill("[name='PASSWORD']", password)
                    await page.click("[id='login-btn']")
                    log_queue.put("Credentials submitted. Waiting for redirect...")
                    try:
                        await page.wait_for_load_state("networkidle", timeout=20000)
                    except Exception:
                        pass
                except Exception as exc:
                    log_queue.put(f"Auto-fill skipped ({exc}). Please sign in manually in the browser.")
            else:
                log_queue.put("No credentials supplied — please sign in manually in the browser.")

            # Inject overlay and wait for the user to search and click Download.
            log_queue.put("Browser ready. Complete the steps shown in the browser overlay, then click Download.")
            page = await _wait_for_download_click(context, page, log_queue)

            # Run scraper on the current results page.
            scraper = DTCRScraper(
                base_url=ISPEED_URL,
                download_dir=str(download_dir),
            )
            scraper.attach_page(page)

            log_queue.put("Starting DTCR attachment download...")
            results = await scraper.process_current_results()

            if results.get("success"):
                log_queue.put(f"Total DTCRs: {results.get('total_dtcrs')}")
                log_queue.put(f"Processed:   {results.get('processed')}")
                log_queue.put(f"Failed:      {results.get('failed')}")
                excel_path = scraper.export_reason_for_change_excel(results)
                log_queue.put(f"Reason-for-change Excel saved: {excel_path}")
                result_holder["results"] = results
                result_holder["scraper_dir"] = download_dir
            else:
                log_queue.put(f"Error: {results.get('error')}")
                result_holder["error"] = results.get("error")

            try:
                if browser.is_connected():
                    await browser.close()
            except Exception:
                pass

    except Exception as exc:
        log_queue.put(f"Fatal error: {exc}")
        result_holder["error"] = str(exc)
    finally:
        done_event.set()


# ---------------------------------------------------------------------------
# Public threading entry point
# ---------------------------------------------------------------------------

def start_dtcr_session(
    username: str,
    password: str,
    download_dir: str | Path,
    log_queue: queue.Queue,
    done_event: threading.Event,
    result_holder: dict,
) -> threading.Thread:
    """
    Launch the Playwright workflow in a daemon thread.

    Callers should poll `done_event` and drain `log_queue` from their own thread
    (e.g. via Streamlit's rerun loop).  When `done_event` is set, `result_holder`
    will contain either {"results": ..., "scraper_dir": ...} or {"error": ...}.
    """
    download_dir = Path(download_dir)
    download_dir.mkdir(parents=True, exist_ok=True)

    handler = _attach_queue_handler(log_queue)

    def _thread_target() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(
                _run_async(username, password, download_dir, log_queue, done_event, result_holder)
            )
        finally:
            loop.close()
            _detach_queue_handler(handler)

    t = threading.Thread(target=_thread_target, daemon=True)
    t.start()
    return t


# ---------------------------------------------------------------------------
# Zip helper
# ---------------------------------------------------------------------------

def zip_download_dir(download_dir: str | Path) -> bytes:
    """Zip everything in download_dir and return the bytes."""
    buf = io.BytesIO()
    root = Path(download_dir)
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(root))
    buf.seek(0)
    return buf.getvalue()
