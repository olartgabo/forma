"""Declared fabrication-rules-v1: conservative family, tool and access rules.

These cover what compiler checks do not: which operation types this family's
progress flow records, which tool classes an operation needs and whether a
part face can still be reached once a join encloses it. They model access;
they do not observe it.
"""

import re

from forma_domain.fabrication_contracts import ToolCheck, ToolClass

# Operation types the tabletop family can record as physical progress.
FAMILY_OPERATION_TYPES = {
    "tabletop_fixture_v1": frozenset(
        {"cut_rect", "fold", "tape_joint", "detach", "inspect", "functional_test"}
    ),
}

JOIN_TYPES = frozenset({"insert_tab", "tape_joint", "tie_joint", "attach_brace"})

# Shaping a part needs both faces free. Once any join holds the part, the
# rules treat the work as unreachable until an explicit detach frees it.
PREPARATION_TYPES = frozenset({"mark", "cut_slot", "fold"})

# Whole words or phrases in a declared tool name that satisfy a tool class.
# Anything else stays undeclared rather than guessed.
TOOL_KEYWORDS: dict[ToolClass, tuple[str, ...]] = {
    "cutting_tool": (
        "scissors",
        "knife",
        "cutter",
        "blade",
        "scalpel",
    ),
    "ruler": ("ruler", "straightedge", "tape measure", "measuring tape"),
    "marker": ("pencil", "pen", "marker"),
    "scale": ("scale",),
    "protractor": ("protractor",),
}


def required_tools(operation) -> tuple[ToolClass, ...]:
    match operation.type:
        case "cut_rect" | "cut_slot" | "tape_joint" | "tie_joint":
            return ("cutting_tool", "ruler")
        case "fold":
            return ("ruler",)
        case "mark":
            return ("marker", "ruler")
        case "measure":
            return {
                "ruler": ("ruler",),
                "scale": ("scale",),
                "protractor": ("protractor",),
                "known_reference": (),
            }[operation.args.method]
        case "inspect":
            return ("ruler",) if operation.args.method == "ruler" else ()
        case "detach":
            return (
                ("cutting_tool",)
                if operation.args.supported_inverse == "cut_cord"
                else ()
            )
    return ()


def tool_confirmations(checks: tuple[ToolCheck, ...]) -> tuple[str, ...]:
    """Name tool gaps that require an actual scoped availability declaration."""
    found = []
    for check in checks:
        name = check.tool.replace("_", " ")
        if check.status == "unknown":
            found.append(f"No tools were saved. Confirm you have a {name}.")
        elif check.status == "not_declared":
            found.append(f"None of your saved tools is a {name}. Confirm you have one.")
    return tuple(found)


def _matches(name: str, keyword: str) -> bool:
    return re.search(rf"\b{re.escape(keyword)}\b", name.casefold()) is not None


def tool_checks(
    operation, declared_tools: tuple[str, ...] | None
) -> tuple[ToolCheck, ...]:
    checks = []
    for tool in required_tools(operation):
        if declared_tools is None:
            checks.append(ToolCheck(tool=tool, status="unknown", declared_name=None))
            continue
        match = next(
            (
                name
                for name in declared_tools
                if any(_matches(name, word) for word in TOOL_KEYWORDS[tool])
            ),
            None,
        )
        checks.append(
            ToolCheck(
                tool=tool,
                status="not_declared" if match is None else "declared",
                declared_name=match,
            )
        )
    return tuple(checks)
