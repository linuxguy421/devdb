/* ============================================================
   dashboard.js — "My Log" page. Fetches the user's watch
   entries and stats, renders them as a list of title cards
   with a score-ring rating on the right.
   ============================================================ */

if (!Auth.isLoggedIn()) {
  window.location.href = "/login";
}

const TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w200";

function posterUrl(posterPath) {
  return posterPath ? `${TMDB_IMAGE_BASE}${posterPath}` : "";
}

function formatMeta(title) {
  const type = title.media_type === "tv" ? "Series" : "Film";
  const year = title.release_year || "—";
  return `${type} · ${year}${title.genres ? " · " + title.genres : ""}`;
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str || "";
  return div.innerHTML;
}

function renderEntry(entry) {
  const title = entry.title;
  const poster = posterUrl(title.poster_path);
  const hasRating = entry.rating != null;
  const peak = hasRating && entry.rating >= 9;
  const pct = hasRating ? entry.rating * 10 : 0;

  return `
    <article class="title-card">
      <div class="title-card__poster-wrap">
        ${poster
          ? `<img class="title-card__poster" src="${poster}" alt="" loading="lazy">`
          : `<div class="title-card__poster-placeholder">${escapeHtml(title.name)}</div>`}
      </div>
      <div class="title-card__body">
        <div class="title-card__text">
          <h2 class="title-card__title">${escapeHtml(title.name)}</h2>
          <p class="title-card__meta">${formatMeta(title)}</p>
          ${entry.review_text
            ? `<p class="title-card__overview">${escapeHtml(entry.review_text)}</p>`
            : title.overview
              ? `<p class="title-card__overview">${escapeHtml(title.overview)}</p>`
              : ""}
        </div>
        ${hasRating
          ? `<div class="score-ring ${peak ? "score-ring--peak" : ""}" style="--pct:${pct}" aria-label="Rated ${entry.rating} out of 10"><span class="tabular">${entry.rating}</span></div>`
          : ""}
      </div>
    </article>
  `;
}

async function loadLog() {
  const listEl = document.getElementById("log-list");

  try {
    const [entries] = await Promise.all([
      api("/watch-entries"),
      loadStats(),
    ]);

    if (entries.length === 0) {
      listEl.innerHTML = `
        <div class="empty-state">
          <p class="empty-state__title">The log is empty.</p>
          <p>Search for something you've watched to add it to your log.</p>
          <p style="margin-top:1rem"><a class="btn btn--signal" href="/search">Search Titles</a></p>
        </div>
      `;
      return;
    }

    listEl.innerHTML = entries.map(renderEntry).join("");
  } catch (err) {
    listEl.innerHTML = `<p class="form-error">Couldn't load your log: ${escapeHtml(err.message)}</p>`;
  }
}

async function loadStats() {
  const userId = Auth.userId();
  if (!userId) return;

  try {
    const stats = await api(`/users/${userId}/stats`);
    document.getElementById("stat-total").textContent = stats.total_watched;
    document.getElementById("stat-avg").textContent =
      stats.average_rating != null ? stats.average_rating.toFixed(1) : "—";
    document.getElementById("stats-strip").hidden = false;
  } catch {
    /* stats are a nice-to-have — don't block the page on their failure */
  }
}

document.addEventListener("DOMContentLoaded", loadLog);
