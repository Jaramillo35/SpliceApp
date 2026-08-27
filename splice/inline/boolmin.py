"""Minimal display forms for sales-code expressions.

The health check composes windows mechanically — unions of every wire's
expression, differenced against the other side — so a window like

    (((XZ2&(RHH/RTC/RDU))/(XZ2&-RHH&-RDU))/(...))&-((XZ2&...)/(...))

is logically tiny but textually huge. :func:`minimize` reduces such an
expression to its minimal sum-of-products via a truth table and
Quine-McCluskey, then factors literals common to every term, yielding e.g.

    -XZ2&(RDU/RHH/RTC/XZ3)

A shorter form is possible only where the loaded complexity tables prove
some branch unbuildable — see the ``configurations`` argument. Nothing about
which codes travel together is assumed here; it is read from the data.

Guarantees:

* the truth table is built with the engine's own evaluator
  (:func:`splice.inline.salescode.evaluate`), so the minimizer inherits its
  exact semantics — including its tolerance for data quirks like the
  ``(/RHH/RTC/RDU)`` leading-slash typo found in real summaries;
* the result is verified logically equivalent to the input over ALL
  assignments of its codes before being returned — on any doubt (too many
  variables, no size win, anything unexpected) the ORIGINAL string comes
  back.

Display only: fingerprints and stored windows keep the raw expression, so
existing disposition baselines are untouched.
"""

from __future__ import annotations

from functools import lru_cache
from itertools import combinations
from typing import List, Tuple

from splice.inline import salescode

MAX_VARS = 12  # 4096-row truth table; windows beyond this stay verbose


# --------------------------------------------------------------------- Quine-McCluskey

def _combine(implicants: set) -> set:
    """One QM pass: merge implicants differing in exactly one cared-for bit."""
    merged, used = set(), set()
    for (b1, m1), (b2, m2) in combinations(implicants, 2):
        if m1 != m2:
            continue
        diff = b1 ^ b2
        if diff and (diff & (diff - 1)) == 0:  # exactly one bit
            merged.add((b1 & ~diff, m1 & ~diff))
            used.add((b1, m1))
            used.add((b2, m2))
    return merged | (implicants - used)


def _prime_implicants(minterms: List[int], nbits: int) -> List[Tuple[int, int]]:
    full_mask = (1 << nbits) - 1
    current = {(m, full_mask) for m in minterms}
    while True:
        nxt = _combine(current)
        if nxt == current:
            return sorted(current)
        current = nxt


def _covers(implicant: Tuple[int, int], minterm: int) -> bool:
    bits, mask = implicant
    return (minterm & mask) == (bits & mask)


def _cover(primes: List[Tuple[int, int]], minterms: List[int]) -> List[Tuple[int, int]]:
    """Essential primes first, then greedy set cover for the rest."""
    chosen, remaining = [], set(minterms)
    for m in minterms:
        covering = [p for p in primes if _covers(p, m)]
        if len(covering) == 1 and covering[0] not in chosen:
            chosen.append(covering[0])
    for p in chosen:
        remaining -= {m for m in remaining if _covers(p, m)}
    while remaining:
        best = max(primes, key=lambda p: len({m for m in remaining if _covers(p, m)}))
        gain = {m for m in remaining if _covers(best, m)}
        if not gain:
            break
        chosen.append(best)
        remaining -= gain
    return chosen


# --------------------------------------------------------------------------- format

def _format(cover: List[Tuple[int, int]], names: List[str]) -> str:
    def literals(bits: int, mask: int) -> List[str]:
        out = []
        for i, name in enumerate(names):
            if mask & (1 << i):
                out.append(name if bits & (1 << i) else f"-{name}")
        return sorted(out, key=lambda lit: lit.lstrip("-"))

    terms = [literals(b, m) for b, m in cover]
    if not terms:
        return ""
    if len(terms) == 1:
        return "&".join(terms[0])

    # factor literals common to EVERY term:  (-A&B)/( -A&C)  ->  -A&(B/C)
    common = set(terms[0])
    for t in terms[1:]:
        common &= set(t)
    if common:
        residues = ["&".join(lit for lit in t if lit not in common) or None
                    for t in terms]
        head = "&".join(sorted(common, key=lambda lit: lit.lstrip("-")))
        if all(res is None for res in residues):
            return head
        group = "/".join(sorted(
            (f"({res})" if "&" in res else res) for res in residues if res))
        return f"{head}&({group})"

    return "/".join(("&".join(t) if len(t) == 1 else f"({'&'.join(t)})")
                    for t in sorted(terms))


