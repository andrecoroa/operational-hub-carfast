(() => {
  const dialog = document.getElementById("email-preview-dialog");
  const bindThread = (root = document) => {
    root.querySelectorAll("[data-email-modal-close]").forEach((button) => button.addEventListener("click", () => dialog?.close()));
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
      if (!dialog || !dialog.open || !form.closest("#email-preview-dialog")) return;
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
  const openPreview = async (threadId) => {
    if (!dialog || !threadId) return;
    dialog.innerHTML = '<div class="email-preview-loading">A abrir conversa…</div>';
    dialog.showModal();
    const response = await fetch(`/v2-clean/email/${threadId}/preview`, {headers: {"X-Requested-With": "fetch"}});
    dialog.innerHTML = await response.text();
    bindThread(dialog);
  };
  document.querySelectorAll("[data-email-preview]").forEach((element) => element.addEventListener("click", (event) => {
    if (event.target.closest("a, button")) return;
    openPreview(element.dataset.emailPreview);
  }));
  document.querySelectorAll("[data-email-preview-trigger]").forEach((button) => button.addEventListener("click", (event) => {
    event.stopPropagation();
    openPreview(button.dataset.emailPreviewTrigger);
  }));
  dialog?.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
  bindThread();
})();
