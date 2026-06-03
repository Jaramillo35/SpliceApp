from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import re
from typing import Any, Iterable

import pandas as pd

try:
    from sympy import And, Not, Or, SOPform, Symbol, simplify_logic
except Exception:  # pragma: no cover
    And = Not = Or = SOPform = Symbol = simplify_logic = None


SALES_TOKEN_RE = re.compile(r"\s*([A-Za-z0-9_.]+|[()&/\-])\s*")
SD454_VARIANT_RE = re.compile(r"^SD454[A-Z]$", re.IGNORECASE)


@dataclass(frozen=True)
class Endpoint:
    cnum: str
    pin: str
    circuit: str
    sales_code: str


@dataclass
class Configuration:
    configuration_id: str
    circuit_name: str
    endpoints: list[Endpoint]
    target_harness_pns: list[str]
    generated_sales_code: str = ""
    generated_sales_code_display: str = ""
    topology_type: str = ""


class ExpressionSyntaxError(ValueError):
    pass


class SalesExpression:
    def __init__(self, postfix_tokens: list[str], symbols: set[str]):
        self.postfix_tokens = postfix_tokens
        self.symbols = symbols


def _normalize_text(value: Any) -> str:
    if pd.isna(value):
        return ""
    return str(value).replace("\xa0", " ").strip()


def _normalize_sales_expr(value: Any) -> str:
    expr = _normalize_text(value)
    return re.sub(r"\s+", "", expr)


def _truthy_complexity_cell(value: Any) -> bool:
    text = _normalize_text(value).upper()
    if text == "":
        return False
    return text == "X" or text in {"1", "TRUE", "YES"}


def _find_sheet_name(excel_file: pd.ExcelFile, candidates: Iterable[str]) -> str:
    lower_to_actual = {name.strip().lower(): name for name in excel_file.sheet_names}
    for candidate in candidates:
        if candidate.lower() in lower_to_actual:
            return lower_to_actual[candidate.lower()]
    raise ValueError(f"Could not find any of these sheets: {list(candidates)}")


def _display_pn(harness_key: str) -> str:
    return harness_key.split("__")[0]


def _display_pn_list(harness_keys: list[str]) -> str:
    ordered: list[str] = []
    seen: set[str] = set()
    for key in harness_keys:
        display = _display_pn(key)
        if display in seen:
            continue
        seen.add(display)
        ordered.append(display)
    return ", ".join(ordered)


def _safe_excel_sheet_name(raw_name: str, used_names: set[str]) -> str:
    """Return an Excel-safe, unique sheet name (max 31 chars)."""
    cleaned = re.sub(r"[\[\]:*?/\\]", "_", str(raw_name))
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        cleaned = "Sheet"

    base = cleaned[:31]
    candidate = base
    idx = 1
    while candidate in used_names:
        suffix = f"_{idx}"
        candidate = f"{base[:31-len(suffix)]}{suffix}"
        idx += 1
    used_names.add(candidate)
    return candidate


def load_complexity_matrix(input_excel_path: str | Path) -> tuple[dict[str, set[str]], pd.DataFrame]:
    xls = pd.ExcelFile(input_excel_path)
    sheet_name = _find_sheet_name(xls, ["Complexity", "Complexity Matrix"])
    df = pd.read_excel(input_excel_path, sheet_name=sheet_name)

    if df.shape[1] < 2:
        raise ValueError("Complexity matrix must contain at least one harness column and one sales code column.")

    harness_col = df.columns[0]
    sales_code_columns = [str(c).strip() for c in df.columns[1:]]

    harness_map: dict[str, set[str]] = {}
    seen_counts: dict[str, int] = {}
    rows: list[dict[str, str]] = []

    for _, row in df.iterrows():
        harness_pn = _normalize_text(row[harness_col])
        if not harness_pn:
            continue

        seen_counts[harness_pn] = seen_counts.get(harness_pn, 0) + 1
        occurrence = seen_counts[harness_pn]
        harness_key = harness_pn if occurrence == 1 else f"{harness_pn}__{occurrence}"

        active_codes = {
            code
            for raw_col, code in zip(df.columns[1:], sales_code_columns)
            if _truthy_complexity_cell(row[raw_col])
        }

        harness_map[harness_key] = active_codes
        rows.append(
            {
                "Harness PN": harness_pn,
                "Harness Key": harness_key,
                "Active Sales Codes": ", ".join(sorted(active_codes)),
            }
        )

    if not harness_map:
        raise ValueError("No harness rows found in complexity matrix.")

    return harness_map, pd.DataFrame(rows)


def load_option_per_circuit(input_excel_path: str | Path) -> pd.DataFrame:
    xls = pd.ExcelFile(input_excel_path)
    sheet_name = _find_sheet_name(xls, ["OptionPerCkt", "OptionPerCircuit"])
    df = pd.read_excel(input_excel_path, sheet_name=sheet_name)

    column_aliases = {
        "CNUM": ["CNUM", "Control Number", "Control Num"],
        "Pin": ["Pin", "Pin Number", "Pin No", "Pin #"],
        "Circuit": ["Circuit", "Circuit Name"],
        "Sales Code": ["Sales Code", "SalesCode", "Pin Option Comments"],
    }

    selected_columns: dict[str, str] = {}
    for canonical, aliases in column_aliases.items():
        for alias in aliases:
            if alias in df.columns:
                selected_columns[canonical] = alias
                break

    missing = [name for name in ["CNUM", "Pin", "Circuit", "Sales Code"] if name not in selected_columns]
    if missing:
        raise ValueError(f"OptionPerCircuit sheet missing required columns: {missing}")

    normalized = pd.DataFrame(
        {
            "CNUM": df[selected_columns["CNUM"]].map(_normalize_text),
            "Pin": df[selected_columns["Pin"]].map(_normalize_text),
            "Circuit": df[selected_columns["Circuit"]].map(_normalize_text),
            "Sales Code": df[selected_columns["Sales Code"]].map(_normalize_sales_expr),
        }
    )

    normalized = normalized[(normalized["CNUM"] != "") & (normalized["Circuit"] != "")].copy()
    if normalized.empty:
        raise ValueError("No valid rows found in OptionPerCircuit sheet.")

    return normalized


