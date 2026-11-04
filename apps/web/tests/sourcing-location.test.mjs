import assert from "node:assert/strict";
import { test } from "node:test";
import {
  approximateDeviceLocation,
  confirmLocation,
  locationFailure,
  requestDeviceLocation,
} from "../src/lib/sourcing-location.ts";

test("device coordinates are rounded before leaving the browser; reported accuracy remains explicit", () => {
  const location = approximateDeviceLocation({
    latitude: 37.774923,
    longitude: -122.419456,
    accuracy: 42,
  });
  assert.deepEqual(location, {
    latitude: 37.775,
    longitude: -122.419,
    accuracy_m: 42,
    location_basis: "device",
    label: "Approximate device area",
  });
  assert.equal("confirmed" in location, false);
  assert.equal("transfer_consented" in location, false);
});

test("local device permission does not imply external map consent or confirmation", () => {
  const candidate = approximateDeviceLocation({
    latitude: -17.39,
    longitude: -66.16,
    accuracy: 25,
  });
  for (const [confirmed, transfer] of [
    [false, false],
    [true, false],
    [false, true],
  ])
    assert.throws(() => confirmLocation(candidate, confirmed, transfer));
  const accepted = confirmLocation(candidate, true, true);
  assert.equal(accepted.confirmed, true);
  assert.equal(accepted.transfer_consented, true);
});

test("confirming a city preserves unknown user offset and strips the geocoder choice id", () => {
  const accepted = confirmLocation(
    {
      id: "city-choice",
      latitude: 37.77,
      longitude: -122.42,
      accuracy_m: null,
      location_basis: "city_center",
      country_code: "US",
      city: "Selected city",
      region: "Selected region",
      label: "Selected city",
    },
    true,
    true,
  );
  assert.equal(accepted.accuracy_m, null);
  assert.equal(accepted.location_basis, "city_center");
  assert.equal(accepted.city, "Selected city");
  assert.equal(accepted.region, "Selected region");
  assert.equal("id" in accepted, false);
});

test("unusable coordinates and unbounded device uncertainty cannot become a search origin", () => {
  for (const change of [
    { latitude: NaN },
    { latitude: 91 },
    { longitude: -181 },
    { accuracy: 0 },
    { accuracy: Infinity },
    { accuracy: 100000 },
  ])
    assert.throws(() =>
      approximateDeviceLocation({
        latitude: 0,
        longitude: 0,
        accuracy: 30,
        ...change,
      }),
    );
});

test("device lookup is only dispatched by an explicit helper invocation and is finite", async () => {
  let calls = 0;
  const geolocation = {
    getCurrentPosition(success, _failure, options) {
      calls++;
      assert.deepEqual(options, {
        enableHighAccuracy: true,
        timeout: 15000,
        maximumAge: 60000,
      });
      success({
        coords: { latitude: 37.774923, longitude: -122.419456, accuracy: 42 },
      });
    },
  };
  assert.equal(calls, 0);
  assert.equal((await requestDeviceLocation(geolocation)).latitude, 37.775);
  assert.equal(calls, 1);
});

test("denied, timed out and unavailable location all offer manual city fallback", async () => {
  for (const code of [1, 2, 3]) {
    assert.match(locationFailure({ code }), /city and country/);
    await assert.rejects(
      requestDeviceLocation({
        getCurrentPosition(_success, failure) {
          failure({ code });
        },
      }),
      /city and country/,
    );
  }
  await assert.rejects(requestDeviceLocation(undefined), /city and country/);
});
