# Roadmap / TODO

## Two-part architecture (decided 2026-08-25, not yet built)

Part A = the Docker host (everything). Part B = the per-user Teams
Transcript Recorder exe (the only desktop-bound feature). Work items:

1. **Transcript upload**: `POST /transcripts` on splice-api; the recorder
   exe posts each finished (already-anonymized) transcript to the
   configured server URL so recordings land in the hosted Meeting
   Transcripts page instead of stranding on user PCs.
2. **Recorder version check**: exe pings the server's version endpoint on
   launch; shows "newer recorder available — download from the app" when
   behind. Distribution stays on the app's Downloads page.
3. **Retire the full-app Windows exe pipeline** (packaging/windows) once
   the hosted URL is the standard access path — also removes the
   NiceGUI-PyInstaller migration from wave 3.
4. **Host auto-update ladder**: Update.bat (now) → Windows Scheduled Task
   nightly → GitHub Actions image builds + Watchtower on the host
   (fully hands-off). Updates run ON the host only — never triggered from
   user PCs.

## Other open items

- NiceGUI wave 3 cutover: Docker serves NiceGUI on :8501, Streamlit
  retires (blocked on pilot sign-off).
- VBOM in-app review-gate resolutions: persist like the Circuit Health
  disposition baseline (currently session-only).
