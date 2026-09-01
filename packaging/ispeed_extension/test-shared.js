const assert = require("node:assert/strict");
const {
  cleanAttachmentName, formatApprovers, isExcludedStatus, isInactiveCode,
  makeSummaryCsv, parseDownloadedName, shouldDownloadStatus, statusCode
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

console.log("shared helper tests passed");
