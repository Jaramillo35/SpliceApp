"""Minimal display forms for sales-code expressions.

The health check composes windows mechanically — unions of every wire's
expression, differenced against the other side — so a window like

    (((XZ2&(RHH/RTC/RDU))/(XZ2&-RHH&-RDU))/(...))&-((XZ2&...)/(...))

is logically tiny but textually huge. :func:`minimize` reduces such an
expression to its minimal sum-of-products via a truth table and
Quine-McCluskey, then factors literals common to every term, yielding e.g.

    -XZ2&-XZ3&(RDU/RHH/RTC)

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
def minimize(expression: str) -> str:
    """The minimal display form of ``expression`` — or the original whenever
    minimization is unsafe, impossible, or simply not shorter."""
    if not expression or not expression.strip():
        return expression
    try:
        names = sorted(salescode.codes_in(expression))
        if not names or len(names) > MAX_VARS:
            return expression

        n = len(names)
        table: List[bool] = []
        minterms: List[int] = []
        for assignment in range(1 << n):
            on = {names[i] for i in range(n) if assignment & (1 << i)}
            value = salescode.evaluate(expression, on)
            table.append(value)
            if value:
                minterms.append(assignment)
        if not minterms or len(minterms) == 1 << n:
            return expression  # never/always true: keep the evidence verbose

        primes = _prime_implicants(minterms, n)
        short = _format(_cover(primes, minterms), names)
        if not short or len(short) >= len(expression):
            return expression

        # safety: the short form must agree with the original on EVERY
        # assignment under the engine's evaluator, or the original is kept
        for assignment in range(1 << n):
            on = {names[i] for i in range(n) if assignment & (1 << i)}
            if salescode.evaluate(short, on) != table[assignment]:
                return expression
        return short
    except Exception:
        return expression
