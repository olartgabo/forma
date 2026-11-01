"""Permanently disabled legacy Python devloop entry point.

Importing this module has no effects. Any execution directs callers to the
active guarded launcher at ``tools/devloop/guarded/run.mjs`` and fails closed.
"""

import sys

MESSAGE = (
    "Legacy Python devloop is permanently disabled; "
    "use tools/devloop/guarded/run.mjs instead."
)


def main() -> int:
    print(MESSAGE, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
