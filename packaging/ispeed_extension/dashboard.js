const { cleanAttachmentName, makeSummaryCsv, normalizeSpace, parseDownloadedName,
        shouldDownloadStatus, statusCode } = ISpeedHelpers;

const params = new URLSearchParams(location.search);
const sourceTabId = Number(params.get("sourceTabId"));
const initialError = params.get("error");
const DETAIL_READY_TIMEOUT_MS = 5 * 60_000;
const RESULTS_READY_TIMEOUT_MS = 5 * 60_000;
const RETURN_RETRY_AFTER_MS = 45_000;
const SLOW_NOTICE_AFTER_MS = 8_000;
const PAGE_POLL_MS = 1_000;
const SUMMARY_FILE_NAME = "DTCR_Summary.csv";

const ui = {
  sourceStatus: document.querySelector("#source-status"),
  folderStatus: document.querySelector("#folder-status"),
  runSummary: document.querySelector("#run-summary"),
  rescan: document.querySelector("#rescan-button"),
  chooseFolder: document.querySelector("#folder-button"),
  start: document.querySelector("#start-button"),
  stop: document.querySelector("#stop-button"),
  clearLog: document.querySelector("#clear-log-button"),
  includeInactive: document.querySelector("#include-inactive"),
  log: document.querySelector("#activity-log"),
  progressTrack: document.querySelector(".progress-track"),
  progressBar: document.querySelector("#progress-bar"),
  total: document.querySelector("#stat-total"),
  complete: document.querySelector("#stat-complete"),
  files: document.querySelector("#stat-files"),
  errors: document.querySelector("#stat-errors")
};

let directoryHandle = null;
let source = null;
let stopRequested = false;
let running = false;
let stats = { total: 0, complete: 0, files: 0, errors: 0 };

ui.rescan.addEventListener("click", scanSource);
ui.chooseFolder.addEventListener("click", chooseDirectory);
ui.start.addEventListener("click", runAutomation);
ui.stop.addEventListener("click", () => {
  stopRequested = true;
  ui.runSummary.textContent = "Stopping after the current DTCR…";
  addLog("Stop requested; finishing the current DTCR.");
});
if (ui.includeInactive) {
  chrome.storage?.local?.get?.(["includeInactive"]).then((saved) => {
    ui.includeInactive.checked = Boolean(saved?.includeInactive);
    scanSource();
  }).catch(() => {});
  ui.includeInactive.addEventListener("change", () => {
    chrome.storage?.local?.set?.({ includeInactive: ui.includeInactive.checked });
    scanSource();
  });
}

ui.clearLog.addEventListener("click", () => { ui.log.replaceChildren(); });

if (initialError) {
  ui.sourceStatus.textContent = initialError;
  addLog(initialError, "error");
} else if (!Number.isInteger(sourceTabId)) {
  ui.sourceStatus.textContent = "Open the extension from the iSpeed results tab.";
} else {
  scanSource();
}

async function scanSource() {
  if (!Number.isInteger(sourceTabId) || running) return;
  ui.sourceStatus.textContent = "Reading the current iSpeed search results…";
  ui.rescan.disabled = true;

  try {
    const tab = await chrome.tabs.get(sourceTabId);
    if (!tab.url?.startsWith("https://ispeed.extra.chrysler.com/")) {
      throw new Error("The source tab is no longer on iSpeed.");
    }

    const frames = await chrome.scripting.executeScript({
      target: { tabId: sourceTabId, allFrames: true },
      func: scanResultsFrame
    });
    const match = frames.find((entry) => entry.result?.found);
    if (!match) throw new Error("No iSpeed results table found. Select a Vehicle Program and Build Phase, then run Search.");

    const includeInactive = Boolean(ui.includeInactive?.checked);
    const allRows = match.result.rows.map((row) => ({
      ...row,
      code: statusCode(row.status, row.statusId)
    }));
    const eligible = allRows.filter((row) => shouldDownloadStatus(row.code, includeInactive));
    const skipped = allRows.length - eligible.length;
    source = {
      frameId: match.frameId,
      frameUrl: match.result.frameUrl,
      program: match.result.program,
      phase: match.result.phase,
      rows: eligible
    };

    stats = { total: eligible.length, complete: 0, files: 0, errors: 0 };
    updateStats();
    ui.sourceStatus.textContent = `${source.program || "Selected program"} · ${source.phase || "Selected phase"} · ${eligible.length} eligible DTCRs`;
    const byCode = eligible.reduce((tally, row) => {
      const key = row.code || "??";
      tally[key] = (tally[key] || 0) + 1;
      return tally;
    }, {});
    const breakdown = Object.entries(byCode).sort().map(([code, n]) => `${n} ${code}`).join(" \u00b7 ");
    ui.runSummary.textContent = skipped
      ? `${breakdown}. ${skipped} rejected/deleted DTCR${skipped === 1 ? "" : "s"} skipped \u2014 tick the box above to include them.`
      : breakdown || "Nothing to download.";
    addLog(`Found ${eligible.length} eligible DTCRs${skipped ? `; skipping ${skipped}` : ""}.`, "success");
  } catch (error) {
    source = null;
    ui.sourceStatus.textContent = error.message;
    addLog(error.message, "error");
  } finally {
    ui.rescan.disabled = false;
    updateStartState();
  }
}

