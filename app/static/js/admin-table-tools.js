(() => {
  const normalize = (value) => (value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .trim()
    .toLowerCase();

  const enhanceTable = (table, index) => {
    if (table.dataset.adminTableReady === "true") return;
    const headers = [...table.querySelectorAll("thead th")];
    const rows = [...table.querySelectorAll("tbody tr")].filter((row) => row.children.length > 1);
    if (!headers.length || !rows.length) return;

    table.dataset.adminTableReady = "true";
    const headerMap = new Map(headers.map((header, column) => [normalize(header.textContent), column]));
    const requested = (table.dataset.adminFilterColumns || "").split(",").map(normalize).filter(Boolean);
    const useful = ["categoria", "funcao", "utilizador/equipa", "utilizador", "perfil", "area", "equipa", "caixa", "tipo", "atribuicao"];
    const filterNames = [...new Set([...requested, ...useful.filter((name) => headerMap.has(name))])];
    const stateColumn = headerMap.get("estado");

    const toolbar = document.createElement("div");
    toolbar.className = "clean-admin-table-tools";
    toolbar.setAttribute("role", "search");
    toolbar.setAttribute("aria-label", "Filtrar tabela");
    toolbar.innerHTML = `<label class="clean-admin-table-search">Pesquisar<input type="search" placeholder="Pesquisar nesta tabela" aria-label="Pesquisar nesta tabela"></label>`;
    const search = toolbar.querySelector("input");
    const filters = [];

    if (stateColumn !== undefined) {
      const label = document.createElement("label");
      label.innerHTML = `<span>Estado</span><select aria-label="Filtrar por estado"><option value="active">Ativos</option><option value="inactive">Inativos</option><option value="all">Todos</option></select>`;
      toolbar.append(label);
      filters.push({ column: stateColumn, select: label.querySelector("select"), state: true });
    }

    filterNames.forEach((name) => {
      const column = headerMap.get(name);
      if (column === undefined || column === stateColumn) return;
      const values = [...new Set(rows.map((row) => row.children[column]?.textContent.trim()).filter(Boolean))]
        .sort((a, b) => a.localeCompare(b, "pt", { sensitivity: "base" }));
      if (values.length < 2 || values.length > 40) return;
      const label = document.createElement("label");
      const title = headers[column].textContent.trim();
      const select = document.createElement("select");
      select.setAttribute("aria-label", `Filtrar por ${title}`);
      select.append(new Option(`${title}: todos`, ""));
      values.forEach((value) => select.append(new Option(value, normalize(value))));
      label.append(title, select);
      toolbar.append(label);
      filters.push({ column, select, state: false });
    });

    const clear = document.createElement("button");
    clear.type = "button";
    clear.className = "secondary compact-button";
    clear.textContent = "Limpar filtros";
    const results = document.createElement("span");
    results.className = "clean-admin-table-results";
    results.setAttribute("aria-live", "polite");
    toolbar.append(clear, results);

    const apply = () => {
      const query = normalize(search.value);
      let visible = 0;
      rows.forEach((row) => {
        const matchesSearch = !query || normalize(row.textContent).includes(query);
        const matchesFilters = filters.every(({ column, select, state }) => {
          if (state) {
            if (select.value === "all") return true;
            const value = normalize(row.children[column]?.textContent);
            return select.value === "active" ? value.startsWith("ativ") : value.startsWith("inativ");
          }
          return !select.value || normalize(row.children[column]?.textContent) === select.value;
        });
        row.hidden = !(matchesSearch && matchesFilters);
        if (!row.hidden) visible += 1;
      });
      results.textContent = `${visible} de ${rows.length} registos`;
    };

    search.addEventListener("input", apply);
    filters.forEach(({ select }) => select.addEventListener("change", apply));
    clear.addEventListener("click", () => {
      search.value = "";
      filters.forEach(({ select, state }) => { select.value = state ? "active" : ""; });
      apply();
      search.focus();
    });

    headers.forEach((header, column) => {
      if (!header.textContent.trim() || normalize(header.textContent).includes("acao")) return;
      header.tabIndex = 0;
      header.classList.add("clean-admin-sortable");
      header.setAttribute("aria-sort", "none");
      const sort = () => {
        const ascending = header.getAttribute("aria-sort") !== "ascending";
        headers.forEach((item) => item.setAttribute("aria-sort", "none"));
        header.setAttribute("aria-sort", ascending ? "ascending" : "descending");
        rows.sort((a, b) => a.children[column].textContent.trim().localeCompare(
          b.children[column].textContent.trim(), "pt", { numeric: true, sensitivity: "base" }
        ) * (ascending ? 1 : -1)).forEach((row) => table.tBodies[0].append(row));
      };
      header.addEventListener("click", sort);
      header.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") { event.preventDefault(); sort(); }
      });
    });

    const container = table.closest(".clean-table-scroll, .table-wrap") || table;
    container.before(toolbar);
    toolbar.dataset.tableIndex = String(index);
    apply();
  };

  document.querySelectorAll(".clean-admin-content table, .clean-work-admin-view table").forEach(enhanceTable);

  const permissionSearch = document.querySelector("[data-permission-search]");
  const permissionState = document.querySelector("[data-permission-state]");
  const permissionResults = document.querySelector("[data-permission-results]");
  const editors = [...document.querySelectorAll("[data-role-editor]")];
  const filterPermissions = () => {
    const editor = editors.find((item) => !item.hidden);
    if (!editor) return;
    const query = normalize(permissionSearch?.value);
    const state = permissionState?.value || "all";
    let visible = 0;
    let total = 0;
    editor.querySelectorAll("[data-permission-group]").forEach((group) => {
      let groupVisible = 0;
      group.querySelectorAll("[data-permission-item]").forEach((item) => {
        total += 1;
        const checked = item.querySelector("input")?.checked;
        const matchesState = state === "all" || (state === "checked" ? checked : !checked);
        item.hidden = !(matchesState && (!query || normalize(item.textContent).includes(query)));
        if (!item.hidden) { visible += 1; groupVisible += 1; }
      });
      group.hidden = groupVisible === 0;
    });
    if (permissionResults) permissionResults.textContent = `${visible} de ${total} permissões`;
  };
  permissionSearch?.addEventListener("input", filterPermissions);
  permissionState?.addEventListener("change", filterPermissions);
  document.getElementById("clean-admin-role-picker")?.addEventListener("change", () => requestAnimationFrame(filterPermissions));
  document.querySelectorAll(".clean-admin-role-select").forEach((button) => button.addEventListener("click", () => requestAnimationFrame(filterPermissions)));
  document.querySelectorAll("[data-permission-group-toggle]").forEach((button) => button.addEventListener("click", () => {
    const group = button.closest("[data-permission-group]");
    const collapsed = group.classList.toggle("is-collapsed");
    button.setAttribute("aria-expanded", String(!collapsed));
  }));
  document.querySelector("[data-permission-expand]")?.addEventListener("click", (event) => {
    const groups = [...document.querySelectorAll("[data-permission-group]")];
    const collapse = groups.some((group) => !group.classList.contains("is-collapsed"));
    groups.forEach((group) => {
      group.classList.toggle("is-collapsed", collapse);
      group.querySelector("[data-permission-group-toggle]")?.setAttribute("aria-expanded", String(!collapse));
    });
    event.currentTarget.textContent = collapse ? "Expandir grupos" : "Recolher grupos";
  });
  filterPermissions();
})();
