# Agent development workflow

## Before editing

Read [AGENTS.md](../AGENTS.md), the complete [spec](../formspec.md), the relevant
module README and the assigned issue. Check `git status`, the current branch,
active [handoffs](handoffs/README.md) and [decisions](decisions.md).

Name the issue, files to change, expected contract inputs/outputs and acceptance
checks. Work on an issue branch. Parallel writing agents use disjoint files;
separate worktrees are useful when multiple people share a checkout. Never
overwrite another lane's uncommitted work.

## During implementation

Keep each change to one reviewable vertical slice. Domain/schema changes land
before dependent generated clients. If a dependency is missing, document its
contract and blocker; keep any temporary mock clearly synthetic and do not
count it as live provider or physical evidence.

Development can use independent exploration/review agents. The deployed product
uses the bounded reasoning flow in [architecture.md](architecture.md); do not
add runtime agent frameworks to support the development workflow.

Do not introduce a new decision solely to fill a template. Resolve routine
implementation choices within the assigned issue and record choices that
affect the other engineer's interfaces, physical claims or deployment.

## Handoff

Copy [handoffs/TEMPLATE.md](handoffs/TEMPLATE.md) to an issue-specific Markdown
file when real work begins. Include changed paths, contract changes, commands
actually run and their outputs, pending facts and the next concrete action.
Link the handoff in the PR body. Keep credentials and private evidence out.

Before publishing, review the diff and run actual repository checks. Use plain
commit/PR text describing the problem, resulting behavior and verification.
No attribution trailers. Do not mark an issue done while acceptance evidence
is missing. Coordinate through repository artifacts; sending teammates messages
requires an explicit user request.
