# Nearby suppliers and price research

Shopping list is part of the connected workbench. Choose a project, allow map
lookup and press **Use my location**. Browser permission is requested on that
explicit action. The rounded device point is confirmed automatically, reverse
lookup supplies a city and editable currency suggestion, and manual city choice
remains available after denial, timeout or unavailable GPS. The browser location
can itself be imprecise; distances include its accuracy and an 80-metre rounding
allowance. They are straight-line estimates, not routes or delivery promises.

Device coordinates are rounded to three decimals before leaving the browser.
The city-level reverse lookup (zoom 10) never substitutes a city-center coordinate
for the device point and never requests a home address. Only city/region/country,
the item and public mapped-shop hints reach Meta after separate transfer consent.
Coordinates, owner tokens, project inventory and photos are not model inputs.

## Runtime pipeline

Owner-scoped, expected-revision and idempotency checks precede a durable research
reservation. Consented automatic research combines a bounded OSM lookup with one
Standard muse-spark-1.3 background response. The request permits one search tool
call and 2,200 output tokens with minimal reasoning. Status polling retrieves the
same provider ID; it never starts another generation. Twenty-four reads and a
finite browser wait bound automatic polling; unknown outcomes stop that flow.
Known terminal output-limit failures retain reported usage and allow explicit new
research, while unreconciled provider outcomes remain blocked.

The provider may return exact source URLs in search metadata while omitting them
and price excerpts from model-visible context. The app therefore discovers product
URLs from the actual tool results, not from guessed model URLs. A separate bounded
public reader verifies numeric prices. A model price alone cannot establish one.

The public reader validates public DNS, pins TLS connections with hostname checks
and the maintained Mozilla CA bundle, and observes applicable robots rules. It
executes no JavaScript, sends no cookies, credentials, seller messages or orders,
and never requests Facebook/Meta pages. Product identity, currency, quantities,
variant ambiguity, misleading free/zero/DM/from/deposit prices and structured price
evidence are checked. Single-item GA4 view_item JSON can bind missing currency only
when its product name and URL item ID match the main Product scope and its amount
agrees with all microdata prices. No analytics script executes.

Limits: three candidate sites, eight requests each including robots/redirects,
24 requests total, 30 seconds, 4 MB per page and 8 MB total response bodies. Refused
hosts (401/403/406/429/451) are stored privately for 24 hours, including www aliases
and redirects. This release imports actual November 4 Paper Source/DoItBest refusal
receipts so deployment cannot retry those known refusals. It uses no proxy rotation,
identity changes, challenge bypass or disabled TLS checks. Retailer restrictions
can still leave prices unknown; the app says so rather than inventing a result.

Mapped nearby shops and online catalogue prices are separate sections. A catalogue
price does not establish a nearby branch, pickup, stock, suitability, taxes or
shipping. Research never changes stock, active plans, physical events or Proof.
Purchased materials still need normal intake, measurements and confirmation.

## Map service

Nominatim is a configurable prototype provider with attribution, shared cross-worker
one-request-per-second limiting and 24-hour caching. Lookups are deliberate user
actions, not autocomplete or systematic POI extraction. Hardware, stationery and DIY
use documented type phrases across languages. Public craft search is unsupported.
A scaled release needs a hosted/self-hosted service suitable for its traffic.
See https://operations.osmfoundation.org/policies/nominatim/ and the provider's
special-phrase documentation. FORMA_NOMINATIM_ORIGIN, FORMA_OSM_USER_AGENT and
FORMA_OSM_CACHE_PATH configure the service; optional Overpass has no automatic
fallback. No location is inferred silently from an IP address or timezone.

## Connected acceptance, November 4, 2026

The production build -> FastAPI -> real Nominatim -> Meta -> permitted public price
source path passed without API interception or a pasted URL. A simulated browser
GPS point in San Francisco resolved its city and USD currency, returned ten mapped
stationery shops and verified Fiskars Stainless Steel Scissors 1 pc at USD 21.99
from the exact Stine Home + Yard product URL returned in Meta search metadata.
Desktop 1280px and mobile 390px checks passed. The saved project was unchanged.
The GPS permission flow is a browser software test, not a claim of physical GPS
observation. Stine's catalogue is online evidence, not verified San Francisco stock.

The first bounded Meta diagnosis ended at its output limit; its terminal state and
reported usage were reconciled, not relabeled unknown forever or hidden. A later
completed search and initial price check exposed the portable CA and main-product
currency-binding defects now covered by regression checks. Earlier retailer
refusals and all older uncertain provider receipts remain preserved in the local
append-only journal. These provider calls consume usage; counts are actual reported
metadata, not assumed prices or claims that calls are free.

## Endpoints and deployment

POST /api/projects/{id}/sourcing/reverse resolves a confirmed rounded point;
/sourcing/locations is the manual city fallback; /sourcing/nearby returns mapped
businesses. POST /sourcing/research and GET /sourcing/research/{run_id} implement
research and same-response polling. Pydantic generates browser contracts. The
supported explicit supplier-page inspector remains an advanced option; Facebook
Marketplace remains a manual handoff without retrieval entitlement.

The release is integrated onto current main, preserving its newer intake, photo,
measurement and engine features. GitHub Actions runs the full checks and container
builds on the exact PR head. Main's existing deployment workflow updates the EC2
host while retaining data volumes and server-only SSM secrets. Deployment and its
fresh authenticated live acceptance are recorded in the supervisor checkpoint.
