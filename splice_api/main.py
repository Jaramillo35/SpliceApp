"""splice-api FastAPI application.

Endpoints (all uploads are multipart ``.xls/.xlsx`` DTx/DTCR reports):

    GET  /health                  → liveness + version
    POST /dtx/compare             → enhanced DTx compare workbook (.xlsx)
    POST /dtx/compare/summary     → typed JSON summary (CompareSummary)
    POST /dtcr/match              → DTCR matching workbook (.xlsx)
    POST /preorder                → PreOrder generation workbook (.xlsx)

Run locally:  ``uvicorn splice_api.main:app --reload``  (from the Splice repo root)
Interactive docs:  http://localhost:8000/docs
"""

from __future__ import annotations

import io
import sys
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import RedirectResponse, StreamingResponse

# Make the sibling ``splice`` package importable when the API is launched from anywhere.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from splice.dtx_compare import launch_preorder_generation_tool, load_dtcr_report
from splice.dtx_compare.engine import generate_dtcr_matching_report
from splice.dtx_compare.enhanced_report import (
    DTCRRequiredError,
    generate_enhanced_dtx_report,
)

from .models import CompareSummary, HealthResponse

__version__ = "0.1.0"
_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

app = FastAPI(
    title="Splice API",
    version=__version__,
    description="HTTP gateway over the Splice DTx/DTCR engines — the versioned service "
    "boundary (ADR-0004). Engines are reused unchanged; this layer only marshals "
    "uploads into engine calls and streams the resulting workbooks back.",
)


# --------------------------------------------------------------------------- helpers
def _xlsx_response(data: bytes, filename: str) -> StreamingResponse:
    return StreamingResponse(
        io.BytesIO(data),
        media_type=_XLSX_MIME,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Output-Filename": filename,
        },
    )


async def _read(upload: UploadFile) -> tuple[bytes, str]:
    data = await upload.read()
    if not data:
        raise HTTPException(status_code=400, detail=f"Empty upload: {upload.filename}")
    return data, upload.filename or "upload.xls"


# --------------------------------------------------------------------------- routes
@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/docs")


@app.get("/health", response_model=HealthResponse, tags=["meta"])
def health() -> HealthResponse:
    return HealthResponse(version=__version__)


@app.post("/dtx/compare", tags=["dtx"], summary="Enhanced DTx compare workbook (.xlsx)")
async def dtx_compare(
    old: UploadFile = File(..., description="OLD DTx report"),
    new: UploadFile = File(..., description="NEW DTx report"),
    dtcr: UploadFile = File(..., description="DTCR report (required)"),
) -> StreamingResponse:
    ob, on = await _read(old)
    nb, nn = await _read(new)
    db, dn = await _read(dtcr)
    try:
        dtcr_df = load_dtcr_report(db, dn)
        result = generate_enhanced_dtx_report(
            old_file_bytes=ob, new_file_bytes=nb,
            old_file_name=on, new_file_name=nn, dtcr_df=dtcr_df,
        )
    except DTCRRequiredError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # engine/parse failures → 500 with the reason
        raise HTTPException(status_code=500, detail=f"DTx compare failed: {exc}") from exc
    return _xlsx_response(result["output_excel_bytes"], result["output_file_name"])


@app.post("/dtx/compare/summary", response_model=CompareSummary, tags=["dtx"],
          summary="DTx compare — typed JSON summary")
async def dtx_compare_summary(
    old: UploadFile = File(...), new: UploadFile = File(...), dtcr: UploadFile = File(...),
) -> CompareSummary:
    ob, on = await _read(old)
    nb, nn = await _read(new)
    db, dn = await _read(dtcr)
    try:
        dtcr_df = load_dtcr_report(db, dn)
        r = generate_enhanced_dtx_report(
            old_file_bytes=ob, new_file_bytes=nb,
            old_file_name=on, new_file_name=nn, dtcr_df=dtcr_df,
        )
    except DTCRRequiredError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"DTx compare failed: {exc}") from exc

    fam_df = r.get("harness_family_summary_df")
    families: list[str] = []
    if fam_df is not None and "Harness Family" in getattr(fam_df, "columns", []):
        families = sorted(fam_df["Harness Family"].dropna().astype(str).unique().tolist())
    dm = r.get("dtcr_matching_df")
    dtcr_total = len(dm) if dm is not None else 0
    dtcr_matched = (
        int((dm["Match Method"] != "No Match").sum())
        if dm is not None and "Match Method" in dm.columns else 0
    )
    return CompareSummary(
        old_file=on, new_file=nn,
        added_cnums=int(r["added_cnum_count"]), removed_cnums=int(r["removed_cnum_count"]),
        added_circuits=int(r["added_circuit_count"]), removed_circuits=int(r["removed_circuit_count"]),
        modified_circuits=int(r["modified_circuit_count"]),
        harness_families=families, dtcr_total=dtcr_total, dtcr_matched=dtcr_matched,
        output_file_name=r["output_file_name"],
    )


