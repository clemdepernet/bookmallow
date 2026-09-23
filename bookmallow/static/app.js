/* Bookmallow front-end: one page, no dependencies. */
(() => {
  "use strict";

  const I18N = {
    fr: {
      tagline: "Tes vidéos YouTube en audiobooks",
      hero_title: "Un lien, un audiobook 🎧",
      hero_lead: "Colle un lien YouTube, choisis la qualité, et Bookmallow te prépare un MP3 à écouter partout.",
      url_label: "Lien YouTube",
      convert: "Transformer",
      quality: "Qualité",
      q64: "Voix · 64k", q64_hint: "≈ 29 Mo/heure, idéal pour un livre lu",
      q128: "Équilibré · 128k", q128_hint: "≈ 58 Mo/heure",
      q192: "Musique · 192k", q192_hint: "≈ 86 Mo/heure",
      queue: "File d'attente",
      queue_empty: "Rien en cours. Colle un lien pour commencer ✨",
      library: "Bibliothèque",
      library_empty: "Aucun fichier pour l'instant.",
      banner: "Bookmallow ne garde que les {n} derniers fichiers : pense à télécharger le tien rapidement 💾",
      banner_one: "Bookmallow ne garde qu'un seul fichier : télécharge-le dès qu'il est prêt 💾",
      next_to_go: "prochain à disparaître",
      expired: "Ce fichier a été supprimé pour faire de la place.",
      download: "Télécharger 💾",
      delete: "Supprimer",
      cancel: "Annuler",
      confirm_delete: "Supprimer « {name} » ?",
      logout: "Se déconnecter",
      footer: "fait avec 💗 à la maison",
      status_queued: "En attente",
      status_fetching: "Récupération des infos…",
      status_converting: "Conversion…",
      status_done: "Prêt",
      status_failed: "Échec",
      status_cancelled: "Annulé",
      err_invalid_url: "Bookmallow n'accepte que les liens YouTube.",
      err_bad_quality: "Qualité inconnue.",
      err_duplicate: "Cette vidéo est déjà dans la file.",
      err_network: "Impossible de joindre le serveur.",
      err_playlist: "Impossible de lire cette playlist.",
      added_one: "Ajouté à la file 🎀",
      added_many: "{n} vidéos ajoutées à la file 🎀",
      skipped: "{n} déjà en file",
      pl_title: "Playlist « {title} »",
      pl_intro: "{count} vidéos trouvées. Coche celles que tu veux convertir.",
      pl_note: "Bookmallow ne garde que {max} fichiers : au maximum {max} vidéos seront ajoutées.",
      pl_single: "Seulement cette vidéo",
      pl_add: "Ajouter {n} vidéo(s)",
      e_private: "Vidéo privée",
      e_age: "Réservée aux adultes (connexion requise)",
      e_geo: "Non disponible dans ce pays",
      e_unavailable: "Vidéo indisponible",
      e_live: "Les directs ne sont pas pris en charge",
      e_no_space: "Pas assez d'espace disque",
      e_too_long: "Vidéo trop longue pour ce serveur",
      e_interrupted: "Interrompue par un redémarrage",
      e_timeout: "YouTube n'a pas répondu à temps",
      e_metadata: "Infos de la vidéo illisibles",
      e_ytdlp: "Erreur yt-dlp",
      e_ffmpeg: "Erreur de conversion",
      e_internal: "Erreur interne",
      hours: "h", minutes: "min",
      lang_switch: "English",
    },
    en: {
      tagline: "Your YouTube videos as audiobooks",
      hero_title: "One link, one audiobook 🎧",
      hero_lead: "Paste a YouTube link, pick a quality, and Bookmallow prepares an MP3 you can listen to anywhere.",
      url_label: "YouTube link",
      convert: "Convert",
      quality: "Quality",
      q64: "Voice · 64k", q64_hint: "≈ 29 MB/hour, ideal for narration",
      q128: "Balanced · 128k", q128_hint: "≈ 58 MB/hour",
      q192: "Music · 192k", q192_hint: "≈ 86 MB/hour",
      queue: "Queue",
      queue_empty: "Nothing in progress. Paste a link to begin ✨",
      library: "Library",
      library_empty: "No files yet.",
      banner: "Bookmallow only keeps the {n} most recent files: download yours soon 💾",
      banner_one: "Bookmallow only keeps one file: download it as soon as it is ready 💾",
      next_to_go: "next to go",
      expired: "This file was removed to make room.",
      download: "Download 💾",
      delete: "Delete",
      cancel: "Cancel",
      confirm_delete: "Delete “{name}”?",
      logout: "Log out",
      footer: "made with 💗 at home",
      status_queued: "Queued",
      status_fetching: "Fetching info…",
      status_converting: "Converting…",
      status_done: "Ready",
      status_failed: "Failed",
      status_cancelled: "Cancelled",
      err_invalid_url: "Bookmallow only accepts YouTube links.",
      err_bad_quality: "Unknown quality.",
      err_duplicate: "This video is already queued.",
      err_network: "Cannot reach the server.",
      err_playlist: "Could not read this playlist.",
      added_one: "Added to the queue 🎀",
      added_many: "{n} videos added to the queue 🎀",
      skipped: "{n} already queued",
      pl_title: "Playlist “{title}”",
      pl_intro: "{count} videos found. Tick the ones you want to convert.",
      pl_note: "Bookmallow keeps only {max} files: at most {max} videos will be added.",
      pl_single: "Only this video",
      pl_add: "Add {n} video(s)",
      e_private: "Private video",
      e_age: "Age-restricted (sign-in required)",
      e_geo: "Not available in this country",
      e_unavailable: "Video unavailable",
      e_live: "Live streams are not supported",
      e_no_space: "Not enough disk space",
      e_too_long: "Video too long for this server",
      e_interrupted: "Interrupted by a restart",
      e_timeout: "YouTube did not answer in time",
      e_metadata: "Unreadable video info",
      e_ytdlp: "yt-dlp error",
      e_ffmpeg: "Conversion error",
      e_internal: "Internal error",
      hours: "h", minutes: "min",
      lang_switch: "Français",
    },
  };

  const body = document.body;
  const $ = (sel) => document.querySelector(sel);
  const el = (tag, attrs = {}, children = []) => {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else if (v !== null && v !== undefined) node.setAttribute(k, v);
    }
    for (const child of children) if (child) node.append(child);
    return node;
  };
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
  };

  const state = {
    lang: store.get("bookmallow.lang") || body.dataset.defaultLang || "fr",
    quality: store.get("bookmallow.quality") || body.dataset.defaultQuality || "64",
    maxFiles: Number(body.dataset.maxFiles || 6),
    data: null,
    timer: null,
    pendingPlaylist: null,
  };
  if (!I18N[state.lang]) state.lang = "fr";

  const t = (key, vars = {}) => {
    const text = (I18N[state.lang] && I18N[state.lang][key]) || I18N.fr[key] || key;
    return text.replace(/\{(\w+)\}/g, (_, k) => (vars[k] !== undefined ? vars[k] : `{${k}}`));
  };

  const fmtDuration = (s) => {
    if (!s && s !== 0) return "";
    const h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60);
    return h ? `${h} ${t("hours")} ${String(m).padStart(2, "0")}` : `${m} ${t("minutes")}`;
  };
  const fmtSize = (b) => {
    if (!b && b !== 0) return "";
    if (b < 1024 * 1024) return `${Math.round(b / 1024)} ${state.lang === "fr" ? "Ko" : "KB"}`;
    if (b < 1024 * 1024 * 1024) return `${(b / 1048576).toFixed(b < 10 * 1048576 ? 1 : 0)} ${state.lang === "fr" ? "Mo" : "MB"}`;
    return `${(b / 1073741824).toFixed(2)} ${state.lang === "fr" ? "Go" : "GB"}`;
  };
  const fmtDate = (iso) => {
    try { return new Date(iso).toLocaleString(state.lang === "fr" ? "fr-FR" : "en-GB", { dateStyle: "medium", timeStyle: "short" }); }
    catch { return iso; }
  };

  function applyI18n() {
    document.documentElement.lang = state.lang;
    document.querySelectorAll("[data-i18n]").forEach((node) => { node.textContent = t(node.dataset.i18n); });
    $("#lang-toggle").textContent = t("lang_switch");
    renderQualities();
    if (state.data) render(state.data);
  }

  function renderQualities() {
    const box = $("#qualities");
    box.querySelectorAll(".quality").forEach((n) => n.remove());
    for (const q of ["64", "128", "192"]) {
      const id = `q-${q}`;
      const input = el("input", { type: "radio", name: "quality", id, value: q, onchange: () => { state.quality = q; store.set("bookmallow.quality", q); } });
      if (q === state.quality) input.checked = true;
      box.append(el("div", { class: "quality" }, [input, el("label", { for: id }, [el("b", { text: t(`q${q}`) }), el("small", { text: t(`q${q}_hint`) })])]));
    }
  }

  function toast(text, kind = "") {
    const node = el("div", { class: `toast ${kind}`, text });
    $("#toasts").append(node);
    setTimeout(() => node.remove(), 4200);
  }

  function setMsg(text, kind = "") {
    const node = $("#form-msg");
    node.textContent = text;
    node.className = `form-msg ${kind}`;
  }

  async function api(path, options = {}) {
    let res;
    try {
      res = await fetch(path, { headers: { "Content-Type": "application/json", Accept: "application/json" }, credentials: "same-origin", ...options });
    } catch {
      throw { network: true };
    }
    if (res.status === 401) { window.location.href = "/login?next=/"; throw { unauthorized: true }; }
    const payload = res.status === 204 ? null : await res.json().catch(() => ({}));
    return { status: res.status, ok: res.ok, payload };
  }

  // ---- rendering ---------------------------------------------------------------------

  function thumb(url) {
    const box = el("div", { class: "thumb" });
    if (url) box.append(el("img", { src: url, alt: "", loading: "lazy", referrerpolicy: "no-referrer" }));
    else box.textContent = "🎧";
    return box;
  }

  function statusPill(status) {
    return el("span", { class: `pill ${status}` }, [el("span", { class: "dot" }), document.createTextNode(t(`status_${status}`))]);
  }

  function jobCard(job) {
    const meta = [];
    if (job.channel) meta.push(el("span", { text: job.channel }));
    if (job.duration) meta.push(el("span", { text: fmtDuration(job.duration) }));
    meta.push(el("span", { text: t(`q${job.quality}`) }));
    const bodyParts = [
      el("div", { class: "item-title", text: job.title || job.url }),
      el("div", { class: "item-meta" }, meta),
      el("div", { class: "item-actions" }, [statusPill(job.status)]),
    ];
    if (job.status === "converting") {
      const bar = el("div", { class: `progress${job.progress > 0 ? "" : " indeterminate"}` }, [el("span")]);
      if (job.progress > 0) bar.firstChild.style.width = `${job.progress}%`;
      bodyParts.push(bar);
      if (job.progress > 0) bodyParts.push(el("div", { class: "progress-label", text: `${job.progress.toFixed(1)} %` }));
    } else if (job.status === "fetching" || job.status === "queued") {
      bodyParts.push(el("div", { class: "progress indeterminate" }, [el("span")]));
    }
    if (job.status === "failed") {
      const err = el("div", { class: "item-error", text: t(`e_${job.error_code || "internal"}`) });
      if (job.error) err.append(el("small", { text: job.error }));
      bodyParts.push(err);
    }
    if (job.status === "done") {
      if (job.expired) bodyParts.push(el("div", { class: "muted", text: t("expired") }));
      else bodyParts[2].append(el("a", { class: "btn primary small", href: `/api/files/${encodeURIComponent(job.filename)}`, text: t("download") }));
    }
    if (["queued", "fetching", "converting"].includes(job.status)) {
      bodyParts[2].append(el("button", { class: "btn ghost small", type: "button", text: t("cancel"), onclick: () => cancelJob(job.id) }));
    }
    return el("li", { class: `item${job.expired ? " expired" : ""}`, "data-id": job.id }, [thumb(job.thumbnail), el("div", { class: "item-body" }, bodyParts)]);
  }

  function fileCard(file, nextToGo) {
    const meta = [];
    if (file.channel) meta.push(el("span", { text: file.channel }));
    if (file.duration) meta.push(el("span", { text: fmtDuration(file.duration) }));
    meta.push(el("span", { text: fmtSize(file.size_bytes) }));
    if (file.quality) meta.push(el("span", { text: t(`q${file.quality}`) }));
    meta.push(el("span", { text: fmtDate(file.modified_at) }));
    const actions = el("div", { class: "item-actions" }, [
      el("a", { class: "btn primary small", href: `/api/files/${encodeURIComponent(file.name)}`, text: t("download") }),
      el("button", { class: "btn ghost small danger", type: "button", text: t("delete"), onclick: () => deleteFile(file) }),
    ]);
    if (file.name === nextToGo) actions.append(el("span", { class: "badge", text: `⏳ ${t("next_to_go")}` }));
    return el("li", { class: "item" }, [thumb(file.thumbnail), el("div", { class: "item-body" }, [
      el("div", { class: "item-title", text: file.title }), el("div", { class: "item-meta" }, meta), actions])]);
  }

  function render(data) {
    state.data = data;
    const maxFiles = data.retention.max_files;
    $("#banner").textContent = maxFiles === 1 ? t("banner_one") : t("banner", { n: maxFiles });

    const visibleJobs = data.jobs
      .filter((j) => j.status !== "done" || j.expired)
      .sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
    const jobsList = $("#jobs");
    jobsList.replaceChildren(...visibleJobs.map(jobCard));
    $("#jobs-empty").classList.toggle("hidden", visibleJobs.length > 0);
    const active = data.jobs.filter((j) => ["queued", "fetching", "converting"].includes(j.status)).length;
    $("#queue-count").textContent = active ? String(active) : "";

    const filesList = $("#files");
    filesList.replaceChildren(...data.files.map((f) => fileCard(f, data.retention.next_to_go)));
    $("#files-empty").classList.toggle("hidden", data.files.length > 0);
    $("#files-count").textContent = data.files.length ? `${data.files.length}/${maxFiles}` : "";

    schedule(active > 0 ? 2000 : 10000);
  }

  function schedule(ms) {
    clearTimeout(state.timer);
    state.timer = setTimeout(refresh, ms);
  }

  async function refresh() {
    try {
      const { ok, payload } = await api("/api/state");
      if (ok) render(payload); else schedule(5000);
    } catch (err) {
      if (!err.unauthorized) schedule(5000);
    }
  }

  // ---- actions -----------------------------------------------------------------------

  async function submit(extra = {}) {
    const url = $("#url").value.trim();
    if (!url) return;
    const btn = $("#submit-btn");
    btn.disabled = true;
    setMsg("");
    try {
      const { status, payload } = await api("/api/jobs", { method: "POST", body: JSON.stringify({ url, quality: state.quality, ...extra }) });
      if (status === 201) {
        const n = payload.jobs.length;
        toast(n === 1 ? t("added_one") : t("added_many", { n }), "ok");
        if (payload.skipped && payload.skipped.length) setMsg(t("skipped", { n: payload.skipped.length }));
        $("#url").value = "";
        closePlaylist();
        refresh();
      } else if (status === 200 && payload.playlist) {
        openPlaylist(payload.playlist);
      } else if (status === 409) {
        setMsg(t("err_duplicate"), "error");
      } else if (status === 400) {
        setMsg(t(payload.error === "bad_quality" ? "err_bad_quality" : "err_invalid_url"), "error");
      } else if (status === 502) {
        setMsg(`${t("err_playlist")} ${payload.code ? t(`e_${payload.code}`) : ""}`.trim(), "error");
      } else {
        setMsg(t("e_internal"), "error");
      }
    } catch (err) {
      if (err.network) setMsg(t("err_network"), "error");
    } finally {
      btn.disabled = false;
    }
  }

  async function cancelJob(id) {
    try { await api(`/api/jobs/${encodeURIComponent(id)}`, { method: "DELETE" }); refresh(); }
    catch (err) { if (err.network) toast(t("err_network"), "error"); }
  }

  async function deleteFile(file) {
    if (!window.confirm(t("confirm_delete", { name: file.title }))) return;
    try { await api(`/api/files/${encodeURIComponent(file.name)}`, { method: "DELETE" }); refresh(); }
    catch (err) { if (err.network) toast(t("err_network"), "error"); }
  }

  // ---- playlist dialog ---------------------------------------------------------------

  function openPlaylist(pl) {
    state.pendingPlaylist = pl;
    $("#pl-title").textContent = t("pl_title", { title: pl.title });
    $("#pl-intro").textContent = t("pl_intro", { count: pl.count });
    $("#pl-note").textContent = t("pl_note", { max: pl.max_files });
    const list = $("#pl-entries");
    list.replaceChildren(...pl.entries.map((e, i) => {
      const id = `pl-${e.video_id}`;
      const input = el("input", { type: "checkbox", id, value: e.video_id, onchange: updatePlaylistButton });
      input.checked = i < pl.max_files;
      return el("li", {}, [el("label", { for: id }, [input, el("span", { text: e.title }), el("span", { class: "dur", text: fmtDuration(e.duration) })])]);
    }));
    $("#pl-single").classList.toggle("hidden", !pl.single_video_url);
    updatePlaylistButton();
    const dialog = $("#playlist-dialog");
    if (typeof dialog.showModal === "function") dialog.showModal(); else dialog.setAttribute("open", "");
  }

  function selectedPlaylistIds() {
    return [...document.querySelectorAll("#pl-entries input:checked")].map((i) => i.value);
  }

  function updatePlaylistButton() {
    const max = state.pendingPlaylist ? state.pendingPlaylist.max_files : state.maxFiles;
    const n = Math.min(selectedPlaylistIds().length, max);
    const btn = $("#pl-add");
    btn.textContent = t("pl_add", { n });
    btn.disabled = n === 0;
  }

  function closePlaylist() {
    const dialog = $("#playlist-dialog");
    if (dialog.open) dialog.close();
    state.pendingPlaylist = null;
  }

  // ---- wiring ------------------------------------------------------------------------

  $("#submit-form").addEventListener("submit", (e) => { e.preventDefault(); submit(); });
  $("#url").addEventListener("paste", () => setTimeout(() => { if ($("#url").value.trim()) submit(); }, 50));
  $("#lang-toggle").addEventListener("click", () => {
    state.lang = state.lang === "fr" ? "en" : "fr";
    store.set("bookmallow.lang", state.lang);
    applyI18n();
  });
  $("#pl-cancel").addEventListener("click", closePlaylist);
  $("#pl-single").addEventListener("click", () => submit({ playlist: "ignore" }));
  $("#pl-add").addEventListener("click", () => submit({ playlist: "expand", video_ids: selectedPlaylistIds() }));
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") refresh(); });

  applyI18n();
  refresh();
})();
