(() => {
  for (const form of document.querySelectorAll("[data-workshop-wait-form]")) {
    const reason = form.querySelector('select[name="waiting_reason"]');
    const other = form.querySelector("[data-workshop-wait-other]");
    const note = other?.querySelector('textarea[name="waiting_note"]');
    if (!reason || !other || !note) continue;

    const sync = () => {
      const needsNote = reason.value === "Outro";
      other.hidden = !needsNote;
      note.disabled = !needsNote;
      note.required = needsNote;
    };
    reason.addEventListener("change", () => {
      sync();
      if (reason.value === "Outro") note.focus();
    });
    sync();
  }
})();
