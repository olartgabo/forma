# Workshop home release

Restore the previously local dashboard as the signed-in landing view. My Projects
lists actual saved projects, My Materials reads selected project stock, and
Shopping List uses the released sourcing panel. Current guided intake and manual
remain mounted while hidden so returning Home cannot abandon an active request.
Existing `?project=` links still open that project after sign-in.

The dashboard uses two owner-scoped read-only routes:

- `GET /api/projects/{id}/construction/preview?expected_inventory_revision_id=…`
  returns the latest completed construction receipt for a current unactivated
  project. Absent receipts return404. Pending, unknown, malformed, foreign or stale
  latest receipts never cause a fallback to an older proposal.
- `GET /api/projects/{id}/versions/{version}/geometry?expected_inventory_revision_id=…`
  returns canonical planned geometry for the current active version. It loads no
  physical events, calls no provider and writes no records. Stale identities
  return409; unsupported geometry returns422. The client may use that immutable
  version's saved manual only for explicitly unsupported geometry.

Both routes reuse existing Pydantic response types and the canonical geometry
producer. Shared API registration and generated contracts remain unchanged.

Checks: `npm run test:web`, scoped geometry/stability pytest, contracts, formatting,
TypeScript and production build. The existing dashboard browser runner consumes
real engine-generated geometry fixtures and verifies empty/error/populated states,
navigation, pagination, draft retention, favorites, thumbnails and responsive
layout without provider calls or project writes. This is regression coverage;
Terra's separate computer-use acceptance runs against the actual deployed app.

Shopping state stays mounted after first opening the section. Active location or
supplier requests lock navigation until the response arrives. An unresolved
outcome locks only that shopping selector and its new-request controls; Home and
unrelated projects remain accessible. Reconciliation stays usable. The regression
retains drafts across sections, checks locking during a delayed reply, and verifies
that an unknown response preserves its receipt through Home/back and reconciles
with GET without an extra research POST.
