/* Nice apartments — filterable, shareable listing board. */
(function () {
  "use strict";

  const DATA = window.LISTINGS || { listings: [] };
  const ALL = (DATA.listings || []).slice();

  const $ = (sel) => document.querySelector(sel);
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };

  const money = (n) => {
    if (n == null) return "—";
    return "€" + Math.round(n).toLocaleString("en-GB");
  };
  const shortDistrict = (d) => (d || "Nice").replace(/^Nice\s*-\s*/, "").replace(/^Nice$/, "Nice");
  const fmtDate = (iso) => {
    if (!iso) return "—";
    const d = new Date(iso);
    if (isNaN(d)) return iso;
    return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
  };

  function photoSrc(listing, index) {
    const name = listing.photos && listing.photos[index];
    if (!name) return null;
    if (window.PHOTOS && window.PHOTOS[name]) return window.PHOTOS[name];
    return "photos/" + name;
  }

  function placeholder() {
    const wrap = el("div", "no-photo");
    wrap.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 4h18a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1Zm1 2v10.6l4.5-4.5 3.2 3.2 3.4-3.4L20 16V6H4Zm12.5 2.2a1.8 1.8 0 1 0 0 3.6 1.8 1.8 0 0 0 0-3.6Z"/></svg>';
    return wrap;
  }

  function roomsLabel(l) {
    if (!l.rooms) return "Studio";
    if (l.rooms === 1) return "1 room";
    return l.rooms + " rooms";
  }

  function bedroomLabel(l) {
    if (l.bedrooms == null) return null;
    if (l.bedrooms === 0) return "Studio";
    return l.bedrooms + (l.bedrooms === 1 ? " bedroom" : " bedrooms");
  }

  function distanceLabel(l) {
    const candidates = [];
    if (l.distance_promenade_km != null) candidates.push(["sea", l.distance_promenade_km]);
    if (l.distance_centre_km != null) candidates.push(["centre", l.distance_centre_km]);
    if (!candidates.length) return null;
    candidates.sort((a, b) => a[1] - b[1]);
    const [kind, km] = candidates[0];
    return { kind, km };
  }

  /* ---------------- filters ---------------- */
  const state = {
    q: "",
    sort: "best",
    maxPrice: 900,
    minSurface: 0,
    rooms: "any",
    furnished: "any",
    district: "any",
    nearOnly: true,
    showRooms: false,
  };

  const els = {
    q: $("#q"), sort: $("#sort"), maxPrice: $("#maxPrice"), minSurface: $("#minSurface"),
    rooms: $("#rooms"), furnished: $("#furnished"), district: $("#district"),
    nearOnly: $("#nearOnly"), showRooms: $("#showRooms"),
    grid: $("#grid"), empty: $("#empty"), count: $("#resultCount"),
    priceOut: $("#priceOut"), surfaceOut: $("#surfaceOut"),
  };

  function fillRange(input) {
    const min = +input.min, max = +input.max, v = +input.value;
    input.style.setProperty("--fill", ((v - min) / (max - min)) * 100 + "%");
  }

  function readState() {
    state.q = els.q.value.trim().toLowerCase();
    state.sort = els.sort.value;
    state.maxPrice = +els.maxPrice.value;
    state.minSurface = +els.minSurface.value;
    state.rooms = els.rooms.value;
    state.furnished = els.furnished.value;
    state.district = els.district.value;
    state.nearOnly = els.nearOnly.checked;
    state.showRooms = els.showRooms.checked;
    els.priceOut.textContent = money(state.maxPrice);
    els.surfaceOut.textContent = state.minSurface + " m²";
    fillRange(els.maxPrice);
    fillRange(els.minSurface);
  }

  function matches(l) {
    if (l.price == null || l.price > state.maxPrice) return false;
    if (state.minSurface > 0 && (l.surface == null || l.surface < state.minSurface)) return false;
    if (state.nearOnly && !l.near_center) return false;
    if (!state.showRooms && (l.is_room || l.is_coloc)) return false;
    if (state.district !== "any" && l.district !== state.district) return false;
    if (state.furnished === "yes" && !l.furnished) return false;
    if (state.furnished === "no" && l.furnished) return false;

    const beds = l.bedrooms != null ? l.bedrooms : Math.max(0, (l.rooms || 1) - 1);
    if (state.rooms === "studio" && beds > 0) return false;
    if (state.rooms === "1" && beds !== 1) return false;
    if (state.rooms === "2" && beds < 2) return false;

    if (state.q) {
      const hay = [l.title, l.description, l.district, l.postal_code, l.agency, l.city]
        .join(" ").toLowerCase();
      if (!state.q.split(/\s+/).every((w) => hay.includes(w))) return false;
    }
    return true;
  }

  function sortListings(list) {
    const s = state.sort;
    return list.sort((a, b) => {
      if (s === "price-asc") return (a.price || 9e9) - (b.price || 9e9);
      if (s === "price-desc") return (b.price || 0) - (a.price || 0);
      if (s === "surface-desc") return (b.surface || 0) - (a.surface || 0);
      if (s === "newest") return String(b.published || "").localeCompare(String(a.published || ""));
      if (!!b.near_center !== !!a.near_center) return b.near_center ? 1 : -1;
      const d = (a.price || 9e9) - (b.price || 9e9);
      if (d) return d;
      return (b.surface || 0) - (a.surface || 0);
    });
  }

  /* ---------------- cards ---------------- */
  function makeCard(l) {
    const card = el("article", "card");
    card.dataset.id = l.id;

    const photo = el("div", "card-photo");
    const src = photoSrc(l, 0);
    if (src) {
      const img = el("img");
      img.src = src;
      img.alt = l.title || "Apartment photo";
      img.loading = "lazy";
      img.decoding = "async";
      photo.appendChild(img);
    } else {
      photo.appendChild(placeholder());
    }

    const badge = el("div", "price-badge");
    badge.innerHTML = "<b>" + money(l.price) + "</b><small>/month</small>";
    photo.appendChild(badge);

    if (l.near_center) photo.appendChild(el("span", "near-badge", "Near centre"));
    if (l.is_room || l.is_coloc) {
      photo.appendChild(el("span", "room-badge", l.is_coloc ? "Colocation" : "Room"));
    }
    photo.addEventListener("click", () => openModal(l));
    card.appendChild(photo);

    const body = el("div", "card-body");
    body.appendChild(el("div", "card-loc", shortDistrict(l.district) + (l.postal_code ? " · " + l.postal_code : "")));

    const h2 = el("h2");
    const titleBtn = el("button", null, l.title || "Apartment in " + shortDistrict(l.district));
    titleBtn.type = "button";
    titleBtn.addEventListener("click", () => openModal(l));
    h2.appendChild(titleBtn);
    body.appendChild(h2);

    const facts = el("div", "facts");
    if (l.surface) facts.appendChild(el("span", "fact", l.surface + " m²"));
    facts.appendChild(el("span", "fact", roomsLabel(l)));
    if (l.furnished) facts.appendChild(el("span", "fact", "Furnished"));
    if (l.dpe) {
      const bad = ["E", "F", "G"].includes(l.dpe);
      facts.appendChild(el("span", "fact dpe" + (bad ? " dpe-bad" : ""), "DPE " + l.dpe));
    }
    body.appendChild(facts);

    if (l.description) {
      body.appendChild(el("p", "card-desc", l.description.replace(/\s+/g, " ").slice(0, 190)));
    }

    const foot = el("div", "card-foot");
    const dist = distanceLabel(l);
    const km = el("span", "km");
    if (dist) {
      km.innerHTML = "<b>" + dist.km.toFixed(1) + " km</b> to the " + (dist.kind === "sea" ? "Promenade" : "centre");
    } else if (l.precision === "cityOrArrondissement") {
      km.textContent = "Location approximate";
    }
    foot.appendChild(km);

    const see = el("button", "see", "See all details");
    see.type = "button";
    see.addEventListener("click", () => openModal(l));
    foot.appendChild(see);
    body.appendChild(foot);

    card.appendChild(body);
    return card;
  }

  function countHiddenRooms() {
    const save = state.showRooms;
    state.showRooms = true;
    const n = ALL.filter((l) => (l.is_room || l.is_coloc) && matches(l)).length;
    state.showRooms = save;
    return n;
  }

  function render() {
    readState();
    const list = sortListings(ALL.filter(matches));
    els.grid.replaceChildren(...list.map(makeCard));
    els.empty.hidden = list.length > 0;

    const hiddenRooms = countHiddenRooms();
    let text = "Showing <strong>" + list.length + "</strong> of " + ALL.length + " apartments";
    if (hiddenRooms > 0) {
      text += " · " + hiddenRooms + " room" + (hiddenRooms === 1 ? "" : "s") + " hidden";
    }
    els.count.innerHTML = text;
  }

  function renderStats() {
    const near = ALL.filter((l) => l.near_center);
    const prices = ALL.map((l) => l.price).filter((n) => n != null).sort((a, b) => a - b);
    const median = prices.length ? prices[Math.floor(prices.length / 2)] : null;
    const cheapest = prices.length ? prices[0] : null;
    const stats = [
      [ALL.length, "apartments found"],
      [near.length, "near centre / sea"],
      [money(cheapest), "cheapest rent"],
      [money(median), "median rent"],
    ];
    const host = $("#stats");
    stats.forEach(([value, label]) => {
      const s = el("div", "stat");
      s.appendChild(el("b", null, value));
      s.appendChild(el("span", null, label));
      host.appendChild(s);
    });
    const gen = $("#generated");
    if (gen) gen.textContent = fmtDate(DATA.generated_at) || "recently";
    if (DATA.total) {
      $("#lede").textContent =
        "A snapshot of " + ALL.length + " flats in Nice at €" + (DATA.max_price || 900) +
        "/month or less — " + near.length + " of them in the centre or within walking distance of the Promenade des Anglais.";
    }
  }

  function fillDistricts() {
    const counts = new Map();
    ALL.forEach((l) => counts.set(l.district, (counts.get(l.district) || 0) + 1));
    const sorted = [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
    sorted.forEach(([name, n]) => {
      const opt = document.createElement("option");
      opt.value = name;
      opt.textContent = shortDistrict(name) + " (" + n + ")";
      els.district.appendChild(opt);
    });
  }

  /* ---------------- modal ---------------- */
  let lastFocus = null;
  const modal = $("#modal");
  const modalBody = $("#modalBody");

  function factBox(label, value) {
    const b = el("div", "fact-box");
    b.appendChild(el("span", null, label));
    b.appendChild(el("b", null, value));
    return b;
  }

  function mapsUrl(l) {
    if (l.lat != null && l.lon != null && l.precision !== "cityOrArrondissement") {
      return "https://www.google.com/maps/search/?api=1&query=" + l.lat + "," + l.lon;
    }
    return "https://www.google.com/maps/search/?api=1&query=" +
      encodeURIComponent((l.district || "Nice") + " " + (l.postal_code || ""));
  }

  function openModal(l) {
    lastFocus = document.activeElement;
    const photos = (l.photos || []).map((_, i) => photoSrc(l, i)).filter(Boolean);

    const gallery = el("div", "gallery");
    const main = el("div", "gallery-main");
    if (photos.length) {
      const img = el("img");
      img.src = photos[0];
      img.alt = l.title || "Apartment photo";
      img.addEventListener("click", () => window.open(photos[0], "_blank", "noopener"));
      main.appendChild(img);
    } else {
      main.appendChild(placeholder());
    }
    gallery.appendChild(main);

    if (photos.length > 1) {
      const thumbs = el("div", "gallery-thumbs");
      photos.slice(0, 4).forEach((src, i) => {
        const btn = el("button");
        btn.type = "button";
        if (i === 0) btn.classList.add("active");
        const t = el("img");
        t.src = src;
        t.alt = "";
        t.loading = "lazy";
        btn.appendChild(t);
        btn.addEventListener("click", () => {
          main.querySelector("img").src = src;
          thumbs.querySelectorAll("button").forEach((b) => b.classList.remove("active"));
          btn.classList.add("active");
        });
        thumbs.appendChild(btn);
      });
      gallery.appendChild(thumbs);
    }
    if (photos.length) {
      gallery.appendChild(el("div", "gallery-note",
        photos.length + " photo" + (photos.length === 1 ? "" : "s") + " · click to enlarge"));
    }

    const summary = el("div", "gallery-summary");
    const gs = (label, value) => {
      const box = el("div", "gs-item");
      box.appendChild(el("span", null, label));
      box.appendChild(el("b", null, value));
      return box;
    };
    summary.appendChild(gs("Rent", money(l.price) + " /mo"));
    if (l.surface != null) summary.appendChild(gs("Surface", l.surface + " m²"));
    const distSummary = distanceLabel(l);
    if (distSummary) {
      summary.appendChild(gs(
        distSummary.kind === "sea" ? "To Promenade" : "To centre",
        distSummary.km.toFixed(1) + " km"
      ));
    }
    gallery.appendChild(summary);

    const detail = el("div", "detail");
    const top = el("div", "detail-top");
    const left = el("div");
    left.appendChild(el("p", "detail-loc", shortDistrict(l.district) + (l.postal_code ? " · " + l.postal_code : "")));
    const h2 = el("h2", null, l.title || "Apartment in " + shortDistrict(l.district));
    h2.id = "modalTitle";
    left.appendChild(h2);
    const sub = el("p", "sub");
    const bits = [];
    if (l.price_per_m2) bits.push("<b>" + money(l.price_per_m2) + "/m²</b>");
    if (l.published) bits.push("Listed " + fmtDate(l.published));
    if (l.agency) bits.push(l.agency);
    sub.innerHTML = bits.join(" · ");
    left.appendChild(sub);
    top.appendChild(left);

    const price = el("div", "price");
    price.innerHTML = money(l.price) + "<small>/month</small>";
    top.appendChild(price);
    detail.appendChild(top);

    const grid = el("div", "fact-grid");
    grid.appendChild(factBox("Rent (incl. charges)", money(l.price)));
    if (l.rent_without_charges != null) grid.appendChild(factBox("Before charges", money(l.rent_without_charges)));
    if (l.charges != null) grid.appendChild(factBox("Charges", money(l.charges) + "/mo"));
    if (l.deposit != null) grid.appendChild(factBox("Deposit", money(l.deposit)));
    if (l.surface != null) grid.appendChild(factBox("Surface", l.surface + " m²"));
    grid.appendChild(factBox("Rooms", roomsLabel(l)));
    if (bedroomLabel(l)) grid.appendChild(factBox("Bedrooms", bedroomLabel(l)));
    grid.appendChild(factBox("Furnished", l.furnished ? "Yes" : "No"));
    if (l.dpe) grid.appendChild(factBox("DPE (energy)", l.dpe + (l.dpe_value ? " · " + l.dpe_value + " kWh/m²/yr" : "")));
    if (l.ges) grid.appendChild(factBox("GES (emissions)", l.ges + (l.ges_value ? " · " + l.ges_value + " kgCO₂/m²/yr" : "")));
    const dist = distanceLabel(l);
    if (dist) grid.appendChild(factBox("To " + (dist.kind === "sea" ? "Promenade" : "centre"), dist.km.toFixed(1) + " km"));
    detail.appendChild(grid);

    if (l.description) {
      detail.appendChild(el("h3", null, "About this apartment"));
      detail.appendChild(el("div", "description", l.description));
    }

    if (l.agency || l.phone) {
      const contact = el("div", "contact-card");
      contact.appendChild(el("div", "avatar", (l.agency || "?").trim().charAt(0).toUpperCase()));
      const p = el("p");
      p.appendChild(el("b", null, l.agency || "Agency"));
      if (l.phone) {
        const a = el("a", null, "Call " + l.phone);
        a.href = "tel:" + l.phone.replace(/\s/g, "");
        p.appendChild(a);
      } else {
        p.appendChild(document.createTextNode("Contact details on the original ad"));
      }
      contact.appendChild(p);
      detail.appendChild(contact);
    }

    const actions = el("div", "actions");
    const ad = el("a", "btn btn-solid", "Open original ad ↗");
    ad.href = l.url;
    ad.target = "_blank";
    ad.rel = "noopener";
    actions.appendChild(ad);

    const map = el("a", "btn btn-outline", "Open in Maps");
    map.href = mapsUrl(l);
    map.target = "_blank";
    map.rel = "noopener";
    actions.appendChild(map);

    if (l.phone) {
      const call = el("a", "btn btn-outline", "Call agency");
      call.href = "tel:" + l.phone.replace(/\s/g, "");
      actions.appendChild(call);
    }

    const copy = el("button", "btn btn-outline", "Copy link");
    copy.type = "button";
    copy.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(l.url);
        copy.textContent = "Link copied ✓";
      } catch (_) {
        window.prompt("Copy this link:", l.url);
      }
      setTimeout(() => (copy.textContent = "Copy link"), 1800);
    });
    actions.appendChild(copy);
    detail.appendChild(actions);

    modalBody.replaceChildren(gallery, detail);
    modal.hidden = false;
    document.body.classList.add("modal-open");
    try { history.replaceState(null, "", "#ad/" + encodeURIComponent(l.id)); } catch (_) { /* file:// */ }
    const closeBtn = $(".modal-close");
    if (closeBtn) closeBtn.focus();
  }

  function closeModal() {
    modal.hidden = true;
    document.body.classList.remove("modal-open");
    try { history.replaceState(null, "", location.pathname + location.search); } catch (_) { /* file:// */ }
    if (lastFocus) lastFocus.focus();
  }

  /* ---------------- share ---------------- */
  async function share() {
    const title = "Nice apartments under €900";
    const text = ALL.length + " flats near the Promenade and centre of Nice, with photos and full details.";
    const url = location.href;
    if (navigator.share) {
      try {
        await navigator.share({ title, text, url });
        return;
      } catch (_) { /* cancelled */ }
    }
    try {
      await navigator.clipboard.writeText(url);
      const btn = $("#shareBtn");
      const old = btn.innerHTML;
      btn.textContent = "Link copied ✓";
      setTimeout(() => (btn.innerHTML = old), 2000);
    } catch (_) {
      window.prompt("Copy this link to share:", url);
    }
  }

  /* ---------------- wire up ---------------- */
  [els.q, els.sort, els.maxPrice, els.minSurface, els.rooms, els.furnished,
   els.district, els.nearOnly, els.showRooms].forEach((node) => {
    node.addEventListener("input", render);
    node.addEventListener("change", render);
  });

  function reset() {
    els.q.value = "";
    els.sort.value = "best";
    els.maxPrice.value = 900;
    els.minSurface.value = 0;
    els.rooms.value = "any";
    els.furnished.value = "any";
    els.district.value = "any";
    els.nearOnly.checked = true;
    els.showRooms.checked = false;
    render();
  }

  $("#resetBtn").addEventListener("click", reset);
  $("#emptyReset").addEventListener("click", reset);
  $("#shareBtn").addEventListener("click", share);
  modal.addEventListener("click", (e) => {
    if (e.target.closest("[data-close]")) closeModal();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !modal.hidden) closeModal();
  });

  fillDistricts();
  renderStats();
  readState();
  render();

  function openFromHash() {
    const match = location.hash.match(/^#ad\/(.+)$/);
    if (!match) return;
    const id = decodeURIComponent(match[1]);
    const listing = ALL.find((l) => l.id === id);
    if (listing) openModal(listing);
  }
  openFromHash();
  window.addEventListener("hashchange", openFromHash);
})();
