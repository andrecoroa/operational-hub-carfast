(() => {
  const documentWorkbench = document.querySelector(".visual-document-workbench");
  if (documentWorkbench) {
    const view = new URLSearchParams(location.search).get("view") || "queue";
    const documentViewKey = `carfast-document-scroll:${location.pathname}:${view}`;
    const savedDocumentScroll = JSON.parse(sessionStorage.getItem(documentViewKey) || "null");
    if (savedDocumentScroll && Date.now() - savedDocumentScroll.savedAt < 8 * 60 * 60 * 1000) {
      requestAnimationFrame(() => scrollTo(0, Number(savedDocumentScroll.scrollY) || 0));
    }
    document.querySelectorAll("[data-document-view-link]").forEach((link) => {
      link.addEventListener("click", () => sessionStorage.setItem(documentViewKey, JSON.stringify({ scrollY, savedAt: Date.now() })));
    });
  }
  const globalSearch = document.querySelector("[data-visual-global-search]");
  globalSearch?.addEventListener("submit", (event) => {
    event.preventDefault();
    const term = new FormData(globalSearch).get("q")?.toString().trim();
    if (!term) return;
    window.location.assign(`/v2-clean/tasks?q=${encodeURIComponent(term)}`);
  });

  const processFilter = document.querySelector("[data-process-filter-form]");
  processFilter?.addEventListener("submit", () => {
    const loading = document.querySelector("[data-process-loading]");
    processFilter.setAttribute("aria-busy", "true");
    if (loading) loading.hidden = false;
    processFilter.querySelectorAll("button").forEach((button) => { button.disabled = true; });
  });

  const menuButton = document.querySelector(".visual-menu-button");
  const sidebar = document.querySelector("#visual-sidebar");
  if (!menuButton || !sidebar) return;

  const closeNavigation = () => {
    document.body.classList.remove("visual-nav-open");
    menuButton.setAttribute("aria-expanded", "false");
    menuButton.focus();
  };

  const focusable = () => [...sidebar.querySelectorAll("a[href],button:not([disabled]),summary,[tabindex='0']")];

  menuButton.setAttribute("aria-expanded", "false");
  menuButton.addEventListener("click", () => {
    const open = !document.body.classList.contains("visual-nav-open");
    document.body.classList.toggle("visual-nav-open", open);
    menuButton.setAttribute("aria-expanded", String(open));
    if (open) sidebar.querySelector("a,button,summary")?.focus();
  });
  sidebar.addEventListener("click", (event) => {
    if (event.target.closest("a")) closeNavigation();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && document.body.classList.contains("visual-nav-open")) closeNavigation();
    if (event.key === "Tab" && document.body.classList.contains("visual-nav-open")) {
      const items = focusable();
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
  });
  document.addEventListener("click", (event) => {
    if (
      document.body.classList.contains("visual-nav-open") &&
      !sidebar.contains(event.target) &&
      !menuButton.contains(event.target)
    ) closeNavigation();
  });
})();
