// Google address dropdown (Places API (New)), shared by the home page and the booking form.
// Loads only when the owner sets the Maps key in Render; if Google is missing, blocked or the
// key is refused, the page's plain address box keeps working (onFail).
//
//   SGPlaces.attach(key, { slot, id, label, onPick(text, lat, lng), onReady(), onFail() })
(function () {
  let loading = null;
  const failures = [];
  // Google calls this when the key is invalid, expired or not allowed on this site.
  window.gm_authFailure = () => failures.forEach((f) => f());

  function load(key) {
    if (!loading) {
      loading = new Promise((resolve, reject) => {
        window.__sgPlacesReady = resolve;
        const s = document.createElement("script");
        s.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(key)}&loading=async&libraries=places&callback=__sgPlacesReady`;
        s.async = true;
        s.onerror = reject;
        document.head.append(s);
      });
    }
    return loading;
  }

  async function attach(key, { slot, id, label, onPick, onReady, onFail }) {
    if (onFail) failures.push(onFail);
    try {
      await load(key);
      const { PlaceAutocompleteElement } = await google.maps.importLibrary("places");
      const picker = new PlaceAutocompleteElement({ includedPrimaryTypes: ["street_address", "premise", "subpremise"] });
      picker.includedRegionCodes = ["us"];                                              // US addresses only
      picker.locationBias = { center: { lat: 30.17, lng: -95.27 }, radius: 50000 };    // Spring / north Houston first
      picker.placeholder = "Start typing your address…";
      picker.id = id;
      picker.setAttribute("aria-label", label || "Service address");
      picker.addEventListener("gmp-select", async ({ placePrediction }) => {
        const place = placePrediction.toPlace();
        await place.fetchFields({ fields: ["formattedAddress", "location"] });
        onPick((place.formattedAddress || "").replace(/, USA$/, ""), place.location.lat(), place.location.lng());
      });
      slot.replaceChildren(picker);
      slot.hidden = false;
      if (onReady) onReady();
    } catch {
      if (onFail) onFail();
    }
  }

  window.SGPlaces = { attach };
})();
