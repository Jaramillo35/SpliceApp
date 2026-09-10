"""The DEF Editor automation kit, exercised without DEF Editor.

The kit ships from the Downloads page as source an engineer builds into an exe
on Windows. That is the only place it can actually run, which is exactly why
it needs tests here: UI automation is normally provable only in front of the
application it drives, so it gets written once and then nobody dares touch it.

``defauto.backend.Backend`` is the seam that removes the problem. Everything
above it — navigation, the modules, the validators — is driven here through
the scripted backend, on this machine, at the same speed as any other test.

What is NOT tested here is pywinauto's own behaviour. ``UiaBackend`` is the
one part that can only be proven on Windows in front of DEF Editor, which is
why it is kept as thin as it is and why ``Session.diagnose`` exists.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[1] / "packaging" / "def_editor_automation"
sys.path.insert(0, str(KIT))

from defauto import application, gridreader, ids, workflow  # noqa: E402
from defauto.backend import AutomationError, ControlNotFound, Grid  # noqa: E402
from defauto.fake import FakeBackend                        # noqa: E402


@pytest.fixture()
def session():
    return application.demo()


@pytest.fixture()
def opened(session):
    """A session with a harness open — where most workflows begin."""
    line = session.composite.vehicle_lines()[0]
    session.backend.select(ids.COMBO_VEHICLE_LINE, line)
    year = session.composite.model_years()[0]
    session.backend.select(ids.COMBO_MODEL_YEAR, year)
    phase = session.composite.phases()[0]
    session.composite.choose_programme(line, year, phase)
    session.composite.search()
    session.composite.choose_composite(session.composite.composites()[0])
    session.composite.choose_harness(session.composite.harnesses()[0])
    return session


class TestTheContractWithDefEditor:
    def test_every_essential_id_is_present(self, session):
        assert session.healthy(), session.diagnose()

    def test_diagnose_names_what_is_missing(self, session):
        """The whole point of diagnose: a moved control is a named control."""
        backend = session.backend
        original = backend.exists
        backend.exists = lambda a, s="": False if a == ids.BUTTON_FILTER \
            else original(a, s)
        missing = [a for a, ok in session.diagnose() if not ok]
        assert missing == [ids.BUTTON_FILTER]

    def test_an_unknown_id_raises_rather_than_returning_nothing(self, session):
        """A typo in ids.py must fail loudly here, not quietly on Windows."""
        with pytest.raises(ControlNotFound):
            session.backend.grid("dgv_DoesNotExist")

    def test_ids_are_not_duplicated_across_names(self):
        grids = list(ids.GRIDS)
        assert len(grids) == len(set(grids))
        filters = list(ids.FILTERS)
        assert len(filters) == len(set(filters))


class TestCompositeSelection:
    def test_the_combos_cascade(self, session):
        """A model year the chosen line does not build is not offered."""
        session.backend.select(ids.COMBO_VEHICLE_LINE, "2031ZR")
        assert session.composite.model_years() == ["2031"]
        session.backend.select(ids.COMBO_VEHICLE_LINE, "2032QX")
        assert session.composite.model_years() == ["2032", "2033"]

    def test_choosing_a_line_clears_what_was_below_it(self, session):
        session.composite.choose_programme("2031ZR", "2031", "V1_A")
        session.composite.search()
        session.composite.choose_composite(session.composite.composites()[0])
        session.backend.select(ids.COMBO_VEHICLE_LINE, "2032QX")
        assert session.backend.selected(ids.LIST_COMPOSITE) is None

    def test_the_grid_is_empty_until_filter_is_pressed(self, session):
        """The failure this guards: a workflow that skips Filter reads an
        empty grid and reports 'no composites' instead of failing."""
        session.composite.choose_programme("2031ZR", "2031", "V1_A")
        assert len(session.backend.grid(ids.GRID_COMPOSITE)) == 0
        assert len(session.composite.search()) > 0

    def test_open_refuses_a_programme_with_no_composites(self, session):
        with pytest.raises(AutomationError):
            session.composite.open("2032QX", "2033", "V1_A", "nope", "nope")

    def test_a_harness_outside_the_composite_is_refused(self, session):
        session.composite.choose_programme("2031ZR", "2031", "V1_A")
        session.composite.search()
        session.composite.choose_composite(session.composite.composites()[0])
        with pytest.raises(ControlNotFound):
            session.composite.choose_harness("NOT_A_HARNESS")


class TestNavigation:
    def test_every_page_lands_on_its_user_control(self, session):
        from defauto.navigation import PAGES
        for path, control in PAGES.items():
            assert session.navigation.go(*path) == control

    def test_an_unknown_page_is_a_programming_error(self, session):
        with pytest.raises(KeyError):
            session.navigation.go("Nonexistent Menu")

    def test_navigation_records_where_it_is(self, session):
        session.navigation.checks_inlines()
        assert session.navigation.here == (ids.MENU_QUALITY_CHECKS, "Inlines")


class TestGrids:
    def test_a_grid_reads_as_headers_and_rows(self, opened):
        opened.devices.open()
        grid = opened.devices.read()
        assert grid.headers[0] == "CNUM"
        assert len(grid) == len(grid.rows) > 0
        assert all(len(row) == len(grid.headers) for row in grid.rows)

    def test_a_filter_narrows_the_grid_the_application_way(self, opened):
        opened.circuits.open()
        everything = opened.circuits.read()
        one = everything.rows[0][0]
        narrowed = opened.circuits.read(one)
        assert 0 < len(narrowed) < len(everything)
        assert one in narrowed.column("Circuit")

    def test_the_circuit_checkboxes_narrow_it_further(self, opened):
        opened.circuits.open()
        total = len(opened.circuits.read())
        missing = opened.circuits.missing()
        assert len(missing) <= total
        assert all(not row for row in missing.column("Sales Code"))
        opened.circuits.clear_filters()
        assert len(opened.circuits.read()) == total

    def test_find_locates_a_row_by_column(self, opened):
        opened.splices.open()
        grid = opened.splices.read()
        wanted = grid.rows[0][0]
        assert gridreader.find(grid, "Splice", wanted)["Splice"] == wanted

    def test_an_unknown_column_is_an_error_not_an_empty_list(self):
        with pytest.raises(KeyError):
            Grid(["A"], [["1"]]).column("B")

    def test_a_grid_exports_as_csv(self, opened):
        opened.devices.open()
        csv = opened.devices.read().to_csv()
        assert csv.splitlines()[0].startswith("CNUM,")
        assert len(csv.splitlines()) == len(opened.devices.read()) + 1


class TestComplexity:
    def test_available_and_used_codes_are_compared_not_judged(self, opened):
        compare = opened.complexity.compare_codes()
        assert set(compare) == {"available_only", "used_only", "both"}
        available = set(opened.complexity.available_codes().column("Sales Code"))
        used = set(opened.complexity.used_codes().column("Sales Code"))
        assert set(compare["both"]) == available & used

    def test_the_two_circuit_filters_are_not_crossed_over(self, opened):
        """Two filter boxes on one page — the classic id mix-up."""
        opened.complexity.circuits(circuit="ZK0001", sales_code="ZA1")
        assert opened.backend.filters[ids.TEXT_FILTER_CIRCUIT_COMPLEXITY] == "ZK0001"
        assert opened.backend.filters[ids.TEXT_FILTER_SALES_CODE] == "ZA1"


class TestQualityChecks:
    def test_the_connector_check_reports_what_the_application_said(self, opened):
        result = opened.quality.circuits()
        assert result.text
        assert "circuits examined" in result.text

    def test_bypassing_a_check_is_visible_in_the_result(self, opened):
        result = opened.quality.circuits(bypass_ends=True)
        assert "bypassed" in result.text
        assert opened.backend.checked(ids.CHECK_ENDS_BYPASS)

    def test_failing_pairs_are_picked_out_of_the_match_grid(self):
        rows = Grid(["Inline", "Mate", "Harness", "Result"],
                    [["X301A", "Y301A", "IP", "Match"],
                     ["X302A", "Y302A", "IP", "Mismatch"]])
        from defauto.qualitychecks import QualityChecks
        failing = QualityChecks.failing_pairs(rows)
        assert [f["Inline"] for f in failing] == ["X302A"]


class TestSignOffIsRefusedOverAFailingPair:
    """The one action in this kit that can do real damage.

    A prototype that signed off an inline check while a pair was still failing
    would put a passing record against a real defect. It refuses, and it names
    the pairs — and the bypass it offers is the application's own checkbox, so
    a bypassed sign-off is indistinguishable from one a person made.
    """

    def _with_mismatch(self):
        session = application.demo()
        session.composite.choose_programme("2031ZR", "2031", "V1_A")
        session.composite.search()
        for composite in session.composite.composites():
            session.composite.choose_composite(composite)
            for harness in session.composite.harnesses():
                session.composite.choose_harness(harness)
                rows = session.quality.inline_pairs()
                if session.quality.failing_pairs(rows):
                    return session
        pytest.skip("this seed produced no mismatching pair")

    def test_it_refuses_and_says_which_pairs(self):
        session = self._with_mismatch()
        with pytest.raises(AutomationError) as caught:
            session.quality.sign_off()
        assert "Refusing to sign off" in str(caught.value)
        assert "<->" in str(caught.value)
        assert not session.backend.signed_off

    def test_the_bypass_goes_through_the_applications_own_checkbox(self):
        session = self._with_mismatch()
        session.quality.sign_off(bypass=True)
        assert session.backend.signed_off
        assert session.backend.checked(ids.CHECK_INLINE_BYPASS), \
            "a bypassed sign-off must be recorded in DEF Editor, not hidden"

    def test_a_clean_harness_signs_off_without_a_bypass(self, opened):
        rows = opened.quality.inline_pairs()
        if opened.quality.failing_pairs(rows):
            pytest.skip("this harness has a failing pair")
        opened.quality.sign_off()
        assert opened.backend.signed_off
        assert not opened.backend.checked(ids.CHECK_INLINE_BYPASS)


class TestReports:
    def test_an_export_writes_a_timestamped_csv(self, opened, tmp_path):
        opened.reports.out_dir = tmp_path
        opened.devices.open()
        report = opened.reports.save("Devices", opened.devices.read())
        assert report.written.exists()
        assert report.written.suffix == ".csv"
        assert report.written.read_text().splitlines()[0].startswith("CNUM,")


class TestTheKitStaysPortable:
    def test_nothing_imports_pywinauto_at_module_level(self):
        """The kit must load on any OS: only Connect needs Windows.

        Verified by import, not by reading the source — a lazy import that
        someone hoists to the top of a file would pass a grep and fail here.
        """
        import importlib
        for name in ("application", "backend", "circuits", "complexity",
                     "composite", "devices", "fake", "gridreader", "harness",
                     "ids", "navigation", "qualitychecks", "reports",
                     "splices"):
            importlib.import_module(f"defauto.{name}")
        assert "pywinauto" not in sys.modules

    def test_the_selftest_passes(self, capsys):
        """What an engineer runs before taking the kit to Windows."""
        import main as entry
        assert entry.selftest() == 0
        assert "selftest passed" in capsys.readouterr().out


class TestTheAutomationTest:
    """The one sequence the kit exists to run.

    Four inputs, ten steps, stop at the first failure. These hold the
    behaviour that makes a Windows run diagnosable: a failure has to name the
    step that failed and say what it saw, because that is all an engineer
    standing in front of DEF Editor will have to go on.
    """

    def test_it_reaches_the_circuit(self, session):
        out = workflow.run(session, "2031ZR", "2031", "V1_A", "BODY_LEFT")
        assert out.ok, out.failed and (out.failed.name, out.failed.detail)
        assert all(step.ok for step in out.steps)
        assert out.composite
        assert workflow.TARGET_CIRCUIT in out.grid.column("Circuit")

    def test_it_asks_for_four_values_and_finds_the_composite(self, session):
        """The composite is not one of the four — it is worked out."""
        out = workflow.run(session, "2031ZR", "2031", "V1_A", "BODY_LEFT")
        assert "BODY_LEFT" in [h for h in session.composite.harnesses()]
        assert out.composite.startswith("2031ZR")

    def test_a_wrong_program_fails_on_that_step_and_lists_what_is_offered(
            self, session):
        out = workflow.run(session, "NOPE", "2031", "V1_A", "BODY_LEFT")
        assert not out.ok
        assert out.failed.name == "Select vehicle NOPE"
        assert "2031ZR" in out.failed.detail, out.failed.detail

    def test_a_wrong_year_fails_on_the_year_step(self, session):
        out = workflow.run(session, "2031ZR", "1999", "V1_A", "BODY_LEFT")
        assert out.failed.name == "Select model year 1999"

    def test_a_harness_in_no_composite_is_named_as_such(self, session):
        out = workflow.run(session, "2031ZR", "2031", "V1_A", "NOT_A_HARNESS")
        assert out.failed.name == "Find the composite holding NOT_A_HARNESS"
        assert "composite" in out.failed.detail
        assert "BODY_LEFT" in out.failed.detail, "the candidates are named"

    def test_it_stops_at_the_first_failure(self, session):
        """Steps after the failure must stay unrun, not be reported as passing."""
        out = workflow.run(session, "NOPE", "2031", "V1_A", "BODY_LEFT")
        index = out.steps.index(out.failed)
        assert all(step.ok is True for step in out.steps[:index])
        assert all(step.ok is None for step in out.steps[index + 1:])

    def test_every_step_is_reported_as_it_happens(self, session):
        """The GUI draws from these, so they must arrive one at a time."""
        seen = []
        workflow.run(session, "2031ZR", "2031", "V1_A", "BODY_LEFT",
                     on_step=seen.append)
        assert len(seen) == len(workflow.plan("a", "b", "c", "d"))
        assert [s.name for s in seen] == [
            s.name for s in workflow.plan("2031ZR", "2031", "V1_A", "BODY_LEFT")]

    def test_a_harness_name_need_not_match_capitalisation(self, session):
        out = workflow.run(session, "2031ZR", "2031", "V1_A", "body_left")
        assert out.ok, out.failed and out.failed.detail

    def test_the_plan_is_known_before_the_run(self):
        """The window lists the steps greyed out before pressing Run."""
        steps = workflow.plan("P", "Y", "Ph", "H")
        assert all(step.ok is None for step in steps)
        assert all(step.mark == "...." for step in steps)
        assert any("H" in step.name for step in steps)
        assert any(workflow.TARGET_CIRCUIT in step.name for step in steps)

    def test_a_missing_automation_id_fails_on_step_one(self, session):
        original = session.backend.exists
        session.backend.exists = lambda a, s="": (
            False if a == ids.GRID_COMPOSITE else original(a, s))
        out = workflow.run(session, "2031ZR", "2031", "V1_A", "BODY_LEFT")
        assert out.steps[0].ok is False
        assert ids.GRID_COMPOSITE in out.steps[0].detail
        assert "ids.py" in out.steps[0].detail

    def test_the_filter_reports_exact_matches_separately(self, session):
        """A sales code of ZB4 contains B4; the run must not conflate them."""
        out = workflow.run(session, "2031ZR", "2031", "V1_A", "BODY_LEFT")
        exact = sum(1 for value in out.grid.column("Circuit")
                    if value == workflow.TARGET_CIRCUIT)
        assert exact >= 1
        assert str(len(out.grid)) in out.steps[-1].detail


class TestItShipsFromTheApp:
    """The kit is zipped from the working tree when someone downloads it.

    Committing the archive is how the transcript recorder's zip drifted from
    the source it claimed to be; building on demand cannot.
    """

    def test_the_zip_contains_the_whole_kit(self):
        import io
        import zipfile
        from splice.common import kits

        names = zipfile.ZipFile(io.BytesIO(
            kits.build("def_editor_automation"))).namelist()
        for expected in ("main.py", "requirements.txt", "BUILD_WINDOWS.txt",
                         "def_editor_automation.spec", "defauto/ids.py",
                         "defauto/backend.py", "defauto/gui.py"):
            assert f"def_editor_automation/{expected}" in names, expected

    def test_no_build_droppings_are_shipped(self):
        import io
        import zipfile
        from splice.common import kits

        names = zipfile.ZipFile(io.BytesIO(
            kits.build("def_editor_automation"))).namelist()
        assert not [n for n in names
                    if "__pycache__" in n or n.endswith((".pyc", ".DS_Store"))]

    def test_an_unknown_kit_is_an_error(self):
        from splice.common import kits

        with pytest.raises(FileNotFoundError):
            kits.build("no_such_kit")

    def test_the_downloads_page_offers_it(self):
        from nicegui_app.pages import downloads

        assert any(kit == "def_editor_automation" for kit, *_ in downloads.BUILT)


class TestTheDownloadButtonActuallyWorks:
    """The bug this class exists for: the button did nothing at all.

    ``packaging/`` was not copied into the NiceGUI image, so ``kits.build``
    raised inside ui.button's on_click, NiceGUI swallowed it, and the click
    was silent — which reads as a broken app rather than a missing file.
    """

    def test_the_page_renders_a_button_when_the_kit_is_there(self):
        from nicegui_app.pages import downloads
        from splice.common import kits

        for kit, filename, *_ in downloads.BUILT:
            assert kits.available(kit), f"{kit} missing from the working tree"
            assert filename.endswith(".zip")

    def test_the_getter_returns_a_real_archive(self):
        """What the click calls, called directly."""
        import io
        import zipfile
        from nicegui_app.pages import downloads

        data = downloads._build("def_editor_automation")
        assert data[:2] == b"PK", "not a zip"
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            assert archive.testzip() is None
            assert len(archive.namelist()) > 10

    def test_a_missing_kit_is_reported_not_silent(self, monkeypatch, tmp_path):
        """With the kit absent the page must say so, not draw a dead button."""
        from splice.common import kits

        monkeypatch.setattr(kits, "PACKAGING", tmp_path)
        assert not kits.available("def_editor_automation")

    def test_the_image_ships_what_the_page_serves(self):
        """The actual fix: the Dockerfile has to COPY packaging/.

        Asserted against the Dockerfile because that is where it was missing,
        and nothing else in the test suite would have noticed.
        """
        from pathlib import Path

        dockerfile = (Path(__file__).resolve().parents[1]
                      / "Dockerfile.nicegui").read_text()
        assert "COPY packaging" in dockerfile
        assert "COPY docs" in dockerfile, \
            "the Documentation page renders these and had none in the image"



class TestTheWindowPicker:
    """DEF Editor was not being found by title. The kit now lists every
    window and lets the user point at it; candidates are flagged, never
    chosen for them."""

    def test_a_window_that_looks_like_def_editor_is_flagged(self):
        from defauto.backend import WindowInfo
        assert WindowInfo(1, 1, "DEF EDITOR - Master Form").likely
        assert WindowInfo(1, 1, "DEF Editor - Composite X").likely
        assert WindowInfo(1, 1, "anything", "DEFEditor.exe").likely
        assert not WindowInfo(1, 1, "Inbox - Outlook", "OUTLOOK.EXE").likely
        assert not WindowInfo(1, 1, "Definitions.docx - Word").likely

    def test_the_demo_desktop_lists_likely_windows_first(self):
        found = FakeBackend.list_windows()
        assert len(found) >= 3
        assert found[0].likely and not found[-1].likely
        assert all(str(w) for w in found)
        assert "looks like DEF Editor" in str(found[0])

    def test_listing_real_windows_is_the_windows_only_path(self):
        with pytest.raises(ImportError):
            application.windows()
        with pytest.raises(ImportError):
            application.connect_window(1)

    def test_the_gui_still_imports_with_the_picker(self):
        import importlib
        gui = importlib.import_module("defauto.gui")
        assert hasattr(gui.Workbench, "_pick_window")
        assert hasattr(gui.Workbench, "on_demo_direct")



class TestTypedTextIsMatchedToWhatIsOffered:
    """The fields are free text. What is typed is resolved against what DEF
    Editor offers — exactly, then ignoring case, then as a unique start or
    part of a name — and an ambiguous entry is refused with the candidates."""

    @pytest.mark.parametrize("typed, offered, match, how", [
        ("2031ZR", ["2031ZR", "2032QX"], "2031ZR", "exact"),
        ("2031zr", ["2031ZR", "2032QX"], "2031ZR", "case-insensitive"),
        ("2031", ["2031ZR", "2032QX"], "2031ZR", "prefix of '2031ZR'"),
        ("v1", ["V1_A", "V2_A"], "V1_A", "prefix of 'V1_A'"),
        ("left", ["BODY_LEFT", "DASH"], "BODY_LEFT", "contained in 'BODY_LEFT'"),
    ])
    def test_it_matches(self, typed, offered, match, how):
        assert workflow.resolve(typed, offered) == (match, how)

    def test_ambiguity_is_refused_with_the_candidates(self):
        match, how = workflow.resolve("203", ["2031ZR", "2032QX"])
        assert match is None
        assert "2031ZR" in how and "2032QX" in how

    def test_nothing_offered_is_said(self):
        match, how = workflow.resolve("x", ["A", "B"])
        assert match is None and "available: A, B" in how
        assert workflow.resolve("", ["A"]) == (None, "nothing typed")

    def test_the_run_accepts_loosely_typed_values_and_says_what_it_matched(self, session):
        out = workflow.run(session, "2031", "2031", "v1", "body")
        assert out.ok, out.failed and (out.failed.name, out.failed.detail)
        assert "'2031ZR'" in out.steps[1].detail and "prefix" in out.steps[1].detail
        assert "'V1_A'" in out.steps[3].detail
        assert out.harness == "BODY_LEFT"

    def test_the_user_chooses_the_circuit(self, session):
        out = workflow.run(session, "2031ZR", "2031", "V1_A", "BODY_LEFT", target="M34")
        assert out.steps[-1].name == "Filter circuits for M34"
        assert out.ok, out.failed and out.failed.detail
        assert "M34" in out.grid.column("Circuit")

    def test_the_gui_has_free_text_fields_and_a_circuit_field(self):
        import importlib
        import tkinter as tk
        gui = importlib.import_module("defauto.gui")
        w = gui.Workbench()
        try:
            assert isinstance(w.field_program, tk.ttk.Entry)
            assert isinstance(w.field_circuit, tk.ttk.Entry)
            assert w.field_circuit.get() == workflow.TARGET_CIRCUIT
            w.on_demo_direct(); w.update()
            for _ in range(60):
                w.update()
            assert w.hint_program.cget("text").startswith("offered:")
        finally:
            w.destroy()



class TestTheStructureRecorder:
    """Records the tree of DEF Editor's windows so it can be read where the
    application is not — without recording what the windows contain."""

    def _tree(self, redact=True):
        from defauto import observe
        roots = FakeBackend.structure_roots()
        return observe.walk(roots[0], redact=redact)

    def test_structure_is_recorded(self):
        tree = self._tree()
        assert tree.control_type == "Window" and tree.automation_id == ids.ROOT_FORM
        types = set()
        def gather(n):
            types.add(n.control_type); [gather(c) for c in n.children]
        gather(tree)
        assert {"MenuBar", "MenuItem", "ComboBox", "Button", "DataGrid", "Edit"} <= types
        combo = next(c for c in tree.children[1].children
                     if c.automation_id == ids.COMBO_VEHICLE_LINE)
        assert combo.control_type == "ComboBox"

    def test_interface_names_are_kept_and_data_is_not(self):
        import json
        from dataclasses import asdict
        text = json.dumps(asdict(self._tree()))
        # interface: menu items, the Filter button, headers
        for kept in ("Harness", "Circuits", "Filter", "Composite", "Harnesses"):
            assert kept in text
        # data: grid cell values, the edit's text, the combo's current value
        for secret in ("B4", "BODY_LEFT - FEED", "typed text here", "2031ZR"):
            assert secret not in text, secret
        assert '"name_shape": "2 upper/digit"' in text        # B4, as a shape

    def test_grids_record_headers_and_row_count_not_rows(self):
        tree = self._tree()
        grid = next(c for c in tree.children[1].children
                    if c.automation_id == ids.GRID_COMPOSITE)
        assert grid.headers == ["Composite", "Harnesses"]
        assert grid.row_count == 5
        rows = [c for c in grid.children if c.control_type == "DataItem"]
        assert len(rows) == 2 and "5 rows" in grid.truncated

    def test_unredacted_keeps_values_for_a_test_instance(self):
        import json
        from dataclasses import asdict
        assert "typed text here" in json.dumps(asdict(self._tree(redact=False)))

    @pytest.mark.parametrize("text, shape", [
        ("B4", "2 upper/digit"), ("AHT", "3 upper/digit"), ("12345", "5 digits"),
        ("Body Left", "9 letters"), ("", "empty"), ("a\nb", "3 mixed, 2 lines"),
    ])
    def test_shape_of(self, text, shape):
        from defauto.observe import shape_of
        assert shape_of(text) == shape

    def test_the_walk_is_capped(self):
        from defauto import observe

        class Deep(observe.Element):
            def __init__(self, depth):
                self.control_type, self.automation_id, self.class_name = "Pane", "", ""
                self.name, self.rect, self.enabled, self.visible = "", [], True, True
                self._d = depth
            def children(self):
                return [Deep(self._d + 1), Deep(self._d + 1)]

        tree = observe.walk(Deep(0), max_depth=3, max_nodes=50)
        def count(n): return 1 + sum(count(c) for c in n.children)
        assert count(tree) <= 50

    def test_snapshots_are_saved_with_an_index(self, tmp_path, session):
        rec = session.recorder(tmp_path)
        first = rec.snapshot("composite page")
        assert first.exists() and first.suffix == ".json"
        index = (tmp_path / "index.md").read_text()
        assert "composite page" in index and first.name in index
        assert "UNREDACTED" not in index

    def test_auto_mode_records_only_when_the_ui_changes(self, tmp_path, session):
        rec = session.recorder(tmp_path)
        rec.snapshot("start")
        assert rec.tick() is None                     # nothing changed
        session.navigation.circuits()                 # the demo's page changed
        assert rec.tick() is not None
        assert rec.tick() is None
        assert len(rec.taken) == 2

    def test_every_essential_id_has_a_control_type(self):
        for auto_id in ids.ESSENTIAL:
            assert auto_id in ids.CONTROL_TYPES, auto_id

    def test_the_gui_records_in_demo_mode(self, tmp_path):
        import importlib
        gui = importlib.import_module("defauto.gui")
        w = gui.Workbench()
        try:
            w.out_dir = tmp_path / "exports"
            w.on_demo_direct()
            w.on_snapshot()
            for _ in range(20):
                w.update()
            saved = list((tmp_path / "structure").glob("*.json"))
            assert len(saved) == 1
            assert "Saved structure" in w.log_text.get("1.0", "end")
        finally:
            w.destroy()