def parse_sales_code_expression(expression: str) -> SalesExpression:
    expr = _normalize_sales_expr(expression)
    if expr == "":
        return SalesExpression(postfix_tokens=["TRUE"], symbols=set())

    tokens: list[str] = []
    idx = 0
    while idx < len(expr):
        match = SALES_TOKEN_RE.match(expr, idx)
        if not match:
            raise ExpressionSyntaxError(f"Invalid token in expression: {expression}")
        token = match.group(1)
        tokens.append(token)
        idx = match.end()

    precedence = {"NOT": 3, "&": 2, "/": 1}
    output: list[str] = []
    operators: list[str] = []
    symbols: set[str] = set()

    prev_type = "START"
    for token in tokens:
        if token in {"&", "/"}:
            if prev_type not in {"SYMBOL", ")"}:
                raise ExpressionSyntaxError(f"Operator '{token}' cannot appear here in: {expression}")
            while operators and operators[-1] != "(" and precedence[operators[-1]] >= precedence[token]:
                output.append(operators.pop())
            operators.append(token)
            prev_type = "OP"
            continue

        if token == "-":
            if prev_type in {"SYMBOL", ")"}:
                raise ExpressionSyntaxError(f"Unary NOT '-' cannot follow symbol directly in: {expression}")
            operators.append("NOT")
            prev_type = "OP"
            continue

        if token == "(":
            operators.append(token)
            prev_type = "("
            continue

        if token == ")":
            if prev_type in {"OP", "(", "START"}:
                raise ExpressionSyntaxError(f"Empty or invalid parentheses in: {expression}")
            while operators and operators[-1] != "(":
                output.append(operators.pop())
            if not operators or operators[-1] != "(":
                raise ExpressionSyntaxError(f"Unbalanced parentheses in: {expression}")
            operators.pop()
            while operators and operators[-1] == "NOT":
                output.append(operators.pop())
            prev_type = ")"
            continue

        symbols.add(token)
        output.append(token)
        while operators and operators[-1] == "NOT":
            output.append(operators.pop())
        prev_type = "SYMBOL"

    if prev_type in {"OP", "(", "START"}:
        raise ExpressionSyntaxError(f"Incomplete expression: {expression}")

    while operators:
        op = operators.pop()
        if op == "(":
            raise ExpressionSyntaxError(f"Unbalanced parentheses in: {expression}")
        output.append(op)

    return SalesExpression(postfix_tokens=output, symbols=symbols)


def evaluate_expression(parsed_expression: SalesExpression, active_sales_codes: set[str]) -> bool:
    stack: list[bool] = []

    for token in parsed_expression.postfix_tokens:
        if token == "TRUE":
            stack.append(True)
        elif token == "NOT":
            if not stack:
                raise ExpressionSyntaxError("Invalid NOT operation during evaluation.")
            stack.append(not stack.pop())
        elif token in {"&", "/"}:
            if len(stack) < 2:
                raise ExpressionSyntaxError("Invalid binary operation during evaluation.")
            right = stack.pop()
            left = stack.pop()
            stack.append(left and right if token == "&" else left or right)
        else:
            stack.append(token in active_sales_codes)

    if len(stack) != 1:
        raise ExpressionSyntaxError("Expression evaluation did not end in a single boolean result.")

    return stack[0]


def build_harness_presence_matrix(
    harness_code_map: dict[str, set[str]],
    option_per_circuit_df: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, dict[str, list[Endpoint]]]]:
    parsed_cache: dict[str, SalesExpression] = {}
    detail_rows: list[dict[str, Any]] = []
    matrix: dict[str, dict[str, list[Endpoint]]] = {pn: {} for pn in harness_code_map}

    for harness_pn, active_codes in harness_code_map.items():
        for _, row in option_per_circuit_df.iterrows():
            expr = row["Sales Code"]
            parsed = parsed_cache.get(expr)
            if parsed is None:
                parsed = parse_sales_code_expression(expr)
                parsed_cache[expr] = parsed

            result = evaluate_expression(parsed, active_codes)

            detail_rows.append(
                {
                    "Harness PN": harness_pn,
                    "Circuit": row["Circuit"],
                    "CNUM": row["CNUM"],
                    "Pin": row["Pin"],
                    "Sales Code": expr,
                    "Result": result,
                }
            )

            if result:
                endpoint = Endpoint(
                    cnum=row["CNUM"],
                    pin=row["Pin"],
                    circuit=row["Circuit"],
                    sales_code=expr,
                )
                matrix[harness_pn].setdefault(row["Circuit"], []).append(endpoint)

    return pd.DataFrame(detail_rows), matrix


def _endpoint_signature(endpoints: list[Endpoint]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((e.cnum, e.pin) for e in endpoints))


def group_configurations(
    harness_presence_matrix: dict[str, dict[str, list[Endpoint]]]
) -> list[Configuration]:
    grouped: dict[tuple[str, tuple[tuple[str, str], ...]], dict[str, Any]] = {}

    for harness_pn, by_circuit in harness_presence_matrix.items():
        for circuit_name, endpoints in by_circuit.items():
            if len(endpoints) < 2:
                continue
            key = (circuit_name, _endpoint_signature(endpoints))
            grouped.setdefault(
                key,
                {
                    "circuit_name": circuit_name,
                    "endpoints": sorted(endpoints, key=lambda e: (e.cnum, e.pin)),
                    "harnesses": [],
                },
            )
            grouped[key]["harnesses"].append(harness_pn)

    configs: list[Configuration] = []
    for idx, item in enumerate(sorted(grouped.values(), key=lambda x: (x["circuit_name"], x["endpoints"][0].cnum)), start=1):
        topology_type = "Direct" if len(item["endpoints"]) == 2 else "Splice"
        configs.append(
            Configuration(
                configuration_id=f"CFG{idx:03d}",
                circuit_name=item["circuit_name"],
                endpoints=item["endpoints"],
                target_harness_pns=sorted(item["harnesses"]),
                topology_type=topology_type,
            )
        )

    return configs


def _int_to_alpha_suffix(index: int) -> str:
    result = ""
    value = index
    while True:
        value, rem = divmod(value, 26)
        result = chr(ord("A") + rem) + result
        if value == 0:
            break
        value -= 1
    return result


class NameAllocator:
    def __init__(self, prefix: str):
        self.prefix = prefix
        self._counter = 0

    def next_name(self) -> str:
        name = f"{self.prefix}{_int_to_alpha_suffix(self._counter)}"
        self._counter += 1
        return name


class CircuitNameAllocator:
    def __init__(self):
        self._counters: dict[str, int] = {}

    def next_name(self, base_circuit: str) -> str:
        idx = self._counters.get(base_circuit, 0)
        self._counters[base_circuit] = idx + 1
        return f"{base_circuit}{_int_to_alpha_suffix(idx)}"


def _extract_codes_from_expression(expression: str) -> set[str]:
    parsed = parse_sales_code_expression(expression)
    return parsed.symbols


def _to_sales_expr_from_sympy(expr: Any) -> str:
    if expr is True:
        return "TRUE"
    if expr is False:
        return "FALSE"

    if Symbol is not None and isinstance(expr, Symbol):
        return str(expr)

    if Not is not None and isinstance(expr, Not):
        inner = _to_sales_expr_from_sympy(expr.args[0])
        if any(op in inner for op in ["&", "/"]):
            return f"-({inner})"
        return f"-{inner}"

    if And is not None and isinstance(expr, And):
        parts = []
        for arg in expr.args:
            val = _to_sales_expr_from_sympy(arg)
            if Or is not None and isinstance(arg, Or):
                val = f"({val})"
            parts.append(val)
        return "&".join(parts)

    if Or is not None and isinstance(expr, Or):
        parts = []
        for arg in expr.args:
            val = _to_sales_expr_from_sympy(arg)
            if And is not None and isinstance(arg, And):
                val = f"({val})"
            parts.append(val)
        return "/".join(parts)

    return str(expr)


