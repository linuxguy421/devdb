/* ============================================================
   search.js — search TMDB via the API, render results as a
   poster grid, and let the user log a title with an optional
   rating right from the results. A logged title with a rating
   gets a score-ring overlaid on its poster.
   ============================================================ */

if (!Auth.isLoggedIn()) {
  window.location.href = "/login";
}

const TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w200";

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str || "";
  return div.innerHTML;
}

function resultCardId(result) {
  return `result-${result.media_type}-${result.tmdb_id}`;
}

function renderResult(result) {
  const poster = result.poster_path ? `${TMDB_IMAGE_BASE}${result.poster_path}` : "";
  const type = result.media_type === "tv" ? "Series" : "Film";
  const year = result.release_year || "—";
  const id = resultCardId(result);

  const ratingOptions = Array.from({ length: 11 }, (_, i) => i)
    .reverse()
    .map((n) => `<option value="${n}">${n}</option>`)
    .join("");

  return `
    <article class="title-card" id="${id}">
      <div class="title-card__poster-wrap" data-poster-wrap>
        ${poster
          ? `<img class="title-card__poster" src="${poster}" alt="" loading="lazy">`
          : `<div class="title-card__poster-placeholder">${escapeHtml(result.name)}</div>`}
      </div>
      <div class="title-card__body">
        <div class="title-card__text">
          <h2 class="title-card__title">${escapeHtml(result.name)}</h2>
          <p class="title-card__meta">${type} · ${year}</p>
          ${result.overview ? `<p class="title-card__overview">${escapeHtml(result.overview)}</p>` : ""}
        </div>
        <div class="title-card__actions" data-actions>
          <div class="rate-control">
            <select aria-label="Rating">
              <option value="">No rating</option>
              ${ratingOptions}
            </select>
          </div>
          <button class="btn btn--signal" type="button" data-file-btn>Log This</button>
        </div>
        <p class="form-error" data-error></p>
      </div>
    </article>
  `;
}

async function fileTitle(result, rating, cardEl) {
  const actionsEl = cardEl.querySelector("[data-actions]");
  const errorEl = cardEl.querySelector("[data-error]");
  const fileBtn = cardEl.querySelector("[data-file-btn]");
  const posterWrap = cardEl.querySelector("[data-poster-wrap]");

  fileBtn.disabled = true;
  errorEl.textContent = "";

  try {
    const entry = await api("/watch-entries", {
      method: "POST",
      body: JSON.stringify({
        tmdb_id: result.tmdb_id,
        media_type: result.media_type,
        rating: rating === "" ? null : Number(rating),
      }),
    });

    if (entry.rating != null) {
      const peak = entry.rating >= 9;
      const pct = entry.rating * 10;
      const ring = document.createElement("div");
      ring.className = `score-ring score-ring--enter${peak ? " score-ring--peak" : ""}`;
      ring.style.setProperty("--pct", pct);
      ring.setAttribute("aria-label", `Rated ${entry.rating} out of 10`);
      ring.innerHTML = `<span class="tabular">${entry.rating}</span>`;
      posterWrap.appendChild(ring);
      actionsEl.innerHTML = `<span style="font-family:var(--font-mono); font-size:0.75rem; color:var(--color-text-muted)">Logged</span>`;
    } else {
      actionsEl.innerHTML = `<span style="font-family:var(--font-mono); font-size:0.78rem; color:var(--color-text-muted)">Logged — no rating</span>`;
    }
  } catch (err) {
    fileBtn.disabled = false;
    errorEl.textContent = err.message;
  }
}

async function runSearch(query) {
  const resultsEl = document.getElementById("search-results");
  resultsEl.innerHTML = `<p style="font-family: var(--font-mono); font-size: 0.85rem; color: var(--color-text-muted);">Searching…</p>`;

  try {
    const results = await api(`/titles/search?q=${encodeURIComponent(query)}`);

    if (results.length === 0) {
      resultsEl.innerHTML = `
        <div class="empty-state">
          <p class="empty-state__title">No matches.</p>
          <p>Try a different title or check the spelling.</p>
        </div>
      `;
      return;
    }

    resultsEl.innerHTML = results.map(renderResult).join("");

    results.forEach((result) => {
      const cardEl = document.getElementById(resultCardId(result));
      const fileBtn = cardEl.querySelector("[data-file-btn]");
      const select = cardEl.querySelector("select");
      fileBtn.addEventListener("click", () => fileTitle(result, select.value, cardEl));
    });
  } catch (err) {
    resultsEl.innerHTML = `<p class="form-error">Search failed: ${escapeHtml(err.message)}</p>`;
  }
}

document.getElementById("search-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const query = document.getElementById("search-input").value.trim();
  if (query) runSearch(query);
});
