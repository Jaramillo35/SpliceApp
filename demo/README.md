# Splice showcase dataset

A complete set of **fabricated** input files for demonstrating every section of
the app — in an interview, to a supervisor, to anyone — without exposing a
single byte of customer data.

Regenerate at any time:

```bash
python -m demo.showcase
```

Files land in `demo/showcase/`, plus `Splice_Showcase_30QX.zip` for carrying to
a machine that has no repository checkout.

## What is invented

| | |
|---|---|
| Programme | **2030 QX**, build phase **V1_A** — no such programme exists |
| Sales codes | `QA1` panoramic roof, `QA2` fixed roof, `QB1` premium audio, `QB2` base audio, `QC1` heated seats, `QD1` trailer tow, `QE1` 360 camera, `QF1` power liftgate, `QZ9` night vision |
| Part numbers | `99xxxxxx` + `AA` — a range no supplier uses |
| Circuits / connectors | `QK1xx` / `CQ1xx`, plus inline `X350` ↔ `Y350` |
| Harness families | Generic industry names (IP, DASH, BODY_LEFT …) which identify no customer |

The files **cross-reference each other**: the same families, codes and part
numbers run through the DTx, the complexity files, the build spec and the
circuit summary. That is what makes the demo hold together when someone asks a
follow-up question.

## Planted findings — what each section will catch

Every section has something real to find. A clean sheet proves nothing.

| Section | What to point at |
|---|---|
| **Circuit Applicability** | `QK107` is conditioned on `QA1&QA2` — the two roof codes are mutually exclusive, so no IP build carries it: a **never built** finding. |
| **Circuit Applicability** | `QK108` needs `QZ9` and `QK603` needs `QE1`, neither tracked by that family's complexity file → the **Sales-code gaps** tab. |
| **Circuit Applicability** | `HEADLINER` is in the DTx with no complexity file → a **red dotted row**. `DOOR_FRONT_LEFT_MAIN` does not auto-match its family → appears as a **candidate** to drag or click. |
| **VBOM Risk Matrix** | 8 VINs → **13 review cases**, in two flavours: *no complete PN covers every required sales code*, and *N/A conflicts with an available base/default PN*. The DEFE template stays withheld until they are resolved. |
| **Harness Complexity** | The IP sheet carries a `C/O` **carryover** (resolves to an *Inferred* P/N), a `DELETE P/N` **excluded** row, a **combined expression** `QB1+(QA1/QA2)` awaiting your decision, and an **equality** `QA1=QA2` that auto-resolves into two columns. |
| **Harness Complexity** | The OLD master lacks `QF1`, so OLD-vs-NEW shows an **added sales code** per family. |
| **Circuit Health** | Inline `X350 ↔ Y350`: cavity 2 has a wire on BODY_LEFT and **nothing opposite** on LIFTGATE → a **Blocker**, alongside 2 auto-cleared proofs. |
| **HRN Chart Builder** | One circuit uses supplier prefix `ZQ`, absent from the shipped list → raises the **supplier update ticket**. |
| **DTx Compare** | The OLD export is missing `QK106` and `QK702`, so the comparison reports **added circuits**. |

## Suggested 10-minute demo order

1. **Circuit Applicability** — load the DTx and all 8 complexity files. Show the
   mapping workbench: 7 auto-connect (green), `DOOR_FRONT_LEFT_MAIN` appears as
   a candidate to click, `HEADLINER` stays red. Run, then open the never-built
   finding and the sales-code gaps. *This is the newest work and the best
   opener.*
2. **VBOM Risk Matrix** — load the BuildSpec + the 8 complexity files. Show the
   progress bar naming each stage, then the review gate withholding the DEFE
   until 13 cases are resolved. Resolve one to show it unlock.
3. **Harness Complexity** — cross-reference + NEW master. Open IP: point at the
   Inferred carryover, the excluded DELETE row, and the combined expression
   waiting on a decision. Generate the `.xlsm`.
4. **Circuit Health** *(optional — currently paused)* — circuit summary + 4
   complexity files. One Blocker on a real inline pair.
5. **HRN Chart Builder** — drop the `.hrn`/`.csv`/`.cmp` triple, then show the
   supplier ticket the unknown `ZQ` prefix raises.

## Honest limits

* **SECR Database / Ask the Database** are not covered by generated files. The
  database is populated by *using* the app — create one or two SECRs live,
  which demonstrates the flow better than an import would.
* **Meeting Transcripts** needs no input file; demo the recorder UI and the
  privacy attestation dialog directly.
* The complexity files are written as `.xlsx`. Real ones are macro-enabled
  `.xlsm`; every reader here opens them by content, so nothing is mislabelled.
