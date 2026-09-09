"""Every AutomationId the automation touches, in one place.

This is the whole contract with DEF Editor. When the application changes an
id, exactly one file needs editing, and ``defauto.diagnose`` can report which
of these are missing from a live window before any workflow runs — which is
far more useful than a traceback three calls deep.

Ids only. No customer, user, machine or business data appears here or
anywhere else in this kit; the sample programme the demo backend serves is
invented.
"""

from __future__ import annotations

# ------------------------------------------------------------------ window
MAIN_WINDOW_TITLE = "DEF EDITOR - Master Form"
ROOT_FORM = "form_Main"

LAYOUT = (
    "Panel_Display",
    "TableLayoutPanel_Page",
    "Panel_Edit",
    "Panel_Header",
    "Panel_Information",
    "StatusStrip1",
)

# ------------------------------------------------------------- user controls
UC_HARNESS = "uc_Harness"
UC_HARNESS_EDIT = "uc_Harness_Edit"
UC_DEVICES = "uc_Harness_Edit_Devices"
UC_CIRCUITS = "uc_Harness_Edit_Circuits"
UC_SPLICES = "uc_Harness_Edit_Splices"
UC_CIRCUITS_USAGE = "uc_Harness_Edit_Circuits_Usage"
UC_SALES_CODES = "uc_Harness_Edit_SalesCodes"
UC_CHECKS_CONNECTORS = "uc_Harness_Checks_Connectors"
UC_CHECKS_INLINE = "uc_Harness_Edit_Checks_Inline"

# --------------------------------------------------------------- navigation
MENU_HARNESS = "Harness"
MENU_DEVICES = "Devices"
MENU_CIRCUITS = "Circuits"
MENU_SPLICES = "Splices"
MENU_COMPLEXITY = "Complexity"
MENU_LOCATION_VARIANCE = "Location Variance"
MENU_QUALITY_CHECKS = "Quality Checks"

#: Top-level menu items, in the order the application shows them.
MENUS = (
    MENU_HARNESS,
    MENU_DEVICES,
    MENU_CIRCUITS,
    MENU_SPLICES,
    MENU_COMPLEXITY,
    MENU_LOCATION_VARIANCE,
    MENU_QUALITY_CHECKS,
)

#: Complexity is the only top-level menu with a second level.
COMPLEXITY_SUBMENUS = ("Devices", "Circuits", "Sales Codes")

#: Quality Checks likewise.
QUALITY_SUBMENUS = ("Circuits", "Inlines")

# ------------------------------------------------------- step 1: composite
COMBO_VEHICLE_LINE = "ComboBox_Vehicle_Line"
COMBO_MODEL_YEAR = "ComboBox_Model_Year"
COMBO_PHASE = "ComboBox_Phase"
BUTTON_FILTER = "SimpleButtonFilter"
GRID_COMPOSITE = "dgv_Composite"

# ------------------------------------------- step 2: composite harness pick
LIST_HARNESS = "ListBox_Harness"
LIST_COMPOSITE = "ListBox_Composite"

# ---------------------------------------------------------------- filters
#: The generic filter box. It appears on several pages, which is why every
#: read is scoped to the user control that owns it rather than searched for
#: across the whole form.
TEXT_FILTER = "TextBox_Filter"
TEXT_FILTER_CIRCUIT = "TextEditCircuitFilter"
TEXT_FILTER_SPLICE = "TextEditSpliceFilter"
TEXT_FILTER_INLINE = "TextEditInlineFilter"
TEXT_FILTER_CIRCUIT_COMPLEXITY = "TextBox_Filter_Circuit"
TEXT_FILTER_SALES_CODE = "TextBox_Filter_Sales_Code"
TEXT_FILTER_HARNESS_PN = "TextBox_Filter_Harness_PN"

FILTERS = (
    TEXT_FILTER,
    TEXT_FILTER_CIRCUIT,
    TEXT_FILTER_SPLICE,
    TEXT_FILTER_INLINE,
    TEXT_FILTER_CIRCUIT_COMPLEXITY,
    TEXT_FILTER_SALES_CODE,
    TEXT_FILTER_HARNESS_PN,
)

