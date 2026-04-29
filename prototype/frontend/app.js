/* MJS Discovery — frontend.
 * Single-page UI, no framework. Talks to /api/* endpoints.
 */
(() => {
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const escape = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));

  let me = null;     // current Principal
  let lastQueryId = null;

  // -- API ---------------------------------------------------------------

  async function api(path, opts = {}) {
    const res = await fetch(path, {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      ...opts,
    });
    if (res.status === 401) { showLogin(); throw new Error("unauthenticated"); }
    if (!res.ok) {
      let detail = `${res.status}`;
      try { const j = await res.json(); detail = j.detail || detail; } catch {}
      throw new Error(detail);
    }
    if (res.status === 204) return null;
    return res.json();
  }

  // -- Boot --------------------------------------------------------------

  async function boot() {
    try {
      me = await api("/api/auth/me");
      showApp();
    } catch {
      showLogin();
    }
  }

  function showLogin() {
    $("#login-view").hidden = false;
    $("#app-view").hidden = true;
    $("#who").innerHTML = "";
  }

  function showApp() {
    $("#login-view").hidden = true;
    $("#app-view").hidden = false;
    $("#who").innerHTML =
      `${escape(me.name)} <span class="role-badge">${escape(me.role)}</span>` +
      `<button class="linklike" id="logout-btn">Sign out</button>`;
    $("#logout-btn").addEventListener("click", logout);
    $$(".admin-only").forEach(el => el.hidden = me.role !== "Admin");
    activateTab("search");
  }

  // -- Login -------------------------------------------------------------

  $("#login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const email = $("#login-email").value.trim();
    const errEl = $("#login-error");
    errEl.hidden = true;
    try {
      me = await api("/api/auth/login", {
        method: "POST", body: JSON.stringify({ email }),
      });
      showApp();
    } catch (e) {
      errEl.textContent = e.message;
      errEl.hidden = false;
    }
  });

  async function logout() {
    await fetch("/api/auth/logout", { method: "POST", credentials: "same-origin" });
    me = null;
    showLogin();
  }

  // -- Tabs --------------------------------------------------------------

  $$(".tab").forEach(b => b.addEventListener("click", () => activateTab(b.dataset.tab)));

  function activateTab(name) {
    $$(".tab").forEach(b => b.classList.toggle("active", b.dataset.tab === name));
    $$(".tab-panel").forEach(p => p.hidden = p.dataset.panel !== name);
    if (name === "guide") loadGuide();
    if (name === "admin") {
      activateSubtab("content");
    }
  }

  $$(".subtab").forEach(b => b.addEventListener("click", () => activateSubtab(b.dataset.subtab)));

  function activateSubtab(name) {
    $$(".subtab").forEach(b => b.classList.toggle("active", b.dataset.subtab === name));
    $$(".subpanel").forEach(p => p.hidden = p.dataset.subpanel !== name);
    if (name === "content")   loadDocs();
    if (name === "issues")    loadIssues();
    if (name === "analytics") loadAnalytics();
  }

  // -- Search ------------------------------------------------------------

  $("#search-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    await runSearch($("#search-input").value.trim());
  });

  // Debounced live search
  let searchTimer;
  $("#search-input").addEventListener("input", (e) => {
    clearTimeout(searchTimer);
    const q = e.target.value.trim();
    if (!q) { renderResults({ results: [], no_results: false, _empty: true }); return; }
    searchTimer = setTimeout(() => runSearch(q), 250);
  });

  async function runSearch(q) {
    if (!q) return;
    $("#search-status").textContent = "Searching…";
    try {
      const out = await api("/api/search?q=" + encodeURIComponent(q));
      lastQueryId = out.query_id;
      renderResults(out);
    } catch (e) {
      $("#search-status").textContent = "Error: " + e.message;
    }
  }

  function renderResults(out) {
    const list = $("#results");
    const status = $("#search-status");

    if (out._empty) { status.textContent = ""; list.innerHTML = ""; return; }

    if (out.no_results) {
      status.textContent = "";
      list.innerHTML = `
        <li class="no-results">
          <h3>No matching content in the index.</h3>
          <p>This tool only returns items that exist in our published corpus.
             Use the <em>Report issue</em> tab if you expected a result.</p>
        </li>`;
      return;
    }

    status.textContent = `${out.results.length} result${out.results.length === 1 ? "" : "s"}`;
    list.innerHTML = out.results.map((r, i) => `
      <li class="result-card">
        <div class="meta">
          <span class="ctype">${escape(r.content_type)}</span>
          <span>${escape(r.publish_date || "")}</span>
          <span class="score-pill">score ${r.score} · recency &times;${r.recency_boost}</span>
        </div>
        <h3><a href="${escape(r.url)}" target="_blank" rel="noopener"
               data-doc="${r.document_id}" data-pos="${i}"
               data-ctype="${escape(r.content_type)}">${escape(r.title)}</a></h3>
        <p class="excerpt">${escape(r.excerpt)}</p>
        ${r.tags.length ? `<div class="tags">${r.tags.map(t => `<span class="tag">${escape(t)}</span>`).join("")}</div>` : ""}
      </li>`).join("");

    list.querySelectorAll("a[data-doc]").forEach(a => a.addEventListener("click", () => {
      api("/api/search/click", {
        method: "POST",
        body: JSON.stringify({
          query_id: lastQueryId,
          document_id: Number(a.dataset.doc),
          position: Number(a.dataset.pos),
          content_type: a.dataset.ctype,
        }),
      }).catch(() => {});
    }));
  }

  // -- Guide -------------------------------------------------------------

  async function loadGuide() {
    const out = await api("/api/guide");
    $("#guide-content").innerHTML =
      `<h2>${escape(out.title)}</h2>` +
      out.sections.map(s =>
        `<h3>${escape(s.heading)}</h3><p>${escape(s.body)}</p>`
      ).join("");
  }

  // -- Issue form --------------------------------------------------------

  $("#issue-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = {
      kind: $("#issue-kind").value,
      query_text: $("#issue-query").value || null,
      message: $("#issue-message").value || null,
    };
    try {
      await api("/api/issues", { method: "POST", body: JSON.stringify(body) });
      $("#issue-status").textContent = "Submitted. Admins will review.";
      e.target.reset();
    } catch (err) {
      $("#issue-status").textContent = "Error: " + err.message;
    }
  });

  // -- Admin: docs & tags ------------------------------------------------

  async function loadDocs() {
    const out = await api("/api/admin/documents");
    $("#docs-table").innerHTML = out.documents.map(d => `
      <div class="docs-row" data-doc="${d.id}">
        <div>
          <div class="doc-title">${escape(d.title)}</div>
          <div class="doc-meta">
            ${escape(d.content_type)} · ${escape(d.publish_date || "")}
            · <a href="${escape(d.source_url)}" target="_blank" rel="noopener">source</a>
          </div>
          <div class="doc-meta">
            source tags: ${d.source_tags.map(t => `<span class="tag">${escape(t)}</span>`).join(" ") || "<em>none</em>"}
          </div>
        </div>
        <div class="tag-edit">
          <input type="text" placeholder="comma-separated admin tags"
                 value="${escape(d.admin_tags.join(", "))}" />
          <button class="ghost save-tags">Save</button>
          <span class="save-state"></span>
        </div>
      </div>`).join("");

    $$("#docs-table .save-tags").forEach(btn => btn.addEventListener("click", async (e) => {
      const row = e.target.closest(".docs-row");
      const docId = row.dataset.doc;
      const input = row.querySelector("input");
      const state = row.querySelector(".save-state");
      const tags = input.value.split(",").map(s => s.trim()).filter(Boolean);
      btn.disabled = true; state.textContent = "saving…";
      try {
        await api(`/api/admin/documents/${docId}/tags`, {
          method: "PUT", body: JSON.stringify({ tags }),
        });
        state.textContent = "saved · re-indexed";
      } catch (err) {
        state.textContent = "error: " + err.message;
      } finally {
        btn.disabled = false;
        setTimeout(() => state.textContent = "", 3000);
      }
    }));
  }

  // -- Admin: issues -----------------------------------------------------

  async function loadIssues() {
    const out = await api("/api/admin/issues");
    if (!out.issues.length) {
      $("#issues-list").innerHTML = `<p class="hint">No issues reported yet.</p>`;
      return;
    }
    $("#issues-list").innerHTML = out.issues.map(i => `
      <div class="issue" data-id="${i.id}">
        <div class="head">
          <span class="kind">${escape(i.kind)}</span>
          <span class="status-pill ${i.status}">${escape(i.status)}</span>
          <span class="hint">${escape(i.user_email || "")} · ${escape(i.created_at)}</span>
        </div>
        ${i.query_text ? `<div><strong>Query:</strong> ${escape(i.query_text)}</div>` : ""}
        ${i.doc_title ? `<div><strong>Document:</strong> <a href="${escape(i.doc_url)}" target="_blank" rel="noopener">${escape(i.doc_title)}</a></div>` : ""}
        ${i.message ? `<div>${escape(i.message)}</div>` : ""}
        <div class="tag-edit">
          <select class="status-select">
            ${["open", "in_progress", "resolved", "wont_fix"]
              .map(s => `<option value="${s}" ${s === i.status ? "selected" : ""}>${s}</option>`)
              .join("")}
          </select>
          <button class="ghost save-status">Update</button>
        </div>
      </div>`).join("");

    $$("#issues-list .save-status").forEach(btn => btn.addEventListener("click", async (e) => {
      const row = e.target.closest(".issue");
      const id = row.dataset.id;
      const status = row.querySelector(".status-select").value;
      try {
        await api(`/api/admin/issues/${id}`, {
          method: "PUT", body: JSON.stringify({ status }),
        });
        loadIssues();
      } catch (err) {
        alert("Error: " + err.message);
      }
    }));
  }

  // -- Admin: analytics --------------------------------------------------

  async function loadAnalytics() {
    const a = await api("/api/admin/analytics");
    const max = (rows, key) => Math.max(1, ...rows.map(r => r[key] || 0));
    const table = (rows, k1, k2, max) => rows.length ? `
      <table class="analytics-table">
        ${rows.map(r => `
          <tr>
            <td>${escape(r[k1] || "")}</td>
            <td class="n">${r[k2]}</td>
            <td style="width:30%"><div class="bar"><span style="width:${(r[k2]/max)*100}%"></span></div></td>
          </tr>`).join("")}
      </table>` : `<p class="hint">no data yet</p>`;

    const t = a.totals;
    $("#analytics").innerHTML = `
      <div class="analytics-grid">
        <div class="card"><h3>Total queries</h3><div class="big">${t.total_queries}</div></div>
        <div class="card"><h3>Zero-result queries</h3><div class="big">${t.zero_result_queries}</div></div>
        <div class="card"><h3>Result clicks</h3><div class="big">${t.total_clicks}</div></div>
        <div class="card"><h3>Indexed documents</h3><div class="big">${t.indexed_documents}</div></div>
      </div>
      <div class="card"><h3>Top queries</h3>
        ${table(a.top_queries, "query_text", "n", max(a.top_queries, "n"))}
      </div>
      <div class="card"><h3>Zero-result queries (content gaps)</h3>
        ${table(a.zero_result_queries, "query_text", "n", max(a.zero_result_queries, "n"))}
      </div>
      <div class="card"><h3>Most-clicked content types</h3>
        ${table(a.clicked_content_types, "content_type", "n", max(a.clicked_content_types, "n"))}
      </div>
      <div class="card"><h3>Daily query volume (last 14 days)</h3>
        ${table(a.daily_volume, "day", "n", max(a.daily_volume, "n"))}
      </div>`;
  }

  // -- Admin: ingestion --------------------------------------------------

  $("#run-seed").addEventListener("click", async () => {
    $("#run-seed").disabled = true;
    $("#seed-result").textContent = "running…";
    try {
      const out = await api("/api/ingest/seed", { method: "POST" });
      $("#seed-result").textContent = JSON.stringify(out, null, 2);
    } catch (e) {
      $("#seed-result").textContent = "error: " + e.message;
    } finally {
      $("#run-seed").disabled = false;
    }
  });

  $("#rss-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = {
      feed_url: $("#rss-url").value.trim(),
      content_type: $("#rss-type").value,
    };
    $("#rss-result").textContent = "fetching…";
    try {
      const out = await api("/api/ingest/rss", {
        method: "POST", body: JSON.stringify(body),
      });
      $("#rss-result").textContent = JSON.stringify(out, null, 2);
    } catch (err) {
      $("#rss-result").textContent = "error: " + err.message;
    }
  });

  boot();
})();
