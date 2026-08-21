# System Engineer Toolkit — How to Run It (No Computer Background Needed)

This is the full wiring-engineering toolkit in your web browser: Splice Generation,
DTx Compare (OLD vs NEW with DTCR matching and the PreOrder list), the SECR Database,
the VBOM Risk Matrix, Inline Continuity checks, and the HRN Chart Builder — all in a
few clicks. There is also a technical API page at http://localhost:8501 for
automation; most people never need it.

You do **not** need to know anything technical. Just follow the steps in order.

> **Two quick things to know first**
> - Installing the helper program (Docker Desktop) usually needs **admin rights**. On a work
>   laptop you may need to ask **IT** to install it for you (one time only).
> - Everything runs **on your own computer** — your files are never uploaded to the internet.

---

## What you'll do (the big picture)

1. **One time:** install one free program (Docker Desktop) and save this tool's folder.
2. **Every time:** double-click **Start**, use the tool in your web browser, double-click **Stop**.

That's it. There is **no typing of commands**.

---

## PART 1 — One-time setup (do this once)

### Step 1 — Install Docker Desktop

Docker Desktop is the "engine" that runs the tool. It's free to download.

**On Windows:**
1. Go to **https://www.docker.com/products/docker-desktop/** and click **Download for Windows**.
2. Open the file you downloaded (`Docker Desktop Installer.exe`) and click through
   **Next / OK / Accept**. If it asks about "WSL 2", leave the box checked.
3. When it finishes, **restart your computer** if it asks you to.
4. Open **Docker Desktop** from the Start menu. The first time, accept the terms.
5. Wait until the little **whale icon** near the clock (bottom-right) stops moving — that means
   it's ready.

**On a Mac:**
1. Go to **https://www.docker.com/products/docker-desktop/** and click **Download for Mac**
   (pick **Apple chip** for newer Macs, **Intel chip** for older ones — if unsure, ask IT).
2. Open the downloaded file and **drag the Docker icon into the Applications folder**.
3. Open **Docker** from Applications. Accept the terms.
4. Wait until the **whale icon** in the top menu bar stops moving — that means it's ready.

> Can't install it (no admin rights)? That's normal on work laptops — **ask IT to install
> Docker Desktop for you.** You only need this done once.

### Step 2 — Save this tool's folder

You should have received a folder called **`splice-api`** (for example, in an email or on a
shared drive). Save it somewhere easy to find, like your **Desktop**. If it came as a `.zip`
file, **right-click it and choose "Extract All" (Windows)** or **double-click it (Mac)** to
unzip it first.

**You're done with setup.** ✅

---

## PART 2 — Every time you want to use the tool

### Step 1 — Make sure Docker Desktop is running

Look for the **whale icon** (near the clock on Windows, top menu bar on Mac). If you don't see
it, open **Docker Desktop** and wait until it says it's running.

### Step 2 — Start the tool

Open the **`splice-api`** folder and **double-click**:
- **`Start (Windows).bat`** if you're on Windows, or
- **`Start (Mac).command`** if you're on a Mac.

A black window will open and show some text. **The very first time, this takes a few minutes**
while it gets everything ready — this is normal, just let it run. Later, it starts in seconds.

When it's ready, your **web browser opens automatically** to the tool. If it doesn't, open your
browser and type this address:

> **http://localhost:8501**

Leave the black window open while you use the tool.

### Step 3 — Run a compare

In the web page you'll see a few blue and green bars. To create your workbook:

1. Find the green bar that says **`POST /dtx/compare`** and click it once to open it.
2. Click the **"Try it out"** button on the right.
3. You'll see three "Choose File" boxes:
   - **old** → pick your **OLD** DTx report
   - **new** → pick your **NEW** DTx report
   - **dtcr** → pick your **DTCR** report
4. Click the big blue **"Execute"** button.
5. Wait a few seconds. Below, a **"Download file"** link appears — click it to **save your
   Excel workbook**.

That's your finished change report. Open it in Excel like any other file.

> Want just the DTCR Matching sheet, or just the PreOrder list? Use `POST /dtcr/match` or
> `POST /preorder` the same way (PreOrder only needs the OLD and NEW files).

### Step 4 — Stop the tool when you're done

Double-click:
- **`Stop (Windows).bat`** (Windows) or **`Stop (Mac).command`** (Mac).

You can also just quit Docker Desktop. Your files stay exactly where they were.

---

## If something doesn't work

| What you see | What to do |
|---|---|
| The Start window says "**Something went wrong / Is Docker Desktop open?**" | Open **Docker Desktop**, wait for the whale icon to stop moving, then double-click **Start** again. |
| The browser page won't open or says "can't reach this site" | Wait 30 seconds (it may still be starting), then refresh the page. Make sure the black **Start** window is still open. |
| **Mac:** double-clicking `Start (Mac).command` says it's from an "unidentified developer" | **Right-click** the file → **Open** → **Open**. You only need to do this the first time. |
| The **first** start is taking several minutes | That's normal the first time — it's preparing everything. Let it finish; it's fast after that. |
| Something else | Take a screenshot of the black window and send it to the person who shared this tool. |

---

## Questions?

Contact **Jaramillo** (the person who shared this tool) with a screenshot if you get stuck.
Nothing here can harm your computer — if in doubt, close the windows and start over.
