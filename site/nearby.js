// "Use my location": find the user's street with OpenStreetMap's reverse geocoder, then suggest homes on that
// street from our own address list. The browser asks permission first; coordinates go only to Nominatim and
// are not stored by this site.
(function () {
  var $ = function (id) { return document.getElementById(id); };
  var TYPES = { street: "ST", avenue: "AVE", boulevard: "BLVD", road: "RD", drive: "DR", parkway: "PKWY", lane: "LN", place: "PL",
    court: "CT", terrace: "TER", circle: "CIR", way: "WAY", trail: "TRL", alley: "ALY", curve: "CURV", path: "PATH" };
  var DIRS = { north: "N", south: "S", east: "E", west: "W", northeast: "NE", northwest: "NW", southeast: "SE", southwest: "SW" };

  // "Lincoln Street Northeast" -> "LINCOLN ST NE", "10th Avenue South" -> "10TH AVE S"
  function normStreet(road) {
    return road.toLowerCase().replace(/\./g, "").split(/\s+/).map(function (w) { return DIRS[w] || TYPES[w] || w; }).join(" ").toUpperCase();
  }
  // OpenStreetMap writes "Northeast Garfield Street"; city records write "GARFIELD ST NE". Try both orders.
  function variants(street) {
    var t = street.split(" "), out = [street];
    if (/^(N|S|E|W|NE|NW|SE|SW)$/.test(t[0]) && t.length > 2) out.push(t.slice(1).join(" ") + " " + t[0]);
    return out;
  }
  function stripDir(s) { return s.replace(/^(N|S|E|W|NE|NW|SE|SW) /, "").replace(/ (N|S|E|W|NE|NW|SE|SW)$/, ""); }

  var keysPromise;
  function loadKeys() {
    keysPromise = keysPromise || fetch("data/addresses.json").then(function (r) { return r.json(); }).then(function (d) { return Object.keys(d); });
    return keysPromise;
  }

  function say(html) { $("near-msg").innerHTML = html; }

  function showChips(list) {
    var box = $("near-chips");
    box.innerHTML = "";
    list.forEach(function (addr) {
      var b = document.createElement("button");
      b.type = "button"; b.className = "btn"; b.dataset.q = addr;
      b.textContent = addr.toLowerCase().replace(/\b\w/g, function (c) { return c.toUpperCase(); }).replace(/\b(Ne|Se|Nw|Sw)\b/g, function (m) { return m.toUpperCase(); });
      box.appendChild(b);
    });
  }

  function pick(addr) {
    var q = $("q");
    q.value = addr;
    q.dispatchEvent(new Event("input"));
    setTimeout(function () { var b = document.querySelector("#suggest button"); if (b) b.click(); }, 50);
  }

  async function nearby(lat, lon) {
    var url = "https://nominatim.openstreetmap.org/reverse?format=jsonv2&addressdetails=1&zoom=18&lat=" + lat + "&lon=" + lon;
    var j = await (await fetch(url, { headers: { "Accept-Language": "en" } })).json();
    var a = j.address || {};
    var city = a.city || a.town || a.village || "";
    if (!a.road) return say("We couldn't tell which street you're on. You can still type an address.");
    if (city && city !== "Minneapolis") return say("You don't seem to be in Minneapolis (" + city + "), so there are no homes to suggest. You can still type a Minneapolis address.");
    var street = normStreet(a.road), num = parseInt(a.house_number, 10);
    var keys = await loadKeys();
    var hits = [];
    function collect(match) {
      keys.forEach(function (k) {
        var m = /^(\d+)\s+(.*)$/.exec(k);
        if (m && match(m[2])) hits.push({ k: k, n: parseInt(m[1], 10) });
      });
    }
    var cands = variants(street);
    collect(function (s) { return cands.indexOf(s) !== -1; });
    if (!hits.length) collect(function (s) { return stripDir(s) === stripDir(street); });
    if (!hits.length) return say("No single-family homes on " + a.road + " in our data. Try typing an address.");
    var mid = isNaN(num) ? hits.map(function (h) { return h.n; }).sort(function (x, y) { return x - y; })[Math.floor(hits.length / 2)] : num;
    hits.sort(function (x, y) { return Math.abs(x.n - mid) - Math.abs(y.n - mid); });
    showChips(hits.slice(0, 4).map(function (h) { return h.k; }));
    say("Homes on " + a.road + " near you:");
  }

  $("use-location").addEventListener("click", function () {
    if (!navigator.geolocation) return say("Your browser can't share its location. You can still type an address.");
    say("Finding your location…"); $("near-chips").innerHTML = "";
    navigator.geolocation.getCurrentPosition(function (pos) {
      nearby(pos.coords.latitude.toFixed(4), pos.coords.longitude.toFixed(4)).catch(function () {
        say("Couldn't look up your street right now. You can still type an address.");
      });
    }, function (err) {
      say(err && err.code === 1 ? "Location is turned off for this site. You can still type an address." : "Couldn't get your location. You can still type an address.");
    }, { enableHighAccuracy: false, timeout: 10000, maximumAge: 300000 });
  });

  $("near-chips").addEventListener("click", function (e) {
    var b = e.target.closest("button[data-q]"); if (b) pick(b.dataset.q);
  });
})();
