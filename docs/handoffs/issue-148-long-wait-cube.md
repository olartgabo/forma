# Issue 148 long-wait cube

The browser shows the cube only in **Invent with my materials**, below the
construction request controls. The 10-second delay starts when the browser
sends the proposal request. Quick replies and local request bookkeeping use
the existing status text. A response with a rotatable preview triggers the
three-turn solve alongside the result. A preview can still require physical
measurements. Failure and cancellation clear the animation, and reduced motion
uses a still waiting cube.

The animation is browser presentation. It takes no new API inputs and makes no
provider calls. The separate assembly viewer in PR #169 is outside this branch.
The placement and delay follow [Endi Saliaj's loading guidance](https://endisaliaj.com/blog/interactive-loading-animation-rubiks-cube/).

Validation used the existing construction fixture exporter and Chromium
browser replay. Both the 390 px and 1280 px scenarios passed, including the
10-second threshold, quick replays, rejection, reduced motion and durable
request recovery. See `apps/web/tests/muse-construction.browser.mjs` for the
local replay. The fixture exercises software only.
