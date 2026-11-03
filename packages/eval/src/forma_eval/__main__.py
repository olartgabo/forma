"""Usage: python -m forma_eval MANIFEST.json  (prints the Markdown report)."""

import sys
from pathlib import Path

from forma_eval.report import conflicts, load, summarize


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    entries = load(Path(argv[0]))
    sys.stdout.write(summarize(entries))
    # Label conflicts are printed in the report and fail the run, so a
    # contradicted result cannot be published by accident.
    return 1 if any(conflicts(a, f) for a, f in entries) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
