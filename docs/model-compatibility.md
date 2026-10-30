# Model compatibility

Status: **not tested**. Owner: @ResniDev. Issues: #4 and #9.

The source spec names Spark and SAM and lists official reference URLs in
section 18. Its model IDs/endpoints are inputs to investigate, not proof that
this team's account or deployment can use them.

## Required live records

| Check                                                          | State           | Evidence |
| -------------------------------------------------------------- | --------------- | -------- |
| Account, region and allowed use                                | Not checked     | Pending  |
| Spark image + text returning typed inventory proposal          | Not run         | Pending  |
| Structured output validation and deterministic tool round-trip | Not run         | Pending  |
| SAM mask/box on an actual team photo                           | Not run         | Pending  |
| Manual box/label fallback                                      | Not implemented | Pending  |
| Quota, privacy mode, latency and actual usage/cost             | Not checked     | Pending  |

For each attempt record date, environment/region, official documentation URL,
exact endpoint, model ID, SDK/version, prompt/schema version, consented fixture
ID, sanitized request/response, elapsed time, actual usage and error codes.
Record failures as failures. Never store keys, authorization headers, private
media URLs or identifiable room photos in public traces.

## Implementation boundary

Keys stay server-side. Runtime-validate proposal/tool data and cap retries,
candidate counts and total model/tool rounds. Preserve the validated manual
when Spark fails. SAM cannot determine exact dimensions or strength; user
correction always remains available. Use Standard privacy mode by default per
the spec, subject to actual verified provider controls and user consent.

Image enhancement and voice are P1 and have no required smoke result yet.
Add [scripts](../scripts/README.md) commands only when executable code exists.
