# Photo deletion protection metadata for issue90

Connected-demo followup: keep the existing server deletion rule and explain it before the user presses Delete. No change to retention or evidence history is authorized by this additive slice.

The API owns canonical Media. Add an optional/default-false evidence_linked boolean to its metadata. The authenticated project media list computes current evidence references across all stored versions in that project, not only the active version. It exposes no evidence IDs, text, counts, asset paths or other-owner data. No schema migration is needed. Upload results remain compatible; list reload is authoritative after evidence changes. The server still rechecks deletion atomically.

The browser uses the generated contract, disables Delete when evidence_linked is true, and explains that diagnosis or physical evidence retains the photo. Existing material-link restrictions remain separate. Reload photo metadata when diagnosis/progress changes, with existing session/project cancellation and stale-response guards. Failure to load metadata must never fabricate a deletable state. No provider calls, evidence deletion, orphaning or project deletion is added.

Muse owns source/tests and regeneration; supervisor reviews the green complete diff. Cover historical-version evidence, owner scope, unreferenced photos, retained deletion block and stale session refresh behavior. Missing real physical facts remain unknown.