# ------------------------------------------------------------------- grids
GRID_DEVICES = "dgv_Devices"
GRID_CIRCUITS = "DataGridView_Circuits"
GRID_SPLICES = "dgv_Splices"
GRID_DEVICE_COMPLEXITY = "dgv_Dev_Complexity"
GRID_CIRCUIT_COMPLEXITY = "dgv_Circuit_Complexity"
GRID_SALES_CODES_EDIT = "dgv_SalesCodes_Edit"
GRID_SALES_CODES_AVAILABLE = "dgv_Sales_Codes_Available"
GRID_SALES_CODES_USED = "dgv_Sales_Codes_Used"
GRID_INLINE_MATCH = "dgv_Match"

GRIDS = (
    GRID_COMPOSITE,
    GRID_DEVICES,
    GRID_CIRCUITS,
    GRID_SPLICES,
    GRID_DEVICE_COMPLEXITY,
    GRID_CIRCUIT_COMPLEXITY,
    GRID_SALES_CODES_EDIT,
    GRID_SALES_CODES_AVAILABLE,
    GRID_SALES_CODES_USED,
    GRID_INLINE_MATCH,
)

# -------------------------------------------------------------- checkboxes
CHECK_LIVE_CHECKS = "CheckBox_LiveChecks"
CHECK_ENDS_BYPASS = "CheckBox_EndsByPass"
CHECK_ATTRIBUTES_BYPASS = "CheckBox_AttributesByPass"
CHECK_INLINE_BYPASS = "CheckBox_InlineByPass"
CHECK_CKT_MISSING = "cb_ckt_filter_missing"
CHECK_CKT_SINGLE_END = "cb_ckt_filter_singleend"

CHECKBOXES = (
    CHECK_LIVE_CHECKS,
    CHECK_ENDS_BYPASS,
    CHECK_ATTRIBUTES_BYPASS,
    CHECK_INLINE_BYPASS,
    CHECK_CKT_MISSING,
    CHECK_CKT_SINGLE_END,
)

# ---------------------------------------------------------------- circuits
COMBO_DELPHI_CONNECTOR = "ComboBox_Delphi_Connector_No"

# ----------------------------------------------------------------- splices
TEXT_CREATE_CAV_COUNT = "TextBox_Create_Cav_Count"
TEXT_CIRCUIT_FAMILY = "TextBox_Circuit_Family"
TEXT_SPLICE_NUMBER = "TextBox_Splice_Number"
LIST_CIRCUIT_FAMILY = "ListBox_Circuit_Family"

# ------------------------------------------------------------- sales codes
TAB_SALES_CODES = "TabControl1"
TAB_AVAILABLE_CIRCUIT = "Available Circuit"
TAB_IMPORT_EXCEL = "Import Excel"

# ---------------------------------------------------------- quality checks
RICH_RESULTS = "RichTextBox_Results"

TAB_INLINE = "XtraTabControlInlineComposite"
TAB_INLINE_SETUP = "Inline Setup"
TAB_INLINE_PAIRS = "Inline Pairs"
TAB_INLINE_RESULTS = "Inline Results"

ACTION_RUN_SELECTED_PAIR = "Run Selected Inline Pair"
ACTION_RUN_ALL_PAIRS = "Run All Inline Pair"
ACTION_SIGN_OFF_INLINE = "Sign-Off Inline Check"

PANEL_SIGN_OFF = "Panel_SignOff"
PICTURE_INLINE_SIGN_OFF = "PictureBox_InlineSignOff"

# ------------------------------------------------------------ global menus
SETTINGS_ITEMS = (
    "Refresh Tables",
    "Stored Procedure Update",
    "Part Nbr/New Model PN",
    "Request Access",
    "Issue List",
    "Session Log",
    "Fix Slow Database",
)

REPORT_ITEMS = (
    "Circuit Summary",
    "Complexity Compare",
    "DEF-DEF Checker",
    "DEF-WHiP Checker",
    "PaperCar(VBoM) Compare",
    "DO_ALL Check",
    "Full Database Complexity Report",
    "GSD Lookup",
)

#: What ``diagnose`` looks for to call an attachment healthy. Deliberately
#: only the ids every workflow needs — a missing splice filter should not
#: stop someone reading the devices grid.
ESSENTIAL = (
    COMBO_VEHICLE_LINE,
    COMBO_MODEL_YEAR,
    COMBO_PHASE,
    BUTTON_FILTER,
    GRID_COMPOSITE,
    LIST_HARNESS,
)