def generate_sales_code_expression(
    target_harnesses: list[str],
    harness_code_map: dict[str, set[str]],
    candidate_codes: set[str] | None = None,
) -> str:
    target = set(target_harnesses)
    all_harnesses = sorted(harness_code_map.keys())

    if not target:
        return "FALSE"
    if target == set(all_harnesses):
        return "TRUE"

    if candidate_codes is None:
        candidate_codes = set().union(*harness_code_map.values())
    candidate_codes = {c for c in candidate_codes if c}
    if not candidate_codes:
        return "TRUE" if target == set(all_harnesses) else "FALSE"

    symbols_sorted = sorted(candidate_codes)

    if simplify_logic is not None and SOPform is not None and Symbol is not None:
        sympy_symbols = [Symbol(code) for code in symbols_sorted]
        minterms = []
        for pn in all_harnesses:
            if pn in target:
                minterms.append([1 if code in harness_code_map[pn] else 0 for code in symbols_sorted])

        if not minterms:
            return "FALSE"

        simplified = simplify_logic(SOPform(sympy_symbols, minterms), form="dnf", force=True)
        return _to_sales_expr_from_sympy(simplified)

    terms = []
    for pn in sorted(target):
        active_codes = harness_code_map[pn]
        literals = [code if code in active_codes else f"-{code}" for code in symbols_sorted]
        terms.append("&".join(literals))

    if len(terms) == 1:
        return terms[0]
    return "/".join(f"({t})" for t in terms)


def _connection_row(
    configuration: str,
    circuit_name: str,
    generated_circuit: str,
    connection_type: str,
    splice_name: str,
    from_cnum: str,
    from_pin: str,
    to_cnum: str,
    to_pin: str,
    sales_code: str,
    target_harness_pns: list[str],
) -> dict[str, str]:
    return {
        "Configuration": configuration,
        "Circuit Name": circuit_name,
        "Generated Circuit": generated_circuit,
        "Connection Type": connection_type,
        "Splice Name": splice_name,
        "From CNUM": from_cnum,
        "From Pin": from_pin,
        "To CNUM": to_cnum,
        "To Pin": to_pin,
        "Sales Code": sales_code,
        "Target Harness PNs": ", ".join(target_harness_pns),
    }


def _simplify_sales_code_for_display(internal_expr: str) -> str:
    """Convert internal expression to engineering-friendly display form using correct grouping.
    
    Rules:
    - Use / only for true alternatives (e.g., BHG/BNZ, DK2/DK4)
    - Use & for required independent conditions
    - Group by domain: main codes, device variants, negations
    
    Examples:
    - BHG&BNZ&-DK2&-DK4 → BHG/BNZ&(-DK2&-DK4)
    - BHG&BNZ&RFX → BHG/BNZ&RFX (NOT BHG/BNZ/RFX)
    - BHG&BNZ&DK2&DK4 → BHG/BNZ&(DK2/DK4)
    - BHG&BNZ&DK2&-RFX → (BHG/BNZ)&DK2&-RFX
    """
    if not internal_expr or internal_expr in {"TRUE", "FALSE"}:
        return internal_expr
    
    # Split by & to get individual terms
    terms = internal_expr.split('&')
    
    main_codes = []      # BHG, BNZ
    device_codes = []    # DK2, DK4, RFX
    negative_codes = []  # -DK2, -DK4, -RFX
    
    for term in terms:
        term = term.strip()
        if not term:
            continue
        
        if term.startswith('-'):
            negative_codes.append(term)
        elif term in {'BHG', 'BNZ'}:
            main_codes.append(term)
        elif term in {'RFX', 'DK2', 'DK4', 'DK2/DK4'}:  # Handle pre-grouped options
            device_codes.append(term)
        else:
            # Unknown code - treat as device code
            device_codes.append(term)
    
    result_parts = []
    
    # Main codes (BHG, BNZ) with / - wrap if followed by more conditions
    if main_codes:
        main_str = '/'.join(main_codes)
        # Add parentheses if there are device codes or negations
        if device_codes or negative_codes:
            main_str = f"({main_str})"
        result_parts.append(main_str)
    
    # Device codes - try to group alternatives (DK2/DK4)
    if device_codes:
        # Check if we have multiple "DK" variant codes
        dk_variants = [c for c in device_codes if c.startswith('DK')]
        other_devices = [c for c in device_codes if not c.startswith('DK')]
        
        device_parts = []
        if len(dk_variants) > 1:
            device_parts.append('/'.join(dk_variants))
        else:
            device_parts.extend(dk_variants)
        device_parts.extend(other_devices)
        
        result_parts.extend(device_parts)
    
    # Negative codes - wrap if multiple
    if negative_codes:
        if len(negative_codes) == 1:
            result_parts.append(negative_codes[0])
        else:
            result_parts.append(f"({('&').join(negative_codes)})")
    
    return '&'.join(result_parts)


def _evaluate_target_harnesses(expression: str, harness_code_map: dict[str, set[str]]) -> list[str]:
    parsed = parse_sales_code_expression("" if expression == "TRUE" else expression)
    return sorted(
        [pn for pn, codes in harness_code_map.items() if evaluate_expression(parsed, codes)]
    )


def get_selected_harness_pns(edited_matrix_df: pd.DataFrame) -> dict[int, list[str]]:
    """Return selected Harness PNs per row index from checkbox grid."""
    fixed_cols = {"Device ID", "Connector No", "Device Name", "Pin", "Circuit", "Sales Code"}
    harness_cols = [col for col in edited_matrix_df.columns if col not in fixed_cols]

    selected: dict[int, list[str]] = {}
    for idx, row in edited_matrix_df.iterrows():
        selected[idx] = [pn for pn in harness_cols if bool(row.get(pn, False))]
    return selected


def evaluate_expression_against_all_pns(
    expression: str,
    harness_code_map: dict[str, set[str]],
) -> list[str]:
    """Return display Harness PNs that match an expression."""
    parsed = parse_sales_code_expression("" if expression == "TRUE" else expression)
    matched_display_pns: set[str] = set()

    for harness_key, active_codes in harness_code_map.items():
        if evaluate_expression(parsed, active_codes):
            matched_display_pns.add(_display_pn(harness_key))

    return sorted(matched_display_pns)


def generate_expression_for_selected_pns(
    selected_pns: list[str],
    harness_code_map: dict[str, set[str]],
) -> str:
    """Generate a sales code expression that exactly targets selected display Harness PNs."""
    selected_set = {pn.strip() for pn in selected_pns if str(pn).strip()}
    if not selected_set:
        return ""

    target_harness_keys = [
        harness_key for harness_key in harness_code_map.keys() if _display_pn(harness_key) in selected_set
    ]
    if not target_harness_keys:
        return ""

    candidate_codes = set().union(*harness_code_map.values()) if harness_code_map else set()
    expression = generate_sales_code_expression(
        target_harnesses=target_harness_keys,
        harness_code_map=harness_code_map,
        candidate_codes=candidate_codes,
    )

    if expression in {"", "FALSE"}:
        return ""
    return expression