# --------------------------------------------------------------------------- api

@lru_cache(maxsize=4096)
def minimize(expression: str, configurations: tuple = ()) -> str:
    """The minimal display form of ``expression`` — or the original whenever
    minimization is unsafe, impossible, or simply not shorter.

    ``configurations`` — optional tuple of ``(codes, vocabulary)`` frozenset
    pairs describing the builds the relevant complexity tables actually ship
    (vocabulary = the codes that harness tracks; a window code outside it is
    treated as present, mirroring ``builds_where``). When given, only the
    assignments realizable by those builds are *cares*; every unbuildable
    combination is a don't-care Quine-McCluskey may exploit. This is what
    lets a branch that no loaded build can reach drop out of the display.

    Co-occurrence is never assumed programme-wide: it is derived per call
    from the harnesses passed in. If one harness's table shows two codes
    always travelling together but another in the same window can build one
    without the other, the branch stays a *care* and survives the reduction.
    Equivalence is guaranteed on every buildable configuration in the care
    set (and only claimed there).
    """
    if not expression or not expression.strip():
        return expression
    try:
        names = sorted(salescode.codes_in(expression))
        if not names or len(names) > MAX_VARS:
            return expression
        n = len(names)

        # project the buildable configurations onto the window's codes
        cares: set[int] | None = None
        if configurations:
            cares = set()
            for codes, vocabulary in configurations:
                assignment = 0
                for i, name in enumerate(names):
                    known = vocabulary is None or name in vocabulary
                    if (name in codes) or not known:
                        assignment |= 1 << i
                cares.add(assignment)
            if not cares:
                cares = None

        table: List[bool] = []
        minterms: List[int] = []
        care_true = care_false = 0
        for assignment in range(1 << n):
            on = {names[i] for i in range(n) if assignment & (1 << i)}
            value = salescode.evaluate(expression, on)
            table.append(value)
            if value:
                minterms.append(assignment)
            if cares is not None and assignment in cares:
                if value:
                    care_true += 1
                else:
                    care_false += 1
        if not minterms or len(minterms) == 1 << n:
            return expression  # never/always true: keep the evidence verbose

        if cares is not None:
            if not care_true or not care_false:
                # constant on every buildable configuration — a constant
                # display would hide the evidence; keep the raw window
                cares = None
            else:
                cover_terms = [m for m in minterms if m in cares]
                dont_cares = [a for a in range(1 << n) if a not in cares]
                primes = _prime_implicants(cover_terms + dont_cares, n)
                short = _format(_cover(primes, cover_terms), names)
        if cares is None:
            primes = _prime_implicants(minterms, n)
            short = _format(_cover(primes, minterms), names)
        if not short or len(short) >= len(expression):
            return expression

        # safety: the short form must agree with the original on every
        # assignment that matters (all of them, or the buildable cares)
        checked = cares if cares is not None else range(1 << n)
        for assignment in checked:
            on = {names[i] for i in range(n) if assignment & (1 << i)}
            if salescode.evaluate(short, on) != table[assignment]:
                return expression
        return short
    except Exception:
        return expression


def care_configurations(*harnesses) -> tuple:
    """Hashable build/vocabulary pairs for :func:`minimize`, from Harness
    objects (duplicates collapse; harnesses without builds contribute none)."""
    pairs = set()
    for harness in harnesses:
        if harness is None or not getattr(harness, "builds", None):
            continue
        vocabulary = frozenset(getattr(harness, "complexity_codes", ()) or ())
        for build in harness.builds:
            pairs.add((frozenset(build.codes), vocabulary or None))
    return tuple(sorted(pairs, key=str))
