import type {
  ConfirmedLocation,
  LocationChoice,
} from "./generated/api-contracts";

// Called only after a location-button gesture; raw coordinates never leave this helper.
export function approximateDeviceLocation(coords: {
  latitude: number;
  longitude: number;
  accuracy: number;
}) {
  if (
    !Number.isFinite(coords.latitude) ||
    Math.abs(coords.latitude) > 90 ||
    !Number.isFinite(coords.longitude) ||
    Math.abs(coords.longitude) > 180 ||
    !Number.isFinite(coords.accuracy) ||
    coords.accuracy <= 0 ||
    coords.accuracy > 99920
  )
    throw new Error(
      "The device did not provide a usable location. Enter a city and country instead.",
    );
  return {
    latitude: Math.round(coords.latitude * 1000) / 1000,
    longitude: Math.round(coords.longitude * 1000) / 1000,
    accuracy_m: coords.accuracy,
    location_basis: "device" as const,
    label: "Approximate device area",
  };
}

export type LocationCandidate =
  LocationChoice | ReturnType<typeof approximateDeviceLocation>;

export function confirmLocation(
  candidate: LocationCandidate,
  confirmed: boolean,
  transferConsented: boolean,
): ConfirmedLocation {
  if (!confirmed || !transferConsented)
    throw new Error(
      "Confirm this area and allow map lookup before sharing it.",
    );
  return {
    latitude: candidate.latitude,
    longitude: candidate.longitude,
    accuracy_m: candidate.accuracy_m,
    location_basis: candidate.location_basis ?? "city_center",
    label: candidate.label,
    ...("country_code" in candidate && candidate.country_code
      ? { country_code: candidate.country_code }
      : {}),
    ...("city" in candidate && typeof candidate.city === "string"
      ? { city: candidate.city }
      : {}),
    ...("region" in candidate && typeof candidate.region === "string"
      ? { region: candidate.region }
      : {}),
    confirmed: true,
    transfer_consented: true,
  };
}

export function locationFailure(error: { code?: number } | null): string {
  if (error?.code === 1)
    return "Location permission was denied. Enter a city and country instead.";
  if (error?.code === 3)
    return "Location timed out. Enter a city and country or try the location button again.";
  return "Your device location is unavailable. Enter a city and country instead.";
}

export function requestDeviceLocation(
  geolocation: Pick<Geolocation, "getCurrentPosition"> | undefined,
): Promise<ReturnType<typeof approximateDeviceLocation>> {
  return new Promise((resolve, reject) => {
    if (!geolocation) return reject(new Error(locationFailure(null)));
    geolocation.getCurrentPosition(
      (position) => {
        try {
          resolve(approximateDeviceLocation(position.coords));
        } catch (error) {
          reject(error);
        }
      },
      (error) => reject(new Error(locationFailure(error))),
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 60000 },
    );
  });
}
