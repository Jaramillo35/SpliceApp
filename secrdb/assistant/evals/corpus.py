"""An invented SECR corpus: what the evaluation questions are asked of.

Nothing here exists outside this file. Programmes ``QX`` and ``ZR``, model
years 2030 and 2031, connectors ``Q###X``, circuits ``K###X`` and DTCRs
``701##`` are made up, generated from a seed so the same seed is the same
corpus — a score is only comparable between runs if the questions are.

The workbooks follow the real SECR layout the importer was proven on (a
Summary sheet, an Add/Remove sheet holding the connector and the circuit
table, a Connector sheet, a Circuit sheet with ``(Old)`` columns and
``DNUM | CAV`` endpoints, a DEF_DEF_Summary), so the corpus goes through the
same parser as a field import rather than being inserted behind its back.
"""

from __future__ import annotations

import io
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple

import openpyxl

PROGRAMS = ("QX", "ZR")
MODEL_YEARS = ("2030", "2031")
PHASES = ("V1", "V2")
FAMILIES = ("BODY_LEFT", "IP", "ENGINE", "DOOR_FRONT")
GAUGES = ("0.35", "0.50", "0.75", "1.00")
COLORS = ("GN/RD", "VT/BU", "PK/YE", "BK/WH", "OG/GY")


@dataclass
class ConnectorChange:
    cnum: str
    old_pn: str
    new_pn: str
    dtcr: str


@dataclass
class CircuitChange:
    circuit: str            # as stored: number + suffix, e.g. K106A
    number: str
    suffix: str
    old_gauge: str
    new_gauge: str
    color: str
    from_cnum: str
    from_cav: str
    to_cnum: str
    to_cav: str
    dtcr: str


@dataclass
class SecrSpec:
    secr_number: str
    program: str
    model_year: str
    phase: str
    harness_family: str
    dtcrs: List[str]
    connectors: List[ConnectorChange] = field(default_factory=list)
    circuits: List[CircuitChange] = field(default_factory=list)

    @property
    def filename(self) -> str:
        return f"SECR_{self.harness_family}_{self.secr_number}_V1.xlsx"


@dataclass
class Corpus:
    seed: int
    secrs: List[SecrSpec]

    def import_into(self, db_path: Path) -> None:
        from secrdb.core.secr.importer import import_secr_files  # noqa: PLC0415
        summary = import_secr_files([(s.filename, workbook(s)) for s in self.secrs],
                                    db_path=db_path)
        if len(summary.imported) != len(self.secrs):
            raise RuntimeError(f"the evaluation corpus did not import cleanly: {summary}")