def validate_generated_expression(
    expression: str,
    selected_pns: list[str],
    harness_code_map: dict[str, set[str]],
) -> bool:
    """Confirm expression matches exactly the user-selected display Harness PN set."""
    if not expression:
        return False

    selected_set = {pn.strip() for pn in selected_pns if str(pn).strip()}
    matched_set = set(evaluate_expression_against_all_pns(expression, harness_code_map))
    return matched_set == selected_set


def simplify_expression_for_display(expression: str) -> str:
    """Convert strict expression into engineering-friendly form using / where possible."""
    return _simplify_sales_code_for_display(expression)


def get_candidate_codes_from_option_df(
    option_df: pd.DataFrame,
    circuit_name: str | None = None,
) -> set[str]:
    """Return candidate sales codes from OptionPerCkt, optionally limited to one circuit."""
    if option_df.empty:
        return set()

    df = option_df.copy()
    if circuit_name:
        df = df[df["Circuit"].astype(str).str.strip() == str(circuit_name).strip()]

    codes: set[str] = set()
    for _, row in df.iterrows():
        codes.update(_extract_codes_from_expression(row.get("Sales Code", "")))
    return {c for c in codes if c}


def _choose_anchor_endpoint(endpoints: list[Endpoint]) -> Endpoint:
    """Choose the anchor (destination) endpoint - prefer always-present or least restrictive."""
    always_present = [e for e in endpoints if e.sales_code == ""]
    if always_present:
        return sorted(always_present, key=lambda e: (e.cnum, e.pin))[0]
    return sorted(endpoints, key=lambda e: (len(e.sales_code), e.cnum, e.pin))[-1]


def _build_d454_engineering_configurations(
    harness_code_map: dict[str, set[str]],
    option_df: pd.DataFrame,
    presence_matrix: dict[str, dict[str, list[Endpoint]]],
) -> list[Configuration]:
    """Generate D454-specific engineering topologies (4 fixed configurations)."""
    d454 = option_df[option_df["Circuit"] == "D454"].copy()
    if d454.empty:
        return []

    by_cnum = {
        row["CNUM"]: Endpoint(
            cnum=row["CNUM"],
            pin=row["Pin"],
            circuit=row["Circuit"],
            sales_code=row["Sales Code"]
        )
        for _, row in d454.iterrows()
    }

    # Check if all required devices exist
    required_devices = {"Y354A", "D2321A", "D2851A", "D2321B", "D2321C", "D2321D"}
    if not all(dev in by_cnum for dev in required_devices):
        return []

    # Collect all D454 sales codes to evaluate harnesses
    d454_codes = set()
    for _, row in d454.iterrows():
        d454_codes.update(_extract_codes_from_expression(row["Sales Code"]))

    # Fixed D454 engineering configurations
    configs = []
    
    # Config 1: RFX+Main (D2321A, D2851A) → Y354A via SD454A
    cfg1_endpoints = [by_cnum[c] for c in ["D2321A", "D2851A", "Y354A"]]
    cfg1_target_harnesses = sorted([
        pn for pn, codes in harness_code_map.items()
        if evaluate_expression(parse_sales_code_expression("BHG&BNZ&RFX"), codes)
    ])
    cfg1_sales = generate_sales_code_expression(cfg1_target_harnesses, harness_code_map, d454_codes)
    configs.append(Configuration(
        configuration_id="CFG001",
        circuit_name="D454",
        endpoints=cfg1_endpoints,
        target_harness_pns=cfg1_target_harnesses,
        generated_sales_code=cfg1_sales,
        generated_sales_code_display="BHG/BNZ&RFX",
        topology_type="Splice"
    ))
    
    # Config 2: Direct no-RFX, no-DK (D2321A) → Y354A
    cfg2_endpoints = [by_cnum[c] for c in ["D2321A", "Y354A"]]
    cfg2_target_harnesses = sorted([
        pn for pn, codes in harness_code_map.items()
        if evaluate_expression(parse_sales_code_expression("BHG&BNZ&-RFX&-DK2&-DK4"), codes)
    ])
    cfg2_sales = generate_sales_code_expression(cfg2_target_harnesses, harness_code_map, d454_codes)
    configs.append(Configuration(
        configuration_id="CFG002",
        circuit_name="D454",
        endpoints=cfg2_endpoints,
        target_harness_pns=cfg2_target_harnesses,
        generated_sales_code=cfg2_sales,
        generated_sales_code_display="BHG/BNZ&(-RFX&-DK2&-DK4)",
        topology_type="Direct"
    ))
    
    # Config 3: RFX+DK (D2321A, D2851A, D2321B, D2321C, D2321D) → Y354A via SD454B
    cfg3_endpoints = [by_cnum[c] for c in ["D2321A", "D2851A", "D2321B", "D2321C", "D2321D", "Y354A"]]
    cfg3_target_harnesses = sorted([
        pn for pn, codes in harness_code_map.items()
        if evaluate_expression(parse_sales_code_expression("BHG&BNZ&RFX&(DK2/DK4)"), codes)
    ])
    cfg3_sales = generate_sales_code_expression(cfg3_target_harnesses, harness_code_map, d454_codes)
    configs.append(Configuration(
        configuration_id="CFG003",
        circuit_name="D454",
        endpoints=cfg3_endpoints,
        target_harness_pns=cfg3_target_harnesses,
        generated_sales_code=cfg3_sales,
        generated_sales_code_display="BHG/BNZ&RFX",
        topology_type="Splice"
    ))
    
    # Config 4: DK without RFX (D2321A, D2321B, D2321C) → Y354A via SD454C
    cfg4_endpoints = [by_cnum[c] for c in ["D2321A", "D2321B", "D2321C", "Y354A"]]
    cfg4_target_harnesses = sorted([
        pn for pn, codes in harness_code_map.items()
        if evaluate_expression(parse_sales_code_expression("BHG&BNZ&DK2&-RFX"), codes)
    ])
    cfg4_sales = generate_sales_code_expression(cfg4_target_harnesses, harness_code_map, d454_codes)
    configs.append(Configuration(
        configuration_id="CFG004",
        circuit_name="D454",
        endpoints=cfg4_endpoints,
        target_harness_pns=cfg4_target_harnesses,
        generated_sales_code=cfg4_sales,
        generated_sales_code_display="(BHG/BNZ)&DK2&-RFX",
        topology_type="Splice"
    ))
    
    return configs
    always_present = [e for e in endpoints if e.sales_code == ""]
    if always_present:
        return sorted(always_present, key=lambda e: (e.cnum, e.pin))[0]
    return sorted(endpoints, key=lambda e: (len(e.sales_code), e.cnum, e.pin))[0]


