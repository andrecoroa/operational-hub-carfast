(() => {
  const dialog = document.getElementById("email-preview-dialog");
  let inlinePreviewRow = null;
  let previewTrigger = null;
  const restorePreviewFocus = () => {
    const trigger = previewTrigger;
    previewTrigger = null;
    if (!(trigger instanceof HTMLElement) || !trigger.isConnected) return;
    setTimeout(() => trigger.focus({preventScroll: true}), 0);
  };
  const resetInlinePreview = () => {
    inlinePreviewRow?.remove();
    inlinePreviewRow = null;
    document.querySelectorAll("[data-email-preview]").forEach((row) => {
      row.classList.remove("is-selected");
      row.setAttribute("aria-expanded", "false");
    });
    document.querySelectorAll("[data-email-preview-trigger]").forEach((button) => button.setAttribute("aria-expanded", "false"));
    restorePreviewFocus();
  };
  const closeActivePreview = () => {
    if (dialog?.open) {
      dialog.close();
      return true;
    }
    if (inlinePreviewRow) {
      resetInlinePreview();
      return true;
    }
    return false;
  };
  const bindWorkHierarchy = (root) => {
    const source = root.querySelector("[data-email-work-hierarchy]");
    const container = root.querySelector("[data-work-hierarchy]");
    if (!source || !container) return;
    let hierarchy;
    try { hierarchy = JSON.parse(source.textContent || "{}"); } catch (_) { return; }
    const levels = ["queue", "department", "category", "subcategory"];
    const selects = Object.fromEntries(levels.map((level) => [level, container.querySelector(`[data-work-level="${level}"]`)]));
    const records = {
      department: hierarchy.departments || [],
      category: hierarchy.categories || [],
      subcategory: hierarchy.subcategories || [],
    };
    const otherLabel = container.querySelector(".clean-work-other");
    const otherInput = otherLabel?.querySelector("input");
    const selectedRecord = (level) => records[level]?.find((item) => String(item.id) === selects[level]?.value);
    const refreshOther = () => {
      const requiresDescription = ["department", "category", "subcategory"].some((level) => selectedRecord(level)?.requires_description);
      if (otherLabel) otherLabel.hidden = !requiresDescription;
      if (otherInput) otherInput.required = requiresDescription;
    };
    const refreshFrom = (levelIndex, clearChildren) => {
      for (let index = Math.max(1, levelIndex + 1); index < levels.length; index += 1) {
        const level = levels[index];
        const parent = selects[levels[index - 1]];
        const select = selects[level];
        if (!select) continue;
        if (clearChildren) select.value = "";
        [...select.options].forEach((option) => {
          if (!option.value) return;
          option.hidden = !parent?.value || option.dataset.parent !== parent.value;
          option.disabled = option.hidden;
        });
        select.disabled = !parent?.value;
      }
      refreshOther();
    };
    levels.forEach((level, index) => selects[level]?.addEventListener("change", () => refreshFrom(index, true)));
    refreshFrom(0, false);
  };
  const bindTemplates = (root) => {
    root.querySelectorAll("[data-email-template]").forEach((select) => select.addEventListener("change", () => {
      const textarea = select.closest("form")?.querySelector('textarea[name="body"]');
      const subject = select.closest("form")?.querySelector('[data-email-compose-subject]');
      const option = select.selectedOptions[0];
      if (textarea && option?.dataset.body) textarea.value = option.dataset.body;
      if (subject && option?.dataset.subject) subject.value = option.dataset.subject;
    }));
    root.querySelectorAll("[data-email-template-search]").forEach((search) => {
      const select = search.closest("form")?.querySelector("[data-email-template]");
      search.addEventListener("input", () => {
        const query = search.value.trim().toLowerCase();
        [...(select?.options || [])].forEach((option, index) => {
          if (!index) return;
          option.hidden = Boolean(query) && !(option.dataset.search || "").includes(query);
        });
      });
    });
  };
  const bindReplyModes = (root) => {
    root.querySelectorAll(".email-composer").forEach((composer) => {
      const form = composer.querySelector(".email-reply-form");
      const modeInput = form?.querySelector("[data-email-compose-mode-value]");
      const to = form?.querySelector("[data-email-compose-to]");
      const cc = form?.querySelector("[data-email-compose-cc]");
      const subject = form?.querySelector("[data-email-compose-subject]");
      let replyAllTo = [];
      let replyAllCc = [];
      try { replyAllTo = JSON.parse(form?.dataset.replyAllTo || "[]"); } catch (_) { replyAllTo = []; }
      try { replyAllCc = JSON.parse(form?.dataset.replyAllCc || "[]"); } catch (_) { replyAllCc = []; }
      composer.querySelectorAll("[data-email-compose-mode]").forEach((button) => button.addEventListener("click", () => {
        const mode = button.dataset.emailComposeMode;
        composer.querySelectorAll("[data-email-compose-mode]").forEach((item) => item.classList.toggle("active", item === button));
        if (modeInput) modeInput.value = mode;
        if (to) to.value = mode === "reply_all" ? replyAllTo.join(", ") : mode === "reply" ? (form.dataset.replyTo || "") : "";
        if (cc) cc.value = mode === "reply_all" ? replyAllCc.join(", ") : "";
        if (subject) {
          const raw = subject.value.replace(/^(Re|Fwd):\s*/i, "");
          subject.value = `${mode === "forward" ? "Fwd" : "Re"}: ${raw}`;
        }
      }));
    });
  };
  const bindReplySenders = (root) => {
    root.querySelectorAll(".email-reply-form").forEach((form) => {
      const summary = form?.querySelector("[data-email-approval-summary]");
      const send = form?.querySelector("[data-email-direct-action]");
      const approval = form?.querySelector("[data-email-approval-action]");
      const refresh = () => {
        const direct = form.dataset.sendDirect === "true";
        if (summary) summary.textContent = direct
          ? "Esta caixa pode enviar diretamente com o teu perfil."
          : "A resposta desta caixa só é enviada depois da aprovação.";
        if (send) send.hidden = !direct;
        if (approval) approval.hidden = direct;
      };
      refresh();
    });
  };
  const bindBodyViews = (root) => {
    root.querySelectorAll("[data-email-body-view]").forEach((button) => button.addEventListener("click", () => {
      const messageId = button.dataset.emailMessageId;
      const frame = root.querySelector(`#email-body-${messageId}`);
      if (!frame) return;
      const view = button.dataset.emailBodyView === "text" ? "text" : "html";
      frame.src = `${frame.dataset.emailBodyBase}?view=${view}`;
      button.closest(".email-body-switch")?.querySelectorAll("[data-email-body-view]").forEach((item) => item.classList.toggle("active", item === button));
    }));
  };
  const bindPanelSwitch = (root) => {
    const shell = root.querySelector("[data-email-thread-id]");
    const triage = root.querySelector('[data-email-panel="triage"]');
    const composer = root.querySelector('[data-email-panel="composer"]');
    const showComposer = (visible) => {
      if (!triage || !composer) return;
      triage.hidden = visible;
      composer.hidden = !visible;
      shell?.classList.toggle("is-composing", visible);
      if (visible) {
        composer.querySelector('textarea[name="body"]')?.focus();
        if (window.matchMedia("(max-width: 900px)").matches) {
          composer.scrollIntoView({block: "start"});
        }
      }
    };
    root.querySelectorAll("[data-email-open-composer]").forEach((button) => button.addEventListener("click", () => showComposer(true)));
    root.querySelectorAll("[data-email-close-composer]").forEach((button) => button.addEventListener("click", () => showComposer(false)));
  };
  const bindLinkKinds = (root) => {
    root.querySelectorAll("[data-email-link-kind]").forEach((select) => {
      const hidden = select.form?.querySelector("[data-email-link-type]");
      const refresh = () => { if (hidden) hidden.value = select.value === "process" ? "process" : "entity"; };
      select.addEventListener("change", refresh);
      refresh();
    });
  };
  const bindThread = (root = document) => {
    bindWorkHierarchy(root);
    bindTemplates(root);
    bindReplyModes(root);
    bindReplySenders(root);
    bindBodyViews(root);
    bindPanelSwitch(root);
    bindLinkKinds(root);
    root.querySelectorAll("[data-email-modal-close]").forEach((button) => button.addEventListener("click", closeActivePreview));
    root.querySelectorAll("[data-email-show-images]").forEach((button) => button.addEventListener("click", () => {
      const frame = document.getElementById(button.dataset.emailShowImages);
      frame?.contentDocument?.querySelectorAll("img[data-email-src]").forEach((image) => { image.src = image.dataset.emailSrc; image.style.display = "inline-block"; });
      button.remove();
    }));
    root.querySelectorAll("[data-email-attachment-preview]").forEach((button) => button.addEventListener("click", async () => {
      const attachmentDialog = root.querySelector("[data-email-attachment-dialog]");
      if (!attachmentDialog) return;
      attachmentDialog.innerHTML = '<div class="email-preview-loading">A abrir anexo…</div>';
      attachmentDialog.showModal();
      const response = await fetch(`/v2-clean/email/attachments/${button.dataset.emailAttachmentPreview}/preview`, {headers: {"X-Requested-With": "fetch"}});
      attachmentDialog.innerHTML = await response.text();
      attachmentDialog.querySelector("[data-email-attachment-close]")?.addEventListener("click", () => attachmentDialog.close());
      const attachmentForm = attachmentDialog.querySelector(".email-attachment-form");
      attachmentForm?.addEventListener("submit", async (event) => {
        event.preventDefault();
        const save = attachmentForm.querySelector('button[type="submit"]');
        if (save) save.disabled = true;
        const result = await fetch(attachmentForm.action, {method: "POST", body: new FormData(attachmentForm), credentials: "same-origin", headers: {"X-Requested-With": "fetch"}});
        const notice = document.createElement("div");
        notice.innerHTML = await result.text();
        attachmentForm.prepend(notice);
        if (save) save.disabled = false;
      });
    }));
    root.querySelectorAll("[data-email-approve]").forEach((button) => button.addEventListener("click", async (event) => {
      event.preventDefault();
      event.stopPropagation();
      const form = button.form;
      if (!form || button.disabled) return;
      button.disabled = true;
      const response = await fetch(form.action, {
        method: "POST",
        body: new FormData(form),
        credentials: "same-origin",
        headers: {"X-Requested-With": "fetch"},
      });
      const resultUrl = new URL(response.url, window.location.origin);
      if (resultUrl.searchParams.has("error")) {
        const notice = document.createElement("div");
        notice.className = "email-notice warning";
        notice.textContent = resultUrl.searchParams.get("error") === "send_disabled"
          ? "A resposta foi aprovada, mas o envio externo está desligado ou incompleto."
          : "Não foi possível aprovar e enviar a resposta.";
        form.closest(".email-approval")?.prepend(notice);
        button.disabled = false;
        return;
      }
      if (response.ok) {
        await openPreview(button.dataset.emailThreadId);
      } else {
        button.disabled = false;
      }
    }));
    root.querySelectorAll("form").forEach((form) => form.addEventListener("submit", async (event) => {
      if (event.submitter?.matches("[data-email-approve]")) return;
      const formPreviewRoot = form.closest("#email-preview-dialog, .email-inline-preview-body");
      if (!formPreviewRoot || (formPreviewRoot === dialog && !dialog.open)) return;
      event.preventDefault();
      const submitter = event.submitter;
      if (submitter) submitter.disabled = true;
      const payload = new FormData(form);
      if (submitter?.name) payload.set(submitter.name, submitter.value);
      const response = await fetch(form.action, {
        method: (form.method || "post").toUpperCase(),
        body: payload,
        credentials: "same-origin",
        headers: {"X-Requested-With": "fetch"},
      });
      const shell = form.closest("[data-email-thread-id]");
      if (response.ok && shell?.dataset.emailThreadId) {
        await openPreview(shell.dataset.emailThreadId);
      } else if (submitter) {
        submitter.disabled = false;
      }
    }));
  };
  const openPreview = async (threadId, trigger = null) => {
    if (!threadId) return;
    const sourceRow = trigger?.closest?.("[data-email-preview]") || document.querySelector(`[data-email-preview="${threadId}"]`);
    if (!sourceRow) return;
    if (inlinePreviewRow?.dataset.emailInlineThread === String(threadId)) {
      resetInlinePreview();
      return;
    }
    inlinePreviewRow?.remove();
    inlinePreviewRow = document.createElement("tr");
    inlinePreviewRow.className = "email-inline-preview-row";
    inlinePreviewRow.dataset.emailInlineThread = String(threadId);
    const cell = document.createElement("td");
    cell.colSpan = sourceRow.children.length || 7;
    const previewRoot = document.createElement("div");
    previewRoot.className = "email-inline-preview-body";
    previewRoot.setAttribute("aria-live", "polite");
    cell.append(previewRoot);
    inlinePreviewRow.append(cell);
    sourceRow.after(inlinePreviewRow);
    if (trigger) previewTrigger = trigger;
    else if (!(previewTrigger instanceof HTMLElement) || !previewTrigger.isConnected) previewTrigger = document.activeElement;
    previewRoot.innerHTML = '<div class="email-preview-loading">A abrir conversa…</div>';
    const response = await fetch(`/v2-clean/email/${threadId}/preview`, {headers: {"X-Requested-With": "fetch"}});
    previewRoot.innerHTML = await response.text();
    bindThread(previewRoot);
    const fullPageLink = previewRoot.querySelector(".email-open-full");
    if (fullPageLink) fullPageLink.href = `${fullPageLink.pathname}?return_context=${encodeURIComponent(location.pathname + location.search)}`;
    previewRoot.querySelector("[data-email-modal-close], button, a, input, select, textarea")?.focus({preventScroll: true});
    document.querySelectorAll("[data-email-preview]").forEach((row) => {
      const selected = row.dataset.emailPreview === String(threadId);
      row.classList.toggle("is-selected", selected);
      row.setAttribute("aria-expanded", String(selected));
    });
    document.querySelectorAll("[data-email-preview-trigger]").forEach((button) => button.setAttribute("aria-expanded", String(button.dataset.emailPreviewTrigger === String(threadId))));
    inlinePreviewRow.scrollIntoView({block: "nearest"});
  };
  document.querySelectorAll("[data-email-preview]").forEach((element) => element.addEventListener("click", (event) => {
    if (event.target.closest("a, button")) return;
    openPreview(element.dataset.emailPreview, element);
  }));
  document.querySelectorAll("[data-email-preview]").forEach((element) => element.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    if (event.target.closest("a, button, input, select, textarea")) return;
    event.preventDefault();
    openPreview(element.dataset.emailPreview, element);
  }));
  document.querySelectorAll("[data-email-preview-trigger]").forEach((button) => button.addEventListener("click", (event) => {
    event.stopPropagation();
    openPreview(button.dataset.emailPreviewTrigger, button);
  }));
  dialog?.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
  dialog?.addEventListener("cancel", (event) => {
    event.preventDefault();
    closeActivePreview();
  });
  dialog?.addEventListener("close", () => {
    document.querySelectorAll("[data-email-preview]").forEach((row) => row.classList.remove("is-selected"));
    restorePreviewFocus();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    const nestedDialog = document.querySelector("dialog[open]:not(#email-preview-dialog)");
    if (nestedDialog) return;
    if (closeActivePreview()) event.preventDefault();
  });
  bindThread();
})();