def build_corpus(seed: int = 2031, secrs: int = 8) -> Corpus:
    rng = random.Random(seed)
    cnums = [f"Q{n}{s}" for n in range(101, 101 + secrs * 4) for s in "A"]
    rng.shuffle(cnums)
    out: List[SecrSpec] = []
    dtcr = 70100
    for i in range(secrs):
        program = PROGRAMS[i % len(PROGRAMS)]
        year = MODEL_YEARS[(i // 2) % len(MODEL_YEARS)]
        phase = PHASES[(i // 4) % len(PHASES)]
        family = FAMILIES[i % len(FAMILIES)]
        number = f"D{year[-2:]}{phase}{program}_{1000 + i}"
        own = [cnums.pop() for _ in range(4)]
        dtcrs = [str(dtcr + 1), str(dtcr + 2)]
        dtcr += 2
        connectors = [
            ConnectorChange(own[0], f"PN{i}0-OLD", f"PN{i}0-NEW", dtcrs[0]),
            ConnectorChange(own[1], f"PN{i}1-OLD", f"PN{i}1-NEW", dtcrs[1]),
        ]
        circuits = []
        for j in range(3):
            num, suffix = f"K{200 + i * 10 + j}", "AB"[j % 2]
            old, new = rng.sample(GAUGES, 2)
            circuits.append(CircuitChange(
                circuit=num + suffix, number=num, suffix=suffix, old_gauge=old,
                new_gauge=new, color=rng.choice(COLORS), from_cnum=own[2],
                from_cav=str(j + 1), to_cnum=own[j % 2], to_cav=str(j + 5),
                dtcr=dtcrs[j % 2]))
        out.append(SecrSpec(number, program, year, phase, family, dtcrs, connectors, circuits))
    return Corpus(seed=seed, secrs=out)


def _row(ws, row: int, values: List) -> None:
    for column, value in enumerate(values, start=1):
        ws.cell(row=row, column=column, value=value)


def workbook(spec: SecrSpec) -> bytes:
    wb = openpyxl.Workbook()
    summary = wb.active
    summary.title = "Summary"
    for cell, value in (
        ("I2", spec.secr_number), ("I3", "1"), ("I4", "2030-01-15"),
        ("C7", f"{spec.model_year[-2:]} {spec.phase} RELEASE"),
        ("C8", f"SECR_{spec.harness_family}_{spec.secr_number}_V1"),
        ("C10", spec.model_year), ("C11", spec.program), ("F10", spec.phase),
        ("C12", spec.harness_family), ("F11", spec.phase), ("F12", "N"),
        ("I10", "A. Engineer"), ("I11", "B. Releaser"), ("I12", "OEM"),
        ("C14", ", ".join(spec.dtcrs)), ("G14", ""),
        ("C26", ", ".join(c.circuit for c in spec.circuits)),
    ):
        summary[cell] = value

    add_remove = wb.create_sheet("Add_Remove_Report_Summary")
    _row(add_remove, 1, ["Connector Add/Remove Report"])
    _row(add_remove, 2, ["SE Comment", "Action", "FCA-CNUM", "Suffix(New)", "Suffix(Old)",
                         "DEF_Connector_PN", "DEF_Connector_PN(Old)", "DEF_Connector_Supplier"])
    _row(add_remove, 3, ["Circuit Add/Remove Report"])
    _row(add_remove, 4, ["SE Comment", "Action", "CKT NBR", "CKT Suffix", "DEF CKT COLOR",
                         "DEF CKT COLOR(Old)", "DEF GAUGE", "DEF GAUGE(Old)"])

    connector = wb.create_sheet("Connector")
    _row(connector, 3, ["SE Comment", "Action", "FCA-CNUM", "Suffix(New)", "Suffix(Old)",
                        "DEF_Connector_PN", "DEF_Connector_PN(Old)", "DEF_Connector_Supplier"])
    for r, c in enumerate(spec.connectors, start=4):
        _row(connector, r, [f"DTCR {c.dtcr}", "COMP CHG", c.cnum, "SFX", "SFX",
                            c.new_pn, c.old_pn, "S1"])

    circuit = wb.create_sheet("Circuit")
    _row(circuit, 3, ["SE Comments", "Action", "CKT NBR", "CKT Suffix", "DEF CKT COLOR",
                      "DEF CKT COLOR(Old)", "DEF GAUGE", "DEF GAUGE(Old)",
                      "CKT FROM (DNUM | CAV)", "Sales_Code", "Sales_Code (Old)",
                      "CKT To (DNUM | CAV)"])
    for r, c in enumerate(spec.circuits, start=4):
        _row(circuit, r, [f"DTCR {c.dtcr}", "CHG", c.number, c.suffix, c.color, c.color,
                          c.new_gauge, c.old_gauge, f"{c.from_cnum}|{c.from_cav}",
                          "ZZ1", "ZZ1", f"{c.to_cnum}|{c.to_cav}"])

    def_def = wb.create_sheet("DEF_DEF_Summary")
    _row(def_def, 3, ["SE Comment", "Action", "Harness PN", "DEF Symbol",
                      "Harness PN (Old)", "DEF Symbol (Old)"])
    buffer = io.BytesIO()
    wb.save(buffer)
    wb.close()
    return buffer.getvalue()


def absent_identifiers() -> Tuple[str, str, str]:
    """A circuit, a connector and a DTCR that no corpus can contain."""
    return "K999Z", "Q999Z", "79999"
