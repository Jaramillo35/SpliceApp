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

  function cleanAttachmentName(rawName, dtcr) {
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
    return `${normalizeSpace(dtcr)} - ${name}`;
  }

  function csvEscape(value) {
    const text = String(value ?? "");
    return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  }

  function makeSummaryCsv(records) {
    const rows = [["DTCR #", "Status", "Reason for Change", "Attachments", "Result"]];
    for (const record of records) {
      rows.push([
        record.dtcr,
        record.status,
        (record.reasons || []).join(" | "),
        (record.files || []).join(" | "),
        record.result || ""
      ]);
    }
    return `${rows.map((row) => row.map(csvEscape).join(",")).join("\r\n")}\r\n`;
  }

  function isExcludedStatus(status) {
    return /\b(?:deleted|cancelled|canceled|rejected)\b/i.test(normalizeSpace(status));
  }

  const api = { cleanAttachmentName, csvEscape, isExcludedStatus, makeSummaryCsv, normalizeSpace };
  root.ISpeedHelpers = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