@app.post("/dtcr/match", tags=["dtcr"], summary="DTCR matching workbook (.xlsx)")
async def dtcr_match(
    old: UploadFile = File(...), new: UploadFile = File(...), dtcr: UploadFile = File(...),
) -> StreamingResponse:
    ob, on = await _read(old)
    nb, nn = await _read(new)
    db, dn = await _read(dtcr)
    try:
        dtcr_df = load_dtcr_report(db, dn)
        r = generate_dtcr_matching_report(
            old_file_bytes=ob, new_file_bytes=nb,
            old_file_name=on, new_file_name=nn, dtcr_df=dtcr_df,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"DTCR match failed: {exc}") from exc
    data = r.get("dtcr_matching_bytes")
    if not data:
        raise HTTPException(status_code=500, detail="DTCR matching produced no workbook.")
    return _xlsx_response(data, r.get("dtcr_matching_file_name", "DTCR_Matching_Report.xlsx"))


@app.post("/hrn/chart", tags=["hrn"], summary="HRN + CMP chart workbook (.xlsx)")
async def hrn_chart(
    hrn: UploadFile = File(..., description=".hrn circuit file"),
    matrix: UploadFile = File(..., description="harness matrix .csv (semicolon-delimited)"),
    cmp: UploadFile | None = File(None, description="optional .cmp connector map"),
    supplier: UploadFile | None = File(
        None, description="optional supplier list override (Excel/CSV)"),
) -> StreamingResponse:
    """Chart workbook named {HarnessFamily}_{ModelYear}{Program}_Chart_{MMDDYYYY}
    (fields extracted from the HRN file name; date = day of the run). Diagnostic
    counts come back in X-Unmatched-Connectors / X-Invalid-Prefixes headers."""
    from splice.hrncmp.engine import build_chart, load_supplier_map

    hb, hn = await _read(hrn)
    mb, _ = await _read(matrix)
    cb = (await _read(cmp))[0] if cmp is not None and cmp.filename else None
    supplier_map = None
    if supplier is not None and supplier.filename:
        sb, sn = await _read(supplier)
        supplier_map = load_supplier_map(sb)
        if not supplier_map:
            raise HTTPException(
                status_code=400, detail=f"Unreadable supplier list: {sn}")
    try:
        r = build_chart(hn, hb, mb, cb, supplier_map=supplier_map)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"HRN chart failed: {exc}") from exc
    response = _xlsx_response(r.workbook, r.filename)
    response.headers["X-Unmatched-Connectors"] = str(len(r.unmatched))
    response.headers["X-Invalid-Prefixes"] = str(len(r.invalid_prefixes))
    return response


@app.post("/preorder", tags=["preorder"], summary="PreOrder generation workbook (.xlsx)")
async def preorder(
    old: UploadFile = File(...), new: UploadFile = File(...),
) -> StreamingResponse:
    ob, on = await _read(old)
    nb, nn = await _read(new)
    try:
        with tempfile.TemporaryDirectory(prefix="splice_api_preorder_") as td:
            root = Path(td)
            old_path = root / Path(on).name
            new_path = root / Path(nn).name
            old_path.write_bytes(ob)
            new_path.write_bytes(nb)
            r = launch_preorder_generation_tool(old_file_path=old_path, new_file_path=new_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"PreOrder generation failed: {exc}") from exc
    return _xlsx_response(r["output_excel_bytes"], r["output_file_name"])