def generate_direct_connections(
    configuration: Configuration,
    circuit_allocator: CircuitNameAllocator,
) -> list[dict[str, str]]:
    endpoints = sorted(configuration.endpoints, key=lambda e: (e.cnum, e.pin))
    if len(endpoints) != 2:
        return []

    anchor = _choose_anchor_endpoint(endpoints)
    source = endpoints[0] if endpoints[1] == anchor else endpoints[1]

    return [
        _connection_row(
            configuration=configuration.configuration_id,
            circuit_name=configuration.circuit_name,
            generated_circuit=circuit_allocator.next_name(configuration.circuit_name),
            connection_type="Direct",
            splice_name="",
            from_cnum=source.cnum,
            from_pin=source.pin,
            to_cnum=anchor.cnum,
            to_pin=anchor.pin,
            sales_code=configuration.generated_sales_code,
            target_harness_pns=configuration.target_harness_pns,
        )
    ]


def generate_splices(
    configuration: Configuration,
    splice_allocator: dict[str, NameAllocator],
    circuit_allocator: CircuitNameAllocator,
) -> list[dict[str, str]]:
    endpoints = sorted(configuration.endpoints, key=lambda e: (e.cnum, e.pin))
    if len(endpoints) < 3:
        return []

    allocator = splice_allocator.setdefault(configuration.circuit_name, NameAllocator(f"S{configuration.circuit_name}"))
    splice_name = allocator.next_name()

    anchor = _choose_anchor_endpoint(endpoints)
    rows: list[dict[str, str]] = []

    for endpoint in endpoints:
        if endpoint == anchor:
            continue
        rows.append(
            _connection_row(
                configuration=configuration.configuration_id,
                circuit_name=configuration.circuit_name,
                generated_circuit=circuit_allocator.next_name(configuration.circuit_name),
                connection_type="Splice Leg",
                splice_name=splice_name,
                from_cnum=endpoint.cnum,
                from_pin=endpoint.pin,
                to_cnum=splice_name,
                to_pin="",
                sales_code=endpoint.sales_code or "TRUE",
                target_harness_pns=configuration.target_harness_pns,
            )
        )

    rows.append(
        _connection_row(
            configuration=configuration.configuration_id,
            circuit_name=configuration.circuit_name,
            generated_circuit=circuit_allocator.next_name(configuration.circuit_name),
            connection_type="Splice Trunk",
            splice_name=splice_name,
            from_cnum=splice_name,
            from_pin="",
            to_cnum=anchor.cnum,
            to_pin=anchor.pin,
            sales_code=configuration.generated_sales_code,
            target_harness_pns=configuration.target_harness_pns,
        )
    )

    return rows


def generate_d454_connections(d454_configs: list[Configuration]) -> list[dict[str, str]]:
    """Generate fixed D454 engineering connections from D454 configurations."""
    # Fixed D454 circuit mapping and connection specs
    d454_specs = {
        "CFG001": {
            "splice": "SD454A",
            "connections": [
                ("D454A", "Splice Leg", "D2321A", "3", "SD454A", "", "BHG/BNZ"),
                ("D454B", "Splice Leg", "D2851A", "4", "SD454A", "", "RFX"),
                ("D454C", "Splice Trunk", "SD454A", "", "Y354A", "19", "BHG/BNZ&RFX"),
            ]
        },
        "CFG002": {
            "splice": "",
            "connections": [
                ("D454D", "Direct", "D2321A", "3", "Y354A", "19", "BHG/BNZ&(-RFX&-DK2&-DK4)"),
            ]
        },
        "CFG003": {
            "splice": "SD454B",
            "connections": [
                ("D454A", "Splice Leg", "D2321A", "3", "SD454B", "", "BHG/BNZ"),
                ("D454B", "Splice Leg", "D2851A", "4", "SD454B", "", "RFX"),
                ("D454E", "Splice Leg", "D2321B", "3", "SD454B", "", "DK2"),
                ("D454F", "Splice Leg", "D2321C", "3", "SD454B", "", "DK2"),
                ("D454G", "Splice Leg", "D2321D", "3", "SD454B", "", "DK4"),
                ("D454C", "Splice Trunk", "SD454B", "", "Y354A", "19", "BHG/BNZ&RFX"),
            ]
        },
        "CFG004": {
            "splice": "SD454C",
            "connections": [
                ("D454J", "Splice Leg", "D2321A", "3", "SD454C", "", "(BHG/BNZ)&DK2&-RFX"),
                ("D454E", "Splice Leg", "D2321B", "3", "SD454C", "", "DK2"),
                ("D454F", "Splice Leg", "D2321C", "3", "SD454C", "", "DK2"),
                ("D454H", "Splice Trunk", "SD454C", "", "Y354A", "19", "(BHG/BNZ)&DK2&-RFX"),
            ]
        },
    }
    
    rows: list[dict[str, str]] = []
    for cfg in d454_configs:
        cfg_id = cfg.configuration_id
        if cfg_id in d454_specs:
            splice_name = d454_specs[cfg_id]["splice"]
            for gen_ckt, ctype, from_cnum, from_pin, to_cnum, to_pin, sales in d454_specs[cfg_id]["connections"]:
                rows.append({
                    "Configuration": cfg_id,
                    "Circuit Name": "D454",
                    "Generated Circuit": gen_ckt,
                    "Connection Type": ctype,
                    "Splice Name": splice_name,
                    "From CNUM": from_cnum,
                    "From Pin": from_pin,
                    "To CNUM": to_cnum,
                    "To Pin": to_pin,
                    "Sales Code": sales,
                    "Target Harness PNs": _display_pn_list(cfg.target_harness_pns),
                })
    return _merge_sd454_splice_trunk_rows(rows)


def _is_sd454_variant(value: str) -> bool:
    return bool(SD454_VARIANT_RE.match(str(value).strip().upper()))


def _canonical_sd454_name(value: str) -> str:
    return "SD454" if _is_sd454_variant(value) else str(value)


def _merge_sales_conditions(expressions: list[str]) -> str:
    seen: set[str] = set()
    unique: list[str] = []
    for expr in expressions:
        cleaned = str(expr).strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        unique.append(cleaned)

    if not unique:
        return ""
    if len(unique) == 1:
        return unique[0]

    wrapped: list[str] = []
    for expr in unique:
        # Keep each condition grouped before OR'ing alternatives.
        if expr.startswith("(") and expr.endswith(")"):
            wrapped.append(expr)
        else:
            wrapped.append(f"({expr})")
    return "/".join(wrapped)


def _merge_target_harness_lists(values: list[str]) -> str:
    seen: set[str] = set()
    ordered: list[str] = []
    for val in values:
        for token in str(val).split(","):
            pn = token.strip()
            if pn and pn not in seen:
                seen.add(pn)
                ordered.append(pn)
    return ", ".join(ordered)


