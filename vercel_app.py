from __future__ import annotations

from pathlib import Path

from flask import Flask, Response, abort, render_template_string, send_file, url_for


APP_DIR = Path(__file__).resolve().parent
EXTENSION_ZIP_PATH = APP_DIR / "assets" / "downloads" / "ispeed-dtcr-downloader.zip"

app = Flask(__name__)


PAGE_TEMPLATE = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>iSpeed DTCR Downloader</title>
    <style>
      :root {
        color-scheme: light;
        --bg-top: #eef6f2;
        --bg-bottom: #f6f9fc;
        --card: #ffffff;
        --border: #d6e1ea;
        --text: #14324a;
        --muted: #35526b;
        --badge-bg: #e8f4ff;
        --badge-text: #0b5ea8;
        --button: #0b5ea8;
        --button-hover: #08497f;
      }

      * {
        box-sizing: border-box;
      }

      body {
        margin: 0;
        font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
        color: var(--text);
        background: linear-gradient(180deg, var(--bg-top), var(--bg-bottom));
      }

      .shell {
        max-width: 960px;
        margin: 0 auto;
        padding: 40px 20px 56px;
      }

      .hero {
        padding: 24px;
        border-radius: 18px;
        border: 1px solid var(--border);
        background: rgba(255, 255, 255, 0.84);
        box-shadow: 0 12px 24px rgba(20, 50, 74, 0.08);
        margin-bottom: 20px;
      }

      .hero h1 {
        margin: 0 0 8px;
        font-size: clamp(2rem, 4vw, 3rem);
      }

      .hero p {
        margin: 0;
        color: var(--muted);
        font-size: 1.05rem;
        line-height: 1.55;
      }

      .card {
        border: 1px solid var(--border);
        border-radius: 18px;
        background: var(--card);
        box-shadow: 0 12px 24px rgba(20, 50, 74, 0.08);
        overflow: hidden;
      }

      .card-main {
        padding: 24px;
      }

      .badge-row {
        margin: 14px 0 18px;
        display: flex;
        gap: 10px;
        flex-wrap: wrap;
      }

      .badge {
        display: inline-block;
        padding: 6px 12px;
        border-radius: 999px;
        background: var(--badge-bg);
        color: var(--badge-text);
        font-size: 0.85rem;
        font-weight: 700;
      }

      .button {
        display: inline-block;
        text-decoration: none;
        border-radius: 12px;
        padding: 14px 18px;
        background: var(--button);
        color: #fff;
        font-weight: 700;
      }

      .button:hover {
        background: var(--button-hover);
      }

      .instructions {
        padding: 0 24px 24px;
      }

      .instructions h2,
      .instructions h3 {
        margin: 22px 0 10px;
      }

      .instructions p,
      .instructions li {
        color: var(--muted);
        line-height: 1.6;
      }

      code {
        padding: 2px 6px;
        border-radius: 6px;
        background: #f1f6fa;
        font-family: "SFMono-Regular", Consolas, monospace;
      }
    </style>
  </head>
  <body>
    <main class="shell">
      <section class="hero">
        <h1>iSpeed DTCR Downloader</h1>
        <p>Download the Chrome extension package used to process iSpeed DTCR search results, collect attachments, and generate a clean DTCR summary export.</p>
      </section>

      <section class="card">
        <div class="card-main">
          <h2>Chrome extension download</h2>
          <p style="color: var(--muted); margin: 0; line-height: 1.6;">This package includes the unpacked extension source in a zip so users can install it in Chrome with Developer mode.</p>
          <div class="badge-row">
            <span class="badge">Chrome Extension</span>
            <span class="badge">DTCR Attachments</span>
            <span class="badge">CSV Summary</span>
          </div>
          <a class="button" href="{{ download_url }}">Download ispeed-dtcr-downloader.zip</a>
        </div>

        <div class="instructions">
          <h2>Ready-to-paste website instructions</h2>

          <h3>Install</h3>
          <ol>
            <li>Download and unzip the extension.</li>
            <li>Open <code>chrome://extensions</code> in Chrome.</li>
            <li>Turn on <strong>Developer mode</strong>.</li>
            <li>Click <strong>Load unpacked</strong>.</li>
            <li>Select the unzipped <code>ispeed-dtcr-downloader</code> folder.</li>
            <li>Pin the extension from Chrome's Extensions menu.</li>
          </ol>

          <h3>What it does</h3>
          <p>The extension processes the current iSpeed DTCR search results. It skips deleted or canceled DTCRs, records each Reason for Change, downloads attachments with cleaned filenames, and creates <code>DTCR_Summary.csv</code>.</p>

          <h3>How to use it</h3>
          <ol>
            <li>Sign in to iSpeed.</li>
            <li>Select a Vehicle Program and Build Phase, then click <strong>Search</strong>.</li>
            <li>With the results visible, click the extension icon.</li>
            <li>Confirm the DTCR count.</li>
            <li>Click <strong>Choose folder</strong> and select an empty destination folder.</li>
            <li>Click <strong>Start download</strong>.</li>
            <li>Keep both tabs open until the run finishes.</li>
          </ol>

          <p>iSpeed can be slow. The extension waits for each detail page and the restored search results before continuing.</p>
        </div>
      </section>
    </main>
  </body>
</html>
"""


@app.get("/")
def index() -> str:
    return render_template_string(
        PAGE_TEMPLATE,
        download_url=url_for("download_extension"),
    )


@app.get("/download/ispeed-dtcr-downloader.zip")
def download_extension() -> Response:
    if not EXTENSION_ZIP_PATH.exists():
        abort(404, description="Extension package is missing from the deployment bundle.")
    return send_file(
        EXTENSION_ZIP_PATH,
        as_attachment=True,
        download_name="ispeed-dtcr-downloader.zip",
        mimetype="application/zip",
    )