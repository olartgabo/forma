# Repository collaboration

Use the [pull request template](pull_request_template.md) for review handoffs.
Link the GitHub issue and report actual acceptance checks.

`workflows/checks.yml` runs on pull requests and pushes to main. It installs the
pinned Node/npm/uv/Python tools, runs `npm ci` and `uv sync --locked`, then
`npm run check` for formatting, lint, TypeScript, offline Python tests and web
build. No model keys or physical evidence are needed. Live provider checks stay
separate. See the [root README](../README.md) for the same local commands.
