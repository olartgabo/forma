# Decisions

Status: planning baseline, October 30, 2026. Accepted entries below come from
the supplied spec or the user's ownership instruction. They are architecture
constraints, not claims that software or physical tests exist.

## Accepted baseline

| ID   | Decision                                                                                   | Basis                                              |
| ---- | ------------------------------------------------------------------------------------------ | -------------------------------------------------- |
| D001 | One low-risk tabletop stand family; P0 build/recovery first                                | formspec.md sections 2, 4, 19                      |
| D002 | Next.js/React/TypeScript web and FastAPI/Pydantic backend                                  | Spec sections 3, 13; exact versions pending        |
| D003 | Pure offline compiler/replanner/renderer; authoritative SVG geometry                       | Spec sections 3-5, 8                               |
| D004 | Model proposals require deterministic validation and user approval                         | Spec sections 5-7                                  |
| D005 | Separate immutable plan versions, physical events and evidence                             | Spec sections 5, 10-12                             |
| D006 | @ResniDev owns compiler + Meta; @olartgabo owns product + validation                       | User instruction; supersedes spec's A/B allocation |
| D007 | PostgreSQL/private object storage production target; SQLite/local assets permitted for dev | Spec section 11; provider choice pending           |

## Pending decisions

| ID   | Question and required evidence                                                                   | Owner                                  | Resolve before                   |
| ---- | ------------------------------------------------------------------------------------------------ | -------------------------------------- | -------------------------------- |
| P001 | Runtime/package versions, npm/Python tooling, dependency install, formatter and real CI commands | @olartgabo with @ResniDev              | #1 implementation                |
| P002 | Python package layout, schema export/type generation paths and error taxonomy                    | @ResniDev with @olartgabo              | #3 consumers                     |
| P003 | Session/auth mechanism and authenticated project/media access                                    | @olartgabo                             | #6 persistence routes            |
| P004 | Hosting region, DB/object-storage providers, migrations, backup and deletion approach            | @olartgabo                             | #6/#16 deployment                |
| P005 | Actual inventories A/B, stand dimensions, material thickness and tools in hand                   | @olartgabo                             | #2/#5 geometry                   |
| P006 | Three tested joint/repair strategies, measured tolerances and supported limits                   | @olartgabo; @ResniDev encodes profiles | #2/#5 profile promotion          |
| P007 | Named device/mass, angle, surface, duration and repeated-use functional test                     | @olartgabo                             | First physical build             |
| P008 | Live Meta access, actual endpoints/model IDs, SDK, region, quota, privacy mode and budget        | @ResniDev                              | #4 live smoke gate               |
| P009 | SAM practical value versus manual box/label fallback                                             | @ResniDev with @olartgabo              | #4/#7 intake                     |
| P010 | Portal team eligibility, terms/media consent, deliverables and exact deadline/timezone           | @olartgabo                             | Day 0; recheck before submission |
| P011 | Independent builder availability and consented study scope                                       | @olartgabo                             | #15 evaluation                   |
| P012 | Narrowing to tested templates/fewer operations if G2/G3 miss October 31                          | Both                                   | October 31 gate                  |

Use spec section 18 as the starting reference list for provider/competition
verification. No live external claims were revalidated by this scaffold.
Optional Image/Voice/3D decisions wait until physical P0 is green.

## Recording a resolution

For each resolved pending item, add date, owner, chosen option, why it fits the
current scope, consequences, supporting issue/experiment and affected contracts.
Update the table status explicitly. If it changes the product, record the
spec impact instead of silently treating the old text as current.
