# Project scripts

Status: no executable scripts exist yet. Owners follow their implementation issue.

Reserve schema export/type generation (#3, @ResniDev), live Meta smoke tests
(#4, @ResniDev) and evaluation execution (#15, @olartgabo). The spec suggests
`smoke_meta.py` and `run_evaluation.py`; publish actual commands only when those
files and their dependencies exist.

Scripts must exit nonzero on failure, redact secrets and keep offline checks
usable without model credentials. Live/physical checks require an explicit mode
and must never emit a fabricated success. Document install prerequisites and
exact check commands in the root README with implementation.
