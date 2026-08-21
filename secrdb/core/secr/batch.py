"""Generating several SECRs from several DEF-to-DEF compares in one pass.

An engineer releasing a phase does not produce one SECR; they produce one per
harness family, from a folder of compares, all carrying the same author, DRE,
requester and dates. Doing that a file at a time is repetition, and repetition
is where the numbering mistakes came from.

This module holds the part that has nothing to do with Streamlit: planning a
set of compares, projecting the numbers they will be issued, generating them,
and packaging the result. The page renders it.
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from secrdb.core.common.errors import SpliceError
from secrdb.core.common.logging import get_logger
from secrdb.core.secr import generation
from secrdb.core.secr.identity import (
    CHANGE_TYPE_DESIGN,
    SecrMetadata,
    scope_key,
)

logger = get_logger(__name__)

#: ``(filename, bytes)`` — one uploaded DEF-to-DEF compare.
CompareFile = Tuple[str, bytes]


@dataclass
class PlannedCompare:
    """One compare, its plan, and the number it is projected to receive."""

    name: str
    payload: bytes
    plan: generation.NewSecrPlan
    number: Optional[int] = None

    @property
    def ready(self) -> bool:
        return self.plan.can_generate

    @property
    def metadata(self) -> SecrMetadata:
        return self.plan.metadata


@dataclass
class BatchResult:
    """What a batch produced, including what it could not."""

    results: List[generation.GeneratedSecr] = field(default_factory=list)
    failures: List[Tuple[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.results) and not self.failures


def signature_for(files: Sequence[CompareFile], change_type: str) -> str:
    """A stable fingerprint of the inputs a generation came from.

    The page uses this to drop a previous result once the uploads change.
    Without it the success panel and its download button survive a new upload,
    so a second compare looks like it did nothing and the file on offer is
    still the previous SECR's — which is how one compare came to be generated
    three times, as 1005, 1006 and 1007.
    """
    digest = hashlib.sha256(change_type.encode("utf-8"))
    for name, payload in files:
        digest.update(name.encode("utf-8", "replace"))
        digest.update(hashlib.sha256(payload).digest())
    return digest.hexdigest()


def plan_batch(
    files: Sequence[CompareFile],
    change_type: str = CHANGE_TYPE_DESIGN,
    *,
    db_path: Optional[Path] = None,
) -> List[PlannedCompare]:
    """Plan every compare, projecting the numbers across the batch.

    Numbers are *projected* rather than peeked per file: within one Model Year
    and Phase the sequence is not consumed until generation, so peeking once
    per file would show every SECR in that scope the same number. A compare
    that cannot be read, or whose metadata is incomplete, is kept in the list
    as a blocked entry — one bad file must not hide the good ones — and
    consumes no number.
    """
    projected: Dict[Tuple[str, str], int] = {}
    planned: List[PlannedCompare] = []

    for name, payload in files:
        try:
            plan = generation.plan_new_secr(
                payload, name, change_type, db_path=db_path
            )
        except Exception as exc:  # noqa: BLE001 - reported per file, not fatal
            logger.warning("Could not plan %s: %s", name, exc)
            plan = generation.NewSecrPlan(
                metadata=SecrMetadata(),
                change_type=change_type,
                sequence_number=0,
                problems=[f"Could not read the DEF compare file: {exc}"],
            )

        number = None
        if plan.can_generate:
            key = scope_key(plan.metadata.model_year, plan.metadata.phase)
            number = projected.get(key, plan.sequence_number)
            projected[key] = number + 1

        planned.append(
            PlannedCompare(name=name, payload=payload, plan=plan, number=number)
        )
    return planned


def generate_batch(
    planned: Sequence[PlannedCompare],
    shared: Optional[Dict[str, Any]] = None,
    dtcr_matching_bytes: Optional[bytes] = None,
    *,
    on_progress: Optional[Callable[[float, str], None]] = None,
    db_path: Optional[Path] = None,
) -> BatchResult:
    """Generate each ready compare, keeping going when one fails.

    ``shared`` carries the details every SECR in the set has in common — the
    author, the DRE, who asked, the dates — entered once and applied to all.

    A failure part-way through does **not** roll back what was already written:
    each SECR is a complete, numbered record the moment it is stored, and
    undoing one because a later file was malformed would destroy good work.
    What failed is reported per file so the engineer knows exactly what to
    retry.
    """
    outcome = BatchResult()
    ready = [item for item in planned if item.ready]
    shared = dict(shared or {})

    for index, item in enumerate(ready, start=1):
        if on_progress:
            on_progress(index / len(ready), item.name)
        try:
            outcome.results.append(
                generation.generate_new_secr(
                    item.payload,
                    item.name,
                    item.plan,
                    dtcr_matching_bytes=dtcr_matching_bytes,
                    db_path=db_path,
                    **shared,
                )
            )
        except SpliceError as exc:
            outcome.failures.append((item.name, str(exc)))
        except Exception as exc:  # noqa: BLE001 - one bad file, not a dead batch
            logger.exception("Generating %s failed", item.name)
            outcome.failures.append((item.name, f"Unexpected error: {exc}"))
    return outcome


def zip_results(results: Sequence[generation.GeneratedSecr]) -> bytes:
    """One archive of the generated workbooks, named as they were issued."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for result in results:
            archive.writestr(result.filename, result.secr_bytes)
    return buffer.getvalue()