async function chooseDirectory() {
  try {
    if (!("showDirectoryPicker" in window)) {
      throw new Error("This Chrome version does not provide folder access to extensions.");
    }
    directoryHandle = await window.showDirectoryPicker({ mode: "readwrite" });
    const permission = await directoryHandle.requestPermission({ mode: "readwrite" });
    if (permission !== "granted") throw new Error("Write access to the selected folder was not granted.");
    ui.folderStatus.textContent = directoryHandle.name;
    addLog(`Destination selected: ${directoryHandle.name}`, "success");
  } catch (error) {
    if (error.name !== "AbortError") {
      ui.folderStatus.textContent = error.message;
      addLog(error.message, "error");
    }
  } finally {
    updateStartState();
  }
}

async function runAutomation() {
  if (!source || !directoryHandle || running) return;

  running = true;
  stopRequested = false;
  const records = [];
  let rowsToProcess = source.rows;

  try {
    // A DTCR is downloaded when the folder holds nothing for it, OR when its
    // status has moved since it was last pulled (DA -> AP -> CO). The status
    // lives in the file name, so the folder itself is the record.
    const downloaded = await collectExistingDownloads();
    const fresh = [];
    let already = 0;
    let restatus = 0;
    for (const row of source.rows) {
      const codes = downloaded.get(normalizeDtcrId(row.dtcr));
      if (!codes) {
        fresh.push(row);
        continue;
      }
      if (row.code && !codes.has(row.code)) {
        const was = [...codes].filter(Boolean).sort().join("/") || "no status";
        fresh.push({ ...row, previousCodes: was });
        restatus += 1;
        addLog(`DTCR ${row.dtcr}: status moved ${was} \u2192 ${row.code}; downloading again.`);
        continue;
      }
      already += 1;
      records.push({ dtcr: row.dtcr, status: row.status, code: row.code, reasons: [],
                     approvers: [], files: [], result: "Skipped: already in folder" });
    }
    rowsToProcess = fresh;
    if (already) {
      addLog(`Skipping ${already} DTCR${already === 1 ? "" : "s"} already in the folder at the same status.`);
    }
    if (restatus) {
      addLog(`${restatus} DTCR${restatus === 1 ? "" : "s"} changed status since the last run.`, "success");
    }
  } catch (error) {
    addLog(`Could not scan existing DTCR files in folder: ${error.message}`, "error");
  }

  stats = { total: rowsToProcess.length, complete: 0, files: 0, errors: 0 };
  updateStats();
  setRunningState(true);

  addLog(`Starting ${source.program} / ${source.phase}.`);
  try {
    for (const row of rowsToProcess) {
      if (stopRequested) break;
      ui.runSummary.textContent = `Opening DTCR ${row.dtcr}…`;

      try {
        await ensureResultsFrame(source.frameId);
        const opened = await clickRowAndOpen(source.frameId, row.dtcr);
        if (!opened) throw new Error("Could not select the row or find Open/Modify.");

        await waitForPageReady(source.frameId, "detail", DETAIL_READY_TIMEOUT_MS, row.dtcr);
        const detail = await extractDetail(source.frameId);
        if (!detail) throw new Error("The detail page did not expose the expected fields.");

        // the detail page is authoritative: a status may move between the
        // search running and the DTCR being opened
        const code = statusCode(detail.status, "") || row.code;
        const includeInactive = Boolean(ui.includeInactive?.checked);
        if (!shouldDownloadStatus(code, includeInactive)) {
          records.push({ ...detail, code, files: [], result: `Skipped: ${detail.status || code}` });
          addLog(`DTCR ${row.dtcr}: skipped (${detail.status || code}).`);
        } else {
          const files = [];
          for (const attachment of detail.attachments) {
            if (stopRequested) break;
            const finalName = await downloadAttachment(
              attachment.url, cleanAttachmentName(attachment.name, detail.dtcr, code));
            files.push(finalName);
            stats.files += 1;
            updateStats();
          }
          records.push({ ...detail, code, files,
                         result: files.length
                           ? (row.previousCodes ? `Re-downloaded (${row.previousCodes} \u2192 ${code})` : "Downloaded")
                           : "No attachments" });
          addLog(`DTCR ${row.dtcr} [${code}]: ${files.length} attachment${files.length === 1 ? "" : "s"}`
                 + `${detail.approvers?.length ? `, ${detail.approvers.length} approver(s)` : ""}.`, "success");
        }
      } catch (error) {
        stats.errors += 1;
        records.push({ dtcr: row.dtcr, status: row.status, code: row.code, reasons: [],
                       approvers: [], files: [], result: `Error: ${error.message}` });
        addLog(`DTCR ${row.dtcr}: ${error.message}`, "error");
      } finally {
        stats.complete += 1;
        updateStats();
        ui.runSummary.textContent = `Returning from DTCR ${row.dtcr}; waiting for the results table…`;
        await returnToResults(source.frameId);
      }
    }

    await writeTextFile(SUMMARY_FILE_NAME, makeSummaryCsv(records), "text/csv");
    ui.runSummary.textContent = stopRequested
      ? `Stopped after ${stats.complete} DTCRs. Partial summary saved.`
      : `Finished ${stats.complete} DTCRs and downloaded ${stats.files} files.`;
    addLog(`${SUMMARY_FILE_NAME} saved.`, "success");
  } catch (error) {
    stats.errors += 1;
    updateStats();
    ui.runSummary.textContent = error.message;
    addLog(error.message, "error");
  } finally {
    running = false;
    setRunningState(false);
  }
}

