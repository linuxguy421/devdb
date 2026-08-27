/* ============================================================
   auth.js — handles the login and register forms. Only one of
   these forms will exist on a given page, so both handlers
   check for their element before attaching.
   ============================================================ */

const loginForm = document.getElementById("login-form");
if (loginForm) {
  loginForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const errorEl = document.getElementById("form-error");
    errorEl.textContent = "";

    const username = document.getElementById("username").value;
    const password = document.getElementById("password").value;

    const body = new URLSearchParams({ username, password });

    try {
      const resp = await fetch("/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body,
      });
      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}));
        throw new Error(data.detail || "Login failed — check your username and password.");
      }
      const data = await resp.json();
      Auth.setToken(data.access_token);
      window.location.href = "/";
    } catch (err) {
      errorEl.textContent = err.message;
    }
  });
}

const registerForm = document.getElementById("register-form");
if (registerForm) {
  registerForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const errorEl = document.getElementById("form-error");
    errorEl.textContent = "";

    const username = document.getElementById("username").value;
    const email = document.getElementById("email").value;
    const password = document.getElementById("password").value;

    try {
      const resp = await fetch("/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, email, password }),
      });
      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}));
        throw new Error(data.detail || "Registration failed.");
      }

      // Registered — now log in immediately so the user lands in their log, not another form.
      const loginResp = await fetch("/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({ username, password }),
      });
      const loginData = await loginResp.json();
      Auth.setToken(loginData.access_token);
      window.location.href = "/";
    } catch (err) {
      errorEl.textContent = err.message;
    }
  });
}
