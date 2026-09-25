/**
 * editing.js — Bloque E: Editing Studio (Pieza 82C)
 *
 * Implements the Editing user interface, action registry EDIT_ACTIONS,
 * unified run dispatcher, preview integration, timeline rendering,
 * captions inline editing, sound controls, and social metadata generator.
 */
(function () {
  "use strict";

  let currentIdeaId = null;
  let currentEditingState = null;
  let previewMountInstance = null;
  let pollingInterval = null;
  let activeTab = "preview"; // "preview" | "final"
  let selectedSceneN = null;
  let isAutoAssembling = false;

  // --- Host Bridge Helpers ---
  function getBS() {
    return (typeof window !== "undefined" && window.BrandStudio) ? window.BrandStudio : {};
  }

  function authFetch(url, options) {
    if (typeof getBS().authenticatedFetch === "function") {
      return getBS().authenticatedFetch(url, options);
    }
    return fetch(url, options);
  }

  function escapeHtml(str) {
    if (typeof getBS().escapeHtml === "function") {
      return getBS().escapeHtml(str);
    }
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  // Re-reads the balance from /api/session. Never call the host's
  // updateCreditsUI(remaining, initial) without arguments: it would store
  // "undefined" as the balance and show 0 credits (found in the browser probe).
  function updateCreditsUI() {
    if (typeof getBS().refreshCredits === "function") {
      getBS().refreshCredits();
    }
  }

  function showPaywall() {
    if (typeof getBS().showPaywall === "function") {
      getBS().showPaywall();
    }
  }

  function hideMainViews() {
    if (typeof getBS().hideMainViews === "function") {
      getBS().hideMainViews();
    }
  }

  function showAudiovisualView() {
    if (typeof getBS().showAudiovisualView === "function") {
      getBS().showAudiovisualView();
    }
  }

  function openRecordingStudio(sceneN) {
    if (typeof getBS().openRecordingStudio === "function") {
      getBS().openRecordingStudio(sceneN);
    }
  }

  function renderPipelineRail() {
    if (typeof getBS().renderPipelineRail === "function") {
      getBS().renderPipelineRail();
    }
  }

  function generateRequestId() {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
      return crypto.randomUUID();
    }
    return "req_" + Date.now() + "_" + Math.random().toString(36).substring(2, 10);
  }

  function safeHttpsUrl(urlStr) {
    if (!urlStr) return "";
    try {
      const u = new URL(urlStr, (typeof window !== "undefined" ? window.location.href : "https://localhost"));
      if (u.protocol === "https:") {
        return u.href;
      }
    } catch (e) {}
    return "";
  }

  // --- UI Error Banner Handler ---
  function showError(err) {
    let msg = "";
    let code = typeof err === "string" ? err : (err && (err.code || err.detail || err.message)) || "";

    if (code === "render_service_not_configured") {
      msg = "Rendering is not configured on the server yet.";
    } else if (code === "raw_not_ready") {
      msg = "Build the raw cut first.";
    } else if (code === "spend_paused") {
      msg = "Rendering is paused (platform spend limit).";
    } else if (code === "brandy_unavailable") {
      msg = "Brandy is busy, try again. You were not charged.";
    } else if (code === "dress_first") {
      msg = "Dress the video first.";
    } else if (code === "rate_limit_exceeded" || code === "429") {
      msg = "Too many raw builds this hour.";
    } else if (code === "missing_takes") {
      msg = "Record all required A-roll scenes first.";
    } else if (code === "402") {
      showPaywall();
      return;
    } else if (typeof err === "string") {
      msg = err;
    } else {
      msg = err.message || err.detail || err.code || "An unexpected error occurred.";
    }

    if (typeof document !== "undefined") {
      const banner = document.getElementById("Editing-Error-Banner");
      if (banner) {
        banner.textContent = msg;
        banner.style.display = "block";
      }
    }
  }

  function clearError() {
    if (typeof document !== "undefined") {
      const banner = document.getElementById("Editing-Error-Banner");
      if (banner) {
        banner.textContent = "";
        banner.style.display = "none";
      }
    }
  }

  // --- API Callers ---
  async function apiCall(endpoint, method, body) {
    clearError();
    const options = { method: method, headers: {} };
    if (body !== null && body !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    const res = await authFetch(endpoint, options);
    if (res.status === 402) {
      showPaywall();
      showError("402");
      return { ok: false, status: 402, data: null };
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      showError(data.code || data.detail || `HTTP ${res.status}`);
      return { ok: false, status: res.status, data: data };
    }
    return { ok: true, status: res.status, data: data };
  }

  async function patchSettings(ideaId, payload) {
    if (!payload.expected_version && currentEditingState) {
      payload.expected_version = currentEditingState.edit_version;
    }
    let res = await apiCall(`/api/editing/${ideaId}/settings`, "PATCH", payload);
    if (!res.ok && res.status === 409 && res.data && res.data.code === "version_conflict" && res.data.current) {
      payload.expected_version = res.data.current;
      res = await apiCall(`/api/editing/${ideaId}/settings`, "PATCH", payload);
    }
    return res.ok ? res.data : null;
  }

  async function patchCaption(ideaId, wordId, text) {
    const encWordId = encodeURIComponent(wordId);
    const payload = {
      text: text,
      expected_version: currentEditingState ? currentEditingState.edit_version : 1
    };
    let res = await apiCall(`/api/editing/${ideaId}/captions/${encWordId}`, "PATCH", payload);
    if (!res.ok && res.status === 409 && res.data && res.data.code === "version_conflict" && res.data.current) {
      payload.expected_version = res.data.current;
      res = await apiCall(`/api/editing/${ideaId}/captions/${encWordId}`, "PATCH", payload);
    }
    return res.ok ? res.data : null;
  }

  async function postRawRender(ideaId) {
    const res = await apiCall(`/api/editing/${ideaId}/raw`, "POST");
    return res.ok ? res.data : null;
  }

  async function postDress(ideaId) {
    const res = await apiCall(`/api/editing/${ideaId}/dress`, "POST");
    return res.ok ? res.data : null;
  }

  async function postRedressScene(ideaId, sceneN) {
    const reqId = generateRequestId();
    const res = await apiCall(`/api/editing/${ideaId}/scenes/${sceneN}/redress`, "POST", { request_id: reqId });
    if (res.ok) {
      updateCreditsUI();
    }
    return res.ok ? res.data : null;
  }

  async function postRender(ideaId) {
    const res = await apiCall(`/api/editing/${ideaId}/render`, "POST");
    if (res.ok) {
      updateCreditsUI();
    }
    return res.ok ? res.data : null;
  }

  async function postMetadata(ideaId) {
    const res = await apiCall(`/api/editing/${ideaId}/metadata`, "POST");
    return res.ok ? res.data : null;
  }

  async function patchMetadata(ideaId, platform, field, value) {
    const payload = {
      platform: platform,
      field: field,
      value: value,
      expected_version: currentEditingState ? currentEditingState.edit_version : 1
    };
    let res = await apiCall(`/api/editing/${ideaId}/metadata`, "PATCH", payload);
    if (!res.ok && res.status === 409 && res.data && res.data.code === "version_conflict" && res.data.current) {
      payload.expected_version = res.data.current;
      res = await apiCall(`/api/editing/${ideaId}/metadata`, "PATCH", payload);
    }
    return res.ok ? res.data : null;
  }

  async function fetchShareLink(ideaId) {
    const res = await apiCall(`/api/editing/${ideaId}/share-link`, "GET");
    return res.ok ? res.data : null;
  }

  async function loadEditingState(ideaId) {
    const res = await apiCall(`/api/editing/${ideaId}`, "GET");
    return res.ok ? res.data : null;
  }

  // --- EDIT_ACTIONS Registry (E10 + P82C: exact 13 actions) ---
  const EDIT_ACTIONS = {
    toggle_face: {
      label: "Toggle Face",
      credits: 0,
      run: async (args) => {
        const scN = args.sceneN;
        let nextVal = true;
        if (args.value !== undefined) {
          nextVal = Boolean(args.value);
        } else if (currentEditingState && currentEditingState.settings && currentEditingState.settings.face) {
          const currentFace = currentEditingState.settings.face[String(scN)];
          nextVal = currentFace === false;
        }
        return await patchSettings(args.ideaId, {
          op: "face",
          scene_n: scN,
          value: nextVal
        });
      }
    },
    reset_face: {
      label: "Reset to Audiovisual choice",
      credits: 0,
      run: async (args) => {
        return await patchSettings(args.ideaId, {
          op: "face",
          scene_n: args.sceneN,
          value: null
        });
      }
    },
    trim: {
      label: "Trim Scene",
      credits: 0,
      run: async (args) => {
        const scN = args.sceneN;
        const currentTrim = (currentEditingState && currentEditingState.settings && currentEditingState.settings.trim && currentEditingState.settings.trim[String(scN)]) || { start_ms: 0, end_ms: 0 };
        const deltaStart = args.deltaStartMs || 0;
        const deltaEnd = args.deltaEndMs || 0;
        const newStart = Math.max(-500, Math.min(500, (currentTrim.start_ms || 0) + deltaStart));
        const newEnd = Math.max(-500, Math.min(500, (currentTrim.end_ms || 0) + deltaEnd));
        return await patchSettings(args.ideaId, {
          op: "trim",
          scene_n: scN,
          value: { start_ms: newStart, end_ms: newEnd }
        });
      }
    },
    mute_music: {
      label: "Background music",
      credits: 0,
      run: async (args) => {
        return await patchSettings(args.ideaId, {
          op: "music_mute",
          value: Boolean(args.value)
        });
      }
    },
    toggle_sfx: {
      label: "Sound effects",
      credits: 0,
      run: async (args) => {
        return await patchSettings(args.ideaId, {
          op: "sfx_enabled",
          value: Boolean(args.value)
        });
      }
    },
    fix_caption: {
      label: "Fix Caption",
      credits: 0,
      run: async (args) => {
        return await patchCaption(args.ideaId, args.wordId, args.text);
      }
    },
    dress_all: {
      label: "Vestir todo · free",
      credits: 0,
      run: async (args) => {
        return await postDress(args.ideaId);
      }
    },
    redress_scene: {
      label: "Otra versión · 2 credits",
      credits: 2,
      run: async (args) => {
        return await postRedressScene(args.ideaId, args.sceneN);
      }
    },
    build_raw: {
      label: "Rebuild raw cut · free",
      credits: 0,
      run: async (args) => {
        return await postRawRender(args.ideaId);
      }
    },
    render: {
      label: "Render · 20 credits",
      credits: 20,
      run: async (args) => {
        return await postRender(args.ideaId);
      }
    },
    gen_metadata: {
      label: "Generate post copy · free",
      credits: 0,
      run: async (args) => {
        return await postMetadata(args.ideaId);
      }
    },
    edit_metadata: {
      label: "Edit Metadata",
      credits: 0,
      run: async (args) => {
        return await patchMetadata(args.ideaId, args.platform, args.field, args.value);
      }
    },
    copy_share_link: {
      label: "Copy link",
      credits: 0,
      run: async (args) => {
        const linkData = await fetchShareLink(args.ideaId);
        if (linkData && linkData.url) {
          if (typeof navigator !== "undefined" && navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
            await navigator.clipboard.writeText(linkData.url);
          } else if (typeof document !== "undefined") {
            const ta = document.createElement("textarea");
            ta.value = linkData.url;
            document.body.appendChild(ta);
            ta.select();
            document.execCommand("copy");
            document.body.removeChild(ta);
          }
          return linkData;
        }
        return null;
      }
    }
  };

  /**
   * Unified Action Dispatcher (runEditAction)
   */
  async function runEditAction(name, args) {
    args = args || {};
    if (!args.ideaId && currentIdeaId) {
      args.ideaId = currentIdeaId;
    }
    const action = EDIT_ACTIONS[name];
    if (!action) {
      console.error("[Editing] Unknown action:", name);
      return null;
    }

    const btn = args.btn || null;
    let originalHtml = "";
    if (btn) {
      originalHtml = btn.innerHTML;
      btn.disabled = true;
      btn.innerHTML = `<span class="spinner" style="width:14px;height:14px;border:2px solid currentColor;border-top-color:transparent;border-radius:50%;display:inline-block;animation:spin 0.8s linear infinite;margin-right:6px"></span> Processing…`;
    }

    try {
      const result = await action.run(args);
      if (result) {
        if (typeof result === "object" && result.edit_version) {
          currentEditingState = result;
        } else if (args.ideaId) {
          currentEditingState = await loadEditingState(args.ideaId);
        }
        if (action.credits > 0) {
          updateCreditsUI();
        }
        if (currentEditingState) {
          renderEditingContent(currentEditingState);
          checkAndStartPolling(args.ideaId, currentEditingState);
          if (hasFinalRender()) {
            renderPipelineRail();
          }
        }
      }
      return result;
    } catch (err) {
      console.error(`[Editing] Action ${name} failed:`, err);
      showError(err);
      return null;
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = originalHtml;
      }
    }
  }

  function hasFinalRender() {
    return Boolean(currentEditingState && currentEditingState.render && currentEditingState.render.signed_url);
  }

  // --- Polling Logic ---
  function checkAndStartPolling(ideaId, state) {
    const rawBusy = state && state.raw && (state.raw.status === "pending" || state.raw.status === "running");
    const renderBusy = state && state.render && (state.render.status === "pending" || state.render.status === "running");
    if (rawBusy || renderBusy) {
      startPolling(ideaId);
    } else {
      stopPolling();
    }
  }

  function startPolling(ideaId) {
    if (pollingInterval) return;
    pollingInterval = setInterval(async () => {
      try {
        const state = await loadEditingState(ideaId);
        if (!state) return;
        currentEditingState = state;
        updateProgressBars(state);

        const rawBusy = state.raw && (state.raw.status === "pending" || state.raw.status === "running");
        const renderBusy = state.render && (state.render.status === "pending" || state.render.status === "running");

        if (!rawBusy && !renderBusy) {
          stopPolling();
          renderEditingContent(state);
          if (hasFinalRender()) {
            renderPipelineRail();
          }
        }
      } catch (err) {
        console.warn("[Editing] Polling error:", err);
      }
    }, 2500);
  }

  function stopPolling() {
    if (pollingInterval) {
      clearInterval(pollingInterval);
      pollingInterval = null;
    }
  }

  function updateProgressBars(state) {
    if (typeof document === "undefined") return;
    const rawProgressEl = document.getElementById("Editing-Raw-Progress");
    if (rawProgressEl && state.raw) {
      if (state.raw.status === "pending" || state.raw.status === "running") {
        rawProgressEl.style.display = "block";
        const pct = state.raw.progress || 10;
        const bar = rawProgressEl.querySelector(".progress-bar-fill");
        if (bar) bar.style.width = pct + "%";
        const txt = rawProgressEl.querySelector(".progress-bar-text");
        if (txt) txt.textContent = `Assembling your raw cut… ${pct}%`;
      } else {
        rawProgressEl.style.display = "none";
      }
    }

    const renderProgressEl = document.getElementById("Editing-Render-Progress");
    if (renderProgressEl && state.render) {
      if (state.render.status === "pending" || state.render.status === "running") {
        renderProgressEl.style.display = "block";
        const pct = state.render.progress || 10;
        const bar = renderProgressEl.querySelector(".progress-bar-fill");
        if (bar) bar.style.width = pct + "%";
        const txt = renderProgressEl.querySelector(".progress-bar-text");
        if (txt) txt.textContent = `Rendering final MP4… ${pct}%`;
      } else {
        renderProgressEl.style.display = "none";
      }
    }
  }

  // --- View Lifecycle ---
  async function showEditingView(ideaId) {
    currentIdeaId = ideaId;
    hideMainViews();

    if (typeof document === "undefined") return;

    const editingView = document.getElementById("Editing-View");
    const guardEl = document.getElementById("Editing-Guard");
    const contentEl = document.getElementById("Editing-Content");

    if (editingView) editingView.style.display = "block";

    if (!ideaId) {
      if (guardEl) {
        guardEl.style.display = "block";
        guardEl.innerHTML = `
          <div style="padding:24px;text-align:center">
            <h3 style="font-size:18px;color:var(--ink)">No Script Selected</h3>
            <p style="font-size:13px;color:var(--ink-soft)">Please select or lock a script in the Script step before editing.</p>
          </div>`;
      }
      if (contentEl) contentEl.style.display = "none";
      return;
    }

    try {
      const state = await loadEditingState(ideaId);
      currentEditingState = state;

      if (!state) {
        throw new Error("Could not load editing state.");
      }

      // 1. Guard check: missing_takes
      if (state.missing_takes && state.missing_takes.length > 0) {
        if (guardEl) {
          guardEl.style.display = "block";
          const sceneButtonsHtml = state.missing_takes
            .map(
              (n) =>
                `<button type="button" class="btn btn--primary editing-rec-scene-btn" data-scene-n="${n}" style="margin:4px">Record scene ${n}</button>`
            )
            .join("");
          guardEl.innerHTML = `
            <div style="padding:24px;text-align:center;background:var(--surface);border:1px solid var(--line);border-radius:8px">
              <h3 style="font-size:18px;font-weight:700;color:var(--ink);margin:0 0 8px">
                Record these scenes first: ${escapeHtml(state.missing_takes.join(", "))}
              </h3>
              <p style="font-size:13px;color:var(--ink-soft);margin:0 0 16px">
                All A-roll scenes require recorded takes before the editing cut can be assembled.
              </p>
              <div style="display:flex;gap:8px;justify-content:center;flex-wrap:wrap">
                ${sceneButtonsHtml}
              </div>
            </div>`;

          guardEl.querySelectorAll(".editing-rec-scene-btn").forEach((btn) => {
            btn.onclick = () => {
              const n = parseInt(btn.dataset.sceneN, 10);
              showAudiovisualView();
              openRecordingStudio(n);
            };
          });
        }
        if (contentEl) contentEl.style.display = "none";
        return;
      }

      // No missing takes: render workbench
      if (guardEl) guardEl.style.display = "none";
      if (contentEl) contentEl.style.display = "block";

      // Auto-assemble raw cut if missing or not fresh and no job is running
      const hasRawUrl = Boolean(state.raw && state.raw.signed_url);
      const isRawFresh = Boolean(state.raw && state.raw.fresh);
      const isJobRunning = Boolean(state.raw && (state.raw.status === "pending" || state.raw.status === "running"));

      if ((!hasRawUrl || !isRawFresh) && !isJobRunning && !isAutoAssembling) {
        isAutoAssembling = true;
        postRawRender(ideaId).then((res) => {
          isAutoAssembling = false;
          if (res) {
            startPolling(ideaId);
          }
        }).catch(() => {
          isAutoAssembling = false;
        });
      }

      renderEditingContent(state);
      checkAndStartPolling(ideaId, state);

    } catch (err) {
      console.error("[Editing] showEditingView failed:", err);
      showError(err);
    }
  }

  function onHideEditingView() {
    stopPolling();
    if (previewMountInstance) {
      if (typeof previewMountInstance.destroy === "function") {
        previewMountInstance.destroy();
      }
      previewMountInstance = null;
    }
    if (typeof document !== "undefined") {
      const editingView = document.getElementById("Editing-View");
      if (editingView) editingView.style.display = "none";
    }
  }

  // --- Main View Renderer ---
  function renderEditingContent(state) {
    if (typeof document === "undefined") return;
    const container = document.getElementById("Editing-Content");
    if (!container) return;

    const timeline = state.timeline || {};
    const scenes = timeline.scenes || [];
    const settings = state.settings || {};
    const raw = state.raw || {};
    const render = state.render || {};
    const dressing = state.dressing || {};
    const ir = state.ir || null;

    const hasRawVideo = Boolean(raw.signed_url && raw.fresh);
    const hasFinalVideo = Boolean(render.signed_url);

    // Active video URL depending on tab
    let activeVideoUrl = "";
    if (activeTab === "final" && hasFinalVideo) {
      activeVideoUrl = render.signed_url;
    } else if (raw.signed_url) {
      activeVideoUrl = raw.signed_url;
    }

    // Determine Dressing status label
    let dressBtnLabel = "Vestir todo · free";
    if (dressing.fresh) {
      dressBtnLabel = "Dressed ✓";
    } else if (dressing.stale) {
      dressBtnLabel = "Your cut changed — dress again · free";
    }

    // Build Scene Cards HTML
    const scenesHtml = scenes.map((sc) => {
      const currentFaceSetting = settings.face ? settings.face[String(sc.n)] : undefined;
      const isFace = currentFaceSetting !== undefined && currentFaceSetting !== null ? Boolean(currentFaceSetting) : (sc.visual === "face");
      const hasBroll = Boolean(sc.broll);
      const brollKind = sc.broll ? sc.broll.kind : "none";
      const scTrim = (settings.trim && settings.trim[String(sc.n)]) || { start_ms: 0, end_ms: 0 };
      const isSelected = selectedSceneN === sc.n;

      return `
        <div class="edit-scene-card ${isSelected ? 'edit-scene-card--selected' : ''}" data-scene-n="${sc.n}" style="padding:14px;background:var(--surface);border:1px solid ${isSelected ? 'var(--accent)' : 'var(--line)'};border-radius:8px;margin-bottom:12px;cursor:pointer">
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px">
            <div style="display:flex;align-items:center;gap:8px">
              <span style="font-weight:700;font-size:14px;color:var(--ink)">Scene ${sc.n}</span>
              <span style="font-size:11px;padding:2px 8px;border-radius:4px;background:var(--surface-alt);color:var(--ink-soft);font-weight:600;text-transform:uppercase">${escapeHtml(sc.phase || "")}</span>
              <span style="font-size:12px;color:var(--ink-soft)">${sc.out_end_ms ? ((sc.out_end_ms - sc.out_start_ms) / 1000).toFixed(1) + "s" : ""}</span>
            </div>
            <div style="font-size:12px;font-weight:600;color:${isFace ? '#2563EB' : '#10B981'}">
              ${isFace ? "📷 Face" : "🎥 B-roll (" + brollKind + ")"}
            </div>
          </div>

          <!-- Controls for Scene -->
          <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:10px">
            <div style="display:inline-flex;border:1px solid var(--line);border-radius:6px;overflow:hidden">
              <button type="button" class="btn btn--secondary" data-edit-action="toggle_face" data-scene-n="${sc.n}" data-value="true" style="padding:4px 10px;font-size:12px;border-radius:0;${isFace ? 'background:var(--accent);color:#fff;' : ''}">Face</button>
              <button type="button" class="btn btn--secondary" data-edit-action="toggle_face" data-scene-n="${sc.n}" data-value="false" ${!hasBroll ? 'disabled title="No b-roll generated for this scene"' : ''} style="padding:4px 10px;font-size:12px;border-radius:0;${!isFace ? 'background:var(--accent);color:#fff;' : ''}">B-roll</button>
            </div>

            <button type="button" class="btn btn--secondary" data-edit-action="reset_face" data-scene-n="${sc.n}" style="padding:4px 10px;font-size:11px">Reset to Audiovisual choice</button>

            ${dressing.fresh ? `<button type="button" class="btn btn--secondary" data-edit-action="redress_scene" data-scene-n="${sc.n}" style="padding:4px 10px;font-size:12px">Otra versión · 2 credits</button>` : ''}
          </div>

          <!-- Trim Controls -->
          <div style="display:flex;gap:12px;align-items:center;font-size:12px;background:var(--surface-alt);padding:8px 12px;border-radius:6px">
            <span style="font-weight:600;color:var(--ink-soft)">Trim:</span>
            <div style="display:flex;align-items:center;gap:4px">
              <span>Start (${scTrim.start_ms > 0 ? '+' : ''}${scTrim.start_ms}ms):</span>
              <button type="button" class="btn btn--secondary" data-edit-action="trim" data-scene-n="${sc.n}" data-trim-type="start" data-trim-delta="-500" style="padding:2px 6px;font-size:11px">−0.5s</button>
              <button type="button" class="btn btn--secondary" data-edit-action="trim" data-scene-n="${sc.n}" data-trim-type="start" data-trim-delta="500" style="padding:2px 6px;font-size:11px">+0.5s</button>
            </div>
            <div style="display:flex;align-items:center;gap:4px;margin-left:8px">
              <span>End (${scTrim.end_ms > 0 ? '+' : ''}${scTrim.end_ms}ms):</span>
              <button type="button" class="btn btn--secondary" data-edit-action="trim" data-scene-n="${sc.n}" data-trim-type="end" data-trim-delta="-500" style="padding:2px 6px;font-size:11px">−0.5s</button>
              <button type="button" class="btn btn--secondary" data-edit-action="trim" data-scene-n="${sc.n}" data-trim-type="end" data-trim-delta="500" style="padding:2px 6px;font-size:11px">+0.5s</button>
            </div>
          </div>
        </div>
      `;
    }).join("");

    // Build Captions Words List for Scene
    const captionsWords = state.captions_words || [];
    const captionsHtml = captionsWords.length > 0 ? captionsWords.map((cw) => {
      const textDisp = cw.edited_text || cw.text;
      return `
        <span class="editing-caption-word" data-word-id="${cw.id}" style="display:inline-block;padding:3px 6px;margin:2px;background:var(--surface-alt);border:1px solid var(--line);border-radius:4px;font-size:13px;cursor:pointer;user-select:none" title="Click to edit word">
          ${escapeHtml(textDisp)}
        </span>
      `;
    }).join("") : `<p style="font-size:13px;color:var(--ink-soft)">No subtitles words generated yet.</p>`;

    // Build Social Copy / Metadata Cards (E8)
    const meta = state.metadata || {};
    const platforms = meta.platforms || {};
    const metaPlatforms = ["linkedin", "instagram", "tiktok"];
    const metaCardsHtml = metaPlatforms.map((plat) => {
      const pData = platforms[plat] || {};
      const title = pData.title || "";
      const desc = pData.description || "";
      const tags = Array.isArray(pData.hashtags) ? pData.hashtags.join(" ") : (pData.hashtags || "");
      const comment = pData.first_comment || "";
      const platLabel = plat === "linkedin" ? "LinkedIn (B2B / Personal Brand)" : (plat === "instagram" ? "Instagram Reels" : "TikTok");

      return `
        <div style="background:var(--surface-alt);border:1px solid var(--line);border-radius:8px;padding:14px;margin-bottom:12px">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
            <h4 style="font-size:13px;font-weight:700;margin:0;color:var(--ink);text-transform:capitalize">${platLabel}</h4>
            <button type="button" class="btn btn--secondary editing-copy-meta-btn" data-platform="${plat}" style="padding:4px 10px;font-size:12px">Copy post text</button>
          </div>
          <div style="display:flex;flex-direction:column;gap:8px">
            <div>
              <label style="font-size:11px;font-weight:600;color:var(--ink-soft);display:block;margin-bottom:2px">Title / Hook:</label>
              <input type="text" class="editing-meta-input" data-platform="${plat}" data-field="title" value="${escapeHtml(title)}" style="width:100%;padding:6px;font-size:12px;border:1px solid var(--line);border-radius:4px;box-sizing:border-box">
            </div>
            <div>
              <label style="font-size:11px;font-weight:600;color:var(--ink-soft);display:block;margin-bottom:2px">Description / Caption:</label>
              <textarea class="editing-meta-input" data-platform="${plat}" data-field="description" rows="3" style="width:100%;padding:6px;font-size:12px;border:1px solid var(--line);border-radius:4px;box-sizing:border-box">${escapeHtml(desc)}</textarea>
            </div>
            <div>
              <label style="font-size:11px;font-weight:600;color:var(--ink-soft);display:block;margin-bottom:2px">Hashtags:</label>
              <input type="text" class="editing-meta-input" data-platform="${plat}" data-field="hashtags" value="${escapeHtml(tags)}" style="width:100%;padding:6px;font-size:12px;border:1px solid var(--line);border-radius:4px;box-sizing:border-box">
            </div>
            <div>
              <label style="font-size:11px;font-weight:600;color:var(--ink-soft);display:block;margin-bottom:2px">First Comment / CTA:</label>
              <input type="text" class="editing-meta-input" data-platform="${plat}" data-field="first_comment" value="${escapeHtml(comment)}" style="width:100%;padding:6px;font-size:12px;border:1px solid var(--line);border-radius:4px;box-sizing:border-box">
            </div>
          </div>
        </div>
      `;
    }).join("");

    // Build timeline blocks (E6)
    const totalDurationMs = timeline.duration_ms || 1;
    const timelineBlocksHtml = scenes.map((sc) => {
      const durMs = (sc.out_end_ms || 0) - (sc.out_start_ms || 0);
      const pctWidth = Math.max(5, Math.min(100, (durMs / totalDurationMs) * 100));
      const isFace = sc.visual === "face";

      return `
        <div class="editing-timeline-block" data-scene-n="${sc.n}" data-start-ms="${sc.out_start_ms}" style="flex:${pctWidth};min-width:40px;background:var(--surface);border:1px solid var(--line);border-radius:4px;padding:6px;text-align:center;cursor:pointer;position:relative" title="Scene ${sc.n} (${(durMs / 1000).toFixed(1)}s) - Click to jump">
          <div style="font-size:11px;font-weight:700;color:var(--ink)">${sc.n} · ${escapeHtml(sc.phase || "")}</div>
          <div style="font-size:10px;color:var(--ink-soft)">${isFace ? "📷" : "🎥"} ${(durMs / 1000).toFixed(1)}s</div>
        </div>
      `;
    }).join("");

    container.innerHTML = `
      <!-- Error Banner -->
      <div id="Editing-Error-Banner" style="display:none;margin-bottom:16px;padding:12px;background:#FEE2E2;border:1px solid #FCA5A5;color:#991B1B;border-radius:6px;font-size:13px;font-weight:600"></div>

      <!-- Action Bar Header (E10 + E3) -->
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:20px;padding-bottom:16px;border-bottom:1px solid var(--line)">
        <div>
          <h2 style="font-size:22px;font-weight:700;color:var(--ink);margin:0 0 4px">Editing Studio</h2>
          <p style="font-size:13px;color:var(--ink-soft);margin:0">
            Edit version ${state.edit_version || 1} · Total duration: ${timeline.duration_ms ? (timeline.duration_ms / 1000).toFixed(1) + "s" : "0s"}
          </p>
        </div>
        <div style="display:flex;gap:10px;align-items:center">
          <button type="button" class="btn btn--secondary" data-edit-action="dress_all" style="font-size:13px">
            ${escapeHtml(dressBtnLabel)}
          </button>
          <button type="button" class="btn btn--go" data-edit-action="render" style="font-size:13px;font-weight:600">
            Render · 20 credits
          </button>
          ${!raw.fresh ? `<button type="button" class="btn btn--secondary" data-edit-action="build_raw" style="font-size:13px">Rebuild raw cut · free</button>` : ''}
        </div>
      </div>

      <!-- Progress Indicators -->
      <div id="Editing-Raw-Progress" style="display:${raw.status === "pending" || raw.status === "running" ? "block" : "none"};margin-bottom:16px;padding:12px;background:var(--surface-alt);border:1px solid var(--line);border-radius:6px">
        <div class="progress-bar-text" style="font-size:12px;font-weight:600;margin-bottom:6px;color:var(--ink)">Assembling your raw cut… ${raw.progress || 10}%</div>
        <div style="width:100%;height:6px;background:var(--line);border-radius:3px;overflow:hidden">
          <div class="progress-bar-fill" style="width:${raw.progress || 10}%;height:100%;background:var(--accent);transition:width 0.3s"></div>
        </div>
      </div>

      <div id="Editing-Render-Progress" style="display:${render.status === "pending" || render.status === "running" ? "block" : "none"};margin-bottom:16px;padding:12px;background:var(--surface-alt);border:1px solid var(--line);border-radius:6px">
        <div class="progress-bar-text" style="font-size:12px;font-weight:600;margin-bottom:6px;color:var(--ink)">Rendering final MP4… ${render.progress || 10}%</div>
        <div style="width:100%;height:6px;background:var(--line);border-radius:3px;overflow:hidden">
          <div class="progress-bar-fill" style="width:${render.progress || 10}%;height:100%;background:#10B981;transition:width 0.3s"></div>
        </div>
      </div>

      <!-- Main Layout: 2 Columns -->
      <div style="display:grid;grid-template-columns:minmax(260px,360px) minmax(0,1fr);gap:24px;align-items:start">

        <!-- Column 1: 9:16 Video Player -->
        <div style="background:var(--surface-alt);padding:16px;border:1px solid var(--line);border-radius:8px">
          <!-- Player Tabs -->
          <div style="display:flex;gap:4px;margin-bottom:12px;background:var(--surface);padding:4px;border-radius:6px;border:1px solid var(--line)">
            <button type="button" id="Editing-Tab-Preview" class="btn btn--secondary" style="flex:1;font-size:12px;padding:6px;${activeTab === 'preview' ? 'background:var(--accent);color:#fff;' : ''}">Preview</button>
            <button type="button" id="Editing-Tab-Final" class="btn btn--secondary" ${!hasFinalVideo ? 'disabled title="Render final video first"' : ''} style="flex:1;font-size:12px;padding:6px;${activeTab === 'final' ? 'background:var(--accent);color:#fff;' : ''}">Final MP4</button>
          </div>

          <!-- Video Container -->
          <div id="Editing-Player-Container" style="position:relative;width:100%;aspect-ratio:9/16;background:#000;border-radius:6px;overflow:hidden;box-shadow:0 4px 12px rgba(0,0,0,0.15);display:flex;align-items:center;justify-content:center">
            <!-- Video element handled programmatically to preserve video element on re-render -->
          </div>

          <!-- Sharing & Download Actions (E8 / E9) -->
          <div style="margin-top:16px;display:flex;flex-direction:column;gap:8px">
            ${hasFinalVideo ? `
              <a href="${safeHttpsUrl(render.signed_url)}" download="brand_video.mp4" class="btn btn--go" style="width:100%;text-align:center;padding:10px 0;font-size:13px;text-decoration:none">
                Download MP4
              </a>
              <div style="display:flex;gap:8px">
                <button type="button" class="btn btn--secondary" data-edit-action="copy_share_link" style="flex:1;font-size:12px">Copy link</button>
                ${typeof navigator !== "undefined" && navigator.share ? `<button type="button" id="Editing-NativeShareBtn" class="btn btn--secondary" style="flex:1;font-size:12px">Share…</button>` : ''}
              </div>
              <div style="font-size:11px;color:var(--ink-soft);text-align:center;margin-top:4px">Link valid for 7 days</div>
            ` : (hasRawVideo ? `
              <div style="font-size:12px;color:var(--ink-soft);text-align:center">Previewing assembled raw cut. Click <strong>Render</strong> to generate publication MP4.</div>
            ` : '')}
          </div>
        </div>

        <!-- Column 2: Timeline, Scene Panel, Sound, Subtitles, Metadata -->
        <div>
          <!-- Timeline Bar (E6) -->
          <div style="background:var(--surface);padding:16px;border:1px solid var(--line);border-radius:8px;margin-bottom:20px">
            <h3 style="font-size:14px;font-weight:700;margin:0 0 12px;color:var(--ink)">Timeline</h3>
            <div style="display:flex;gap:6px;width:100%;box-sizing:border-box">
              ${timelineBlocksHtml || '<div style="font-size:12px;color:var(--ink-soft)">No timeline blocks.</div>'}
            </div>
          </div>

          <!-- Sound Controls (E5) -->
          <div style="background:var(--surface);padding:16px;border:1px solid var(--line);border-radius:8px;margin-bottom:20px">
            <h3 style="font-size:14px;font-weight:700;margin:0 0 12px;color:var(--ink)">Sound & Effects</h3>
            <div style="display:flex;gap:20px;flex-wrap:wrap;align-items:center">
              <label style="display:flex;align-items:center;gap:8px;font-size:13px;cursor:pointer;color:var(--ink)">
                <input type="checkbox" id="Editing-MusicMute" ${settings.music_muted ? "checked" : ""} data-edit-action="mute_music">
                Background music
              </label>
              <label style="display:flex;align-items:center;gap:8px;font-size:13px;cursor:pointer;color:var(--ink)">
                <input type="checkbox" id="Editing-SfxToggle" ${settings.sfx_enabled !== false ? "checked" : ""} data-edit-action="toggle_sfx">
                Sound effects
              </label>
            </div>
          </div>

          <!-- Scene Settings List -->
          <div style="margin-bottom:20px">
            <h3 style="font-size:14px;font-weight:700;margin:0 0 12px;color:var(--ink)">Scenes (${scenes.length})</h3>
            ${scenesHtml || '<p style="font-size:13px;color:var(--ink-soft)">No scenes available.</p>'}
          </div>

          <!-- Subtitles / Captions Words List (E3/E10) -->
          <div style="background:var(--surface);padding:16px;border:1px solid var(--line);border-radius:8px;margin-bottom:20px">
            <h3 style="font-size:14px;font-weight:700;margin:0 0 4px;color:var(--ink)">Subtitles (Click word to edit)</h3>
            <p style="font-size:12px;color:var(--ink-soft);margin:0 0 12px">Click any word to edit its text inline. Press Enter to save (1-40 chars).</p>
            <div id="Editing-Captions-Container" style="line-height:1.8">
              ${captionsHtml}
            </div>
          </div>

          <!-- Social Copy & Publication Metadata (E8) -->
          <div style="background:var(--surface);padding:16px;border:1px solid var(--line);border-radius:8px">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
              <h3 style="font-size:14px;font-weight:700;margin:0;color:var(--ink)">Social Copy & Metadata</h3>
              <button type="button" class="btn btn--secondary" data-edit-action="gen_metadata" style="font-size:12px">Generate post copy · free</button>
            </div>
            <div id="Editing-Metadata-Content">
              ${metaCardsHtml || `<p style="font-size:12px;color:var(--ink-soft)">Click "Generate post copy · free" to produce post copy for LinkedIn, Instagram, and TikTok.</p>`}
            </div>
          </div>

        </div>
      </div>
    `;

    // --- Wire Video Element preserving existing video DOM element if src hasn't changed ---
    const playerContainer = document.getElementById("Editing-Player-Container");
    if (playerContainer) {
      let videoEl = document.getElementById("Editing-Video");
      const targetSrc = safeHttpsUrl(activeVideoUrl);

      if (!targetSrc) {
        playerContainer.innerHTML = `
          <div style="text-align:center;padding:24px;color:#8E9CAE">
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="margin:0 auto 12px;display:block">
              <polygon points="5 3 19 12 5 21 5 3"></polygon>
            </svg>
            <p style="font-size:13px;margin:0 0 8px;font-weight:600">No video generated yet</p>
            <p style="font-size:11px;margin:0">Assembling your raw cut…</p>
          </div>`;
        if (previewMountInstance) {
          previewMountInstance.destroy();
          previewMountInstance = null;
        }
      } else {
        if (!videoEl || videoEl.getAttribute("src") !== targetSrc) {
          playerContainer.innerHTML = `<video id="Editing-Video" src="${escapeHtml(targetSrc)}" controls playsinline style="width:100%;height:100%;object-fit:contain;background:#000;"></video>`;
          videoEl = document.getElementById("Editing-Video");
          if (previewMountInstance) {
            previewMountInstance.destroy();
            previewMountInstance = null;
          }
        }

        // Mount or update preview
        if (window.BrandStudioPreview && activeTab === "preview") {
          if (!previewMountInstance) {
            previewMountInstance = window.BrandStudioPreview.mount(playerContainer, videoEl, ir);
          } else {
            previewMountInstance.update(ir);
          }
          if (previewMountInstance && state.sfx_urls) {
            previewMountInstance.setSfxUrls(state.sfx_urls);
          }
        } else if (previewMountInstance && activeTab === "final") {
          previewMountInstance.destroy();
          previewMountInstance = null;
        }
      }
    }

    // --- Wire Up Tabs ---
    const tabPrev = document.getElementById("Editing-Tab-Preview");
    const tabFinal = document.getElementById("Editing-Tab-Final");
    if (tabPrev) {
      tabPrev.onclick = () => {
        activeTab = "preview";
        renderEditingContent(state);
      };
    }
    if (tabFinal && hasFinalVideo) {
      tabFinal.onclick = () => {
        activeTab = "final";
        renderEditingContent(state);
      };
    }

    // --- Wire Up Timeline Blocks Jump ---
    container.querySelectorAll(".editing-timeline-block").forEach((blk) => {
      blk.onclick = () => {
        const startMs = parseInt(blk.dataset.startMs, 10) || 0;
        const videoEl = document.getElementById("Editing-Video");
        if (videoEl) {
          videoEl.currentTime = startMs / 1000;
        }
      };
    });

    // --- Wire Up Native Share Button ---
    const nativeShareBtn = document.getElementById("Editing-NativeShareBtn");
    if (nativeShareBtn) {
      nativeShareBtn.onclick = async () => {
        const linkData = await fetchShareLink(currentIdeaId);
        if (linkData && linkData.url && navigator.share) {
          try {
            await navigator.share({
              title: "Brand Studio Video",
              url: linkData.url
            });
          } catch (e) {}
        }
      };
    }

    // --- Wire Up Subtitle Word Inline Editing ---
    container.querySelectorAll(".editing-caption-word").forEach((wSpan) => {
      wSpan.onclick = (e) => {
        e.stopPropagation();
        const wordId = wSpan.dataset.wordId;
        const oldText = wSpan.textContent.trim();
        const input = document.createElement("input");
        input.type = "text";
        input.maxLength = 40;
        input.value = oldText;
        input.style.width = Math.max(60, oldText.length * 10) + "px";
        input.style.fontSize = "12px";
        input.style.padding = "2px 4px";
        input.style.border = "1px solid var(--accent)";
        input.style.borderRadius = "4px";

        wSpan.replaceWith(input);
        input.focus();
        input.select();

        const saveWord = async () => {
          const newText = input.value.trim();
          if (newText && newText !== oldText && newText.length <= 40) {
            await runEditAction("fix_caption", { ideaId: currentIdeaId, wordId: wordId, text: newText });
          } else {
            renderEditingContent(state);
          }
        };

        input.onkeydown = (ev) => {
          if (ev.key === "Enter") {
            ev.preventDefault();
            input.onblur = null;
            saveWord();
          } else if (ev.key === "Escape") {
            ev.preventDefault();
            input.onblur = null;
            renderEditingContent(state);
          }
        };

        input.onblur = () => {
          saveWord();
        };
      };
    });

    // --- Wire Up Copy Post Text for Metadata Cards ---
    container.querySelectorAll(".editing-copy-meta-btn").forEach((btn) => {
      btn.onclick = async () => {
        const plat = btn.dataset.platform;
        const pData = (state.metadata && state.metadata.platforms && state.metadata.platforms[plat]) || {};
        const title = pData.title || "";
        const desc = pData.description || "";
        const tags = Array.isArray(pData.hashtags) ? pData.hashtags.join(" ") : (pData.hashtags || "");
        const comment = pData.first_comment || "";

        const copyText = `${title}\n\n${desc}\n\n${tags}\n\n${comment}`.trim();

        if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
          await navigator.clipboard.writeText(copyText);
        } else if (typeof document !== "undefined") {
          const ta = document.createElement("textarea");
          ta.value = copyText;
          document.body.appendChild(ta);
          ta.select();
          document.execCommand("copy");
          document.body.removeChild(ta);
        }
        btn.textContent = "Copied!";
        setTimeout(() => {
          btn.textContent = "Copy post text";
        }, 2000);
      };
    });

    // --- Wire Up Metadata Field Inputs (Blur -> PATCH) ---
    container.querySelectorAll(".editing-meta-input").forEach((input) => {
      input.onchange = async () => {
        const plat = input.dataset.platform;
        const field = input.dataset.field;
        const val = input.value.trim();
        await runEditAction("edit_metadata", { ideaId: currentIdeaId, platform: plat, field: field, value: val });
      };
    });
  }

  // --- Delegated Listener for [data-edit-action] ---
  if (typeof document !== "undefined" && typeof document.addEventListener === "function") {
    document.addEventListener("click", async (e) => {
      const btn = e.target.closest("#Editing-View [data-edit-action]");
      if (!btn) return;
      if (btn.type === "checkbox") return;

      const actionName = btn.dataset.editAction;
      if (!actionName) return;

      e.preventDefault();

      const args = {
        btn: btn,
        ideaId: currentIdeaId,
        sceneN: btn.dataset.sceneN ? parseInt(btn.dataset.sceneN, 10) : undefined,
        deltaStartMs: btn.dataset.trimDelta && btn.dataset.trimType === "start" ? parseInt(btn.dataset.trimDelta, 10) : undefined,
        deltaEndMs: btn.dataset.trimDelta && btn.dataset.trimType === "end" ? parseInt(btn.dataset.trimDelta, 10) : undefined,
        value: btn.dataset.value === "true" ? true : (btn.dataset.value === "false" ? false : undefined)
      };

      await runEditAction(actionName, args);
    });

    document.addEventListener("change", async (e) => {
      const input = e.target.closest("#Editing-View [data-edit-action]");
      if (!input || input.type !== "checkbox") return;

      const actionName = input.dataset.editAction;
      if (actionName === "mute_music" || actionName === "toggle_sfx") {
        await runEditAction(actionName, { ideaId: currentIdeaId, value: input.checked });
      }
    });
  }

  // --- Public API ---
  const API = {
    show: showEditingView,
    onHide: onHideEditingView,
    run: runEditAction,
    EDIT_ACTIONS: EDIT_ACTIONS,
    hasFinalRender: hasFinalRender
  };

  if (typeof window !== "undefined") {
    window.BrandStudioEditing = API;
  }
  if (typeof module !== "undefined" && module.exports) {
    module.exports = API;
  }
})();