async function ensureResultsFrame(frameId) {
  const state = await readPageState(frameId);
  if (!state.resultsReady) {
    await returnToResults(frameId);
    await waitForPageReady(frameId, "results", RESULTS_READY_TIMEOUT_MS);
  }
}

async function clickRowAndOpen(frameId, dtcr) {
  const results = await chrome.scripting.executeScript({
    target: { tabId: sourceTabId, frameIds: [frameId] },
    world: "MAIN",
    args: [String(dtcr)],
    func: (targetDtcr) => {
      const radio = Array.from(document.querySelectorAll('#resultsTable input[name="selectedDTCRID"]'))
        .find((input) => String(input.value).trim() === targetDtcr);
      if (!radio) return false;

      radio.click();
      if (!radio.checked) {
        radio.checked = true;
        radio.dispatchEvent(new Event("input", { bubbles: true }));
        radio.dispatchEvent(new Event("change", { bubbles: true }));
      }

      const openButton = Array.from(document.querySelectorAll("button"))
        .find((button) => /open\/modify/i.test(button.textContent || "") || /doOpenDTCR/.test(button.getAttribute("onclick") || ""));
      if (!openButton || !radio.checked) return false;
      openButton.click();
      return true;
    }
  });
  return Boolean(results[0]?.result);
}

async function extractDetail(frameId) {
  const results = await chrome.scripting.executeScript({
    target: { tabId: sourceTabId, frameIds: [frameId] },
    func: extractDetailFrame
  });
  return results[0]?.result || null;
}

async function returnToResults(frameId) {
  let state = await readPageState(frameId);
  if (state.resultsReady) return;

  if (state.detailReady) {
    const clicked = await clickBackToResults(frameId);
    if (!clicked) throw new Error("Could not find the Go back to Search Results button.");
  }

  try {
    await waitForPageReady(frameId, "results", RETURN_RETRY_AFTER_MS, "", false);
    return;
  } catch {
    state = await readPageState(frameId);
    if (state.detailReady) {
      addLog("iSpeed is still on the detail page; retrying Go back to Search Results once.");
      const clickedAgain = await clickBackToResults(frameId);
      if (!clickedAgain) throw new Error("Could not retry Go back to Search Results.");
    }
  }

  await waitForPageReady(frameId, "results", RESULTS_READY_TIMEOUT_MS);
}

