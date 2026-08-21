"""HRN + CMP chart builder.

Combines a .hrn circuit file with a semicolon-delimited harness matrix .csv
(and an optional .cmp connector map) into a styled chart workbook, named
{HarnessFamily}_{ModelYear}{Program}_Chart_{MMDDYYYY} from the HRN file name
and the day the conversion runs.

Fully in-memory (bytes in, bytes out), so the same engine serves the Streamlit
page, the splice-api endpoint, and the desktop app it was ported from.
"""
