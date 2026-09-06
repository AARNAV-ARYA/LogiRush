#!/usr/bin/env python
"""
End-to-end browser tests for the NER Logistics Intelligence Platform.

Drives a real Chromium browser against a running frontend + backend and asserts the whole
stack works together: pages render, the API is reached, routing responds, incidents flow
through verification into a route recalculation, and the offline queue survives a dead
network.

Run:
    # 1. backend
    cd routeOptimiserBackend && python main.py

    # 2. frontend (pointing at that backend)
    cd routeOptimiserFrontend && VITE_API_BASE_URL=http://127.0.0.1:5001 npm run build \
        && npx vite preview --port 4173

    # 3. tests
    pip install playwright && playwright install chromium
    python e2e/test_e2e.py --base-url http://127.0.0.1:4173 --api-url http://127.0.0.1:5001

Exit code is 0 only if every check passes, so this is usable as a CI gate.
"""

import argparse
import json
import os
import uuid
import sys
import urllib.request
from playwright.sync_api import sync_playwright

PASS, FAIL = "PASS", "FAIL"
results = []


def check(name, condition, detail=""):
    results.append((PASS if condition else FAIL, name, detail))
    marker = "✓" if condition else "✗"
    print(f"  {marker} {name}" + (f" — {detail}" if detail and not condition else ""))
    return bool(condition)


def api_post(api_url, path, payload, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"{api_url}{path}",
        data=json.dumps(payload).encode(),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read())


def sign_in(api_url, username, password):
    """Get a bearer token for one of the seeded demonstration accounts.

    Verification stopped being an anonymous POST when the access model landed: it is a
    decision that closes roads, so the API wants to know whose decision it was. A test that
    drives that pipeline has to sign in like an operator does.
    """
    body = api_post(api_url, "/api/auth/login", {"username": username, "password": password})
    return body["token"], body["user"]


def api_get(api_url, path):
    with urllib.request.urlopen(f"{api_url}{path}", timeout=60) as response:
        return json.loads(response.read())


def new_page(browser, width=1280, height=900):
    page = browser.new_page(viewport={"width": width, "height": height})
    page.js_errors = []
    page.failed_internal = []
    page.on("pageerror", lambda e: page.js_errors.append(str(e)))
    # External tile/font hosts may be blocked by a sandbox or offline CI; only same-origin
    # and API failures indicate a real problem with the application.
    page.on(
        "requestfailed",
        lambda r: page.failed_internal.append(r.url)
        if ("127.0.0.1" in r.url or "localhost" in r.url)
        else None,
    )
    return page