async function clickBackToResults(frameId) {
  const clicked = await chrome.scripting.executeScript({
    target: { tabId: sourceTabId, frameIds: [frameId] },
    world: "MAIN",
    func: () => {
      const backButton = Array.from(document.querySelectorAll("button"))
        .find((button) => /go back to search results/i.test(button.textContent || "") ||
          /goBackToDTCRSearchResults/.test(button.getAttribute("onclick") || ""));
      if (!backButton) return false;
      backButton.click();
      return true;
    }
  }).catch(() => []);
  return Boolean(clicked[0]?.result);
}

async function readPageState(frameId, expectedDtcr = "") {
  const result = await chrome.scripting.executeScript({
    target: { tabId: sourceTabId, frameIds: [frameId] },
    args: [String(expectedDtcr)],
    func: (targetDtcr) => {
      const resultsTable = document.querySelector("#resultsTable");
      const rows = resultsTable?.querySelectorAll('tbody input[name="selectedDTCRID"]') || [];
      const detailId = Array.from(document.querySelectorAll('input[name="dtcrID"]'))
        .map((input) => String(input.value || "").trim())
        .find(Boolean) || "";
      const backButton = Array.from(document.querySelectorAll("button"))
        .find((button) => /go back to search results/i.test(button.textContent || "") ||
          /goBackToDTCRSearchResults/.test(button.getAttribute("onclick") || ""));

      return {
        readyState: document.readyState,
        resultsReady: document.readyState !== "loading" && Boolean(resultsTable) && rows.length > 0,
        detailReady: document.readyState !== "loading" && Boolean(backButton) && Boolean(detailId) &&
          (!targetDtcr || detailId === targetDtcr),
        detailId,
        rowCount: rows.length,
        url: location.href
      };
    }
  }).catch(() => []);
  return result[0]?.result || { resultsReady: false, detailReady: false, loading: true };
}

async function waitForPageReady(frameId, mode, timeoutMs, expectedDtcr = "", showSlowNotice = true) {
  const start = Date.now();
  let slowNoticeShown = false;
  while (Date.now() - start < timeoutMs) {
    const state = await readPageState(frameId, expectedDtcr);
    const ready = mode === "detail" ? state.detailReady : state.resultsReady;
    if (ready) return state;

    if (showSlowNotice && !slowNoticeShown && Date.now() - start >= SLOW_NOTICE_AFTER_MS) {
      slowNoticeShown = true;
      const destination = mode === "detail" ? `DTCR ${expectedDtcr}` : "the search results";
      ui.runSummary.textContent = `iSpeed is still loading ${destination}. Waiting…`;
      addLog(`iSpeed is still loading ${destination}; the extension will keep waiting.`);
    }
    await delay(PAGE_POLL_MS);
  }
  const destination = mode === "detail" ? `DTCR ${expectedDtcr}` : "the search results";
  throw new Error(`iSpeed did not finish loading ${destination} within ${Math.round(timeoutMs / 60_000)} minutes.`);
}

async function downloadAttachment(url, requestedName) {
  const response = await fetch(url, { credentials: "include", cache: "no-store" });
  if (!response.ok) throw new Error(`Attachment request failed (${response.status}).`);

  const contentType = response.headers.get("content-type") || "application/octet-stream";
  if (/text\/html/i.test(contentType)) throw new Error("iSpeed returned an HTML page instead of the attachment; sign in again.");

  const finalName = await uniqueFileName(requestedName);
  const handle = await directoryHandle.getFileHandle(finalName, { create: true });
  const writable = await handle.createWritable();
  try {
    await response.body.pipeTo(writable);
  } catch (error) {
    await writable.abort().catch(() => {});
    throw error;
  }
  return finalName;
}

