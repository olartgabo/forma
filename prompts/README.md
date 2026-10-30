# Versioned prompts

Owner: @ResniDev. Reviewer: @olartgabo. Issue: #9. Status: offline implementation.

Runnable trusted instructions are packaged in
`apps/api/src/forma_api/proposal_prompts.py` at version `bounded-proposals-v1`;
the flat domain proposal schema version is `domain-proposals-v1`. Packaging
instructions in Python keeps installed API deployments independent of a root
working directory. Change the version when instructions or output contracts
change. `ProposalService` selects intake/design/diagnose/repair instructions.
User text, scoped snapshot and exact compiler feedback are separate JSON data
in the user role; they never become system instructions. Typed tools validate
scope and arguments before reading a snapshot/profile catalog. Provider output
still requires domain validation and deterministic compiler/replanner checks.

Approved revision explanation remains future work; no model can approve one.
Safe request traces record prompt/schema versions, transport model/latency/usage,
model rounds, tool executions and stable error codes without private content.

Inputs are bounded snapshots with explicit IDs and confirmed/unknown facts.
Diagnosis separates observations, hypotheses and requested measurements.
Output uses validated flat/bounded schemas: at most two designs or three repairs,
with default four total model/tool rounds. Never instruct the model to complete
physical actions or mark tests passed. The orchestrator enforces these limits.

Tool allowlist from spec section 7: get_project_snapshot,
get_supported_joint_profiles, simulate_patch, request_measurement, request_photo,
explain_validator_error and propose_alternate_inventory. Validate arguments and
project scope server-side. Commit/completion/test-pass tools are prohibited.

Implemented #9 tools are `get_project_snapshot` and
`get_supported_joint_profiles`; the latter exposes typed catalog status including
experimental profiles, never promotes them. The trusted compiler callback makes
the final feasibility decision. #4's typed `check_measurements` smoke tool remains
available. Other spec tools are reserved, not implemented runtime capabilities.
The gateway's name allowlist does not create a service tool automatically.
