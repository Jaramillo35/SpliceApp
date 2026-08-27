"""User-facing instructions for the VBOM Risk Matrix.

One source of truth: the NiceGUI page, the Streamlit page, and the README
shipped inside the generated bundle all render :data:`GUIDE_MD`, so the
instructions cannot drift between where the work is done and where the
output files end up.
"""

from __future__ import annotations

GUIDE_MD = """\
## What this tool does

For every VIN in the programme's build data it decides **which harness part
number belongs to each harness family**, using the sales codes that VIN
carries and the applicability marked in each harness complexity file. Where it
cannot decide on its own it flags the case for you instead of guessing, and
once every flagged case is resolved it produces the DEFE template.

## Before you run

| Input | What to give it |
|---|---|
| **Model year** | Two digits — `28` for MY2028. Tags every output file. |
| **Program** | The programme code, e.g. `DT`. Also tags the outputs. |
| **Input type** | `DoAll` or `BuildSpec` — must match the file you upload. |
| **DoAll / BuildSpec file** | The programme export listing every VIN and its sales codes. |
| **Harness complexity files** | One `.xlsm` per harness. Upload them all at once; 40+ is normal. |

Every output is named with the `{MY}_{Program}` tag (e.g. `28_DT`), so bundles
from different programmes never get mixed up.

## The files you get

| File | What it is | When you use it |
|---|---|---|
| `Harness_Selection_Review_{tag}.xlsm` | **Start here.** The review workbook: `Review` (flagged cases), `Candidate_Options` (the PNs considered for each), `Selections_Data`, `Config`. | Resolve every flagged case, in Excel or on this page. |
| `VIN_to_Harness_Selection_{tag}.xlsx` | The decision for every VIN × family: `Selections` (the chosen PN and why), `AllCandidates` (every PN considered, with its score), `Excluded_SalesCodes`, `Final_BOM_By_VIN`, `Family_Code_Stats`. | Auditing a specific VIN, or answering "why this PN?". |
| `VIN_Salescode_matrix_{tag}.xlsx` | Every VIN against every sales code, plus `SalesCode_Diff` comparing the codes in the build data against the codes the harnesses know. | Checking the input data before trusting the result. |
| `Master_Combined_Harness_Complexity_{tag}.xlsx` | All uploaded complexity files in one workbook, one sheet per harness. | Cross-checking applicability without opening 44 files. |
| `{tag}_VBOM_Template_for_DEFE.xlsx` | The deliverable. **Withheld until every flagged case is resolved.** | Hand-off to DEFE. |

## The review gate

The DEFE template is deliberately withheld while any case is open — the same
rule the Excel macro enforces. Resolve the cases on this page (pick the PN,
add a note, then **Generate**) or in the review workbook (resolve, then its
**Generate DEFE Template** button). Both write the same file.

Three things get flagged:

* **No complete PN covers every required sales code** — no part number in that
  family carries all the codes the VIN needs. Either a code is missing from the
  complexity file, or that VIN genuinely needs a new part.
* **Multiple PNs share the best score** — two or more parts fit equally well
  and the tool will not choose for you.
* **N/A conflicts with an available base/default PN** — the family was marked
  not-applicable for this VIN, but a base part exists that would fit.

Resolving to **N/A** is a valid answer and is recorded as such.

## How a part number is chosen

A VIN carries a set of sales codes. Each part number in a complexity file
carries the codes marked `X` in its row (a `G` mark means *giveaway* — the code
is carried, but it came along with the part rather than being ordered). A part
that carries every code the VIN requires is a candidate; candidates are scored
on how exactly they match, and the best-scoring one wins. A part missing a
required code is incomplete, which is what raises the first review reason.

## Before you trust the output

* **`Excluded_SalesCodes`** lists codes present in the build data that no
  uploaded harness knows about. A long list usually means a complexity file is
  missing from the upload, not that the codes are irrelevant.
* **Only `X` and `G` count as marks.** A cell holding anything else — `O` is
  the one that turns up in practice — is read as *not applicable*, silently.
  If a harness is missing from a VIN you expected it on, check the marks in
  that complexity file first.
* **Check `SalesCode_Diff`** when the results look wrong across the board; it
  is usually an input mismatch rather than a selection bug.
"""

#: Shipped inside the generated bundle so the files stay self-explanatory once
#: they are emailed on, detached from the app.
README_FILENAME = "README - How to use these files.md"


def bundle_readme(tag: str, defe_output_name: str, review_case_count: int) -> str:
    """The README written into the bundle, stamped with this run's specifics."""
    open_line = (
        f"This run flagged **{review_case_count} selection(s)** for your review."
        if review_case_count else
        "This run flagged **no** selections — the DEFE template can be "
        "generated straight away."
    )
    return (
        f"# VBOM Risk Matrix — {tag}\n\n"
        f"{open_line}\n\n"
        f"The DEFE template for this run is named `{defe_output_name}`.\n\n"
        f"{GUIDE_MD}"
    )
