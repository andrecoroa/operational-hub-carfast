(() => {
  let activeSelect = null;
  let priorValue = "";
  let suggestionTimer = null;

  const dialog = document.createElement("dialog");
  dialog.className = "classification-proposal-dialog";
  dialog.innerHTML = `
    <form method="dialog" class="classification-proposal-panel" data-proposal-form>
      <header><div><span class="eyebrow">Classificação transversal</span><h2 data-proposal-title>Propor classificação</h2></div><button value="cancel" class="classification-dialog-close" aria-label="Fechar">×</button></header>
      <p class="classification-proposal-explainer">A proposta fica identificada como <b>Provisório</b>. Não cria imediatamente uma classificação oficial.</p>
      <label>Nome proposto<input name="name" maxlength="160" required autocomplete="off"></label>
      <label>Motivo / descrição<textarea name="reason" rows="4" maxlength="4000" required placeholder="Explica por que a classificação atual não é suficiente."></textarea></label>
      <section class="classification-suggestions" data-proposal-suggestions hidden><h3>Semelhantes</h3><div data-proposal-suggestion-list></div></section>
      <p class="classification-proposal-error" data-proposal-error hidden></p>
      <footer><button value="cancel" class="secondary">Cancelar</button><button type="submit" value="default" data-proposal-submit>Criar proposta provisória</button></footer>
    </form>`;
  document.body.append(dialog);

  const form = dialog.querySelector("[data-proposal-form]");
  const nameInput = form.elements.name;
  const reasonInput = form.elements.reason;
  const suggestionBox = form.querySelector("[data-proposal-suggestions]");
  const suggestionList = form.querySelector("[data-proposal-suggestion-list]");
  const errorBox = form.querySelector("[data-proposal-error]");
  const submitButton = form.querySelector("[data-proposal-submit]");

  const contextFor = (select) => {
    const root = select.closest("[data-work-hierarchy]");
    if (!root) return null;
    const department = root.querySelector('[data-work-level="department"]');
    const category = root.querySelector('[data-work-level="category"]');
    const kind = select.dataset.workLevel === "category" ? "category" : "subcategory";
    const categoryValue = category?.value || "";
    return {
      root,
      kind,
      departmentId: Number(department?.value || 0),
      categoryId: kind === "subcategory" && /^\d+$/.test(categoryValue) ? Number(categoryValue) : null,
      parentProposalId: kind === "subcategory" && categoryValue.startsWith("proposal:")
        ? Number(categoryValue.slice(9)) : null,
      parentValue: kind === "category" ? String(department?.value || "") : categoryValue,
    };
  };

  const selectSuggestion = (item) => {
    if (!activeSelect) return;
    const value = item.type === "proposal" ? `proposal:${item.id}` : String(item.id);
    let option = [...activeSelect.options].find((candidate) => candidate.value === value);
    if (!option) {
      option = new Option(
        `${item.name}${item.type === "proposal" ? ` · Provisório (${item.code})` : ""}`,
        value,
      );
      option.dataset.parent = contextFor(activeSelect)?.parentValue || "";
      if (item.type === "proposal") option.dataset.provisional = "";
      activeSelect.add(option);
    }
    activeSelect.value = value;
    activeSelect.dispatchEvent(new Event("change", {bubbles: true}));
    dialog.close();
  };

  const renderSuggestions = (items) => {
    suggestionList.replaceChildren();
    suggestionBox.hidden = !items.length;
    items.forEach((item) => {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "classification-suggestion-row";
      const meta = item.type === "proposal"
        ? `${item.code} · ${item.usage_count || 0} utilizações${item.priority_review ? " · revisão prioritária" : ""}`
        : `${item.code} · classificação oficial${item.active ? " ativa" : " inativa"}`;
      const label = document.createElement("span");
      const strong = document.createElement("strong");
      const small = document.createElement("small");
      strong.textContent = item.name;
      small.textContent = meta;
      label.append(strong, small);
      const action = document.createElement("b");
      action.textContent = item.type === "proposal" ? "Usar proposta" : "Usar existente";
      row.append(label, action);
      row.addEventListener("click", () => selectSuggestion(item));
      suggestionList.append(row);
    });
  };

  const loadSuggestions = async () => {
    const context = contextFor(activeSelect);
    const name = nameInput.value.trim();
    if (!context || name.length < 2) {
      renderSuggestions([]);
      return;
    }
    const params = new URLSearchParams({
      kind: context.kind,
      name,
      department_id: String(context.departmentId),
    });
    if (context.categoryId) params.set("category_id", String(context.categoryId));
    if (context.parentProposalId) {
      params.set("parent_proposal_id", String(context.parentProposalId));
    }
    const response = await fetch(`/api/classification-proposals/suggestions?${params}`, {
      credentials: "same-origin",
      headers: {"X-Requested-With": "fetch"},
    });
    if (response.ok) renderSuggestions((await response.json()).items || []);
  };

  const openProposal = (select) => {
    activeSelect = select;
    const context = contextFor(select);
    if (!context || !context.departmentId) return;
    select.value = priorValue && !priorValue.startsWith("__propose_") ? priorValue : "";
    form.reset();
    renderSuggestions([]);
    errorBox.hidden = true;
    form.querySelector("[data-proposal-title]").textContent = context.kind === "category"
      ? "Propor nova categoria" : "Propor nova subcategoria";
    dialog.showModal();
    nameInput.focus();
  };

  document.addEventListener("focusin", (event) => {
    if (event.target.matches('[data-work-level="category"], [data-work-level="subcategory"]')) {
      priorValue = event.target.value;
    }
  });
  document.addEventListener("change", (event) => {
    const select = event.target;
    if (!select.matches?.('[data-work-level="category"], [data-work-level="subcategory"]')) {
      return;
    }
    if (select.value.startsWith("__propose_")) openProposal(select);
    else priorValue = select.value;
  });
  nameInput.addEventListener("input", () => {
    clearTimeout(suggestionTimer);
    suggestionTimer = setTimeout(loadSuggestions, 250);
  });

  form.addEventListener("submit", async (event) => {
    if (event.submitter?.value === "cancel") return;
    event.preventDefault();
    const context = contextFor(activeSelect);
    if (!context) return;
    submitButton.disabled = true;
    errorBox.hidden = true;
    const payload = {
      kind: context.kind,
      name: nameInput.value,
      reason: reasonInput.value,
      department_id: context.departmentId,
      category_id: context.categoryId,
      parent_proposal_id: context.parentProposalId,
      origin_module: location.pathname.includes("/email") ? "email" : "service_desk",
      origin_url: `${location.pathname}${location.search}`,
    };
    try {
      const response = await fetch("/api/classification-proposals", {
        method: "POST",
        credentials: "same-origin",
        headers: {"Content-Type": "application/json", "X-Requested-With": "fetch"},
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok) {
        const detail = data.detail;
        const existing = typeof detail === "object" ? detail.existing : null;
        if (response.status === 409 && existing) {
          selectSuggestion({...existing, type: "proposal"});
          return;
        }
        throw new Error(typeof detail === "string" ? detail : detail?.message || "Não foi possível criar a proposta.");
      }
      selectSuggestion({...data, type: "proposal", usage_count: 0});
      if (context.kind === "category") {
        const subcategory = context.root.querySelector('[data-work-level="subcategory"]');
        if (subcategory && ![...subcategory.options].some((item) => item.value === `__propose_subcategory__:proposal:${data.id}`)) {
          const proposeSub = new Option("+ Propor nova subcategoria", `__propose_subcategory__:proposal:${data.id}`);
          proposeSub.dataset.parent = `proposal:${data.id}`;
          proposeSub.dataset.propose = "";
          subcategory.add(proposeSub);
        }
      }
    } catch (error) {
      errorBox.textContent = error.message;
      errorBox.hidden = false;
    } finally {
      submitButton.disabled = false;
    }
  });
})();