async function uniqueFileName(name) {
  const dot = name.lastIndexOf(".");
  const base = dot > 0 ? name.slice(0, dot) : name;
  const extension = dot > 0 ? name.slice(dot) : "";
  let candidate = name;
  let number = 2;
  while (await fileExists(candidate)) {
    candidate = `${base} (${number})${extension}`;
    number += 1;
  }
  return candidate;
}

async function fileExists(name) {
  try {
    await directoryHandle.getFileHandle(name);
    return true;
  } catch (error) {
    if (error.name === "NotFoundError") return false;
    throw error;
  }
}

function normalizeDtcrId(value) {
  return String(value ?? "").trim();
}

function splitCsvLine(line) {
  const cells = [];
  let inQuotes = false;
  let value = "";
  const text = String(line ?? "");
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (char === '"') {
      if (inQuotes && text[index + 1] === '"') {
        value += '"';
        index += 1;
      } else {
        inQuotes = !inQuotes;
      }
      continue;
    }
    if (char === "," && !inQuotes) {
      cells.push(value);
      value = "";
      continue;
    }
    value += char;
  }
  cells.push(value);
  return cells;
}

/** [dtcr, code] pairs from a previous run's summary. The Code column was added
 *  later, so an older summary still yields its DTCRs with an empty code. */
function extractDtcrsFromSummaryCsv(text) {
  const values = [];
  const lines = String(text ?? "").split(/\r?\n/);
  const header = splitCsvLine(lines[0] || "").map((cell) => cell.trim().toLowerCase());
  const codeIndex = header.indexOf("code");
  for (let rowIndex = 1; rowIndex < lines.length; rowIndex += 1) {
    const line = lines[rowIndex];
    if (!line.trim()) continue;
    const cells = splitCsvLine(line);
    const dtcr = normalizeDtcrId(cells[0] || "");
    if (!dtcr) continue;
    values.push([dtcr, codeIndex >= 0 ? normalizeSpace(cells[codeIndex] || "") : ""]);
  }
  return values;
}

/** DTCR number -> the set of status codes already downloaded for it.
 *  Files written before status prefixes existed contribute an empty code, so
 *  they still count as present and any known status reads as a change. */
async function collectExistingDownloads() {
  const downloaded = new Map();
  const remember = (dtcr, code) => {
    if (!dtcr) return;
    if (!downloaded.has(dtcr)) downloaded.set(dtcr, new Set());
    downloaded.get(dtcr).add(code || "");
  };

  for await (const [name, handle] of directoryHandle.entries()) {
    if (handle.kind !== "file") continue;

    const parsed = parseDownloadedName(name);
    if (parsed.dtcr) {
      remember(parsed.dtcr, parsed.code);
      continue;
    }

    if (name.toLowerCase() === SUMMARY_FILE_NAME.toLowerCase()) {
      const file = await handle.getFile();
      const summaryText = await file.text();
      for (const [dtcr, code] of extractDtcrsFromSummaryCsv(summaryText)) {
        remember(dtcr, code);
      }
    }
  }

  return downloaded;
}

async function writeTextFile(name, contents, type) {
  const handle = await directoryHandle.getFileHandle(name, { create: true });
  const writable = await handle.createWritable();
  await writable.write(new Blob([contents], { type }));
  await writable.close();
}

function scanResultsFrame() {
  const table = document.querySelector("#resultsTable");
  if (!table) return { found: false };

  const headers = Array.from(table.querySelectorAll("thead th")).map((cell) => (cell.textContent || "").replace(/\s+/g, " ").trim().toLowerCase());
  const statusIndex = headers.findIndex((header) => header === "status");
  const rows = Array.from(table.querySelectorAll("tbody tr")).map((tr) => {
    const radio = tr.querySelector('input[name="selectedDTCRID"]');
    const cells = Array.from(tr.cells);
    return radio ? {
      dtcr: String(radio.value || cells[1]?.textContent || "").trim(),
      status: String(cells[statusIndex]?.textContent || "").replace(/\s+/g, " ").trim(),
      // iSpeed's own numeric status id; steadier than the display text
      statusId: String(radio.getAttribute("status-id") || "").trim()
    } : null;
  }).filter(Boolean);

  return {
    found: true,
    frameUrl: location.href,
    program: document.querySelector("#programID")?.selectedOptions?.[0]?.textContent?.trim() || "",
    phase: document.querySelector("#phaseNameID")?.selectedOptions?.[0]?.textContent?.trim() || "",
    rows
  };
}

