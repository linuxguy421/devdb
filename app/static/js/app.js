/* ============================================================
   app.js — shared across every page: auth state, API calls,
   and the nav bar's login/logout tabs.
   ============================================================ */

const Auth = {
  KEY: "ledger_token",

  getToken() {
    return localStorage.getItem(this.KEY);
  },

  setToken(token) {
    localStorage.setItem(this.KEY, token);
  },

  clear() {
    localStorage.removeItem(this.KEY);
  },

  isLoggedIn() {
    return !!this.getToken();
  },

  /** Decode the JWT payload just to read the user id (sub claim). No verification —
   *  the server is the source of truth; this is purely for UI convenience. */
  userId() {
    const token = this.getToken();
    if (!token) return null;
    try {
      const payload = JSON.parse(atob(token.split(".")[1]));
      return parseInt(payload.sub, 10);
    } catch {
      return null;
    }
  },
};

/** Wrapper around fetch() that attaches the auth header and handles 401s
 *  by bouncing to /login. Throws on non-2xx so callers can catch and
 *  show an inline error rather than a blank page. */
async function api(path, options = {}) {
  const headers = options.headers || {};
  const token = Auth.getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (options.body && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }

  const resp = await fetch(path, { ...options, headers });

  if (resp.status === 401) {
    Auth.clear();
    window.location.href = "/login";
    throw new Error("Not authenticated");
  }

  if (!resp.ok) {
    let detail = `Request failed (${resp.status})`;
    try {
      const body = await resp.json();
      if (body.detail) detail = body.detail;
    } catch {
      /* response wasn't JSON — keep the generic message */
    }
    throw new Error(detail);
  }

  if (resp.status === 204) return null;
  return resp.json();
}

function renderNav() {
  const el = document.getElementById("nav-links");
  if (!el) return;

  if (Auth.isLoggedIn()) {
    el.innerHTML = `
      <a class="drawer-tab" href="/">My Log</a>
      <a class="drawer-tab" href="/search">Search</a>
      <button class="drawer-tab" id="logout-btn" type="button">Log Out</button>
    `;
    document.getElementById("logout-btn").addEventListener("click", () => {
      Auth.clear();
      window.location.href = "/login";
    });
  } else {
    el.innerHTML = `
      <a class="drawer-tab" href="/login">Log In</a>
      <a class="drawer-tab" href="/register">Register</a>
    `;
  }

  // Highlight the tab matching the current page
  const path = window.location.pathname;
  el.querySelectorAll("a.drawer-tab").forEach((a) => {
    if (a.getAttribute("href") === path) a.classList.add("drawer-tab--active");
  });
}

document.addEventListener("DOMContentLoaded", renderNav);
