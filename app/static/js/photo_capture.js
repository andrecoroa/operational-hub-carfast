(() => {
  const categoryLabels = { front: "Frente", rear: "Traseira", side: "Lateral", damage: "Dano", document: "Documento", part: "Peça", odometer: "Quilometragem", other: "Outro" };
  const statusLabels = { pending: "Pendente", captured: "Capturada", submitted: "Submetida", approved: "Aprovada", rejected: "Rejeitada" };
  const escapeHtml = (value) => String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
  const contextFor = (root) => {
    const number = (key) => root.dataset[key] ? Number(root.dataset[key]) : null;
    return { task_id: number("taskId"), task_flow_step_id: number("taskFlowStepId"), workshop_process_id: number("workshopProcessId"), phased_process_id: number("phasedProcessId"), phase_id: number("phaseId"), vehicle_id: number("vehicleId"), entity_type: root.dataset.entityType || null, entity_id: root.dataset.entityId || null };
  };
  const contextQuery = (root) => {
    const params = new URLSearchParams();
    Object.entries(contextFor(root)).forEach(([key, value]) => { if (value !== null && value !== "") params.set(key, value); });
    return params.toString();
  };
  const request = async (url, options = {}) => {
    const response = await fetch(url, options);
    const payload = (response.headers.get("content-type") || "").includes("application/json") ? await response.json() : null;
    if (!response.ok) throw new Error(payload?.detail || "Não foi possível concluir a operação.");
    return payload;
  };
  const setFeedback = (root, message, kind = "") => {
    const target = root.querySelector("[data-photo-feedback]");
    target.textContent = message || "";
    target.className = `photo-capture__feedback ${kind}`;
  };
  const itemMarkup = (session, item, editable) => `
    <figure class="photo-capture__item">
      <a href="${escapeHtml(item.content_url)}" target="_blank" rel="noopener"><img src="${escapeHtml(item.thumbnail_url)}" alt="${escapeHtml(item.category_label)}${item.observation ? `: ${escapeHtml(item.observation)}` : ""}" loading="lazy"></a>
      <figcaption><strong>${escapeHtml(item.category_label)}</strong><span>${escapeHtml(item.observation || "Sem observação")}</span><small>${Math.round((item.file_size || 0) / 1024)} KB · ${item.width || "?"}×${item.height || "?"}</small></figcaption>
      ${editable ? `<button type="button" class="photo-capture__remove" data-photo-remove="${item.id}" data-session-id="${session.id}" aria-label="Remover fotografia ${escapeHtml(item.category_label)}">Remover</button>` : ""}
    </figure>`;
  const captureFormMarkup = (session) => {
    const config = session.config || {};
    const capture = config.capture || {};
    const categories = (config.categories || ["other"]).map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(categoryLabels[value] || value)}</option>`).join("");
    const observation = config.observation || "optional";
    const accept = "image/jpeg,image/png,image/webp";
    return `<form class="photo-capture__form" data-photo-upload="${session.id}">
      <div class="photo-capture__source-buttons">
        ${capture.allow_camera !== false ? `<label class="photo-capture__source primary">Abrir câmara<input type="file" name="camera_photo" accept="${accept}" capture="environment" data-photo-input data-source="camera"></label>` : ""}
        ${capture.allow_gallery !== false ? `<label class="photo-capture__source">Galeria / ficheiro<input type="file" name="file_photo" accept="${accept}" data-photo-input data-source="gallery"></label>` : ""}
      </div>
      <div class="photo-capture__preview" data-photo-preview hidden><img alt="Pré-visualização da fotografia antes de submeter"><div><strong data-preview-name></strong><span data-preview-size></span></div><button type="button" data-photo-clear>Remover / substituir</button></div>
      <div class="photo-capture__fields"><label>Tipo de fotografia<select name="category">${categories}</select></label>${observation !== "disabled" ? `<label>Observação${observation === "required" ? " *" : ""}<textarea name="observation" rows="2" ${observation === "required" ? "required" : ""} maxlength="4000"></textarea></label>` : ""}</div>
      ${config.location?.enabled ? `<label class="photo-capture__consent"><input type="checkbox" name="location_consent"> Associar localização atual (com consentimento)</label>` : ""}
      <p class="photo-capture__file-help">Máximo ${Math.round((config.max_file_bytes || 15000000) / 1000000)} MB. Confirme a pré-visualização antes de guardar.</p>
      <button type="submit" disabled data-photo-upload-button>Guardar fotografia</button>
    </form>`;
  };
  const sessionMarkup = (session) => {
    const editable = ["pending", "captured"].includes(session.status);
    const canSubmit = editable && session.progress.count >= session.progress.minimum;
    return `<article class="photo-capture__session" data-session="${session.id}">
      <header><div><h4>${escapeHtml(session.title)}${session.required ? " *" : ""}</h4>${session.instructions ? `<p>${escapeHtml(session.instructions)}</p>` : ""}</div><span class="photo-capture__status status-${escapeHtml(session.status)}">${escapeHtml(statusLabels[session.status] || session.status)}</span></header>
      ${session.rejection_reason ? `<div class="photo-capture__rejection" role="alert"><strong>Motivo da rejeição</strong><span>${escapeHtml(session.rejection_reason)}</span></div>` : ""}
      <div class="photo-capture__progress"><span>${escapeHtml(session.progress.label)}</span><progress value="${session.progress.count}" max="${session.progress.maximum}">${escapeHtml(session.progress.label)}</progress></div>
      <div class="photo-capture__gallery">${session.items.map((item) => itemMarkup(session, item, editable)).join("")}</div>
      ${editable && session.progress.count < session.progress.maximum ? captureFormMarkup(session) : ""}
      <div class="photo-capture__actions">${canSubmit ? `<button type="button" data-photo-submit="${session.id}" class="primary">Submeter captura</button>` : ""}${session.blocker && !canSubmit ? `<span class="photo-capture__blocker">${escapeHtml(session.blocker)}</span>` : ""}${session.status === "submitted" ? `<button type="button" data-photo-approve="${session.id}">Aprovar</button><button type="button" data-photo-reject="${session.id}" class="danger">Rejeitar / pedir nova</button>` : ""}${session.status === "rejected" ? `<button type="button" data-photo-repeat="${session.id}">Repetir captura</button>` : ""}</div>
    </article>`;
  };
  const bindSession = (root) => {
    root.querySelectorAll("[data-photo-input]").forEach((input) => input.addEventListener("change", () => {
      const form = input.closest("form");
      form.querySelectorAll("[data-photo-input]").forEach((other) => { if (other !== input) other.value = ""; });
      const file = input.files?.[0];
      const preview = form.querySelector("[data-photo-preview]");
      const button = form.querySelector("[data-photo-upload-button]");
      if (!file) { preview.hidden = true; button.disabled = true; return; }
      preview.hidden = false;
      preview.querySelector("img").src = URL.createObjectURL(file);
      preview.querySelector("[data-preview-name]").textContent = file.name;
      preview.querySelector("[data-preview-size]").textContent = `${Math.round(file.size / 1024)} KB`;
      form.dataset.captureSource = input.dataset.source;
      button.disabled = false;
    }));
    root.querySelectorAll("[data-photo-clear]").forEach((button) => button.addEventListener("click", () => {
      const form = button.closest("form");
      form.querySelectorAll("[data-photo-input]").forEach((input) => { input.value = ""; });
      form.querySelector("[data-photo-preview]").hidden = true;
      form.querySelector("[data-photo-upload-button]").disabled = true;
    }));
    root.querySelectorAll("[data-photo-upload]").forEach((form) => form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const input = Array.from(form.querySelectorAll("[data-photo-input]")).find((candidate) => candidate.files?.length);
      if (!input) return;
      const button = form.querySelector("[data-photo-upload-button]");
      button.disabled = true;
      setFeedback(root, "A validar e guardar a fotografia…");
      try {
        const body = new FormData();
        body.append("photo", input.files[0]); body.append("category", form.elements.category.value); body.append("observation", form.elements.observation?.value || ""); body.append("capture_source", form.dataset.captureSource || "file"); body.append("is_new_capture", form.dataset.captureSource === "camera" ? "true" : "false"); body.append("client_captured_at", new Date().toISOString());
        if (form.elements.location_consent?.checked) {
          if (!navigator.geolocation) throw new Error("Este dispositivo não disponibiliza localização.");
          const position = await new Promise((resolve, reject) => navigator.geolocation.getCurrentPosition(resolve, reject, { enableHighAccuracy: true, timeout: 10000 }));
          body.append("location_consent", "true"); body.append("location_latitude", position.coords.latitude); body.append("location_longitude", position.coords.longitude); body.append("location_accuracy_m", position.coords.accuracy);
        }
        await request(`/api/photo-actions/sessions/${form.dataset.photoUpload}/photos`, { method: "POST", body });
        setFeedback(root, "Fotografia guardada.", "success"); await load(root);
      } catch (error) { setFeedback(root, error.message, "error"); button.disabled = false; }
    }));
    root.querySelectorAll("[data-photo-remove]").forEach((button) => button.addEventListener("click", async () => { try { await request(`/api/photo-actions/sessions/${button.dataset.sessionId}/photos/${button.dataset.photoRemove}`, { method: "DELETE" }); setFeedback(root, "Fotografia removida da captura.", "success"); await load(root); } catch (error) { setFeedback(root, error.message, "error"); } }));
    root.querySelectorAll("[data-photo-submit]").forEach((button) => button.addEventListener("click", async () => { try { await request(`/api/photo-actions/sessions/${button.dataset.photoSubmit}/submit`, { method: "POST" }); setFeedback(root, "Captura submetida.", "success"); await load(root); } catch (error) { setFeedback(root, error.message, "error"); } }));
    root.querySelectorAll("[data-photo-approve]").forEach((button) => button.addEventListener("click", async () => { try { await request(`/api/photo-actions/sessions/${button.dataset.photoApprove}/review`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ decision: "approved" }) }); setFeedback(root, "Captura aprovada.", "success"); await load(root); } catch (error) { setFeedback(root, error.message, "error"); } }));
    root.querySelectorAll("[data-photo-reject]").forEach((button) => button.addEventListener("click", async () => { const reason = window.prompt("Motivo obrigatório da rejeição:"); if (!reason?.trim()) return; try { await request(`/api/photo-actions/sessions/${button.dataset.photoReject}/review`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ decision: "rejected", reason }) }); setFeedback(root, "Captura rejeitada; pode ser repetida.", "success"); await load(root); } catch (error) { setFeedback(root, error.message, "error"); } }));
    root.querySelectorAll("[data-photo-repeat]").forEach((button) => button.addEventListener("click", async () => { try { await request(`/api/photo-actions/sessions/${button.dataset.photoRepeat}/repeat`, { method: "POST" }); setFeedback(root, "Nova tentativa criada.", "success"); await load(root); } catch (error) { setFeedback(root, error.message, "error"); } }));
  };
  const render = (root, sessions) => {
    const target = root.querySelector("[data-photo-sessions]");
    target.innerHTML = sessions.length ? sessions.map(sessionMarkup).join("") : '<p class="muted">Ainda não existem capturas neste contexto.</p>';
    target.setAttribute("aria-busy", "false"); bindSession(root);
  };
  const load = async (root) => { try { render(root, await request(`/api/photo-actions/sessions?${contextQuery(root)}`)); } catch (error) { root.querySelector("[data-photo-sessions]").setAttribute("aria-busy", "false"); setFeedback(root, error.message, "error"); } };
  document.querySelectorAll("[data-photo-capture]").forEach((root) => {
    root.querySelector("[data-photo-new]").addEventListener("click", async () => { setFeedback(root, "A preparar a captura…"); try { await request("/api/photo-actions/sessions", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ definition_code: "take_photo.default", ...contextFor(root) }) }); setFeedback(root, "Captura preparada. Abra a câmara ou escolha um ficheiro.", "success"); await load(root); } catch (error) { setFeedback(root, error.message, "error"); } });
    load(root);
  });
})();
