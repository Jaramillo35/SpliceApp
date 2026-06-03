"""
DTCR Change Requests Scraper
Searches, retrieves, and downloads DTCR attachments
"""

import asyncio
import logging
import re
from pathlib import Path
from playwright.async_api import async_playwright
from openpyxl import Workbook

logger = logging.getLogger(__name__)


class DTCRScraper:
    """Scrapes DTCR information and downloads attachments"""
    
    def __init__(self, base_url="https://ispeed.extra.chrysler.com/ispeed/index.html", download_dir="dtcr_downloads"):
        self.base_url = base_url
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(exist_ok=True)
        self.attachments_dir = self.download_dir / "attachments"
        self.attachments_dir.mkdir(exist_ok=True)
        self.page = None
        self.browser = None
        self.context = None
        self.playwright = None
        self.results_frame = None

    def _dtcr_already_downloaded(self, dtcr_number):
        """Return True when shared attachments folder already contains file(s) for DTCR."""
        prefix = f"{dtcr_number} - "
        for item in self.attachments_dir.iterdir():
            if item.is_file() and item.stat().st_size > 0 and item.name.startswith(prefix):
                return True
        return False

    async def _refresh_results_frame(self):
        """Refresh results frame detection after navigation back to Search Results."""
        rows = await self.get_dtcr_rows()
        return rows

    async def _select_dtcr_row_exact(self, dtcr_number):
        """
        Select DTCR row checkbox/radio by exact DTCR number in second column.

        Returns:
            bool: True if a row was selected.
        """
        target = self.results_frame if self.results_frame else self.page.main_frame
        selected = False

        try:
            selected = await target.evaluate(
                """
                (targetDtcr) => {
                    const clean = (s) => (s || '').replace(/\\s+/g, ' ').trim();
                    const rows = [...document.querySelectorAll('table tr')];
                    for (const row of rows) {
                        const cells = row.querySelectorAll('td');
                        if (cells.length < 2) continue;
                        const dtcr = clean(cells[1].innerText);
                        if (dtcr !== targetDtcr) continue;

                        const chooser = row.querySelector("input[type='radio'], input[type='checkbox']");
                        if (!chooser) return false;
                        chooser.click();
                        return true;
                    }
                    return false;
                }
                """,
                str(dtcr_number),
            )
        except Exception:
            selected = False

        return bool(selected)

    async def _go_back_to_search_results(self):
        """Return to Search Results page and refresh table/frame context."""
        try:
            await self.page.go_back()
        except Exception:
            pass

        await asyncio.sleep(1)
        try:
            await self.page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass

        await self._refresh_results_frame()
    
    async def init_browser(self, headless=False):
        """Initialize browser"""
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=headless)
        self.context = await self.browser.new_context(accept_downloads=True)
        self.page = await self.context.new_page()

    def attach_page(self, page):
        """Attach an existing page/session managed by another orchestrator."""
        self.page = page
        self.context = page.context
    
    async def close_browser(self):
        """Close browser"""
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
    
    async def navigate_to_change_requests(self):
        """Navigate to Change Requests page from iSpeed home"""
        logger.info("Navigating to Change Requests...")
        
        try:
            # Wait for page to load
            await self.page.wait_for_load_state("networkidle")
            
            # Look for Change Requests link/button
            change_requests_selector = "a:has-text('Change Request'), button:has-text('Change Request'), [href*='change' i]"
            
            # Try to find the Change Requests navigation element
            try:
                await self.page.click("text=Change Request", timeout=5000)
                logger.info("✓ Clicked Change Request button")
            except:
                logger.warning("Could not find Change Request button")
                return False
            
            # Wait for page load
            await asyncio.sleep(2)
            await self.page.wait_for_load_state("networkidle", timeout=10000)
            
            logger.info(f"✓ Navigated to: {self.page.url}")
            return True
            
        except Exception as e:
            logger.error(f"✗ Failed to navigate to Change Requests: {e}")
            return False
    
    async def search_dtcrs(self, search_params):
        """
        Perform search with user-provided parameters
        
        Args:
            search_params (dict): Search parameters
                - dtcr_number: DTCR ID to search
                - requester: Optional requester name
                - status: Optional status filter
        
        Returns:
            bool: True if search successful
        """
        logger.info("\nSearching for DTCRs...")
        
        try:
            # Find and fill search fields
            dtcr_number = search_params.get("dtcr_number", "")
            
            if not dtcr_number:
                logger.warning("DTCR number not provided")
                return False
            
            # Try to find and fill DTCR search field
            search_field_selectors = [
                "[name*='dtcr' i]",
                "[placeholder*='dtcr' i]",
                "[id*='dtcr' i]",
                "input[type='text']:first-of-type"
            ]
            
            found_field = False
            for selector in search_field_selectors:
                try:
                    field = await self.page.query_selector(selector)
                    if field:
                        await self.page.fill(selector, str(dtcr_number))
                        logger.info(f"✓ Filled DTCR field: {dtcr_number}")
                        found_field = True
                        break
                except:
                    pass
            
            if not found_field:
                logger.warning("Could not find DTCR search field")
                return False
            
            # Find and click Search button
            search_button_selectors = [
                "button:has-text('Search')",
                "[value='Search']",
                "input[type='submit']:has-text('Search')",
                "button[type='submit']"
            ]
            
            clicked = False
            for selector in search_button_selectors:
                try:
                    await self.page.click(selector, timeout=2000)
                    logger.info("✓ Clicked Search button")
                    clicked = True
                    break
                except:
                    pass
            
            if not clicked:
                logger.warning("Could not find Search button")
                return False
            
            # Wait for results to load
            logger.info("Waiting for search results...")
            await asyncio.sleep(2)
            
            try:
                await self.page.wait_for_load_state("networkidle", timeout=10000)
            except:
                pass
            
            logger.info(f"✓ Search completed. Current URL: {self.page.url}")
            return True
            
        except Exception as e:
            logger.error(f"✗ Search failed: {e}")
            return False
    
    async def get_dtcr_rows(self):
        """
        Get all DTCR rows from the results table
        
        Returns:
            list: List of DTCR data dictionaries
        """
        logger.info("\nScanning for DTCR rows...")
        
        try:
            # Wait for table to load
            await asyncio.sleep(1)
            
            # Search in main document and all frames to handle legacy iframe layouts.
            frame_candidates = [self.page.main_frame] + [f for f in self.page.frames if f != self.page.main_frame]

            best_rows = []
            best_frame = None

            for frame in frame_candidates:
                rows = await frame.query_selector_all("tbody tr, table tr")
                candidate_rows = []

                for i, row in enumerate(rows):
                    try:
                        cells = await row.query_selector_all("td")
                        if len(cells) < 2:
                            continue

                        dtcr_num = (await cells[1].text_content() or "").strip()
                        if dtcr_num.isdigit():
                            candidate_rows.append({"index": i, "dtcr_number": dtcr_num})
                    except Exception:
                        continue

                if len(candidate_rows) > len(best_rows):
                    best_rows = candidate_rows
                    best_frame = frame

            if not best_rows:
                logger.warning("Could not find results table")
                await self.page.screenshot(path="debug_table_not_found.png")
                return []

            self.results_frame = best_frame
            logger.info("✓ Found results table")
            logger.info(f"Found {len(best_rows)} DTCR rows")

            dtcr_rows = []
            for item in best_rows:
                try:
                    dtcr_num = item["dtcr_number"]
                    idx = item["index"]
                    dtcr_rows.append({"index": idx, "dtcr_number": dtcr_num})
                    logger.info(f"  [{idx}] DTCR: {dtcr_num}")
                except Exception as e:
                    logger.debug(f"Error parsing row: {e}")
                    continue
            
            logger.info(f"✓ Identified {len(dtcr_rows)} DTCR entries")
            return dtcr_rows
            
        except Exception as e:
            logger.error(f"✗ Error scanning DTCR rows: {e}")
            return []
    
    async def download_dtcr_attachments(self, dtcr_data, skip_download=False):
        """
        Download all attachments for a DTCR
        
        Args:
            dtcr_data (dict): DTCR row data with dtcr_number and row_element
            
        Returns:
            dict: Processing result including success, files_downloaded, and reason_for_change.
        """
        dtcr_number = dtcr_data.get("dtcr_number")
        logger.info(f"\n--- Processing DTCR: {dtcr_number} ---")
        
        try:
            logger.info(f"✓ Using shared attachments folder: {self.attachments_dir}")

            # Refresh frame/rows so each iteration starts from current Search Results state.
            await self._refresh_results_frame()

            # Select exact DTCR row in Search Results.
            if not await self._select_dtcr_row_exact(dtcr_number):
                logger.warning(f"Could not select exact row for DTCR {dtcr_number}")
                return {"success": False, "files_downloaded": 0, "reason_for_change": ""}

            logger.info("✓ Selected DTCR row")
            await asyncio.sleep(0.5)

            target = self.results_frame if self.results_frame else self.page.main_frame
            
            # Click Open/Modify button
            clicked_open = False
            open_selectors = [
                "button:has-text('Open/Modify')",
                "input[type='button'][value='Open/Modify']",
                "input[type='submit'][value='Open/Modify']",
                "text=Open/Modify"
            ]
            for selector in open_selectors:
                try:
                    await target.click(selector, timeout=3000)
                    clicked_open = True
                    logger.info("✓ Clicked Open/Modify button")
                    break
                except Exception:
                    try:
                        await self.page.click(selector, timeout=3000)
                        clicked_open = True
                        logger.info("✓ Clicked Open/Modify button")
                        break
                    except Exception:
                        continue
            if not clicked_open:
                logger.warning("Could not find Open/Modify button")
                return {"success": False, "files_downloaded": 0, "reason_for_change": ""}
            
            # Wait for detail page to load
            logger.info("Waiting for detail page to load...")
            await asyncio.sleep(2)
            
            try:
                await self.page.wait_for_load_state("networkidle", timeout=10000)
            except:
                pass
            
            logger.info(f"✓ Page loaded: {self.page.url}")

            # Extract Reason for Change from Requested Actions table.
            reason_for_change = await self._extract_reason_for_change()
            if reason_for_change:
                logger.info(f"✓ Reason for Change: {reason_for_change}")
            else:
                logger.warning("Reason for Change not found for this DTCR")
            
            # Find and download attachments (unless already present for this DTCR).
            if skip_download:
                logger.info(f"Skipping attachment download for DTCR {dtcr_number}: files already exist")
                files_downloaded = 0
            else:
                files_downloaded = await self._download_attachments(self.attachments_dir, dtcr_number)
            logger.info(f"✓ Downloaded {files_downloaded} files for DTCR {dtcr_number}")

            # Explicitly return to Search Results before next DTCR.
            await self._go_back_to_search_results()
            
            return {
                "success": True,
                "files_downloaded": files_downloaded,
                "reason_for_change": reason_for_change
            }
            
        except Exception as e:
            logger.error(f"✗ Failed to process DTCR {dtcr_number}: {e}")
            return {"success": False, "files_downloaded": 0, "reason_for_change": ""}

    async def _extract_reason_for_change(self):
        """Extract 'Reason for Change' from the Requested Actions table on DTCR detail page."""
        frame_targets = [self.page.main_frame] + [f for f in self.page.frames if f != self.page.main_frame]
        best_reasons = []

        for frame in frame_targets:
            try:
                reasons = await frame.evaluate(
                    """
                    () => {
                        const clean = (s) => (s || '').replace(/\\s+/g, ' ').trim();
                        const unique = new Set();

                        for (const table of document.querySelectorAll('table')) {
                            const headerCells = [...table.querySelectorAll('th')].map(th => clean(th.innerText).toLowerCase());

                            // Only parse structured tables like Requested Actions.
                            if (headerCells.length < 5) {
                                continue;
                            }

                            const hasActionName = headerCells.some(h => h === 'action name');
                            const hasBuildPhase = headerCells.some(h => h === 'build phase');
                            if (!hasActionName || !hasBuildPhase) {
                                continue;
                            }

                            let reasonIdx = headerCells.findIndex(h => h === 'reason for change');
                            if (reasonIdx === -1) {
                                reasonIdx = headerCells.findIndex(h => h.includes('reason for change') && !h.includes('late'));
                            }

                            if (reasonIdx === -1) {
                                continue;
                            }

                            for (const tr of table.querySelectorAll('tr')) {
                                const tds = [...tr.querySelectorAll('td')];
                                if (!tds.length || reasonIdx >= tds.length) {
                                    continue;
                                }
                                const value = clean(tds[reasonIdx].innerText);
                                if (value) {
                                    unique.add(value);
                                }
                            }
                        }

                        return [...unique];
                    }
                    """
                )
                if reasons and len(reasons) > len(best_reasons):
                    best_reasons = reasons
            except Exception:
                continue

        return " | ".join(best_reasons)
    
    async def _download_attachments(self, save_folder, dtcr_number):
        """
        Find and download all attachments on current page
        
        Args:
            save_folder (Path): Folder to save files to
            
        Returns:
            int: Number of files downloaded
        """
        logger.info("Looking for attachments section...")
        
        try:
            # Wait for page
            await asyncio.sleep(1)

            # Search in main frame and child frames for the real Attachments table.
            frame_targets = [self.page.main_frame] + [f for f in self.page.frames if f != self.page.main_frame]
            attachment_rows = []

            for frame in frame_targets:
                tables = frame.locator("table")
                table_count = await tables.count()
                for t in range(table_count):
                    table = tables.nth(t)
                    header_text = (await table.inner_text()).lower()
                    if "file name" not in header_text or "download" not in header_text:
                        continue

                    rows = table.locator("tr")
                    row_count = await rows.count()
                    for r in range(row_count):
                        row = rows.nth(r)
                        link = row.locator("a:has-text('Download')").first
                        if await link.count() == 0:
                            continue

                        first_cell = row.locator("td").first
                        raw_name = (await first_cell.inner_text()).strip() if await first_cell.count() > 0 else ""
                        if not raw_name:
                            continue

                        normalized = raw_name.lower()
                        # Guardrail: skip non-file pseudo rows accidentally matched in other tables.
                        bad_tokens = ["enter dtcr", "create dtcr", "delegate dtcr", "attachments", "file name", "download"]
                        if any(token in normalized for token in bad_tokens):
                            # Keep valid file names that include extension.
                            if not re.search(r"\.[a-z0-9]{2,5}$", normalized):
                                continue

                        attachment_rows.append((frame, link, raw_name))

            if not attachment_rows:
                logger.warning("Attachments section/download rows not found")
                return 0

            logger.info(f"Found {len(attachment_rows)} attachment rows")

            downloaded_count = 0
            seen_names = set()
            for i, (frame, link, raw_name) in enumerate(attachment_rows, start=1):
                try:
                    logger.info(f"  Downloading attachment {i}/{len(attachment_rows)}")
                    async with self.page.expect_download(timeout=20000) as dl_info:
                        await link.click()
                    download = await dl_info.value

                    suggested = download.suggested_filename or f"attachment_{i}"
                    original_name = re.sub(r'[<>:"/\\|?*]', '_', raw_name)
                    filename = f"{dtcr_number} - {original_name}"
                    if not re.search(r"\.[a-z0-9]{2,5}$", filename.lower()) and "." in suggested:
                        filename = f"{filename}{Path(suggested).suffix}"

                    # Avoid duplicate writes of same filename in same DTCR folder.
                    if filename in seen_names:
                        continue
                    seen_names.add(filename)

                    file_path = save_folder / filename
                    await download.save_as(str(file_path))
                    logger.info(f"    ✓ Saved: {file_path}")
                    downloaded_count += 1
                except Exception as e:
                    logger.warning(f"    ✗ Download failed for attachment {i}: {e}")
            
            return downloaded_count
            
        except Exception as e:
            logger.error(f"✗ Error downloading attachments: {e}")
            return 0
    
    async def process_current_results(self):
        """
        Process all DTCR rows visible on the current page.
        Expects caller to already be on the loaded search results page.

        Returns:
            dict: Summary of processed DTCRs
        """
        try:
            dtcr_rows = await self.get_dtcr_rows()
            if not dtcr_rows:
                return {"success": False, "error": "No DTCRs found"}

            results = {
                "success": True,
                "total_dtcrs": len(dtcr_rows),
                "processed": 0,
                "failed": 0,
                "dtcrs": {}
            }

            # Process by DTCR number and re-locate each row each time.
            for dtcr_data in dtcr_rows:
                if self.page is None or self.page.is_closed():
                    logger.warning("Page closed during processing; stopping remaining DTCR iterations")
                    break

                dtcr_num = dtcr_data.get("dtcr_number")

                already_downloaded = self._dtcr_already_downloaded(dtcr_num)
                result_data = await self.download_dtcr_attachments(
                    dtcr_data,
                    skip_download=already_downloaded,
                )
                success = result_data.get("success", False)

                results["dtcrs"][dtcr_num] = {
                    "success": success,
                    "folder": str(self.attachments_dir),
                    "reason_for_change": result_data.get("reason_for_change", ""),
                    "files_downloaded": result_data.get("files_downloaded", 0)
                }

                if success:
                    results["processed"] += 1
                else:
                    results["failed"] += 1

            return results
        except Exception as e:
            logger.error(f"✗ Fatal error while processing current results: {e}")
            return {"success": False, "error": str(e)}

    def export_reason_for_change_excel(self, results, file_name="dtcr_reason_for_change.xlsx"):
        """Create Excel file with columns: DTCR# and Reason for Change."""
        output_path = self.download_dir / file_name
        wb = Workbook()
        ws = wb.active
        ws.title = "DTCR Reasons"
        ws.append(["DTCR#", "Reason for Change"])

        dtcr_items = results.get("dtcrs", {})
        sorted_items = sorted(dtcr_items.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else str(x[0]))
        for dtcr_num, info in sorted_items:
            ws.append([str(dtcr_num), info.get("reason_for_change", "")])

        wb.save(output_path)
        return str(output_path.resolve())

    async def process_all_dtcrs(self, search_params, headless=False):
        """
        Main method: search, get DTCR list, download all attachments
        
        Args:
            search_params (dict): Search parameters
            headless (bool): Run browser in headless mode
            
        Returns:
            dict: Summary of processed DTCRs
        """
        try:
            # Initialize browser
            await self.init_browser(headless=headless)
            
            # Search for DTCRs
            if not await self.search_dtcrs(search_params):
                return {"success": False, "error": "Search failed"}
            
            # Get DTCR rows
            dtcr_rows = await self.get_dtcr_rows()
            
            if not dtcr_rows:
                return {"success": False, "error": "No DTCRs found"}
            
            # Process current loaded results.
            results = await self.process_current_results()
            
            await self.close_browser()
            
            return results
            
        except Exception as e:
            logger.error(f"✗ Fatal error: {e}")
            await self.close_browser()
            return {"success": False, "error": str(e)}