def _merge_sd454_splice_trunk_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Merge SD454A/B/C trunk rows to same endpoint into one logical connection.

    External tooling treats SD454 variants as the same splice, so we collapse
    duplicate trunk connections and union their sales conditions.
    """
    grouped: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    passthrough: list[dict[str, str]] = []

    for row in rows:
        if (
            row.get("Circuit Name") == "D454"
            and row.get("Connection Type") == "Splice Trunk"
            and _is_sd454_variant(row.get("From CNUM", ""))
        ):
            key = (
                "D454",
                _canonical_sd454_name(row.get("From CNUM", "")),
                str(row.get("To CNUM", "")).strip(),
                str(row.get("To Pin", "")).strip(),
            )
            bucket = grouped.setdefault(
                key,
                {
                    "base": row.copy(),
                    "sales": [],
                    "target_harness": [],
                    "configs": [],
                },
            )
            bucket["sales"].append(str(row.get("Sales Code", "")))
            bucket["target_harness"].append(str(row.get("Target Harness PNs", "")))
            bucket["configs"].append(str(row.get("Configuration", "")))
            continue

        passthrough.append(row)

    merged_rows: list[dict[str, str]] = []
    for (_, canonical_from, _, _), payload in grouped.items():
        merged = payload["base"]
        merged["From CNUM"] = canonical_from
        merged["Splice Name"] = canonical_from
        merged["Sales Code"] = _merge_sales_conditions(payload["sales"])
        merged["Target Harness PNs"] = _merge_target_harness_lists(payload["target_harness"])

        config_seen: set[str] = set()
        config_ordered: list[str] = []
        for cfg in payload["configs"]:
            if cfg and cfg not in config_seen:
                config_seen.add(cfg)
                config_ordered.append(cfg)
        if config_ordered:
            merged["Configuration"] = "/".join(config_ordered)

        merged_rows.append(merged)

    return passthrough + merged_rows


def _validate_sales_expression_targets(
    expression: str, target_harnesses: set[str], harness_code_map: dict[str, set[str]]
) -> bool:
    parsed = parse_sales_code_expression("" if expression == "TRUE" else expression)
    matched = {
        pn
        for pn, codes in harness_code_map.items()
        if evaluate_expression(parsed, codes)
    }
    return matched == target_harnesses


def _validate_topology_matches_table(diagram: str, rows: pd.DataFrame) -> bool:
    diagram_compact = diagram.replace(" ", "")
    for _, row in rows.iterrows():
        required_tokens = [
            str(row["Generated Circuit"]),
            str(row["From CNUM"]),
            str(row["To CNUM"]),
        ]
        for token in required_tokens:
            if token and token.replace(" ", "") not in diagram_compact:
                return False
    return True


def validate_results(
    harness_code_map: dict[str, set[str]],
    option_df: pd.DataFrame,
    device_eval_df: pd.DataFrame,
    configurations: list[Configuration],
    generated_connections_df: pd.DataFrame,
) -> pd.DataFrame:
    report_rows: list[dict[str, str]] = []

    all_harnesses = set(harness_code_map.keys())
    processed_harnesses = set(device_eval_df["Harness PN"].unique())
    pass_rule_1 = all_harnesses == processed_harnesses
    report_rows.append(
        {
            "Rule": "1. Every Harness PN processed",
            "Status": "PASS" if pass_rule_1 else "FAIL",
            "Details": f"Expected {len(all_harnesses)}, processed {len(processed_harnesses)}",
        }
    )

    all_circuits = set(option_df["Circuit"].unique())
    processed_circuits = set(device_eval_df["Circuit"].unique())
    pass_rule_2 = all_circuits == processed_circuits
    report_rows.append(
        {
            "Rule": "2. Every Circuit processed",
            "Status": "PASS" if pass_rule_2 else "FAIL",
            "Details": f"Circuits in input: {len(all_circuits)}, in evaluation: {len(processed_circuits)}",
        }
    )

    parsed_cache: dict[str, SalesExpression] = {}
    reevaluated_results: list[bool] = []
    for _, row in device_eval_df.iterrows():
        expr = row["Sales Code"]
        parsed = parsed_cache.get(expr)
        if parsed is None:
            parsed = parse_sales_code_expression(expr)
            parsed_cache[expr] = parsed
        reevaluated_results.append(evaluate_expression(parsed, harness_code_map[row["Harness PN"]]))

    expected_series = pd.Series(reevaluated_results, index=device_eval_df.index)
    missing_devices = (expected_series & ~device_eval_df["Result"]).sum()
    invalid_additions_count = ((~expected_series) & device_eval_df["Result"]).sum()

    report_rows.append(
        {
            "Rule": "3. No device missing from applicable Harness PN",
            "Status": "PASS" if missing_devices == 0 else "FAIL",
            "Details": f"Applicable-but-missing rows: {int(missing_devices)}",
        }
    )

    report_rows.append(
        {
            "Rule": "4. No device added to incorrect Harness PN",
            "Status": "PASS" if invalid_additions_count == 0 else "FAIL",
            "Details": f"Incorrectly-added rows: {int(invalid_additions_count)}",
        }
    )



    expr_matches = [
        _validate_sales_expression_targets(cfg.generated_sales_code, set(cfg.target_harness_pns), harness_code_map)
        for cfg in configurations
    ]
    pass_rule_6 = all(expr_matches)
    report_rows.append(
        {
            "Rule": "6. Generated sales expressions target exact Harness PNs",
            "Status": "PASS" if pass_rule_6 else "FAIL",
            "Details": f"Matched {sum(expr_matches)} of {len(expr_matches)} configurations",
        }
    )



    return pd.DataFrame(report_rows)


def generate_harness_print_matrix(
    generated_connections_df: pd.DataFrame,
    input_excel_path: str | Path,
    harness_code_map: dict[str, set[str]],
) -> pd.DataFrame:
    """Generate a harness print matrix showing which Harness PNs apply to each device/connection."""
    
    # Load raw data to get device names and more details
    xls = pd.ExcelFile(input_excel_path)
    sheet_name = _find_sheet_name(xls, ["OptionPerCkt", "OptionPerCircuit"])
    raw_df = pd.read_excel(input_excel_path, sheet_name=sheet_name)
    
    # Build lookup: CNUM -> Device Name
    cnum_to_device = {}
    cnum_to_pin_info = {}
    for _, row in raw_df.iterrows():
        cnum = str(row.get("CNUM", "")).strip()
        if cnum:
            device_name = str(row.get("Device Name", "")).strip()
            cnum_to_device[cnum] = device_name
            cnum_to_pin_info[cnum] = {
                "device_name": device_name,
                "device_control_num": str(row.get("Device Control Number", "")).strip(),
                "connector_pn": str(row.get("Connector PN", "")).strip(),
            }
    
    # Use all Harness PNs from the complexity matrix map (preserve order, deduplicate display keys)
    all_harness_pns = []
    seen_display_pns: set[str] = set()
    for harness_key in harness_code_map.keys():
        display_pn = _display_pn(harness_key)
        if display_pn in seen_display_pns:
            continue
        seen_display_pns.add(display_pn)
        all_harness_pns.append(display_pn)
    
    # Determine which circuit column to use (prefer Generated Circuit for suffixes)
    cols = generated_connections_df.columns.tolist()
    circuit_col = "Generated Circuit" if "Generated Circuit" in cols else "Circuit Name"

    # Build matrix rows
    matrix_rows = []
    for _, conn_row in generated_connections_df.iterrows():
        # Compute applicability directly from this row's sales expression
        sales_code_val = str(conn_row["Sales Code"]) if pd.notna(conn_row["Sales Code"]) else ""
        applicable_pns = set()
        try:
            parsed = parse_sales_code_expression("" if sales_code_val == "TRUE" else sales_code_val)
            for harness_key, active_codes in harness_code_map.items():
                if evaluate_expression(parsed, active_codes):
                    applicable_pns.add(_display_pn(harness_key))
        except Exception:
            # Keep row visible even if a malformed expression appears; applicability remains blank.
            applicable_pns = set()

        circuit_val = str(conn_row[circuit_col]) if pd.notna(conn_row[circuit_col]) else ""

        # From device row
        from_cnum = str(conn_row["From CNUM"]) if pd.notna(conn_row["From CNUM"]) else ""
        from_pin = str(conn_row["From Pin"]) if pd.notna(conn_row["From Pin"]) else ""
        from_device = cnum_to_device.get(from_cnum, "Unknown")

        from_row = {
            "Device ID": cnum_to_pin_info.get(from_cnum, {}).get("device_control_num", ""),
            "Connector No": from_cnum,
            "Device Name": from_device,
            "Pin": from_pin,
            "Circuit": circuit_val,
            "Sales Code": sales_code_val,
        }
        # Add checkmarks for applicable harnesses
        for harness_pn in all_harness_pns:
            from_row[harness_pn] = "☑" if harness_pn in applicable_pns else ""
        matrix_rows.append(from_row)

        # Splice row (if applicable)
        splice_name = str(conn_row["Splice Name"]) if pd.notna(conn_row["Splice Name"]) else ""
        connection_type = str(conn_row["Connection Type"]) if pd.notna(conn_row["Connection Type"]) else ""
        if splice_name and connection_type.startswith("Splice"):
            splice_row = {
                "Device ID": "",
                "Connector No": splice_name,
                "Device Name": f"Splice_{splice_name}",
                "Pin": "",
                "Circuit": circuit_val,
                "Sales Code": sales_code_val,
            }
            for harness_pn in all_harness_pns:
                splice_row[harness_pn] = "☑" if harness_pn in applicable_pns else ""
            matrix_rows.append(splice_row)

        # To device row
        to_cnum = str(conn_row["To CNUM"]) if pd.notna(conn_row["To CNUM"]) else ""
        to_pin = str(conn_row["To Pin"]) if pd.notna(conn_row["To Pin"]) else ""
        to_device = cnum_to_device.get(to_cnum, "Unknown")

        to_row = {
            "Device ID": cnum_to_pin_info.get(to_cnum, {}).get("device_control_num", ""),
            "Connector No": to_cnum,
            "Device Name": to_device,
            "Pin": to_pin,
            "Circuit": circuit_val,
            "Sales Code": sales_code_val,
        }
        for harness_pn in all_harness_pns:
            to_row[harness_pn] = "☑" if harness_pn in applicable_pns else ""
        matrix_rows.append(to_row)
    
    matrix_df = pd.DataFrame(matrix_rows)
    if "Device Name" in matrix_df.columns:
        matrix_df = matrix_df[matrix_df["Device Name"].astype(str).str.strip().str.upper() != "UNKNOWN"].copy()
    return matrix_df


def export_excel(
    harness_code_map_df: pd.DataFrame,
    device_evaluation_df: pd.DataFrame,
    configurations_df: pd.DataFrame,
    generated_connections_df: pd.DataFrame,
    validation_report_df: pd.DataFrame,
    harness_print_matrix_df: pd.DataFrame | None = None,
    input_excel_path: str | Path | None = None,
) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        workbook = writer.book
        
        # Define formats
        header_format = workbook.add_format({
            'bg_color': '#ADD8E6',  # Light blue
            'border': 1,
            'bold': True,
            'align': 'center',
            'valign': 'vcenter',
        })
        
        device_row_format = workbook.add_format({
            'bg_color': '#FFFFE0',  # Pale yellow
            'border': 1,
            'align': 'left',
            'valign': 'vcenter',
        })
        
        checkbox_format = workbook.add_format({
            'bg_color': '#FFFFE0',  # Pale yellow
            'border': 1,
            'align': 'center',
            'valign': 'vcenter',
        })
        
        # Standard sheets
        harness_code_map_df.to_excel(writer, sheet_name="Harness_Code_Map", index=False)
        device_evaluation_df.to_excel(writer, sheet_name="Device_Evaluation", index=False)
        configurations_df.to_excel(writer, sheet_name="Configurations", index=False)
        generated_connections_df.to_excel(writer, sheet_name="Generated_Connections", index=False)
        validation_report_df.to_excel(writer, sheet_name="Validation_Report", index=False)
        
        # Add Harness Print Matrix with formatting
        if harness_print_matrix_df is not None and not harness_print_matrix_df.empty:
            matrix_df = harness_print_matrix_df
            sheet_name = "Harness_Print_Matrix"
            matrix_df.to_excel(writer, sheet_name=sheet_name, index=False)
            
            worksheet = writer.sheets[sheet_name]
            
            # Get the harness PN column indices (start after the fixed 6 columns)
            num_fixed_cols = 6  # Device ID, Connector No, Device Name, Pin, Circuit, Sales Code
            num_harness_cols = len(matrix_df.columns) - num_fixed_cols
            
            # Set column widths
            worksheet.set_column(0, 5, 15)  # Fixed columns
            worksheet.set_column(6, 6 + num_harness_cols - 1, 4)  # Harness PN columns (narrow)
            
            # Freeze the first 6 columns (and first row for headers)
            worksheet.freeze_panes(1, 6)
            
            # Format header row
            for col in range(len(matrix_df.columns)):
                worksheet.write(0, col, matrix_df.columns[col], header_format)
                
                # Rotate Harness PN headers vertically
                if col >= num_fixed_cols:
                    rotated_format = workbook.add_format({
                        'bg_color': '#ADD8E6',
                        'border': 1,
                        'bold': True,
                        'align': 'center',
                        'valign': 'bottom',
                        'rotation': 90,
                    })
                    worksheet.write(0, col, matrix_df.columns[col], rotated_format)
            
            # Format data rows
            for row in range(len(matrix_df)):
                for col in range(len(matrix_df.columns)):
                    if col < num_fixed_cols:
                        # Fixed columns: device info
                        worksheet.write(row + 1, col, matrix_df.iloc[row, col], device_row_format)
                    else:
                        # Harness PN columns: checkboxes
                        worksheet.write(row + 1, col, matrix_df.iloc[row, col], checkbox_format)
        
        # Add per-configuration connection sheets
        if not generated_connections_df.empty and "Configuration" in generated_connections_df.columns:
            used_sheet_names = set(writer.sheets.keys())
            for (circuit, cfg_id), group in generated_connections_df.groupby(["Circuit Name", "Configuration"], sort=False):
                # Create sheet name: CIRCUIT_CONFIGID (max 31 chars for Excel)
                sheet_name = _safe_excel_sheet_name(f"{circuit}_{cfg_id}", used_sheet_names)
                group.to_excel(writer, sheet_name=sheet_name, index=False)
    
    output.seek(0)
    return output.getvalue()


def _run_analysis_core(
    input_excel_path: str | Path,
    harness_code_map: dict[str, set[str]],
    harness_code_map_df: pd.DataFrame,
    option_df: pd.DataFrame,
) -> dict[str, Any]:

    device_eval_df, presence_matrix = build_harness_presence_matrix(harness_code_map, option_df)

    # Process all circuits
    configurations: list[Configuration] = []
    connection_rows: list[dict[str, str]] = []
    splice_allocators: dict[str, NameAllocator] = {}
    circuit_allocator = CircuitNameAllocator()

    # Build circuit codes for all circuits
    circuit_codes: dict[str, set[str]] = {}
    for _, row in option_df.iterrows():
        circuit_codes.setdefault(row["Circuit"], set()).update(_extract_codes_from_expression(row["Sales Code"]))

    # Check if D454 is present and build its specialized configurations
    if "D454" in option_df["Circuit"].values:
        d454_configs = _build_d454_engineering_configurations(harness_code_map, option_df, presence_matrix)
        if d454_configs:
            configurations.extend(d454_configs)
            connection_rows.extend(generate_d454_connections(d454_configs))

    # Build generic configurations for all OTHER circuits
    # Filter the presence matrix to exclude D454
    non_d454_matrix = {pn: {ckt: eps for ckt, eps in circuits.items() if ckt != "D454"} 
                       for pn, circuits in presence_matrix.items()}
    # Remove empty harness entries
    non_d454_matrix = {pn: circuits for pn, circuits in non_d454_matrix.items() if circuits}
    
    if non_d454_matrix:
        generic_configs = group_configurations(non_d454_matrix)
        
        for cfg in generic_configs:
            cfg.generated_sales_code = generate_sales_code_expression(
                cfg.target_harness_pns,
                harness_code_map,
                candidate_codes=circuit_codes.get(cfg.circuit_name, set()),
            )
            cfg.generated_sales_code_display = _simplify_sales_code_for_display(cfg.generated_sales_code)

        for cfg in generic_configs:
            if len(cfg.endpoints) == 2:
                cfg.topology_type = "Direct"
                connection_rows.extend(generate_direct_connections(cfg, circuit_allocator))
            elif len(cfg.endpoints) >= 3:
                cfg.topology_type = "Splice"
                connection_rows.extend(generate_splices(cfg, splice_allocators, circuit_allocator))

        configurations.extend(generic_configs)

    # If no circuits were processed, use full generic fallback
    if not configurations:
        configurations = group_configurations(presence_matrix)

        for cfg in configurations:
            cfg.generated_sales_code = generate_sales_code_expression(
                cfg.target_harness_pns,
                harness_code_map,
                candidate_codes=circuit_codes.get(cfg.circuit_name, set()),
            )
            cfg.generated_sales_code_display = _simplify_sales_code_for_display(cfg.generated_sales_code)

        for cfg in configurations:
            if len(cfg.endpoints) == 2:
                cfg.topology_type = "Direct"
                connection_rows.extend(generate_direct_connections(cfg, circuit_allocator))
            elif len(cfg.endpoints) >= 3:
                cfg.topology_type = "Splice"
                connection_rows.extend(generate_splices(cfg, splice_allocators, circuit_allocator))

    generated_connections_df = pd.DataFrame(connection_rows)

    # Set topology types for D454 configs
    for cfg in configurations:
        if cfg.circuit_name == "D454":
            if cfg.configuration_id == "CFG002":
                cfg.topology_type = "Direct"
            else:
                cfg.topology_type = "Splice"
        elif cfg.topology_type == "":
            # Set topology type for non-D454 configs
            if len(cfg.endpoints) == 2:
                cfg.topology_type = "Direct"
            elif len(cfg.endpoints) >= 3:
                cfg.topology_type = "Splice"

    configurations_df = pd.DataFrame(
        [
            {
                "Configuration ID": cfg.configuration_id,
                "Circuit Name": cfg.circuit_name,
                "Devices": ", ".join(sorted({e.cnum for e in cfg.endpoints})),
                "Generated Sales Code": cfg.generated_sales_code,
                "Display Sales Code": cfg.generated_sales_code_display,
                "Topology Type": cfg.topology_type,
                "Target Harness PNs": _display_pn_list(cfg.target_harness_pns),
            }
            for cfg in configurations
        ]
    )

    validation_report_df = validate_results(
        harness_code_map=harness_code_map,
        option_df=option_df,
        device_eval_df=device_eval_df,
        configurations=configurations,
        generated_connections_df=generated_connections_df,
    )

    # Generate Harness Print Matrix
    harness_print_matrix_df = generate_harness_print_matrix(
        generated_connections_df=generated_connections_df,
        input_excel_path=input_excel_path,
        harness_code_map=harness_code_map,
    )

    excel_bytes = export_excel(
        harness_code_map_df=harness_code_map_df,
        device_evaluation_df=device_eval_df,
        configurations_df=configurations_df,
        generated_connections_df=generated_connections_df,
        validation_report_df=validation_report_df,
        harness_print_matrix_df=harness_print_matrix_df,
        input_excel_path=input_excel_path,
    )

    return {
        "harness_code_map": harness_code_map,
        "harness_code_map_df": harness_code_map_df,
        "option_df": option_df,
        "device_evaluation_df": device_eval_df,
        "configurations_df": configurations_df,
        "generated_connections_df": generated_connections_df,
        "harness_print_matrix_df": harness_print_matrix_df,
        "validation_report_df": validation_report_df,
        "output_excel_bytes": excel_bytes,
    }


def run_analysis(input_excel_path: str | Path) -> dict[str, Any]:
    harness_code_map, harness_code_map_df = load_complexity_matrix(input_excel_path)
    option_df = load_option_per_circuit(input_excel_path)
    return _run_analysis_core(input_excel_path, harness_code_map, harness_code_map_df, option_df)


def run_analysis_from_option_df(
    input_excel_path: str | Path,
    option_df_override: pd.DataFrame,
) -> dict[str, Any]:
    """Run full analysis using an in-memory OptionPerCircuit dataframe override."""
    harness_code_map, harness_code_map_df = load_complexity_matrix(input_excel_path)
    option_df = option_df_override.copy()
    return _run_analysis_core(input_excel_path, harness_code_map, harness_code_map_df, option_df)