function extractDetailFrame() {
  const text = (value) => String(value ?? "").replace(/\s+/g, " ").trim();
  const dtcr = text(document.querySelector('input[name="dtcrID"]')?.value) ||
    text(Array.from(document.querySelectorAll("*"))
      .find((element) => /^DTCR#:/i.test(text(element.childNodes?.[0]?.textContent)))?.textContent)
      .match(/DTCR#:\s*(\d+)/i)?.[1] || "";

  const bodyText = text(document.body.innerText);
  const status = bodyText.match(/Status:\s*([^\s]+(?:\s+[^\s]+)?)(?=\s+DTCR#:)/i)?.[1] || "";

  // The detail page nests every section inside one page-layout <table>, so a
  // header match that would accept a first row swallows the whole page. Only
  // the real section tables carry a <thead>; pickTablesByHeader requires one.
  const labelsOf = (table) => {
    const row = table.tHead?.rows?.[0];
    return row ? Array.from(row.cells).map((cell) => text(cell.textContent).toUpperCase()) : null;
  };
  const pickTables = (...required) => Array.from(document.querySelectorAll("table")).filter((table) => {
    const labels = labelsOf(table);
    return !!labels && required.every((label) => labels.includes(label));
  });

  const reasons = [];
  const actionTables = pickTables("REASON FOR CHANGE", "VEHICLE PROGRAM");

  for (const actionTable of actionTables) {
    const reasonIndex = labelsOf(actionTable).indexOf("REASON FOR CHANGE");
    const dataRows = Array.from(actionTable.tBodies).flatMap((body) => Array.from(body.rows));
    for (const row of dataRows) {
      const reason = text(row.cells[reasonIndex]?.textContent);
      if (reason && !reasons.includes(reason)) reasons.push(reason);
    }
  }

  // Approvals: APPROVER | NAME | STATUS | COMMENT | DATE. The table carries no
  // id or class, so it is found by its own header row.
  const approvers = [];
  const approvalTables = pickTables("APPROVER", "STATUS");

  for (const approvalTable of approvalTables) {
    const headers = labelsOf(approvalTable);
    const columnOf = (label) => headers.indexOf(label);
    const dataRows = Array.from(approvalTable.tBodies).flatMap((body) => Array.from(body.rows));
    for (const row of dataRows) {
      const cellAt = (label) => {
        const index = columnOf(label);
        return index >= 0 ? text(row.cells[index]?.textContent) : "";
      };
      const entry = {
        role: cellAt("APPROVER"),
        name: cellAt("NAME"),
        status: cellAt("STATUS"),
        date: cellAt("DATE"),
        comment: cellAt("COMMENT")
      };
      if (entry.role || entry.name || entry.status || entry.date) approvers.push(entry);
    }
  }

  const attachments = Array.from(document.querySelectorAll('a[href*="downloadAttachment.action"]')).map((link) => {
    const row = link.closest("tr");
    const name = text(row?.cells?.[0]?.textContent) || `attachment-${new URL(link.href).searchParams.get("attachmentID") || "file"}`;
    return { name, url: link.href };
  });

  return { dtcr, status: text(status), reasons, approvers, attachments };
}

function setRunningState(value) {
  ui.start.disabled = value || !source || !directoryHandle;
  ui.stop.disabled = !value;
  ui.rescan.disabled = value;
  ui.chooseFolder.disabled = value;
}

function updateStartState() {
  ui.start.disabled = running || !source || !directoryHandle;
}

function updateStats() {
  ui.total.textContent = stats.total;
  ui.complete.textContent = stats.complete;
  ui.files.textContent = stats.files;
  ui.errors.textContent = stats.errors;
  const percent = stats.total ? Math.round((stats.complete / stats.total) * 100) : 0;
  ui.progressBar.style.width = `${percent}%`;
  ui.progressTrack.setAttribute("aria-valuenow", String(percent));
}

function addLog(message, kind = "") {
  const item = document.createElement("li");
  const time = document.createElement("time");
  const text = document.createElement("span");
  time.textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  text.textContent = normalizeSpace(message);
  if (kind) text.className = kind;
  item.append(time, text);
  ui.log.append(item);
  item.scrollIntoView({ block: "nearest" });
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
