# Versioned prompts

Owner: @ResniDev. Reviewer: @olartgabo. Issue: #9. Status: no runnable prompts yet.

Reserve task-specific prompt sources for intake interpretation, supported design
proposal, failure diagnosis, adaptation proposal and explanation of an approved
revision. Record a prompt/schema version with each real provider trace.

Inputs are bounded snapshots with explicit IDs and confirmed/unknown facts.
Diagnosis separates observations, hypotheses and requested measurements.
Output uses validated flat/bounded schemas: at most two designs or three repairs,
with default four total model/tool rounds. Never instruct the model to complete
physical actions or mark tests passed. The orchestrator enforces these limits.

Tool allowlist from spec section 7: get_project_snapshot,
get_supported_joint_profiles, simulate_patch, request_measurement, request_photo,
explain_validator_error and propose_alternate_inventory. Validate arguments and
project scope server-side. Commit/completion/test-pass tools are prohibited.
