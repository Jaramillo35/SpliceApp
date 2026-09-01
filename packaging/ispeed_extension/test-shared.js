const assert = require("node:assert/strict");
const {
  cleanAttachmentName, formatApprovers, headerLabelsOf, isExcludedStatus,
  isInactiveCode, makeSummaryCsv, parseDownloadedName, pickTablesByHeader,
  shouldDownloadStatus, statusCode
} = require("./shared.js");

// --- names keep working exactly as before when no status code is supplied ---
assert.equal(cleanAttachmentName("2028_RU_UPDATE .xls***", "49951"), "49951 - 2028_RU_UPDATE.xls");
assert.equal(cleanAttachmentName("bad<>name?.pdf]", "42"), "42 - bad__name_.pdf");
assert.equal(cleanAttachmentName("folder\\drawing.dwg", "7"), "7 - drawing.dwg");

// --- the status code leads the name when there is one ---
assert.equal(cleanAttachmentName("spec.pdf", "51163", "AP"), "AP 51163 - spec.pdf");
assert.equal(cleanAttachmentName("spec.pdf", "51163", "co"), "CO 51163 - spec.pdf");
assert.equal(cleanAttachmentName("bad<>name?.pdf]", "42", "DA"), "DA 42 - bad__name_.pdf");

// --- iSpeed's numeric status id wins; display text is the fallback ---
assert.equal(statusCode("anything", "10"), "DA");
assert.equal(statusCode("anything", "11"), "AP");
assert.equal(statusCode("anything", "12"), "RE");
assert.equal(statusCode("anything", "13"), "CO");
assert.equal(statusCode("anything", "14"), "DE");
assert.equal(statusCode("Complete", ""), "CO");
assert.equal(statusCode("  draft ", ""), "DA");
assert.equal(statusCode("Cancelled", ""), "CA");   // not in iSpeed, mapped anyway
assert.equal(statusCode("Whatever", "99"), "");    // unknown stays empty, never guessed

// --- reading a name back tells us which status was downloaded ---
assert.deepEqual(parseDownloadedName("AP 51163 - spec.pdf"), { code: "AP", dtcr: "51163" });
assert.deepEqual(parseDownloadedName("51163 - spec.pdf"), { code: "", dtcr: "51163" });
assert.deepEqual(parseDownloadedName("DTCR_Summary.csv"), { code: "", dtcr: "" });
assert.deepEqual(parseDownloadedName("ap 51163 - spec.pdf"), { code: "AP", dtcr: "51163" });

// --- a name survives the round trip, so re-download decisions stay stable ---
for (const code of ["DA", "AP", "CO", "RE", "DE"]) {
  const name = cleanAttachmentName("file.pdf", "50001", code);
  assert.deepEqual(parseDownloadedName(name), { code, dtcr: "50001" },
    `round trip failed for ${code}`);
}

// --- inactive statuses are skipped unless the SE opts in ---
assert.equal(isInactiveCode("RE"), true);
assert.equal(isInactiveCode("DE"), true);
assert.equal(isInactiveCode("CA"), true);
assert.equal(isInactiveCode("AP"), false);
assert.equal(shouldDownloadStatus("RE", false), false);
assert.equal(shouldDownloadStatus("RE", true), true);
assert.equal(shouldDownloadStatus("CO", false), true);
assert.equal(shouldDownloadStatus("", false), true);   // unknown is not inactive

// the old helper still behaves, so nothing that used it changes meaning
assert.equal(isExcludedStatus("Deleted"), true);
assert.equal(isExcludedStatus("CANCELED"), true);
assert.equal(isExcludedStatus("Cancelled by administrator"), true);
assert.equal(isExcludedStatus("Complete"), false);

// --- approvers flatten to one readable cell ---
assert.equal(
  formatApprovers([{ role: "Wiring PC", name: "Doe, Jane", status: "Approved", date: "14/05/26", comment: "" }]),
  "Wiring PC / Doe, Jane / Approved / 14/05/26");
assert.equal(
  formatApprovers([{ role: "Device Engineer", name: "A B", status: "Approved", date: "12/05/26", comment: "[Normal Development]" }]),
  "Device Engineer / A B / Approved / 12/05/26 / ([Normal Development])");
assert.equal(formatApprovers([]), "");
assert.equal(formatApprovers(undefined), "");

// --- the summary carries the code and the approvers, and still escapes ---
const csv = makeSummaryCsv([{
  dtcr: "1", status: "Complete", code: "CO", reasons: ['A, "B"'],
  approvers: [{ role: "Wiring PC", name: "Doe, Jane", status: "Approved", date: "14/05/26" }],
  files: ["CO 1 - file.pdf"], result: "Downloaded"
}]);
assert.match(csv, /DTCR #,Status,Code,Reason for Change,Approvers,Attachments,Result/);
assert.match(csv, /"A, ""B"""/);
assert.match(csv, /CO 1 - file\.pdf/);
assert.match(csv, /Wiring PC \/ Doe, Jane/);

// --- picking the right table on a page built entirely out of tables ---
// Minimal stand-ins: only tHead/rows/cells/textContent are read.
const cells = (...labels) => ({ cells: labels.map((textContent) => ({ textContent })) });
const section = (...labels) => ({ tHead: { rows: [cells(...labels)] }, rows: [] });
const layout = (...labels) => ({ tHead: null, rows: [cells(...labels)] });  // no <thead>

const approvals = section("APPROVER", "NAME", "STATUS", "COMMENT", "DATE");
const actions = section("VEHICLE PROGRAM", "BUILD PHASE", "ACTION NAME", "REASON FOR CHANGE");
// the real page wraps every section in one layout table whose first row reads
// as the concatenated text of all 13 nested tables — it must never match
const wrapper = layout("APPROVER NAME STATUS COMMENT DATE REASON FOR CHANGE");

assert.deepEqual(pickTablesByHeader([approvals, actions, wrapper], "APPROVER", "STATUS"),
  [approvals], "the layout wrapper must not be mistaken for the approvals table");
assert.deepEqual(
  pickTablesByHeader([approvals, actions, wrapper], "REASON FOR CHANGE", "VEHICLE PROGRAM"),
  [actions]);
assert.deepEqual(pickTablesByHeader([wrapper], "APPROVER", "STATUS"), [],
  "a table with no <thead> is never a section table");
assert.deepEqual(pickTablesByHeader([], "APPROVER"), []);
assert.deepEqual(pickTablesByHeader(null, "APPROVER"), []);

// every required label must be present, not just one
assert.deepEqual(pickTablesByHeader([approvals], "APPROVER", "DNUM"), []);
// matching is case-insensitive on the caller's side too
assert.deepEqual(pickTablesByHeader([approvals], "approver", "status"), [approvals]);

assert.deepEqual(headerLabelsOf(approvals), ["APPROVER", "NAME", "STATUS", "COMMENT", "DATE"]);
assert.equal(headerLabelsOf(wrapper), null);
assert.equal(headerLabelsOf({}), null);

console.log("shared helper tests passed");
