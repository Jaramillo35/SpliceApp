# iSpeed DTCR Attachment Downloader

Chrome Manifest V3 extension for the Chrysler iSpeed DTCR search results.

## What it does

- Uses the Vehicle Program and Build Phase already selected in iSpeed.
- Reads every row in `#resultsTable`.
- Skips statuses containing `Deleted`, `Canceled`, `Cancelled`, or `Rejected`.
- Selects each row's `selectedDTCRID` radio control and clicks **Open/Modify**.
- Extracts the DTCR number and every **Reason for Change** value.
- Reads **Reason for Change** from the Requested Actions table's own header and data rows, avoiding iSpeed's nested layout tables.
- Downloads every attachment to a user-selected folder.
- Clicks **Go back to Search Results** before processing the next DTCR.
- Waits until the next detail page or restored results table is actually usable (up to five minutes).
- Retries **Go back to Search Results** once if the legacy page remains on the detail view.
- Prefixes attachment filenames with the DTCR's **status code** and number, e.g.
  `AP 51163 - drawing.pdf`. Codes come from iSpeed's own Status vocabulary:
  `DA` Draft, `AP` Approved, `RE` Rejected, `CO` Complete, `DE` Deleted
  (`CA` Cancel is mapped too, though iSpeed does not currently expose it).
  The row's numeric `status-id` is preferred over the display text.
- Skips DTCRs already in the folder **at the same status**, and re-downloads one
  whose status has moved since the last run (`DA` -> `AP` -> `CO`). The status
  lives in the file name, so the folder itself is the record — no side database.
  A file left by an older version (no status prefix) is re-downloaded once and
  is stable afterwards. Superseded files are kept, so the folder shows the
  history rather than overwriting it.
- Rejected and Deleted DTCRs are skipped unless **Also download Rejected and
  Deleted DTCRs** is ticked on the dashboard; the choice is remembered.
- Records each DTCR's approvals — approver role, name, status, date and comment.
- Removes invalid filename characters and garbage after known file extensions.
- Preserves existing files by adding `(2)`, `(3)`, and so on.
- Writes `DTCR_Summary.csv` to the selected folder, with columns
  DTCR # / Status / Code / Reason for Change / Approvers / Attachments / Result.

## Develop

Source of truth is this folder. Run the helper tests with `node test-shared.js`,
then rebuild the shipped archive with `python3 build.py`, which writes
`assets/downloads/ispeed-dtcr-downloader.zip`.

## Install locally

1. Open `chrome://extensions` in Chrome.
2. Enable **Developer mode**.
3. Click **Load unpacked**.
4. Select this `ispeed-dtcr-downloader` folder.

## Use

1. Sign in to iSpeed.
2. Select the Vehicle Program and Build Phase, then run the iSpeed search so the DTCR table is visible.
3. Click the extension's toolbar icon while that iSpeed tab is active.
4. In the dashboard, confirm the source count.
5. Click **Choose folder** and grant write access.
6. Click **Start download**.
7. Keep the iSpeed tab and dashboard open until the run completes.

## Notes

- The extension processes one DTCR at a time to avoid overloading the legacy application.
- Slow iSpeed navigation is expected. After eight seconds the dashboard reports that it is still waiting; it does not advance until the required page is ready.
- Authentication remains in Chrome. The extension sends attachment requests only to `ispeed.extra.chrysler.com` and writes only to the folder selected by the user.
- If iSpeed returns a login page during a run, sign in again, return to the search results, click **Refresh source**, and restart.
- This first version was mapped against iSpeed's current legacy frame layout and should be tested on a small result set before a full run.