def run(base_url, api_url, headed=False):
    with sync_playwright() as p:
        # Let Playwright resolve its own browser. This used to hardcode
        # executable_path="/opt/pw-browsers/chromium", which is one particular machine's
        # layout: it fails on CI and on any developer's laptop with "executable doesn't
        # exist", no matter how correctly the browser was installed. Playwright's own
        # resolution already honours PLAYWRIGHT_BROWSERS_PATH, so an environment that keeps
        # browsers somewhere unusual sets that and this works unchanged. CHROMIUM_PATH stays
        # as an explicit override for a browser Playwright did not install.
        chromium_path = os.environ.get("CHROMIUM_PATH") or None
        browser = p.chromium.launch(headless=not headed, executable_path=chromium_path)

        # ------------------------------------------------------------------ pages render
        print("\n[1] Page rendering and API connectivity")
        # Expectations are the words the screens actually show. They drifted when the
        # dashboard and map were rebuilt around the map as the canvas, and a check that
        # asserts against a vanished heading fails for the wrong reason forever after.
        pages = [
            ("/dashboard", ["operations overview", "accessibility", "impassable", "field reports"]),
            ("/accessibility-map", ["corridor network", "state", "category"]),
            ("/shipment-planner", ["shipment planner", "cargo type", "urgency"]),
            ("/shipments", ["shipments"]),
            ("/incidents", ["incident review"]),
            ("/report-incident", ["report an incident", "severity", "submit report"]),
            # Provenance is a claim the platform makes about itself, so it is worth an
            # assertion that it still says the thing that matters: rainfall is not IMD's.
            ("/data-sources", ["where this data comes from", "live", "synthetic", "imd"]),
        ]
        for path, expected in pages:
            page = new_page(browser)
            page.goto(f"{base_url}{path}", wait_until="networkidle", timeout=45000)
            page.wait_for_timeout(2500)
            body = page.inner_text("body").lower()
            missing = [t for t in expected if t not in body]
            check(f"{path} renders", not missing, f"missing: {missing}")
            check(f"{path} has no JS errors", not page.js_errors, str(page.js_errors[:2]))
            check(f"{path} has no failed app requests", not page.failed_internal,
                  str(page.failed_internal[:2]))
            page.close()

        # ------------------------------------------------------------------ weather provenance
        print("\n[1b] Rainfall provenance")
        weather = api_get(api_url, "/api/ner/weather")
        check("weather endpoint responds", weather.get("status") == "success")
        # Whatever the feed is doing, the platform must never claim this is an IMD product.
        check("never claims to be an official IMD feed",
              weather.get("official_imd_feed") is False)
        check("says which source it is actually using", bool(weather.get("data_source")))
        check("reports every corridor", weather.get("count", 0) >= 30)
        # CI pins the snapshot, so this asserts the fallback is honest about itself.
        check("labels itself correctly when not live",
              weather.get("live") is True or "snapshot" in weather.get("data_source", "").lower(),
              f"live={weather.get('live')} source={weather.get('data_source')}")

        # ------------------------------------------------------------------ dashboard data
        print("\n[2] Dashboard shows live backend data")
        page = new_page(browser)
        page.goto(f"{base_url}/dashboard", wait_until="networkidle", timeout=45000)
        page.wait_for_timeout(3000)
        body = page.inner_text("body")
        check("provenance is stated on screen", "synthetic risk data" in body.lower())
        check("network figures rendered", "/100" in body and "corridors" in body.lower())
        check("field reports listed", "Field reports" in body)
        page.close()

        # ------------------------------------------------------------------ map
        print("\n[3] Map renders corridors")
        page = new_page(browser)
        page.goto(f"{base_url}/accessibility-map", wait_until="networkidle", timeout=45000)
        page.wait_for_timeout(3000)
        polylines = page.locator("path.leaflet-interactive").count()
        check("map draws corridor polylines", polylines > 10, f"{polylines} drawn")
        # The corridor table became a list in the map's inspector panel; the behaviour being
        # tested — filtering by state actually narrows what is listed — is unchanged.
        rows_before = page.locator("[data-testid='corridor-row']").count()
        page.select_option("select >> nth=0", label="Assam")
        page.wait_for_timeout(1200)
        rows_after = page.locator("[data-testid='corridor-row']").count()
        check("state filter narrows the corridor list", 0 < rows_after < rows_before,
              f"{rows_before} -> {rows_after}")
        page.close()

        # ------------------------------------------------------------------ planning
        print("\n[4] Route planning through the UI")
        page = new_page(browser, height=1300)
        page.goto(f"{base_url}/shipment-planner", wait_until="networkidle", timeout=45000)
        page.wait_for_timeout(2000)
        # Origin and destination became searchable comboboxes when place search landed, so a
        # plan now starts the way an operator starts it: by typing a place name and picking
        # from the suggestions.
        def choose_place(index, text):
            box = page.locator("input[role='combobox']").nth(index)
            box.click()
            box.fill("")
            box.type(text, delay=40)
            page.wait_for_selector("li[role='option']", timeout=20000)
            page.locator("li[role='option']").first.click()
            page.wait_for_timeout(300)

        choose_place(0, "Guwahati")
        choose_place(1, "Silchar")
        page.select_option("#cargo", label="Relief Material")
        page.click("button:has-text('Plan route')")
        page.wait_for_selector("[data-testid='recommended-route']", timeout=45000)
        body = page.inner_text("body")
        check("recommended route rendered", "Recommended" in body)
        check("route map highlights the plan", page.locator("[data-testid='route-map']").count() > 0)
        check("optimisation weights shown", "Optimisation profile" in body)
        page.click("summary:has-text('Why this route?')")
        page.wait_for_timeout(500)
        expanded = page.inner_text("body")
        check("explanation expands", "not a guarantee" in expanded.lower())

        # Cargo profile must actually change the recommendation.
        #
        # This used to read `route-path`, which shows only the endpoints — so after the
        # planner card was redesigned the comparison was "Guwahati→Silchar" against
        # "Guwahati→Silchar" and could never detect anything. The full waypoint list is what
        # actually distinguishes two routes between the same pair of towns.
        def recommended_path():
            return page.locator("[data-testid='route-waypoints']").first.get_attribute("data-path")

        relief_path = recommended_path()
        page.select_option("#cargo", label="Perishable Agricultural Goods")
        page.select_option("#urgency", label="critical")
        page.click("button:has-text('Plan route')")
        page.wait_for_selector("[data-testid='recommended-route']", timeout=45000)
        page.wait_for_timeout(2500)
        perishable_path = recommended_path()
        check("changing cargo re-plans and renders a route", bool(perishable_path))
        page.close()

        # What the cargo profiles actually guarantee.
        #
        # These two checks used to assert that relief and perishable pick *different* routes,
        # and that the relief one goes via Lumding specifically. Both held only because the
        # corridor risk values were synthetic: the direct Guwahati-Silchar corridor was hand-
        # scored 49/100, poor enough to force a detour. Once rainfall became live that corridor
        # scored 69 on a dry day, the detour was correctly no longer worth taking, and the test
        # failed for a system behaving perfectly. It was asserting the shape of the fake data.
        #
        # Divergence *is* still tested, deterministically, against the pinned snapshot where it
        # is a genuine property — see tests/test_ner_routing.py::
        # test_cargo_profile_changes_selected_route. What belongs here is the invariant that
        # must hold whatever the weather is doing: a risk-averse profile never accepts more
        # risk than a time-first one, and a time-first profile is never slower.
        relief = api_post(api_url, "/api/ner/plan-route", {
            "origin": "LOC002", "destination": "LOC007",
            "cargo_type": "relief", "urgency": "normal",
        })["recommended_route"]
        perishable = api_post(api_url, "/api/ner/plan-route", {
            "origin": "LOC002", "destination": "LOC007",
            "cargo_type": "perishable", "urgency": "critical",
        })["recommended_route"]

        check(
            "risk-averse relief never accepts more risk than a time-first run",
            relief["risk_score"] <= perishable["risk_score"] + 1e-6,
            f"relief risk={relief['risk_score']} perishable risk={perishable['risk_score']}",
        )
        check(
            "time-critical perishable is never slower than relief",
            perishable["eta_hours"] <= relief["eta_hours"] + 1e-6,
            f"perishable={perishable['eta_hours']}h relief={relief['eta_hours']}h",
        )
        check(
            "the profiles really do weight the objectives differently",
            api_post(api_url, "/api/ner/plan-route", {
                "origin": "LOC002", "destination": "LOC007",
                "cargo_type": "relief", "urgency": "normal",
            })["objective_weights"] != api_post(api_url, "/api/ner/plan-route", {
                "origin": "LOC002", "destination": "LOC007",
                "cargo_type": "perishable", "urgency": "critical",
            })["objective_weights"],
        )

        # ------------------------------------------------------------------ offline queue
        print("\n[5] Offline incident queueing")
        page = new_page(browser)
        page.goto(f"{base_url}/report-incident", wait_until="networkidle", timeout=45000)
        page.wait_for_timeout(1500)
        page.route("**/api/ner/incidents", lambda route: route.abort())  # simulate no network
        page.fill("input[type=number] >> nth=0", "25.60")
        page.fill("input[type=number] >> nth=1", "93.80")
        page.fill("textarea", "E2E offline test report")
        page.click("button:has-text('Submit report')")
        page.wait_for_timeout(3000)
        body = page.inner_text("body").lower()
        check("offline submission is queued locally", "saved on this device" in body)
        check("pending queue is surfaced", "waiting to sync" in body)

        # The queue must survive a reload — that is the whole point of IndexedDB here.
        page.unroute("**/api/ner/incidents")
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(2500)
        check("queue survives a page reload", "waiting to sync" in page.inner_text("body").lower())

        # And flushing it must clear it.
        page.click("button:has-text('Sync now')")
        page.wait_for_timeout(4000)
        check("sync clears the queue", "waiting to sync" not in page.inner_text("body").lower())
        page.close()

        # ------------------------------------------------------------------ incident -> reroute
        print("\n[6] Incident verification changes routing (full pipeline)")
        before = api_post(api_url, "/api/ner/plan-route", {
            "origin": "LOC002", "destination": "LOC007",
            "cargo_type": "perishable", "urgency": "critical",
        })
        before_path = before["recommended_route"]["path_names"]
        blocked = before["recommended_route"]["segments"][0]["segment_id"]

        # A fresh uuid per run. Reports are idempotent on client_uuid — that is what makes
        # replaying an offline queue safe — so a fixed one can be created exactly once ever,
        # and every later run was handed back the previous run's already-resolved report.
        created = api_post(api_url, "/api/ner/incidents", {
            "client_uuid": f"e2e-blocking-incident-{uuid.uuid4()}",
            "type": "landslide", "severity": 5,
            "description": "E2E test: corridor blocked",
            "latitude": 25.49, "longitude": 92.26,
        })
        incident_id = created["incident"]["id"]
        check("incident attributed to a corridor", created["incident"]["segment_id"] is not None,
              str(created["incident"]["segment_id"]))

        page = new_page(browser)
        page.goto(f"{base_url}/incidents", wait_until="networkidle", timeout=45000)
        page.wait_for_timeout(2500)
        check("incident appears in review queue",
              page.locator("[data-testid='incident-row']").count() > 0)
        page.close()

        # Closing a corridor takes two different verifiers, and the incident is in Assam, so
        # the Assam verifier signs and a controller (who may act anywhere) countersigns. One
        # signature must NOT be enough — that rule is the reason this pipeline exists.
        assam_token, _ = sign_in(api_url, "verifier.as", "verify123")
        control_token, _ = sign_in(api_url, "controller", "control123")

        first = api_post(api_url, f"/api/ner/incidents/{incident_id}/verify", {}, token=assam_token)
        check("one signature leaves the corridor open",
              first["incident"]["verification_status"] == "awaiting_countersign",
              first["incident"]["verification_status"])

        mid = api_post(api_url, "/api/ner/plan-route", {
            "origin": "LOC002", "destination": "LOC007",
            "cargo_type": "perishable", "urgency": "critical",
        })
        check("route is unchanged until the second signature",
              mid["recommended_route"]["path_names"] == before_path,
              f"{before_path} -> {mid['recommended_route']['path_names']}")

        second = api_post(api_url, f"/api/ner/incidents/{incident_id}/verify", {}, token=control_token)
        check("second signature verifies the closure",
              second["incident"]["verification_status"] == "verified",
              second["incident"]["verification_status"])

        after = api_post(api_url, "/api/ner/plan-route", {
            "origin": "LOC002", "destination": "LOC007",
            "cargo_type": "perishable", "urgency": "critical",
        })
        after_path = after["recommended_route"]["path_names"]
        check("route changes after verified blocking incident", before_path != after_path,
              f"{before_path} -> {after_path}")
        after_segments = [s["segment_id"] for s in after["recommended_route"]["segments"]]
        check("blocked corridor is excluded", blocked not in after_segments)

        # Clean up so repeated runs start from the same state. Resolving is the correct
        # transition for "the obstruction is gone" — it reopens the corridor at once and
        # keeps the record, which is what the platform asks operators to do.
        api_post(
            api_url,
            f"/api/ner/incidents/{incident_id}/resolve",
            {"reason": "E2E teardown: test obstruction cleared"},
            token=control_token,
        )

        # ------------------------------------------------------------------ contract checks
        print("\n[7] Frontend/backend contract")
        bands = api_get(api_url, "/api/ner/segments")["segments"]
        categories = {s["accessibility_category"] for s in bands}
        check("backend uses the 5 documented categories",
              categories <= {"Excellent", "Good", "Moderate", "Poor", "Critical"},
              str(categories))
        model = api_get(api_url, "/api/ner/model-info")
        check("model info declares synthetic training data",
              model["training"]["data"] == "synthetic")
        check("model is excluded from route selection",
              "route selection" in model["not_used_for"])

        # ------------------------------------------------------------------ responsive
        print("\n[8] Mobile layout (field users are on phones)")
        page = new_page(browser, width=390, height=844)  # iPhone-ish
        page.goto(f"{base_url}/dashboard", wait_until="networkidle", timeout=45000)
        page.wait_for_timeout(2500)
        scroll_width = page.evaluate("document.documentElement.scrollWidth")
        client_width = page.evaluate("document.documentElement.clientWidth")
        check("no horizontal overflow on mobile", scroll_width <= client_width + 2,
              f"scroll {scroll_width} vs client {client_width}")
        # Primary navigation became a persistent bottom tab bar rather than a hamburger, so
        # the six main screens are always one tap away; the secondary sheet (sign-in, about,
        # contact) is behind "More links" in the top bar.
        tabs = page.locator("nav[aria-label='Main'] a")
        check("mobile tab bar shows the main screens", tabs.count() >= 5, f"{tabs.count()} tabs")
        # The rail carries its own copy of this control; at this width only the top bar's is
        # rendered, so the test asserts on the visible one rather than the DOM count.
        more = page.locator("button[aria-label='More links']:visible")
        check("secondary links are reachable on a phone", more.count() == 1, f"{more.count()} visible")
        more.first.click()
        page.wait_for_timeout(700)
        sheet = page.locator("div[role='dialog'][aria-label='More links']")
        check("secondary sheet opens", sheet.count() == 1)
        check("sign-in is reachable from a phone",
              "Sign in" in page.inner_text("body"))
        page.screenshot(path="e2e-mobile-dashboard.png")
        page.close()

        # ------------------------------------------------------------------ accessibility
        print("\n[9] Accessibility basics")
        page = new_page(browser)
        page.goto(f"{base_url}/report-incident", wait_until="networkidle", timeout=45000)
        page.wait_for_timeout(1500)
        unlabelled = page.evaluate(
            """() => Array.from(document.querySelectorAll('input, select, textarea'))
                 .filter(el => !el.labels?.length && !el.getAttribute('aria-label')
                            && !el.getAttribute('aria-labelledby') && !el.getAttribute('placeholder'))
                 .length"""
        )
        check("all form controls are labelled", unlabelled == 0, f"{unlabelled} unlabelled")
        check("page has exactly one h1", page.locator("h1").count() == 1)
        skip_link = page.evaluate(
            "() => document.querySelector('a[href=\"#main\"]')?.textContent || ''"
        )
        check("skip-to-content link exists", "Skip to content" in skip_link)
        page.close()

        browser.close()

    failures = [r for r in results if r[0] == FAIL]
    print(f"\n{'=' * 60}")
    print(f"{len(results) - len(failures)}/{len(results)} checks passed")
    if failures:
        print("\nFailures:")
        for _, name, detail in failures:
            print(f"  ✗ {name} {detail}")
    return 1 if failures else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:4173")
    parser.add_argument("--api-url", default="http://127.0.0.1:5001")
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()
    sys.exit(run(args.base_url, args.api_url, args.headed))
