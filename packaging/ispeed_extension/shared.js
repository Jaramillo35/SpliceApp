(function exposeHelpers(root) {
  const KNOWN_EXTENSIONS = [
    "7z", "bmp", "csv", "doc", "docm", "docx", "dwg", "dxf", "eml", "gif",
    "htm", "html", "jpeg", "jpg", "json", "msg", "pdf", "png", "ppt", "pptm",
    "pptx", "rar", "rtf", "tif", "tiff", "txt", "xls", "xlsb", "xlsm", "xlsx",
    "xml", "zip"
  ];

  function normalizeSpace(value) {
    return String(value ?? "").replace(/\s+/g, " ").trim();
  }

  // iSpeed's own status vocabulary, taken from the Status filter on the search
  // page (statusID options). The numeric id is what the results table carries
  // on each row, and it is immune to wording changes, so it is preferred; the
  // display text is the fallback for pages that omit the attribute.
  const STATUS_ID_CODES = {
    "10": "DA",   // Draft
    "11": "AP",   // Approved
    "12": "RE",   // Rejected
    "13": "CO",   // Complete
    "14": "DE"    // Deleted
  };

  const STATUS_TEXT_CODES = {
    draft: "DA",
    approved: "AP",
    approve: "AP",
    rejected: "RE",
    reject: "RE",
    complete: "CO",
    completed: "CO",
    deleted: "DE",
    delete: "DE",
    // iSpeed does not currently expose a Cancel status; kept so a programme
    // that does still yields a sensible prefix instead of an empty one.
    cancel: "CA",
    canceled: "CA",
    cancelled: "CA"
  };

  //: codes whose DTCRs are not downloaded unless the SE opts in
  const INACTIVE_CODES = ["RE", "DE", "CA"];

  function statusCode(status, statusId) {
    const byId = STATUS_ID_CODES[normalizeSpace(statusId)];
    if (byId) return byId;
    return STATUS_TEXT_CODES[normalizeSpace(status).toLowerCase()] || "";
  }

  function isInactiveCode(code) {
    return INACTIVE_CODES.includes(String(code || "").toUpperCase());
  }

  function shouldDownloadStatus(code, includeInactive) {
    return includeInactive ? true : !isInactiveCode(code);
  }

  /** Split a downloaded file name back into its status code and DTCR number.
   *  Understands both the current "AP 51163 - file.pdf" form and files left by
   *  earlier versions ("51163 - file.pdf"), so an existing folder keeps working. */
  function parseDownloadedName(name) {
    const text = String(name ?? "");
    const withCode = text.match(/^\s*([A-Za-z]{2})\s+(\d+)\s*-\s*/);
    if (withCode) return { code: withCode[1].toUpperCase(), dtcr: normalizeSpace(withCode[2]) };
    const legacy = text.match(/^\s*(\d+)\s*-\s*/);
    if (legacy) return { code: "", dtcr: normalizeSpace(legacy[1]) };
    return { code: "", dtcr: "" };
  }

  function cleanAttachmentName(rawName, dtcr, code) {
    let name = normalizeSpace(rawName)
      .replace(/^.*[\\/]/, "")
      .normalize("NFKC");

    const extensionPattern = KNOWN_EXTENSIONS.join("|");
    const recognized = name.match(new RegExp(`^(.+?\\.(?:${extensionPattern}))(?=$|[^a-z0-9].*)`, "i"));
    if (recognized) name = recognized[1];

    name = name
      .replace(/[<>:"/\\|?*\u0000-\u001F]/g, "_")
      .replace(/\s+([.])/g, "$1")
      .replace(/[. ]+$/g, "")
      .trim();

    if (!name) name = "attachment";
    const statusPrefix = normalizeSpace(code).toUpperCase();
    const head = statusPrefix
      ? `${statusPrefix} ${normalizeSpace(dtcr)}`
      : normalizeSpace(dtcr);
    return `${head} - ${name}`;
  }

  function csvEscape(value) {
    const text = String(value ?? "");
    return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  }

  function formatApprovers(approvers) {
    return (approvers || [])
      .map((a) => [a.role, a.name, a.status, a.date,
                   a.comment ? `(${a.comment})` : ""]
        .map((part) => normalizeSpace(part))
        .filter(Boolean)
        .join(" / "))
      .filter(Boolean)
      .join(" | ");
  }

  function makeSummaryCsv(records) {
    const rows = [["DTCR #", "Status", "Code", "Reason for Change", "Approvers",
                   "Attachments", "Result"]];
    for (const record of records) {
      rows.push([
        record.dtcr,
        record.status,
        record.code || "",
        (record.reasons || []).join(" | "),
        formatApprovers(record.approvers),
        (record.files || []).join(" | "),
        record.result || ""
      ]);
    }
    return `${rows.map((row) => row.map(csvEscape).join(",")).join("\r\n")}\r\n`;
  }

  // iSpeed's DTCR detail page is a frameset whose content frame nests every
  // section inside one page-layout <table>. Reading that outer table's first
  // row gives you the text of all 13 inner tables at once, so a header match
  // that accepts a first row would swallow the whole page as if it were the
  // approvals table. The real section tables carry a proper <thead>; the
  // layout table does not. That is the whole guard.
  // Verified against a live Complete DTCR, 2026-09-01: one strict match, and
  // the single loose match was an ancestor of it holding 13 nested tables.
  function headerLabelsOf(table) {
    const row = table && table.tHead && table.tHead.rows && table.tHead.rows[0];
    if (!row) return null;
    return Array.from(row.cells || [])
      .map((cell) => normalizeSpace(cell.textContent).toUpperCase());
  }

  function pickTablesByHeader(tables, ...required) {
    const wanted = required.map((label) => label.toUpperCase());
    return Array.from(tables || []).filter((table) => {
      const labels = headerLabelsOf(table);
      return !!labels && wanted.every((label) => labels.includes(label));
    });
  }

  function isExcludedStatus(status) {
    return /\b(?:deleted|cancelled|canceled|rejected)\b/i.test(normalizeSpace(status));
  }

  const api = {
    INACTIVE_CODES, STATUS_ID_CODES, STATUS_TEXT_CODES,
    cleanAttachmentName, csvEscape, formatApprovers, headerLabelsOf,
    isExcludedStatus, isInactiveCode, makeSummaryCsv, normalizeSpace,
    parseDownloadedName, pickTablesByHeader, shouldDownloadStatus, statusCode
  };
  root.ISpeedHelpers = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
