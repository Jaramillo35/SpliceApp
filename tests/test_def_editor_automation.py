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

from defauto import application, gridreader, ids            # noqa: E402
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
