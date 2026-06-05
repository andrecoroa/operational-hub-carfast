# ruff: noqa: E501
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(prefix="/workshop", tags=["workshop-ui"])


@router.get("/new-process", response_class=HTMLResponse)
def new_workshop_process_page() -> str:
    return """<!doctype html>
<html lang="pt">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Novo Processo Oficina por Fases</title>
  <style>
    :root {
      --bg: #f5f7f8;
      --panel: #ffffff;
      --line: #d9e0e5;
      --line-strong: #b9c5cc;
      --text: #07152d;
      --muted: #5c6c7b;
      --brand: #b24a34;
      --brand-soft: #fbf1ee;
      --green: #2f7d50;
      --green-soft: #edf7ef;
      --amber: #9a6711;
      --amber-soft: #fff6df;
      --blue: #2f5d8c;
      --blue-soft: #eef5fb;
      --danger: #b42318;
      font-family: Inter, "Segoe UI", Arial, sans-serif;
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      color: var(--text);
      background: var(--bg);
      font-size: 14px;
      letter-spacing: 0;
    }

    .app {
      display: grid;
      grid-template-columns: 248px minmax(0, 1fr);
      min-height: 100vh;
    }

    aside {
      background: #10202c;
      color: #d9e7ef;
      padding: 20px 14px;
      border-right: 1px solid #0b1720;
    }

    .brand {
      font-weight: 800;
      font-size: 18px;
      padding: 8px 10px 20px;
      color: #ffffff;
    }

    .nav-group { display: grid; gap: 4px; }

    .nav-item,
    .nav-sub {
      width: 100%;
      display: flex;
      align-items: center;
      gap: 10px;
      min-height: 36px;
      padding: 8px 10px;
      border-radius: 8px;
      color: #d9e7ef;
      text-decoration: none;
      font-weight: 650;
    }

    .nav-item.active {
      background: #203441;
      color: #ffffff;
    }

    .nav-sub {
      margin-left: 18px;
      width: calc(100% - 18px);
      font-size: 13px;
      color: #b6cad5;
    }

    .nav-sub.active {
      background: #f4ebe7;
      color: #7d2f1f;
    }

    main {
      padding: 22px 28px 84px;
    }

    .topbar {
      display: flex;
      justify-content: space-between;
      align-items: start;
      gap: 18px;
      margin-bottom: 18px;
    }

    .top-actions {
      display: flex;
      flex-wrap: wrap;
      justify-content: flex-end;
      gap: 8px;
    }

    .top-link {
      display: inline-flex;
      align-items: center;
      min-height: 36px;
      padding: 8px 11px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #ffffff;
      color: var(--text);
      font-weight: 800;
      text-decoration: none;
    }

    h1 {
      margin: 0 0 4px;
      font-size: 25px;
      line-height: 1.2;
    }

    .subtitle {
      color: var(--muted);
      margin: 0;
    }

    .layout {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 360px;
      gap: 18px;
      align-items: start;
    }

    .stack { display: grid; gap: 14px; }

    section,
    .preview,
    .result {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }

    section {
      padding: 18px;
    }

    .section-title {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      margin-bottom: 14px;
    }

    h2 {
      margin: 0;
      font-size: 17px;
      line-height: 1.25;
    }

    .required {
      color: var(--danger);
      font-weight: 800;
    }

    .grid-2 {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }

    .grid-3 {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }

    label {
      display: grid;
      gap: 6px;
      color: var(--muted);
      font-weight: 650;
    }

    .vehicle-card {
      margin-top: 12px;
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfcfd;
    }

    .vehicle-card div {
      display: grid;
      gap: 3px;
    }

    .vehicle-card span {
      color: var(--muted);
      font-size: 12px;
      font-weight: 750;
    }

    .vehicle-card strong {
      color: var(--text);
      font-size: 14px;
      line-height: 1.25;
    }

    .vehicle-card.empty {
      grid-template-columns: 1fr;
      color: var(--muted);
      font-weight: 700;
    }

    input,
    textarea,
    select {
      width: 100%;
      min-height: 38px;
      border: 1px solid var(--line-strong);
      border-radius: 8px;
      padding: 9px 10px;
      color: var(--text);
      background: #ffffff;
      font: inherit;
    }

    textarea {
      min-height: 86px;
      resize: vertical;
    }

    .segmented,
    .cards {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }

    .choice,
    .service-card {
      border: 1px solid var(--line);
      background: #ffffff;
      border-radius: 8px;
      padding: 9px 11px;
      cursor: pointer;
      user-select: none;
      font-weight: 750;
      color: var(--text);
    }

    .choice input,
    .service-card input {
      position: absolute;
      opacity: 0;
      pointer-events: none;
    }

    .choice:has(input:checked),
    .service-card:has(input:checked) {
      border-color: var(--brand);
      background: var(--brand-soft);
      color: #762d20;
      box-shadow: inset 4px 0 0 var(--brand);
    }

    .service-card {
      min-height: 46px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
    }

    .service-detail {
      margin-top: 10px;
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfcfd;
      display: none;
    }

    .service-detail.active { display: block; }

    .chip {
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      min-height: 28px;
      padding: 4px 10px;
      font-size: 12px;
      font-weight: 800;
      color: var(--muted);
      background: #eef1f3;
    }

    .chip.ok {
      color: var(--green);
      background: var(--green-soft);
    }

    .chip.warn {
      color: var(--amber);
      background: var(--amber-soft);
    }

    .preview {
      position: sticky;
      top: 18px;
      padding: 18px;
    }

    .phase-list {
      display: grid;
      gap: 8px;
      margin: 14px 0 0;
      padding: 0;
      list-style: none;
    }

    .phase-list li {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      padding: 10px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfcfd;
      font-weight: 700;
    }

    .checks {
      display: grid;
      gap: 8px;
      margin-top: 16px;
    }

    .check {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      color: var(--muted);
    }

    .actions {
      position: fixed;
      right: 0;
      bottom: 0;
      left: 248px;
      display: flex;
      justify-content: flex-end;
      gap: 10px;
      padding: 12px 28px;
      border-top: 1px solid var(--line);
      background: rgba(245, 247, 248, .94);
      backdrop-filter: blur(8px);
    }

    button {
      min-height: 40px;
      border: 1px solid var(--line-strong);
      border-radius: 8px;
      padding: 9px 14px;
      background: #ffffff;
      color: var(--text);
      font: inherit;
      font-weight: 800;
      cursor: pointer;
    }

    button.primary {
      background: var(--brand);
      border-color: var(--brand);
      color: #ffffff;
    }

    button:disabled {
      opacity: .55;
      cursor: not-allowed;
    }

    .result {
      margin-top: 14px;
      padding: 14px;
      display: none;
    }

    .result.active { display: block; }

    .result.success {
      border-color: #b7d7be;
      background: #f1faf3;
    }

    .result.error {
      border-color: #e2b7b3;
      background: #fff4f2;
    }

    .hint {
      font-size: 12px;
      color: var(--muted);
      line-height: 1.4;
    }

    @media (max-width: 980px) {
      .app { grid-template-columns: 1fr; }
      aside { display: none; }
      main { padding: 18px 16px 84px; }
      .layout { grid-template-columns: 1fr; }
      .preview { position: static; }
      .grid-2,
      .grid-3,
      .vehicle-card { grid-template-columns: 1fr; }
      .actions { left: 0; padding: 12px 16px; }
    }
  </style>
</head>
<body>
  <div class="app">
    <aside>
      <div class="brand">CarFast v2</div>
      <nav class="nav-group">
        <a class="nav-item" href="/">Início</a>
        <a class="nav-item" href="/fleet">Frota</a>
        <a class="nav-item active" href="/workshop">Oficina</a>
        <a class="nav-sub" href="/workshop/manage">Processos atuais</a>
        <a class="nav-sub" href="/workshop/processes-ui">Processos por fases</a>
        <a class="nav-sub active" href="/workshop/new-process">Novo processo por fases</a>
        <a class="nav-item" href="/task-board">Tarefas</a>
        <a class="nav-item" href="/documents">Documentos</a>
        <a class="nav-item" href="/task-board/manage?workspace=management">Gestão</a>
        <a class="nav-item" href="/admin">Administração</a>
      </nav>
    </aside>
    <main>
      <div class="topbar">
        <div>
          <h1>Novo processo por fases</h1>
          <p class="subtitle">Selecionar viatura da frota, serviços de entrada e fase inicial.</p>
        </div>
        <div class="top-actions">
          <a class="top-link" href="/workshop">Oficina</a>
          <a class="top-link" href="/workshop/manage">Processos atuais</a>
          <a class="top-link" href="/workshop/processes-ui">Processos por fases</a>
          <a class="top-link" href="/fleet">Frota</a>
        </div>
      </div>

      <div class="layout">
        <form id="processForm" class="stack">
          <section>
            <div class="section-title">
              <h2>Tipo de criação</h2>
              <span class="chip ok">Obrigatório</span>
            </div>
            <div id="creationModes" class="segmented"></div>
          </section>

          <section>
            <div class="section-title">
              <h2>Viatura</h2>
              <span class="required">*</span>
            </div>
            <div class="grid-2">
              <label>Matrícula / Viatura
                <input id="plate" name="plate" list="vehicleOptions" placeholder="Pesquisar matrícula, Unit, VIN, marca ou modelo" autocomplete="off" required>
                <input id="vehicleId" name="vehicle_id" type="hidden">
                <datalist id="vehicleOptions"></datalist>
              </label>
              <label>Km atual
                <input id="kmCurrent" name="km_current" type="number" min="0" placeholder="Opcional">
              </label>
            </div>
            <div id="vehiclePreview" class="vehicle-card empty">Pesquisar e selecionar uma viatura da frota.</div>
          </section>

          <section>
            <div class="section-title">
              <h2>Serviços de entrada</h2>
              <span class="required">*</span>
            </div>
            <div id="serviceCards" class="grid-3"></div>
            <div id="serviceDetails"></div>
          </section>

          <section id="manualTitleSection" hidden>
            <div class="section-title">
              <h2>Serviço Outro</h2>
              <span class="required">*</span>
            </div>
            <div class="grid-2">
              <label>Título manual
                <input id="manualTitle" name="title_manual">
              </label>
              <label>Descrição
                <input id="otherDetail" data-service-detail="other" data-field="detail">
              </label>
            </div>
          </section>

          <section>
            <div class="section-title">
              <h2>Entrada</h2>
            </div>
            <div class="stack">
              <label>Origem da entrada
                <select id="origin" name="origin"></select>
              </label>
              <label id="originDetailWrap" hidden>Descrição da origem
                <input id="originDetail" name="origin_detail">
              </label>
            </div>
          </section>

          <section>
            <div class="section-title">
              <h2>Gestão</h2>
            </div>
            <div class="stack">
              <label>Prioridade
                <div id="priorities" class="segmented"></div>
              </label>
              <div class="grid-2">
                <label>Responsável
                  <input id="responsibleUserId" type="number" min="1" placeholder="ID utilizador, opcional">
                </label>
                <label id="scheduledAtWrap" hidden>Data/hora prevista
                  <input id="scheduledAt" type="datetime-local">
                </label>
              </div>
              <label>Observação inicial
                <textarea id="initialObservation" placeholder="Contexto curto da entrada"></textarea>
              </label>
            </div>
          </section>
        </form>

        <aside class="preview">
          <h2>Verificações</h2>
          <div id="checks" class="checks"></div>

          <h2 style="margin-top: 22px;">Fases geradas</h2>
          <ol id="phaseList" class="phase-list"></ol>

          <p class="hint" style="margin-top: 14px;">
            Ao criar, a app gera as fases padrão e abre a Receção Administrativa.
          </p>

          <div id="result" class="result"></div>
        </aside>
      </div>

      <div class="actions">
        <button type="button" id="cancelButton">Cancelar</button>
        <button type="submit" form="processForm" class="primary" id="submitButton">+ Criar processo</button>
      </div>
    </main>
  </div>

  <script>
    const state = {
      config: null,
      selectedMode: "immediate_entry",
      selectedPriority: "normal",
      vehicleResults: [],
      selectedVehicle: null,
      vehicleTimer: null,
    };

    const els = {
      form: document.querySelector("#processForm"),
      plate: document.querySelector("#plate"),
      vehicleId: document.querySelector("#vehicleId"),
      vehicleOptions: document.querySelector("#vehicleOptions"),
      vehiclePreview: document.querySelector("#vehiclePreview"),
      creationModes: document.querySelector("#creationModes"),
      serviceCards: document.querySelector("#serviceCards"),
      serviceDetails: document.querySelector("#serviceDetails"),
      manualTitleSection: document.querySelector("#manualTitleSection"),
      manualTitle: document.querySelector("#manualTitle"),
      origin: document.querySelector("#origin"),
      originDetailWrap: document.querySelector("#originDetailWrap"),
      originDetail: document.querySelector("#originDetail"),
      priorities: document.querySelector("#priorities"),
      scheduledAtWrap: document.querySelector("#scheduledAtWrap"),
      scheduledAt: document.querySelector("#scheduledAt"),
      checks: document.querySelector("#checks"),
      phaseList: document.querySelector("#phaseList"),
      result: document.querySelector("#result"),
      submitButton: document.querySelector("#submitButton"),
      cancelButton: document.querySelector("#cancelButton"),
    };

    function radioCard(name, value, label, checked) {
      return `<label class="choice"><input type="radio" name="${name}" value="${value}" ${checked ? "checked" : ""}>${label}</label>`;
    }

    function vehicleLabel(vehicle) {
      return [vehicle.plate, vehicle.rentway_unit_nr ? `Unit ${vehicle.rentway_unit_nr}` : "", [vehicle.brand, vehicle.model, vehicle.version].filter(Boolean).join(" ")].filter(Boolean).join(" · ");
    }

    function renderVehiclePreview(vehicle) {
      if (!vehicle) {
        els.vehiclePreview.className = "vehicle-card empty";
        els.vehiclePreview.textContent = els.plate.value.trim() ? "Seleciona uma viatura da lista para importar dados da frota." : "Pesquisar e selecionar uma viatura da frota.";
        return;
      }
      els.vehiclePreview.className = "vehicle-card";
      els.vehiclePreview.innerHTML = [
        ["Matrícula", vehicle.plate],
        ["Marca / modelo", [vehicle.brand, vehicle.model, vehicle.version].filter(Boolean).join(" ")],
        ["Unit Rentway", vehicle.rentway_unit_nr],
        ["VIN", vehicle.vin],
        ["Estado operacional", vehicle.operational_status],
        ["Estado frota", vehicle.lifecycle_status],
      ].map(([label, value]) => `<div><span>${label}</span><strong>${value || "-"}</strong></div>`).join("");
    }

    function selectVehicle(vehicle) {
      state.selectedVehicle = vehicle || null;
      els.vehicleId.value = vehicle?.id || "";
      if (vehicle?.plate) els.plate.value = vehicle.plate;
      renderVehiclePreview(vehicle);
      updateUiState();
    }

    function syncSelectedVehicleFromInput() {
      const value = els.plate.value.trim().toUpperCase();
      const vehicle = state.vehicleResults.find((item) => item.plate === value || vehicleLabel(item).toUpperCase() === value);
      selectVehicle(vehicle || null);
    }

    async function searchVehicles() {
      const query = els.plate.value.trim();
      els.vehicleId.value = "";
      state.selectedVehicle = null;
      renderVehiclePreview(null);
      if (query.length < 2) {
        state.vehicleResults = [];
        els.vehicleOptions.innerHTML = "";
        updateUiState();
        return;
      }
      const response = await fetch(`/task-board/vehicle-search?q=${encodeURIComponent(query)}&context=workshop`);
      if (!response.ok) return;
      const data = await response.json();
      state.vehicleResults = data.items || [];
      els.vehicleOptions.innerHTML = state.vehicleResults.map((vehicle) => `<option value="${vehicle.plate}" label="${vehicleLabel(vehicle)}"></option>`).join("");
      syncSelectedVehicleFromInput();
    }

    function renderConfig(config) {
      state.config = config;
      els.creationModes.innerHTML = config.creation_modes
        .map((mode) => radioCard("creation_mode", mode.code, mode.label, mode.code === state.selectedMode))
        .join("");

      els.priorities.innerHTML = config.priorities
        .map((priority) => radioCard("priority", priority.code, priority.label, priority.code === state.selectedPriority))
        .join("");

      els.origin.innerHTML = `<option value="">Selecionar origem</option>` + config.entry_origins
        .map((origin) => `<option value="${origin.code}">${origin.label}</option>`)
        .join("");

      els.serviceCards.innerHTML = config.services.map((service) => `
        <label class="service-card">
          <span>${service.label}</span>
          <input type="checkbox" name="service" value="${service.code}">
        </label>
      `).join("");

      els.serviceDetails.innerHTML = config.services.map((service) => `
        <div class="service-detail" data-detail-panel="${service.code}">
          <div class="section-title">
            <h2>${service.label}</h2>
            <span class="chip">Detalhe</span>
          </div>
          <div class="grid-3">
            <label>Detalhe
              <input data-service-detail="${service.code}" data-field="detail">
            </label>
            <label>Eixo / zona
              <input data-service-detail="${service.code}" data-field="zone">
            </label>
            <label>Observação curta
              <input data-service-detail="${service.code}" data-field="short_observation">
            </label>
          </div>
        </div>
      `).join("");

      els.phaseList.innerHTML = config.phases.map((phase) => `
        <li><span>${phase.sort_order}. ${phase.name}</span><span class="chip">Auto</span></li>
      `).join("");

      bindDynamicEvents();
      updateUiState();
    }

    function bindDynamicEvents() {
      document.querySelectorAll("input[name='creation_mode']").forEach((input) => {
        input.addEventListener("change", () => {
          state.selectedMode = input.value;
          updateUiState();
        });
      });

      document.querySelectorAll("input[name='priority']").forEach((input) => {
        input.addEventListener("change", () => {
          state.selectedPriority = input.value;
          updateUiState();
        });
      });

      document.querySelectorAll("input[name='service']").forEach((input) => {
        input.addEventListener("change", updateUiState);
      });
      els.plate.addEventListener("input", () => {
        clearTimeout(state.vehicleTimer);
        state.vehicleTimer = setTimeout(searchVehicles, 160);
        updateUiState();
      });
      els.plate.addEventListener("change", syncSelectedVehicleFromInput);
      els.origin.addEventListener("change", updateUiState);
      ["manualTitle", "otherDetail", "originDetail", "scheduledAt"].forEach((id) => {
        document.querySelector(`#${id}`).addEventListener("input", updateUiState);
      });
    }

    function selectedServices() {
      return [...document.querySelectorAll("input[name='service']:checked")].map((input) => input.value);
    }

    function updateUiState() {
      const services = selectedServices();
      document.querySelectorAll("[data-detail-panel]").forEach((panel) => {
        panel.classList.toggle("active", services.includes(panel.dataset.detailPanel) && panel.dataset.detailPanel !== "other");
      });

      const hasOtherService = services.includes("other");
      els.manualTitleSection.hidden = !hasOtherService;
      els.manualTitle.required = hasOtherService;
      document.querySelector("#otherDetail").required = hasOtherService;

      const originIsOther = els.origin.value === "other";
      els.originDetailWrap.hidden = !originIsOther;
      els.originDetail.required = originIsOther;

      const isAppointment = state.selectedMode === "appointment";
      els.scheduledAtWrap.hidden = !isAppointment;
      els.scheduledAt.required = isAppointment;

      renderChecks();
    }

    function renderChecks() {
      const services = selectedServices();
      const checks = [
        ["Viatura selecionada da frota", Boolean(els.vehicleId.value), true],
        ["Serviços selecionados", services.length > 0, true],
        ["Título manual obrigatório", !services.includes("other") || Boolean(els.manualTitle.value.trim()), services.includes("other")],
        ["Descrição do Outro", !services.includes("other") || Boolean(document.querySelector("#otherDetail").value.trim()), services.includes("other")],
        ["Descrição da origem", els.origin.value !== "other" || Boolean(els.originDetail.value.trim()), els.origin.value === "other"],
        ["Data/hora prevista", state.selectedMode !== "appointment" || Boolean(els.scheduledAt.value), state.selectedMode === "appointment"],
        ["Km atual", Boolean(document.querySelector("#kmCurrent").value), false],
        ["Observação inicial", Boolean(document.querySelector("#initialObservation").value.trim()), false],
      ];

      els.checks.innerHTML = checks.map(([label, ok, required]) => `
        <div class="check">
          <span>${label}</span>
          <span class="chip ${ok ? "ok" : required ? "warn" : ""}">${ok ? "OK" : required ? "Pendente" : "Opcional"}</span>
        </div>
      `).join("");
    }

    function servicePayload(code) {
      return {
        service_code: code,
        detail: document.querySelector(`[data-service-detail="${code}"][data-field="detail"]`)?.value || null,
        zone: document.querySelector(`[data-service-detail="${code}"][data-field="zone"]`)?.value || null,
        short_observation: document.querySelector(`[data-service-detail="${code}"][data-field="short_observation"]`)?.value || null,
      };
    }

    async function submitProcess(event) {
      event.preventDefault();
      if (!els.vehicleId.value) {
        els.result.className = "result error active";
        els.result.textContent = "Seleciona uma viatura da frota antes de criar o processo.";
        els.plate.focus();
        return;
      }
      els.submitButton.disabled = true;
      els.result.className = "result";
      els.result.textContent = "";

      const services = selectedServices().map(servicePayload);
      const payload = {
        vehicle_id: els.vehicleId.value ? Number(els.vehicleId.value) : null,
        plate: document.querySelector("#plate").value.trim(),
        creation_mode: state.selectedMode,
        services,
        title_manual: els.manualTitle.value.trim() || null,
        km_current: document.querySelector("#kmCurrent").value ? Number(document.querySelector("#kmCurrent").value) : null,
        origin: els.origin.value || null,
        origin_detail: els.originDetail.value.trim() || null,
        priority: state.selectedPriority,
        responsible_user_id: document.querySelector("#responsibleUserId").value ? Number(document.querySelector("#responsibleUserId").value) : null,
        initial_observation: document.querySelector("#initialObservation").value.trim() || null,
        scheduled_at: els.scheduledAt.value ? new Date(els.scheduledAt.value).toISOString() : null,
      };

      try {
        const response = await fetch("/api/workshop/processes/phased", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const data = await response.json();
        if (!response.ok) {
          throw new Error(data.detail ? JSON.stringify(data.detail) : "Erro ao criar processo.");
        }
        els.result.className = "result success active";
        els.result.innerHTML = `<strong>Processo criado:</strong><br>${data.title}<br><span class="hint">Estado: ${data.status}. Fase atual: ${data.current_phase_code}.</span><br><br><a href="/workshop/processes-ui/${data.id}/manage">Abrir processo</a>`;
      } catch (error) {
        els.result.className = "result error active";
        els.result.textContent = error.message;
      } finally {
        els.submitButton.disabled = false;
      }
    }

    els.form.addEventListener("submit", submitProcess);
    els.cancelButton.addEventListener("click", () => { window.location.href = "/workshop"; });

    fetch("/api/workshop/process-config")
      .then((response) => response.json())
      .then(renderConfig)
      .catch((error) => {
        els.result.className = "result error active";
        els.result.textContent = `Não foi possível carregar configuração: ${error.message}`;
      });
  </script>
</body>
</html>"""


@router.get("/processes-ui/{process_id}", response_class=HTMLResponse)
def workshop_process_detail_page(process_id: int) -> str:
    return f"""<!doctype html>
<html lang="pt">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Processo Oficina #{process_id}</title>
  <style>
    :root {{
      --bg: #f5f7f8;
      --panel: #ffffff;
      --line: #d9e0e5;
      --line-strong: #b9c5cc;
      --text: #07152d;
      --muted: #5c6c7b;
      --brand: #b24a34;
      --brand-soft: #fbf1ee;
      --green: #2f7d50;
      --green-soft: #edf7ef;
      --amber: #9a6711;
      --amber-soft: #fff6df;
      --red: #b42318;
      --red-soft: #fff4f2;
      font-family: Inter, "Segoe UI", Arial, sans-serif;
    }}

    * {{ box-sizing: border-box; }}
    body {{ margin: 0; color: var(--text); background: var(--bg); font-size: 14px; letter-spacing: 0; }}
    .app {{ display: grid; grid-template-columns: 248px minmax(0, 1fr); min-height: 100vh; }}
    aside {{ background: #10202c; color: #d9e7ef; padding: 20px 14px; border-right: 1px solid #0b1720; }}
    .brand {{ font-weight: 800; font-size: 18px; padding: 8px 10px 20px; color: #ffffff; }}
    .nav-group {{ display: grid; gap: 4px; }}
    .nav-item, .nav-sub {{ width: 100%; display: flex; align-items: center; gap: 10px; min-height: 36px; padding: 8px 10px; border-radius: 8px; color: #d9e7ef; text-decoration: none; font-weight: 650; }}
    .nav-item.active {{ background: #203441; color: #ffffff; }}
    .nav-sub {{ margin-left: 18px; width: calc(100% - 18px); font-size: 13px; color: #b6cad5; }}
    .nav-sub.active {{ background: #f4ebe7; color: #7d2f1f; }}
    main {{ padding: 22px 28px 42px; }}
    .topbar {{ display: flex; justify-content: space-between; align-items: start; gap: 18px; margin-bottom: 18px; }}
    .top-actions {{ display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }}
    .button {{ display: inline-flex; align-items: center; min-height: 38px; border: 1px solid var(--line-strong); border-radius: 8px; padding: 8px 12px; background: #fff; color: var(--text); font-weight: 800; text-decoration: none; }}
    .button.primary {{ background: var(--brand); border-color: var(--brand); color: #fff; }}
    h1 {{ margin: 0 0 4px; font-size: 25px; line-height: 1.2; }}
    h2 {{ margin: 0; font-size: 17px; line-height: 1.25; }}
    .subtitle {{ color: var(--muted); margin: 0; }}
    .layout {{ display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 18px; align-items: start; }}
    .stack {{ display: grid; gap: 14px; }}
    section, .panel {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 18px; }}
    .section-title {{ display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 14px; }}
    .chip {{ display: inline-flex; align-items: center; border-radius: 999px; min-height: 28px; padding: 4px 10px; font-size: 12px; font-weight: 800; color: var(--muted); background: #eef1f3; }}
    .chip.ok, .chip.done {{ color: var(--green); background: var(--green-soft); }}
    .chip.progress {{ color: #1d5f94; background: #eaf3fb; }}
    .chip.warn, .chip.review {{ color: var(--amber); background: var(--amber-soft); }}
    .chip.neutral {{ color: var(--muted); background: #eef1f3; }}
    .chip.danger {{ color: var(--red); background: var(--red-soft); }}
    .grid-3 {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }}
    .metric {{ border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: #fbfcfd; }}
    .metric span {{ display: block; color: var(--muted); font-size: 12px; font-weight: 750; margin-bottom: 5px; }}
    .metric strong {{ font-size: 16px; }}
    .phase-list, .plain-list {{ display: grid; gap: 8px; margin: 0; padding: 0; list-style: none; }}
    .phase-list li, .plain-list li {{ display: flex; justify-content: space-between; gap: 12px; align-items: center; padding: 10px; border: 1px solid var(--line); border-radius: 8px; background: #fbfcfd; font-weight: 700; }}
    .phase-list li.active {{ border-color: var(--brand); background: var(--brand-soft); box-shadow: inset 4px 0 0 var(--brand); }}
    .muted {{ color: var(--muted); }}
    .actions {{ display: flex; gap: 10px; margin-top: 14px; flex-wrap: wrap; }}
    a.button {{ min-height: 40px; border: 1px solid var(--line-strong); border-radius: 8px; padding: 9px 14px; background: #ffffff; color: var(--text); font-weight: 800; text-decoration: none; }}
    a.button.primary {{ background: var(--brand); border-color: var(--brand); color: #ffffff; }}
    .loading {{ padding: 22px; color: var(--muted); }}
    @media (max-width: 980px) {{
      .app {{ grid-template-columns: 1fr; }}
      aside {{ display: none; }}
      main {{ padding: 18px 16px; }}
      .layout, .grid-3 {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="app">
    <aside>
      <div class="brand">CarFast v2</div>
      <nav class="nav-group">
        <a class="nav-item" href="/">Início</a>
        <a class="nav-item" href="/fleet">Frota</a>
        <a class="nav-item active" href="/workshop">Oficina</a>
        <a class="nav-sub" href="/workshop/manage">Processos atuais</a>
        <a class="nav-sub active" href="/workshop/processes-ui">Processos por fases</a>
        <a class="nav-sub" href="/workshop/new-process">Novo processo por fases</a>
        <a class="nav-item" href="/task-board">Tarefas</a>
        <a class="nav-item" href="/documents">Documentos</a>
        <a class="nav-item" href="/task-board/manage?workspace=management">Gestão</a>
        <a class="nav-item" href="/admin">Administração</a>
      </nav>
    </aside>
    <main>
      <div id="app" class="loading">A carregar processo...</div>
    </main>
  </div>

  <script>
    const processId = {process_id};
    const root = document.querySelector("#app");

    const STATUS = {{
      completed:["Concluído","done"], completed_with_pending_items:["Concluído com pendências","review"], validated:["Validado","done"],
      in_progress:["Em curso","progress"], pending_review:["Por rever","review"], reception_pending:["Receção pendente","review"],
      pending_definition:["Por definir","review"], pending:["Pendente","review"], open:["Aberto","review"], not_started:["Não iniciado","neutral"],
      not_applicable:["Não aplicável","neutral"], unable_to_read:["Falha na leitura","danger"], critical:["Crítica","danger"]
    }};
    const PHASES = {{
      process_creation:"Criação do processo", administrative_reception:"Receção administrativa", history_check:"Verificações",
      technical_phase:"Fase técnica", diagnosis_decision:"Diagnóstico e decisão", budget_approval:"Orçamento / aprovação",
      internal_repair_execution:"Reparação interna / execução", final_closure:"Fecho definitivo"
    }};
    const VALUES = {{normal:"Normal", high:"Alta", urgent:"Urgente", reception:"Receção", appointment:"Marcação", station:"Estação", customer_driver:"Cliente / condutor", rentway_alert:"Alerta Rentway", internal_preparation:"Preparação interna", other:"Outro"}};
    function safe(value) {{
      return String(value ?? "-").replace(/[&<>"']/g, c => c === "&" ? "&amp;" : c === "<" ? "&lt;" : c === ">" ? "&gt;" : c === '"' ? "&quot;" : "&#39;");
    }}
    function label(value) {{ return VALUES[value] || value || "-"; }}
    function statusMeta(status) {{ return STATUS[status] || [status || "-", "neutral"]; }}
    function chip(status) {{ const meta = statusMeta(status); return `<span class="chip ${{meta[1]}}">${{safe(meta[0])}}</span>`; }}

    function render(process) {{
      const activePhase = process.current_phase_code;
      const v = process.vehicle || {{}};
      const status = statusMeta(process.status);
      const model = [v.brand, v.model, v.version].filter(Boolean).join(" ");
      const alerts = Array.from(new Map(process.alerts.map(a => [`${{a.code}}:${{a.message}}`, a])).values());
      root.className = "";
      root.innerHTML = `
        <div class="topbar">
          <div>
            <h1>${{safe(process.services_label || process.title)}}</h1>
            <p class="subtitle">${{safe(v.plate || process.plate || "-")}} · ${{safe(model || "Dados da viatura por completar")}} · ${{safe(status[0])}}</p>
          </div>
          <div class="top-actions">
            <a class="button" href="/workshop">Oficina</a>
            <a class="button" href="/workshop/manage">Processos atuais</a>
            <a class="button" href="/fleet">Frota</a>
            <a class="button primary" href="/workshop/processes-ui/${{process.id}}/manage">Operar</a>
          </div>
        </div>
        <div class="grid-3" style="margin-bottom: 14px;">
          <div class="metric"><span>Matrícula</span><strong>${{safe(v.plate || process.plate)}}</strong></div>
          <div class="metric"><span>Marca / modelo</span><strong>${{safe(model)}}</strong></div>
          <div class="metric"><span>Unit Rentway</span><strong>${{safe(v.rentway_unit_nr)}}</strong></div>
          <div class="metric"><span>VIN</span><strong>${{safe(v.vin)}}</strong></div>
          <div class="metric"><span>Prioridade</span><strong>${{safe(label(process.priority))}}</strong></div>
          <div class="metric"><span>Fase atual</span><strong>${{safe(PHASES[activePhase] || activePhase)}}</strong></div>
        </div>
        <div class="layout">
          <div class="stack">
            <section>
              <div class="section-title"><h2>Fases</h2><span class="chip">${{process.phases.length}}</span></div>
              <ol class="phase-list">
                ${{process.phases.map((phase) => `
                  <li class="${{phase.phase_code === activePhase ? "active" : ""}}">
                    <span>${{phase.sort_order}}. ${{safe(PHASES[phase.phase_code] || phase.name)}}</span>
                    ${{chip(phase.status)}}
                  </li>
                `).join("")}}
              </ol>
            </section>
            <section>
              <div class="section-title"><h2>Serviços de entrada</h2><span class="chip">${{process.services.length}}</span></div>
              <ul class="plain-list">
                ${{process.services.map((service) => `
                  <li><span>${{service.service_label}}</span><span class="muted">${{service.zone || service.detail || ""}}</span></li>
                `).join("") || "<li>Sem serviços</li>"}}
              </ul>
            </section>
            <section>
              <div class="section-title"><h2>Relatórios e verificações</h2></div>
              <div class="grid-3">
                <div class="metric"><span>Relatórios técnicos</span><strong>${{process.technical_reports.length}}</strong></div>
                <div class="metric"><span>Verificações técnicas</span><strong>${{process.technical_checks.length}}</strong></div>
                <div class="metric"><span>Incidentes</span><strong>${{process.technical_incidents.length}}</strong></div>
              </div>
            </section>
          </div>
          <div class="panel">
            <div class="section-title"><h2>Alertas</h2><span class="chip warn">${{alerts.length}}</span></div>
            <ul class="plain-list">
              ${{alerts.map((alert) => `
                <li><span>${{safe(alert.message)}}</span>${{chip(alert.status || alert.severity)}}</li>
              `).join("") || "<li>Sem alertas</li>"}}
            </ul>
            <div class="actions">
              <a class="button primary" href="/workshop/new-process">+ Novo processo</a>
            </div>
          </div>
        </div>
      `;
    }}

    fetch(`/api/workshop/processes/${{processId}}`)
      .then((response) => {{
        if (!response.ok) throw new Error("Processo não encontrado");
        return response.json();
      }})
      .then(render)
      .catch((error) => {{
        root.className = "panel";
        root.textContent = error.message;
      }});
  </script>
</body>
</html>"""


@router.get("/processes-ui", response_class=HTMLResponse)
def workshop_process_list_page() -> str:
    return """<!doctype html>
<html lang="pt">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Oficina - Processos por Fases</title>
  <style>
    :root { --bg:#f5f7f8; --panel:#fff; --line:#d9e0e5; --line2:#b9c5cc; --text:#07152d; --muted:#5c6c7b; --brand:#b24a34; --brand-soft:#fbf1ee; --green:#2f7d50; --green-soft:#edf7ef; --blue:#1d5f94; --blue-soft:#eaf3fb; --amber:#9a6711; --amber-soft:#fff6df; --red:#b42318; --red-soft:#fff4f2; font-family:Inter,"Segoe UI",Arial,sans-serif; }
    *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--text);font-size:14px;letter-spacing:0}.app{display:block;min-height:100vh}aside{display:none}.brand{font-weight:800;font-size:18px;padding:8px 10px 20px;color:#fff}.nav{display:grid;gap:4px}.nav a{min-height:36px;padding:8px 10px;border-radius:8px;color:#d9e7ef;text-decoration:none;font-weight:650}.nav .sub{margin-left:18px;color:#b6cad5}.nav .active{background:#f4ebe7;color:#7d2f1f}main{padding:14px 16px 34px}h1{margin:0 0 4px;font-size:24px}.subtitle{margin:0;color:var(--muted)}.topbar{display:flex;justify-content:space-between;gap:16px;align-items:start;margin-bottom:14px}.top-actions{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:8px}.button{display:inline-flex;align-items:center;justify-content:center;min-height:36px;border-radius:8px;padding:8px 13px;background:var(--brand);color:#fff;text-decoration:none;font-weight:800;border:1px solid var(--brand)}.button.secondary{background:#fff;color:var(--text);border-color:var(--line)}.board{background:#fff;border:1px solid var(--line);border-radius:8px;padding:12px 14px}.kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-bottom:12px}.kpi{border:1px solid var(--line);border-radius:8px;background:#fbfcfd;padding:10px}.kpi span{display:block;color:var(--muted);font-size:12px;font-weight:850}.kpi strong{display:block;margin-top:5px;font-size:24px;line-height:1}.filters{display:grid;grid-template-columns:minmax(260px,1fr) 210px 190px 190px auto;gap:8px;align-items:center;margin-bottom:14px}.filters input,.filters select{width:100%;min-height:38px;border:1px solid var(--line2);border-radius:8px;background:#fff;color:var(--text);font:inherit;font-weight:700;padding:8px 10px}.updated{justify-self:end;color:var(--muted);font-size:12px;font-weight:800}.table-head,.process-row{display:grid;grid-template-columns:70px minmax(250px,1.2fr) minmax(220px,1fr) minmax(230px,1fr) 160px 130px 150px 150px;gap:12px;align-items:center}.table-head{padding:10px;color:#46576a;font-size:12px;font-weight:900;text-transform:uppercase}.rows{display:grid;gap:8px}.process-row{min-height:72px;border:1px solid var(--line);border-radius:8px;background:#fff;padding:9px 10px}.vehicle-cell{display:grid;grid-template-columns:88px minmax(0,1fr);gap:12px;align-items:center}.vehicle-thumb{display:grid;place-items:center;width:88px;height:54px;border:1px solid var(--line);border-radius:8px;background:#f4f7f8;color:var(--muted);font-size:11px;font-weight:900}.plate{font-size:16px;font-weight:950}.small{font-size:12px;color:var(--muted);line-height:1.35}.service{font-weight:850}.phase-cell{display:grid;gap:8px}.phase-name{font-weight:850}.status-cell{display:grid;justify-items:start;gap:5px}.open-count{color:var(--amber);font-size:11px;font-weight:900}.progress{display:grid;grid-template-columns:repeat(8,1fr);gap:4px}.step{height:7px;border-radius:999px;background:#e7ebef}.step.done{background:#7fbd8c}.step.current{background:#2b6cb0}.chip{display:inline-flex;align-items:center;justify-content:center;width:max-content;max-width:100%;border-radius:999px;min-height:26px;padding:4px 10px;background:#eef1f3;color:var(--muted);font-size:12px;font-weight:850}.chip.done{color:var(--green);background:var(--green-soft)}.chip.progress{color:var(--blue);background:var(--blue-soft)}.chip.review{color:var(--amber);background:var(--amber-soft)}.chip.danger{color:var(--red);background:var(--red-soft)}.chip.neutral{color:var(--muted);background:#eef1f3}.priority-dot{display:inline-flex;align-items:center;gap:8px;color:var(--muted);font-weight:800}.priority-dot::before{content:"";width:8px;height:8px;border-radius:50%;background:#2f63c6}.empty{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:24px;color:var(--muted)}@media(max-width:1180px){.table-head{display:none}.process-row{grid-template-columns:1fr}.vehicle-cell{grid-template-columns:74px 1fr}.filters,.kpis{grid-template-columns:1fr 1fr}.updated{justify-self:start}}@media(max-width:900px){main{padding:18px 16px}.topbar{display:grid}.filters,.kpis{grid-template-columns:1fr}.process-row .button{width:100%}}
  </style>
</head>
<body>
  <div class="app">
    <aside><div class="brand">CarFast v2</div><nav class="nav"><a href="/">Início</a><a href="/fleet">Frota</a><a href="/workshop">Oficina</a><a class="sub" href="/workshop/manage">Processos atuais</a><a class="sub active" href="/workshop/processes-ui">Processos por fases</a><a class="sub" href="/workshop/new-process">Novo processo por fases</a><a href="/task-board">Tarefas</a><a href="/documents">Documentos</a></nav></aside>
    <main>
      <div class="topbar"><div><h1>Oficina - Processos por fases</h1><p class="subtitle">Acompanhar processos criados no novo modelo por blocos.</p></div><div class="top-actions"><a class="button secondary" href="/">Menu principal</a><a class="button secondary" href="/workshop">Oficina</a><a class="button secondary" href="/workshop/manage">Processos atuais</a><a class="button secondary" href="/fleet">Frota</a><a class="button" href="/workshop/new-process">+ Novo processo por fases</a></div></div>
      <section class="board">
        <div class="kpis">
          <div class="kpi"><span>Total processos</span><strong id="kpiTotal">0</strong></div>
          <div class="kpi"><span>Em falta / abertos</span><strong id="kpiOpen">0</strong></div>
          <div class="kpi"><span>Em curso</span><strong id="kpiProgress">0</strong></div>
          <div class="kpi"><span>Fechados</span><strong id="kpiClosed">0</strong></div>
        </div>
        <div class="filters">
          <input id="search" placeholder="Pesquisar por matrícula, título, Unit ou VIN...">
          <select id="statusFilter"><option value="">Estado: Todos</option></select>
          <select id="phaseFilter"><option value="">Fase: Todas</option></select>
          <select id="priorityFilter"><option value="">Prioridade: Todas</option><option value="normal">Normal</option><option value="high">Alta</option><option value="urgent">Urgente</option></select>
          <span id="updated" class="updated">A carregar...</span>
        </div>
        <div class="table-head"><span>ID</span><span>Viatura</span><span>Serviços</span><span>Fase atual</span><span>Estado</span><span>Prioridade</span><span>Atualizado</span><span>Ação</span></div>
        <div id="rows" class="rows"><div class="empty">A carregar processos...</div></div>
      </section>
    </main>
  </div>
  <script>
    const rows = document.querySelector("#rows");
    const state = { items: [] };
    const STATUS = {
      completed:["Concluído","done"], completed_with_pending_items:["Concluído com pendências","review"], validated:["Validado","done"],
      in_progress:["Em curso","progress"], pending_review:["Por rever","review"], reception_pending:["Receção pendente","review"],
      scheduled:["Marcado","progress"], pending:["Pendente","review"], pending_definition:["Por definir","review"], not_started:["Não iniciado","neutral"], open:["Aberto","review"], cancelled:["Cancelado","danger"]
    };
    const PHASES = {
      process_creation:"Criação do processo", administrative_reception:"Receção administrativa", history_check:"Verificações",
      technical_phase:"Fase técnica", diagnosis_decision:"Diagnóstico e decisão", budget_approval:"Orçamento / aprovação",
      internal_repair_execution:"Reparação interna / execução", final_closure:"Fecho definitivo"
    };
    const PRIORITY = {low:"Baixa", normal:"Normal", high:"Alta", urgent:"Urgente"};
    function meta(map, code) { return map[code] || [code || "-", "neutral"]; }
    function displayStatusCode(p) {
      if (p.closed_at || ["completed","completed_with_pending_items","cancelled"].includes(p.status)) return p.status;
      if ((p.open_alerts_count || 0) > 0) return "open";
      return p.status || "open";
    }
    function safe(value) {
      return String(value ?? "-").replace(/[&<>"']/g, c => c === "&" ? "&amp;" : c === "<" ? "&lt;" : c === ">" ? "&gt;" : c === '"' ? "&quot;" : "&#39;");
    }
    function vehicleName(v) { return [v?.brand, v?.model, v?.version].filter(Boolean).join(" ") || "Dados da viatura por completar"; }
    function unitLine(v) { return [v?.rentway_unit_nr ? `Unit ${v.rentway_unit_nr}` : null, v?.vin ? `VIN ${v.vin}` : null].filter(Boolean).join(" · ") || "Sem Unit/VIN registado"; }
    function dateLabel(value) {
      if (!value) return "-";
      const date = new Date(value);
      const today = new Date();
      const sameDay = date.toDateString() === today.toDateString();
      const yesterday = new Date(today); yesterday.setDate(today.getDate() - 1);
      const prefix = sameDay ? "Hoje" : (date.toDateString() === yesterday.toDateString() ? "Ontem" : date.toLocaleDateString("pt-PT"));
      return `${prefix}, ${date.toLocaleTimeString("pt-PT", {hour:"2-digit", minute:"2-digit"})}`;
    }
    function phaseProgress(p) {
      const phases = p.phases || [];
      return `<div class="progress">${phases.map((phase) => {
        const cls = phase.phase_code === p.current_phase_code ? "current" : (["completed","validated","completed_with_pending_items"].includes(phase.status) ? "done" : "");
        return `<span class="step ${cls}" title="${safe(PHASES[phase.phase_code] || phase.name)}"></span>`;
      }).join("")}</div>`;
    }
    function card(p) {
      const v = p.vehicle || {};
      const statusCode = displayStatusCode(p);
      const status = meta(STATUS, statusCode);
      const phase = PHASES[p.current_phase_code] || p.current_phase_code || "-";
      const service = p.services_label || p.title || "Processo oficina";
      return `<article class="process-row">
        <strong>#${p.id}</strong>
        <div class="vehicle-cell"><div class="vehicle-thumb">Frota</div><div><div class="plate">${safe(v.plate || p.plate)}</div><div class="small">${safe(vehicleName(v))}</div><div class="small">${safe(unitLine(v))}</div></div></div>
        <div class="service">${safe(service)}</div>
        <div class="phase-cell"><span class="phase-name">${safe(phase)}</span>${phaseProgress(p)}</div>
        <div class="status-cell"><span class="chip ${status[1]}">${safe(status[0])}</span>${(p.open_alerts_count || 0) > 0 ? `<span class="open-count">${p.open_alerts_count} em falta</span>` : ""}</div>
        <span class="priority-dot">${safe(PRIORITY[p.priority] || p.priority || "-")}</span>
        <span class="small">${safe(dateLabel(p.updated_at || p.created_at))}</span>
        <a class="button secondary" href="/workshop/processes-ui/${p.id}/manage">Abrir processo</a>
      </article>`;
    }
    function matches(p) {
      const query = document.querySelector("#search").value.trim().toLowerCase();
      const status = document.querySelector("#statusFilter").value;
      const phase = document.querySelector("#phaseFilter").value;
      const priority = document.querySelector("#priorityFilter").value;
      const v = p.vehicle || {};
      const haystack = [p.id, p.title, p.services_label, p.plate, v.plate, v.rentway_unit_nr, v.vin, v.brand, v.model, v.version].join(" ").toLowerCase();
      return (!query || haystack.includes(query)) && (!status || displayStatusCode(p) === status) && (!phase || p.current_phase_code === phase) && (!priority || p.priority === priority);
    }
    function render() {
      const items = state.items;
      document.querySelector("#kpiTotal").textContent = items.length;
      document.querySelector("#kpiOpen").textContent = items.filter(p => displayStatusCode(p) === "open").length;
      document.querySelector("#kpiProgress").textContent = items.filter(p => ["in_progress","scheduled"].includes(p.status) || (p.current_phase_code && !p.closed_at)).length;
      document.querySelector("#kpiClosed").textContent = items.filter(p => p.closed_at || ["completed","completed_with_pending_items"].includes(p.status)).length;
      const filtered = items.filter(matches);
      rows.innerHTML = filtered.map(card).join("") || `<div class="empty">Sem processos para os filtros atuais.</div>`;
      document.querySelector("#updated").textContent = `Atualizado ${new Date().toLocaleTimeString("pt-PT", {hour:"2-digit", minute:"2-digit"})}`;
    }
    function fillFilters(items) {
      const statuses = ["open", ...new Set(items.map(displayStatusCode).filter(Boolean).filter(code => code !== "open"))];
      document.querySelector("#statusFilter").innerHTML = `<option value="">Estado: Todos</option>` + statuses.map(code => `<option value="${code}">${safe(meta(STATUS, code)[0])}</option>`).join("");
      document.querySelector("#statusFilter").value = "open";
      document.querySelector("#phaseFilter").innerHTML = `<option value="">Fase: Todas</option>` + Object.entries(PHASES).map(([code,label]) => `<option value="${code}">${label}</option>`).join("");
      ["search","statusFilter","phaseFilter","priorityFilter"].forEach(id => document.querySelector(`#${id}`).addEventListener("input", render));
    }
    fetch("/api/workshop/processes").then(r => r.json()).then((items) => {
      state.items = items;
      fillFilters(items);
      render();
    }).catch((e) => { rows.innerHTML = `<div class="empty">${e.message}</div>`; });
  </script>
</body>
</html>"""


@router.get("/processes-ui/{process_id}/manage", response_class=HTMLResponse)
def workshop_process_manage_page(process_id: int) -> str:
    return workshop_process_manage_v3_page(process_id)
    return f"""<!doctype html>
<html lang="pt">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Operar Processo Oficina #{process_id}</title>
  <style>
    :root{{--bg:#f5f7f8;--panel:#fff;--line:#d9e0e5;--line2:#b9c5cc;--text:#07152d;--muted:#5c6c7b;--brand:#b24a34;--soft:#fbf1ee;--green:#2f7d50;--green-soft:#edf7ef;--amber:#9a6711;--amber-soft:#fff6df;--red:#b42318;--red-soft:#fff4f2;font-family:Inter,"Segoe UI",Arial,sans-serif}}
    *{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font-size:14px;letter-spacing:0}}.app{{display:block;min-height:100vh}}aside{{display:none}}main{{padding:18px 22px 44px}}h1{{margin:0 0 4px;font-size:24px}}h2{{margin:0;font-size:20px}}h3{{margin:0 0 10px;font-size:15px}}.subtitle,.muted{{color:var(--muted)}}.topbar{{display:flex;justify-content:space-between;gap:16px;align-items:center;margin:-18px -22px 18px;padding:22px;border-bottom:1px solid var(--line);background:#fff}}.top-actions{{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:8px}}.process-heading{{display:grid;grid-template-columns:auto minmax(0,1fr);gap:14px;align-items:center}}.process-titleline{{display:flex;align-items:center;gap:12px;flex-wrap:wrap}}.process-meta{{display:flex;align-items:center;gap:10px;flex-wrap:wrap;color:var(--muted);font-weight:700}}.back-button{{display:inline-grid;place-items:center;width:34px;height:34px;min-height:34px;padding:0;border:0;border-radius:8px;background:transparent;color:var(--text);font-size:28px;font-weight:700;text-decoration:none}}.back-button:hover{{background:var(--soft);color:#7d2f1f}}.vehicle-strip{{display:none}}.vehicle-thumb{{display:grid;place-items:center;min-height:104px;border:1px solid var(--line);border-radius:8px;background:#f4f7f8;color:var(--muted);font-size:13px;font-weight:900;text-align:center}}.vehicle-main{{display:grid;align-content:center;gap:10px}}.vehicle-main strong{{font-size:22px}}.vehicle-facts{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}}.vehicle-facts div,.vehicle-state{{display:grid;gap:4px;border:1px solid var(--line);border-radius:8px;background:#fbfcfd;padding:10px}}.vehicle-state{{align-content:center}}.vehicle-facts span,.vehicle-state span,.memory span{{color:var(--muted);font-size:12px;font-weight:750}}.vehicle-facts strong,.vehicle-state strong,.memory strong{{font-size:14px}}.layout{{display:grid;grid-template-columns:minmax(0,1fr) 360px;gap:22px;align-items:start}}.stack{{display:grid;gap:12px}}section,.panel{{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:16px}}.panel.sticky{{position:sticky;top:14px}}.section-title{{display:flex;justify-content:space-between;gap:12px;align-items:center;margin-bottom:14px}}.summary-block{{display:grid;gap:10px;margin-top:18px;padding-top:18px;border-top:1px solid var(--line)}}.summary-block:first-child{{margin-top:0;padding-top:0;border-top:0}}.summary-title{{display:flex;justify-content:space-between;align-items:center;gap:10px}}.summary-title h3{{margin:0}}.summary-kpis{{display:grid;grid-template-columns:1fr;gap:8px}}.summary-kpis div{{display:grid;gap:4px;border:1px solid var(--line);border-radius:8px;background:#fbfcfd;padding:10px}}.summary-kpis span{{color:var(--muted);font-size:11px;font-weight:850}}.summary-kpis strong{{font-size:20px;line-height:1}}.grid2{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}}.grid3{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}}.document-card-grid{{display:grid;grid-template-columns:repeat(2,minmax(260px,1fr));gap:14px;margin-top:16px}}.document-card{{display:grid;gap:14px;align-content:start;min-height:220px;border:1px solid var(--line);border-radius:8px;background:#fff;padding:18px}}.document-card-header{{display:flex;justify-content:space-between;align-items:start;gap:12px}}.document-title{{display:flex;align-items:center;gap:10px;font-size:18px;font-weight:950}}.doc-icon{{display:inline-grid;place-items:center;width:28px;height:28px;color:var(--text);font-size:20px}}.document-card p{{margin:0;color:var(--muted);line-height:1.45}}.document-card .info-note{{border:1px solid transparent;border-radius:8px;background:#f7f8f9;padding:10px;color:var(--muted);font-weight:750}}.document-card .plan-compare{{display:grid;gap:6px;border:1px solid var(--line);border-radius:8px;background:#fbfcfd;padding:10px}}.plan-compare div{{display:flex;justify-content:space-between;gap:12px}}.plan-compare strong{{color:#c94f3d}}.document-actions{{display:flex;gap:8px;flex-wrap:wrap;margin-top:auto}}.document-actions .button,.document-actions button{{flex:1 1 160px}}.document-controls{{display:grid;gap:8px}}.document-controls.link-required input{{display:block}}.document-controls:not(.link-required) input{{display:none}}.verification-advanced{{margin-top:14px;border:1px solid var(--line);border-radius:8px;background:#fbfcfd;padding:12px}}.verification-advanced summary{{cursor:pointer;font-weight:900}}.report-type-grid{{display:grid;grid-template-columns:repeat(5,minmax(150px,1fr));gap:10px;margin:12px 0 10px}}.report-type-card{{display:grid;gap:5px;min-height:78px;text-align:left;border:1px solid var(--line);border-radius:8px;background:#fbfcfd;padding:10px;cursor:pointer}}.report-type-card.active{{border-color:var(--brand);background:var(--soft);box-shadow:inset 4px 0 0 var(--brand)}}.report-type-card strong{{font-size:14px}}.report-type-card span{{color:var(--muted);font-size:12px;font-weight:800}}.report-instance-list{{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 14px}}.report-instance-list button{{display:inline-flex;align-items:center;gap:8px;min-height:34px;border-radius:999px;padding:6px 10px;font-size:12px}}.report-instance-list button.active{{border-color:var(--brand);background:var(--soft);color:#7d2f1f}}.report-layout{{display:grid;grid-template-columns:1fr;gap:14px;align-items:start}}.report-workspace{{display:grid;gap:12px}}.report-controls{{border:1px solid var(--line);border-radius:8px;background:#fbfcfd;padding:12px}}.report-original-row{{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px;align-items:end}}.report-field-table{{display:grid;grid-template-columns:1fr;gap:0;border:1px solid var(--line);border-radius:8px;overflow:hidden;background:#fff}}.report-field-table label{{display:grid;grid-template-columns:minmax(180px,.9fr) minmax(180px,1fr) 38px;gap:10px;align-items:center;min-height:58px;padding:9px 10px;border-top:1px solid var(--line);color:var(--text)}}.report-field-table label:first-child{{border-top:0}}.report-field-table input{{min-height:36px}}.report-field-table .field-info{{display:inline-grid;place-items:center;width:24px;height:24px;border-radius:50%;border:1px solid var(--line2);background:#fff;color:var(--muted);font-size:12px;font-weight:900;line-height:1;cursor:pointer}}.report-json{{border:1px solid var(--line);border-radius:8px;background:#fbfcfd;padding:10px}}.report-json summary{{cursor:pointer;font-weight:850;color:var(--muted)}}.validation-panel{{display:grid;gap:10px;border:1px solid var(--line);border-radius:8px;background:#fff;padding:12px}}label{{display:grid;gap:6px;color:var(--muted);font-weight:650}}input,textarea,select{{width:100%;min-height:38px;border:1px solid var(--line2);border-radius:8px;padding:9px 10px;color:var(--text);background:#fff;font:inherit}}textarea{{min-height:76px;resize:vertical}}button,.button{{min-height:38px;border:1px solid var(--line2);border-radius:8px;padding:8px 12px;background:#fff;color:var(--text);font:inherit;font-weight:800;cursor:pointer;text-decoration:none}}button.primary,.button.primary{{background:var(--brand);border-color:var(--brand);color:#fff}}.button.secondary{{background:#fff;color:var(--text);border-color:var(--line2)}}.button.ghost{{border-color:transparent;background:transparent}}.chip{{display:inline-flex;align-items:center;width:max-content;max-width:100%;border-radius:999px;min-height:26px;padding:4px 10px;background:#eef1f3;color:var(--muted);font-size:12px;font-weight:800}}.chip.ok,.chip.done{{color:var(--green);background:var(--green-soft)}}.chip.progress{{color:#1d5f94;background:#eaf3fb}}.chip.warn,.chip.review{{color:var(--amber);background:var(--amber-soft)}}.chip.neutral{{color:var(--muted);background:#eef1f3}}.chip.danger{{color:var(--red);background:var(--red-soft)}}.phase-list,.plain-list{{display:grid;gap:8px;margin:0;padding:0;list-style:none}}.plain-list li{{display:flex;justify-content:space-between;gap:12px;align-items:center;padding:12px;border:1px solid var(--line);border-radius:8px;background:#fbfcfd;font-weight:700}}.tabs{{display:grid;grid-template-columns:repeat(8,minmax(96px,1fr));gap:0;margin-bottom:20px;border:1px solid var(--line);border-radius:8px;overflow:hidden;background:#fff}}.tab{{position:relative;display:grid;grid-template-columns:1fr auto;gap:4px 8px;align-items:center;min-width:0;border:0;border-left:1px solid var(--line);border-radius:0;background:#fff;padding:12px 14px;font-size:14px;font-weight:900;cursor:pointer;text-align:center}}.tab:first-child{{border-left:0}}.tab-title{{font-size:16px}}.tab-state{{display:none}}.tab-alert{{display:inline-flex;align-items:center;gap:4px;min-width:26px;height:22px;border-radius:999px;background:var(--amber-soft);color:var(--amber);font-size:12px;font-weight:950;padding:0 7px}}.tab-alert::before{{content:"";width:0;height:0;border-left:5px solid transparent;border-right:5px solid transparent;border-bottom:9px solid var(--amber)}}.tab.active{{background:var(--soft);box-shadow:inset 0 0 0 1px var(--brand);color:#7d2f1f}}.tab.complete{{background:#fbfffc}}.tab.incomplete{{background:#fffaf1}}.tab.incomplete.active{{background:#fff4e3;color:#7d4a09}}.form-section{{display:none}}.form-section.active{{display:block}}.memory{{display:none;margin:12px 0;padding:12px;border:1px solid #dce6dd;background:#f7fbf7;border-radius:8px}}.memory.active{{display:block}}.memory-grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}}.result{{display:none;margin-top:10px;border-radius:8px;padding:10px;border:1px solid var(--line)}}.result.active{{display:block}}.result.ok{{background:var(--green-soft);border-color:#b7d7be}}.result.err{{background:var(--red-soft);border-color:#e2b7b3}}@media(max-width:1280px){{.layout{{grid-template-columns:1fr}}.panel.sticky{{position:static}}.report-type-grid{{grid-template-columns:repeat(3,minmax(0,1fr))}}.tabs{{grid-template-columns:repeat(4,minmax(120px,1fr))}}}}@media(max-width:980px){{main{{padding:18px 16px}}.topbar{{display:grid;margin:-18px -16px 18px;padding:16px}}.process-heading{{grid-template-columns:1fr}}.layout,.vehicle-strip,.vehicle-facts,.grid2,.grid3,.memory-grid,.report-original-row,.report-field-table label,.document-card-grid{{grid-template-columns:1fr}}.report-type-grid{{grid-template-columns:1fr 1fr}}.tabs{{grid-template-columns:1fr 1fr}}}}
  </style>
</head>
<body>
  <div class="app">
    <aside><div class="brand">CarFast v2</div><nav class="nav"><a href="/">Início</a><a href="/fleet">Frota</a><a href="/workshop">Oficina</a><a class="sub" href="/workshop/manage">Processos atuais</a><a class="sub active" href="/workshop/processes-ui">Processos por fases</a><a class="sub" href="/workshop/new-process">Novo processo por fases</a><a href="/task-board">Tarefas</a><a href="/documents">Documentos</a></nav></aside>
    <main>
      <div id="header" class="topbar"><div class="process-heading"><a class="back-button" href="/workshop/processes-ui">Voltar</a><div><h1>Processo Oficina</h1><p class="subtitle">A carregar...</p></div></div><div class="top-actions"><a class="button secondary" href="/workshop">Oficina</a><a class="button secondary" href="/workshop/manage">Processos atuais</a><a class="button secondary" href="/fleet">Frota</a><a class="button" href="/workshop/processes-ui">Lista por fases</a></div></div>
      <div class="layout">
        <div class="stack">
          <div id="vehicleStrip" class="vehicle-strip"></div>
          <section>
            <div id="phaseTabs" class="tabs"></div>
            <div id="reception" class="form-section active">
              <h2>Receção Administrativa</h2>
              <div id="receptionMemory" class="memory"></div>
              <div class="grid2"><label>KM entrada<input id="recKm" type="number" min="0"></label><label>Foto quadrante inicial<input id="recPhoto" placeholder="https://..."></label></div>
              <label>Observação inicial<textarea id="recObs"></textarea></label>
              <div class="grid2"><label>Estado visual<select id="recVisual"><option value="">Selecionar</option><option>Sem danos aparentes</option><option>Com danos ligeiros</option><option>Com danos relevantes</option><option>Não verificado</option></select></label><label>Descrição danos<input id="recDamage"></label></div>
              <button id="receptionButton" class="primary" onclick="confirmReception()">Confirmar receção</button>
            </div>
            <div id="services" class="form-section">
              <h2>Serviços a executar</h2>
              <p class="muted">Adicionar trabalhos que surjam depois da criação do processo.</p>
              <ul id="serviceList" class="plain-list" style="margin:12px 0 16px"></ul>
              <div class="grid3"><label>Serviço<select id="serviceCode"></select></label><label id="serviceZoneLabel">Zona / sistema<input id="serviceZone" placeholder="Motor, travagem, pneus..."></label><label id="serviceDetailLabel">Detalhe<input id="serviceDetail" placeholder="Descrição do trabalho"></label></div>
              <label id="serviceObservationLabel">Observação curta<textarea id="serviceObservation" placeholder="Motivo, evidência, indicação do técnico..."></textarea></label>
              <p id="serviceFormHint" class="muted" style="margin:8px 0 0"></p>
              <button class="primary" onclick="addService()">Adicionar serviço</button>
            </div>
            <div id="history" class="form-section">
              <h2>Documentos esperados</h2>
              <p class="muted">Anexe e valide os documentos necessários para esta fase.</p>
              <div id="historyMemory" class="memory"></div>
              <div class="document-card-grid">
                <article class="document-card" data-doc-card="service_box">
                  <div class="document-card-header"><div class="document-title"><span class="doc-icon">▣</span><span>Service Box</span></div><span id="histServiceBoxChip" class="chip review">Em falta</span></div>
                  <p>Comprovativo da consulta do Service Box da viatura.</p>
                  <div class="info-note">Obrigatório para viaturas Stellantis.</div>
                  <div class="document-controls" id="histServiceBoxControls">
                    <label>Estado<select id="histServiceBox"><option value="pending_review">Por rever</option><option value="no">Não</option><option value="not_applicable">Não aplicável</option><option value="evidence_link">Link para print</option></select></label>
                    <label>Print Service Box<input id="histServiceBoxLink" placeholder="https://..."></label>
                  </div>
                  <div class="document-actions"><button type="button" class="primary" onclick="markVerificationEvidence('#histServiceBox')">Anexar print</button><a id="histServiceBoxOpen" class="button secondary" href="#" target="_blank" rel="noopener">Abrir documento</a></div>
                </article>
                <article class="document-card" data-doc-card="campaigns">
                  <div class="document-card-header"><div class="document-title"><span class="doc-icon">◁</span><span>Campanhas</span></div><span id="histCampaignsChip" class="chip review">Por validar</span></div>
                  <p>Comprovativo da verificação de campanhas em aberto.</p>
                  <div class="document-controls" id="histCampaignsControls">
                    <label>Estado<select id="histCampaigns"><option value="pending_review">Por rever</option><option value="no">Não</option><option value="not_applicable">Não aplicável</option><option value="evidence_link">Link para print</option></select></label>
                    <label>Print campanhas<input id="histCampaignsLink" placeholder="https://..."></label>
                  </div>
                  <div class="document-actions"><button type="button" class="primary" onclick="confirmHistory()">Validar</button><a id="histCampaignsOpen" class="button secondary" href="#" target="_blank" rel="noopener">Abrir documento</a></div>
                </article>
                <article class="document-card" data-doc-card="maintenance_plan">
                  <div class="document-card-header"><div class="document-title"><span class="doc-icon">⌕</span><span>Plano manutenção</span></div><span id="histMaintenancePlanChip" class="chip review">Por rever</span></div>
                  <p>Plano da marca vs. plano parametrizado no Rentway.</p>
                  <div class="plan-compare" id="maintenancePlanCompare">
                    <div><span>Service Box</span><strong>Por validar</strong></div>
                    <div><span>Rentway</span><strong>Por validar</strong></div>
                  </div>
                  <div id="maintenancePlanAlert" class="info-note">Valide o relatório de plano para confirmar se existe divergência.</div>
                  <div class="document-controls" id="histMaintenancePlanControls">
                    <label>Estado<select id="histMaintenancePlan"><option value="pending_review">Por rever</option><option value="no">Não</option><option value="not_applicable">Não aplicável</option><option value="evidence_link">Link para print</option></select></label>
                    <label>Print plano manutenção<input id="histMaintenancePlanLink" placeholder="https://..."></label>
                  </div>
                  <div class="document-actions"><button type="button" class="primary" onclick="markVerificationEvidence('#histMaintenancePlan')">Anexar plano</button><a id="histMaintenancePlanOpen" class="button secondary" href="#" target="_blank" rel="noopener">Abrir documento</a></div>
                </article>
                <article class="document-card" data-doc-card="internal_history">
                  <div class="document-card-header"><div class="document-title"><span class="doc-icon">◷</span><span>Histórico interno</span></div><span id="histInternalChip" class="chip review">Por rever</span></div>
                  <p>Relatório do histórico interno da viatura e intervenções relevantes.</p>
                  <div class="document-controls">
                    <label>Consulta histórico interno<select id="histInternal"><option value="yes">Sim</option><option value="no">Não</option><option value="pending_review">Por rever</option></select></label>
                  </div>
                  <div class="document-actions"><button type="button" class="primary" onclick="confirmHistory()">Validar</button></div>
                </article>
              </div>
              <details class="verification-advanced">
                <summary>Outras verificações</summary>
                <div class="grid2" style="margin-top:12px"><label>Accident reports<select id="histAccidents"><option value="no">Não</option><option value="yes">Sim</option><option value="pending_review">Por rever</option></select></label><label>Processos anteriores<select id="histPrev"><option value="yes">Sim</option><option value="none">Não existem</option><option value="pending_review">Por rever</option></select></label></div>
                <label>Detalhe accident reports<input id="histAccidentsDetail"></label>
                <div class="grid2"><label>Incidência repetida<select id="histRepeat"><option value="no">Não</option><option value="yes">Sim</option><option value="pending_review">Por avaliar</option></select></label><label>Observação verificações<textarea id="histObs"></textarea></label></div>
              </details>
              <div style="display:flex;justify-content:flex-end;margin-top:14px"><button id="historyButton" class="primary" onclick="confirmHistory()">Confirmar verificações</button></div>
            </div>
            <div id="reports" class="form-section">
              <div class="section-title"><h2>Relatórios Técnicos</h2><span id="reportTabCount" class="chip">0</span></div>
              <div id="reportTypeCards" class="report-type-grid"></div>
              <div id="reportInstanceList" class="report-instance-list"></div>
              <div id="selectedReportDetail" class="memory"></div>
              <div class="report-layout">
                <div class="report-workspace">
                  <div class="report-controls">
                    <div class="grid3"><label>Relatório<select id="reportCode"></select></label><label>Momento<select id="reportMoment"><option value="initial">Inicial</option><option value="final">Final</option></select></label><label>Origem<select id="reportOrigin"><option value="stellantis_machine">Máquina Stellantis</option><option value="autel">Autel</option><option value="other">Outro</option></select></label></div>
                    <div class="report-original-row"><label>Link relatório original<input id="reportLink" placeholder="https://..."></label><a id="reportPreviewOpen" class="button secondary" href="#" target="_blank" rel="noopener">Abrir original</a></div>
                    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:10px"><button id="reportSaveButton" class="primary" onclick="saveReportDraft()">Adicionar relatório</button><button type="button" onclick="newReportDraft()">Novo relatório</button></div>
                    <p id="reportHint" class="muted" style="margin:10px 0 0"></p>
                    <div id="reportExtractionGuide" style="display:none"></div>
                  </div>
                  <div class="section-title" style="margin:0"><div><h3>Valores extraídos</h3><p class="muted" style="margin:4px 0 0">Rever e ajustar conforme o relatório original.</p></div></div>
                  <div id="reportFieldGrid" class="report-field-table"></div>
                  <details class="report-json"><summary>JSON extraído</summary><label style="margin-top:10px">Valores extraídos JSON<textarea id="reportValues" placeholder='{{"campo":"valor"}}'></textarea></label></details>
                  <div class="validation-panel">
                    <div class="section-title" style="margin:0"><div><h3>Validar relatório</h3><p class="muted" style="margin:4px 0 0">Valida os valores extraídos revistos sem criar outro relatório.</p></div><button class="primary" onclick="validateReport()">Validar como revisto</button></div>
                    <div class="grid2"><label>ID relatório<input id="validateReportId" type="number" readonly></label><label>Valores validados JSON<textarea id="validateValues" placeholder='{{"campo":"valor"}}'></textarea></label></div>
                  </div>
                </div>
              </div>
            </div>
            <div id="checks" class="form-section">
              <h2>Verificações Técnicas</h2>
              <div class="grid3"><label>Verificação<select id="checkCode"></select></label><label>Estado<select id="checkStatus"><option value="ok">OK</option><option value="not_ok">Não OK</option><option value="not_applicable">Não aplicável</option><option value="pending_review">Por rever</option></select></label><label>Evidência<input id="checkEvidence" placeholder="https://..."></label></div>
              <label>Observação<textarea id="checkObs"></textarea></label>
              <div class="grid2"><label><input id="checkTask" type="checkbox"> Gerar tarefa</label><label><input id="checkCharge" type="checkbox"> Potencial cobrança ao cliente</label></div>
              <label>Título da tarefa<input id="checkTaskTitle" placeholder="Avaliar cobrança..."></label>
              <button class="primary" onclick="saveCheck()">Guardar verificação</button>
              <h3 style="margin-top:16px">Incidente técnico</h3>
              <div class="grid3"><label>Tipo<input id="incidentType" placeholder="valor_fora_esperado"></label><label>Gravidade<select id="incidentSeverity"><option value="low">Baixa</option><option value="medium">Média</option><option value="high">Alta</option><option value="critical">Crítica</option></select></label><label>Pode circular?<select id="incidentCirculate"><option value="yes">Sim</option><option value="no">Não</option><option value="restricted">Com restrições</option><option value="pending">Por avaliar</option></select></label></div>
              <label>Descrição incidente<textarea id="incidentDescription"></textarea></label><button onclick="createIncident()">Registar incidente</button>
            </div>
            <div id="decision" class="form-section">
              <h2>Diagnóstico e Decisão</h2>
              <div id="decisionMemory" class="memory"></div>
              <div class="grid3"><label>Diagnóstico principal<input id="decisionDiagnosis"></label><label>Tipo intervenção<select id="decisionType"><option value="maintenance">Manutenção</option><option value="fault">Avaria</option><option value="warranty">Garantia</option><option value="damage">Dano / sinistro</option><option value="sale_preparation">Preparação venda</option><option value="none">Sem intervenção</option><option value="other">Outro</option></select></label><label>Sistema afetado<input id="decisionSystem" placeholder="Motor, pneus, travagem..."></label></div>
              <div class="grid3"><label>Gravidade<select id="decisionSeverity"><option value="low">Baixa</option><option value="medium">Média</option><option value="high">Alta</option><option value="critical">Crítica</option></select></label><label>Pode circular?<select id="decisionCirculate"><option value="yes">Sim</option><option value="no">Não</option><option value="restricted">Com restrições</option><option value="pending">Por avaliar</option></select></label><label>Próxima ação<select id="decisionNext"><option value="internal_repair">Reparar internamente</option><option value="request_budget">Pedir orçamento</option><option value="send_supplier">Enviar fornecedor</option><option value="wait_parts">Aguardar peça</option><option value="wait_decision">Aguardar decisão</option><option value="immobilize">Imobilizar viatura</option><option value="return_fleet">Pode voltar à frota</option><option value="close_no_intervention">Fechar sem intervenção</option></select></label></div>
              <label>Causa provável<input id="decisionCause"></label><label>Observação diagnóstico<textarea id="decisionObs"></textarea></label>
              <div class="grid3"><label><input id="decisionNeedsRepair" type="checkbox"> Necessita reparação</label><label><input id="decisionNeedsBudget" type="checkbox"> Necessita orçamento</label><label><input id="decisionNeedsApproval" type="checkbox"> Necessita aprovação</label></div>
              <div class="grid2"><label><input id="decisionCharge" type="checkbox"> Potencial cobrança cliente</label><label><input id="decisionWarranty" type="checkbox"> Garantia</label></div>
              <div class="grid3"><label>Motivo cobrança<input id="decisionChargeReason"></label><label>Contrato / cliente<input id="decisionContract"></label><label>Evidência cobrança<input id="decisionChargeEvidence" placeholder="https://..."></label></div>
              <div class="grid2"><label><input id="decisionCreateTask" type="checkbox"> Criar tarefa próxima ação</label><label>Responsável próxima ação<input id="decisionResponsible" type="number"></label></div>
              <button id="decisionButton" class="primary" onclick="saveDecision()">Confirmar decisão</button>
            </div>
            <div id="budget" class="form-section">
              <h2>Orçamento / Aprovação</h2>
              <div id="budgetMemory" class="memory"></div>
              <p class="muted">Aplicável sobretudo a reparação externa.</p>
              <div class="grid3"><label>Fornecedor / oficina<input id="budgetSupplier"></label><label>Valor estimado<input id="budgetValue" type="number" step="0.01"></label><label>Estado aprovação<select id="budgetApproval"><option value="pending">Pendente</option><option value="approved">Aprovado</option><option value="rejected">Rejeitado</option><option value="not_required">Não necessita</option></select></label></div>
              <label>Descrição do pedido<textarea id="budgetDescription"></textarea></label>
              <div class="grid2"><label>Link orçamento<input id="budgetLink" placeholder="https://..."></label><label>Resultado<select id="budgetResult"><option value="">Selecionar</option><option value="approved_for_execution">Aprovado para execução</option><option value="rejected">Rejeitado</option><option value="wait_new_budget">Aguardar novo orçamento</option><option value="wait_decision">Aguardar decisão</option></select></label></div>
              <div class="grid2"><label><input id="budgetReceived" type="checkbox"> Orçamento recebido</label><label><input id="budgetNeedsApproval" type="checkbox" checked> Necessita aprovação</label></div>
              <label>Observação orçamento<textarea id="budgetObs"></textarea></label>
              <button id="budgetButton" class="primary" onclick="saveBudget()">Guardar orçamento</button>
            </div>
            <div id="repair" class="form-section">
              <h2>Reparação Interna / Execução</h2>
              <div id="repairMemory" class="memory"></div>
              <div class="grid2"><label>Tipo execução<input id="repairType"></label><label>Resultado<select id="repairResult"><option value="resolved">Resolvido</option><option value="partially_resolved">Parcialmente resolvido</option><option value="not_resolved">Não resolvido</option><option value="waiting_parts">Aguardar peça</option><option value="external_repair">Enviar externa</option><option value="no_intervention_needed">Sem intervenção</option></select></label></div>
              <label>Descrição intervenção<textarea id="repairDescription"></textarea></label>
              <div class="grid2"><label>Foto quadrante final<input id="repairFinalPhoto" placeholder="https://..."></label><label>KM final visível<input id="repairFinalKm" type="number"></label></div>
              <button id="repairButton" class="primary" onclick="saveRepair()">Guardar reparação</button>
            </div>
            <div id="close" class="form-section">
              <h2>Fecho Definitivo</h2>
              <div id="closeMemory" class="memory"></div>
              <div class="grid3"><label>Resultado final<select id="closeResult"><option>Concluído</option><option>Concluído com pendências</option><option>Fechado sem intervenção</option><option>Cancelado</option></select></label><label>Viatura pronta?<select id="closeReady"><option>Sim</option><option>Não</option><option>Com restrições</option></select></label><label>Novo estado<select id="closeStatus"><option value="free">Livre</option><option value="in_contract">Em contrato</option><option value="in_preparation">Em preparação</option><option value="blocked">Bloqueada</option><option value="in_maintenance">Em manutenção</option><option value="for_sale">Em venda</option><option value="immobilized">Imobilizada</option></select></label></div>
              <label>Observação final<textarea id="closeObs"></textarea></label><label><input id="closePending" type="checkbox"> Fechar com pendências</label><label>Justificação pendências<input id="closePendingJustification"></label>
              <button id="closeButton" class="primary" onclick="closeProcess()">Fechar processo</button>
            </div>
            <div id="result" class="result"></div>
          </section>
        </div>
        <div class="panel sticky"><div class="section-title"><h2>Processo</h2><span id="statusChip" class="chip">-</span></div><div id="documentFolder"></div><div id="summary"></div></div>
      </div>
    </main>
  </div>
  <script>
    const processId = {process_id}; let processData = null; let config = null; let selectedReportType = null; let selectedReportId = null; const result = document.querySelector("#result");
    function payloadValue(id) {{ return document.querySelector(id).value || null; }}
    function jsonValue(id) {{ const v = payloadValue(id); if (!v) return null; try {{ return JSON.parse(v); }} catch {{ throw new Error(`JSON inválido em ${{id}}`); }} }}
    function previewableReportUrl(value) {{
      const url = (value || "").trim();
      if (!url) return null;
      if (url.startsWith("/") || url.startsWith("http://") || url.startsWith("https://")) return url;
      return null;
    }}
    function updateReportPreview() {{
      const url = previewableReportUrl(payloadValue("#reportLink"));
      const open = document.querySelector("#reportPreviewOpen");
      if (!open) return;
      if (!url) {{
        open.removeAttribute("href");
        open.classList.add("secondary");
        return;
      }}
      open.href = url;
    }}
    function updateVerificationLink(inputId, openId) {{
      const url = previewableReportUrl(payloadValue(inputId));
      const open = document.querySelector(openId);
      if (!open) return;
      if (!url) {{
        open.removeAttribute("href");
        return;
      }}
      open.href = url;
    }}
    function updateVerificationLinks() {{
      updateVerificationLink("#histServiceBoxLink", "#histServiceBoxOpen");
      updateVerificationLink("#histCampaignsLink", "#histCampaignsOpen");
      updateVerificationLink("#histMaintenancePlanLink", "#histMaintenancePlanOpen");
      renderVerificationCards();
    }}
    function setChip(id, text, tone) {{
      const el = document.querySelector(id);
      if (!el) return;
      el.textContent = text;
      el.className = `chip ${{tone || "neutral"}}`;
    }}
    function verificationStatus(value, link, defaultLabel = "Em falta") {{
      if (value === "not_applicable") return ["Não aplicável", "neutral"];
      if (value === "no" || value === "yes") return ["Validado", "done"];
      if (value === "evidence_link" && previewableReportUrl(link)) return ["Por validar", "review"];
      if (value === "evidence_link") return [defaultLabel, "danger"];
      return [defaultLabel, "review"];
    }}
    function updateDocumentControl(selectId, controlsId) {{
      const controls = document.querySelector(controlsId);
      if (!controls) return;
      controls.classList.toggle("link-required", payloadValue(selectId) === "evidence_link");
    }}
    function latestMaintenancePlanReport() {{
      const reports = (processData?.technical_reports || []).filter(report => report.report_code === "maintenance_plan_validation");
      return reports.sort((a,b) => (b.id || 0) - (a.id || 0))[0] || null;
    }}
    function reportValues(report) {{
      return objectValues(report?.validated_values || report?.extracted_values);
    }}
    function renderMaintenancePlanCompare() {{
      const report = latestMaintenancePlanReport();
      const values = reportValues(report);
      const serviceBox = [values.servicebox_plan, values.servicebox_interval_km ? `${{values.servicebox_interval_km}} km` : "", values.servicebox_interval_months ? `${{values.servicebox_interval_months}} meses` : ""].filter(Boolean).join(" / ") || "Por validar";
      const rentway = [values.rentway_plan, values.rentway_interval_km ? `${{values.rentway_interval_km}} km` : "", values.rentway_interval_months ? `${{values.rentway_interval_months}} meses` : ""].filter(Boolean).join(" / ") || "Por validar";
      const compare = document.querySelector("#maintenancePlanCompare");
      if (compare) compare.innerHTML = `<div><span>Service Box</span><strong>${{safe(serviceBox)}}</strong></div><div><span>Rentway</span><strong>${{safe(rentway)}}</strong></div>`;
      const mismatch = (processData?.alerts || []).some(alert => ["rentway_maintenance_plan_mismatch","maintenance_request_plan_mismatch"].includes(alert.code));
      const note = document.querySelector("#maintenancePlanAlert");
      if (note) note.textContent = mismatch ? "Existe divergência entre os planos." : (report ? "Plano registado. Validar se a parametrização coincide." : "Valide o relatório de plano para confirmar se existe divergência.");
      return mismatch;
    }}
    function renderVerificationCards() {{
      if (!document.querySelector("#history")) return;
      updateDocumentControl("#histServiceBox", "#histServiceBoxControls");
      updateDocumentControl("#histCampaigns", "#histCampaignsControls");
      updateDocumentControl("#histMaintenancePlan", "#histMaintenancePlanControls");
      const serviceBox = verificationStatus(payloadValue("#histServiceBox"), payloadValue("#histServiceBoxLink"), "Em falta");
      const campaigns = verificationStatus(payloadValue("#histCampaigns"), payloadValue("#histCampaignsLink"), "Em falta");
      const plan = verificationStatus(payloadValue("#histMaintenancePlan"), payloadValue("#histMaintenancePlanLink"), "Em falta");
      const internal = verificationStatus(payloadValue("#histInternal"), "", "Por rever");
      const mismatch = renderMaintenancePlanCompare();
      setChip("#histServiceBoxChip", serviceBox[0], serviceBox[1]);
      setChip("#histCampaignsChip", campaigns[0], campaigns[1]);
      setChip("#histMaintenancePlanChip", mismatch ? "Divergente" : plan[0], mismatch ? "danger" : plan[1]);
      setChip("#histInternalChip", internal[0], internal[1]);
    }}
    function markVerificationEvidence(selectId) {{
      const select = document.querySelector(selectId);
      if (select) select.value = "evidence_link";
      renderVerificationCards();
    }}
    function activateTab(tabId) {{
      document.querySelectorAll(".tab,.form-section").forEach(x => x.classList.remove("active"));
      const tab = document.querySelector(`.tab[data-tab="${{tabId}}"]`);
      const section = document.querySelector(`#${{tabId}}`);
      if (tab) tab.classList.add("active");
      if (section) section.classList.add("active");
    }}
    function reportTypeLabel(code) {{
      const report = (config?.stellantis_reports || []).find(item => item.code === code);
      return report?.label || code || "Relatorio";
    }}
    function formatReportValues(values) {{
      if (!values || (typeof values === "object" && Object.keys(values).length === 0)) return "Sem valores registados";
      return JSON.stringify(values, null, 2);
    }}
    function serializeReportValues(values) {{
      if (!values || Array.isArray(values) || typeof values !== "object") return JSON.stringify(values || {{}}, null, 2);
      return JSON.stringify(values, null, 2);
    }}
    function hasReportValues(values) {{
      return Boolean(values && typeof values === "object" && Object.keys(values).length);
    }}
    function reportLinkButton(report) {{
      const url = previewableReportUrl(report?.original_link);
      return url ? `<a class="button secondary" href="${{safe(url)}}" target="_blank" rel="noopener">Abrir original</a>` : `<span class="chip neutral">Sem link original</span>`;
    }}
    function showFieldInfo(message) {{
      showResult(true, message || "Sem referencia configurada para este campo.");
    }}
    function objectValues(values) {{
      return values && !Array.isArray(values) && typeof values === "object" ? values : {{}};
    }}
    function normalizedKey(value) {{
      return String(value || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[^a-z0-9]+/g, "");
    }}
    function valueForField(values, field) {{
      const source = objectValues(values);
      const labels = [
        field.code,
        field.label,
        field.unit ? `${{field.label}} (${{field.unit}})` : null,
      ].filter(Boolean);
      for (const key of labels) {{
        if (source[key] !== undefined && source[key] !== null) return source[key];
      }}
      const wanted = labels.map(normalizedKey);
      const foundKey = Object.keys(source).find(key => wanted.includes(normalizedKey(key)));
      return foundKey ? source[foundKey] : "";
    }}
    function setReportFieldValues(values) {{
      const report = selectedReportConfig();
      const fields = report?.fields || [];
      document.querySelectorAll("[data-report-field]").forEach(input => {{
        const field = fields.find(item => item.code === input.dataset.reportField);
        const value = field ? valueForField(values, field) : "";
        input.value = Array.isArray(value) || (value && typeof value === "object") ? JSON.stringify(value) : (value ?? "");
      }});
    }}
    function updateReportActions() {{
      const button = document.querySelector("#reportSaveButton");
      if (button) button.textContent = selectedReportId ? "Guardar alterações" : "Adicionar relatório";
    }}
    function matchingReportDraft() {{
      const link = payloadValue("#reportLink").trim();
      if (!link) return null;
      return (processData?.technical_reports || []).find(report =>
        String(report.original_link || "").trim() === link &&
        report.report_code === payloadValue("#reportCode") &&
        report.report_moment === payloadValue("#reportMoment") &&
        report.reading_origin === payloadValue("#reportOrigin")
      ) || null;
    }}
    function selectReport(reportId) {{
      const report = (processData?.technical_reports || []).find(item => String(item.id) === String(reportId));
      if (!report) return;
      activateTab("reports");
      selectedReportId = report.id;
      selectedReportType = report.report_code;
      renderReportTypeCards();
      setValue("#reportCode", report.report_code);
      setValue("#reportMoment", report.report_moment);
      setValue("#reportOrigin", report.reading_origin);
      renderReportFields();
      setValue("#reportLink", report.original_link);
      setValue("#validateReportId", report.id);
      setReportFieldValues(report.extracted_values || {{}});
      document.querySelector("#reportValues").value = serializeReportValues(report.extracted_values || {{}});
      document.querySelector("#validateValues").value = hasReportValues(report.validated_values) ? serializeReportValues(report.validated_values) : "";
      updateReportPreview();
      updateReportActions();
      const detail = document.querySelector("#selectedReportDetail");
      detail.className = "memory active";
      detail.innerHTML = `
        <div class="section-title">
          <h3>#${{report.id}} ${{safe(report.report_name)}}</h3>
          ${{reportLinkButton(report)}}
        </div>
        <div class="memory-grid">
          <div><span>Origem</span><strong>${{safe(label(report.reading_origin))}}</strong></div>
          <div><span>Momento</span><strong>${{safe(label(report.report_moment))}}</strong></div>
          <div><span>Estado</span><strong>${{safe(statusMeta(report.status)[0])}}</strong></div>
          <div><span>Validado em</span><strong>${{safe(dateLabel(report.validated_at))}}</strong></div>
        </div>
      `;
      detail.scrollIntoView({{behavior:"smooth", block:"nearest"}});
    }}
    function newReportDraft() {{
      selectedReportId = null;
      const code = selectedReportType || payloadValue("#reportCode");
      if (code) setValue("#reportCode", code);
      renderReportFields();
      setValue("#reportLink", "");
      setValue("#validateReportId", "");
      document.querySelector("#reportValues").value = "";
      document.querySelector("#validateValues").value = "";
      document.querySelector("#selectedReportDetail").className = "memory";
      document.querySelector("#selectedReportDetail").innerHTML = "";
      updateReportPreview();
      updateReportActions();
      renderReportTypeCards();
      showResult(true, `Novo relatório: ${{reportTypeLabel(code)}}.`);
    }}
    function selectReportType(code) {{
      selectedReportType = code;
      renderReportTypeCards();
      const reports = processData?.technical_reports || [];
      const candidate = reports
        .filter(report => report.report_code === code)
        .sort((a, b) => (a.status === "pending_validation" ? -1 : 0) - (b.status === "pending_validation" ? -1 : 0) || b.id - a.id)[0];
      if (candidate) {{
        selectReport(candidate.id);
      }} else {{
        selectedReportId = null;
        setValue("#reportCode", code);
        renderReportFields();
        document.querySelector("#selectedReportDetail").className = "memory";
        document.querySelector("#selectedReportDetail").innerHTML = "";
        setValue("#validateReportId", "");
        document.querySelector("#reportValues").value = "";
        document.querySelector("#validateValues").value = "";
        updateReportActions();
        showResult(true, `Preparar novo relatório: ${{reportTypeLabel(code)}}.`);
      }}
    }}
    function selectedReportConfig() {{
      const code = payloadValue("#reportCode");
      return (config?.stellantis_reports || []).find(report => report.code === code) || null;
    }}
    const REPORT_EXTRACTION_GUIDES = {{
      engine_lubrication: {{
        stellantis_machine: {{source:"PSA-DIAG / Stellantis", example:"lubrificacao_motor_informacoes-lubrificacao-motor", note:"Confirmar valores de oleo, pressao, carbono, protecao e intervalo calculado."}},
        autel: {{source:"Autel", example:"lubrificacao_motor_informacoes-lubrificacao-motor", note:"A nomenclatura pode variar; validar unidades antes de gravar."}},
        other: {{source:"Outro relatorio tecnico", example:"Relatorio de lubrificacao motor", note:"Usar apenas se o documento identificar claramente parametros de lubrificacao."}}
      }},
      maintenance_information: {{
        stellantis_machine: {{source:"PSA-DIAG / Stellantis", example:"manutencao_informacoes-de-manutencao", note:"Copiar contadores, limites de manutencao e indicadores de chave."}},
        autel: {{source:"Autel", example:"manutencao_informacoes-manutencao", note:"Comparar designacao Autel com o campo CarFast antes de preparar valores."}},
        other: {{source:"Outro relatorio tecnico", example:"Informacoes de manutencao", note:"Aceitar se tiver KM, dias e contadores de manutencao."}}
      }},
      maintenance_programming: {{
        stellantis_machine: {{source:"PSA-DIAG / Stellantis", example:"parametrizacao_manutencao_parametros-de-manutencao-recuperados-do-veiculo", note:"Referencia principal encontrada para parametrizacao/programacao de manutencao."}},
        autel: {{source:"Autel", example:"Sem exemplo Autel confirmado", note:"Preencher manualmente apenas se o relatorio mostrar limiar, duracao e inicio da primeira manutencao."}},
        other: {{source:"Outro relatorio tecnico", example:"Parametros de manutencao", note:"Exigir valores de parametrizacao, nao apenas informacao de manutencao."}}
      }},
      maintenance_plan_validation: {{
        stellantis_machine: {{source:"Service Box + Rentway", example:"plano-manutencao-servicebox-rentway", note:"Comparar solicitacao do processo com plano Service Box e confirmar se a parametrizacao Rentway tem os mesmos intervalos."}},
        autel: {{source:"Autel + Service Box + Rentway", example:"plano-manutencao-validacao", note:"Usar Autel apenas como apoio; a referencia do plano deve ser Service Box e a parametrizacao deve ser comparada com Rentway."}},
        other: {{source:"Plano externo + Rentway", example:"plano-manutencao", note:"Guardar evidencia e preencher explicitamente se pedido e Rentway batem certo com o plano."}}
      }},
      fault_reading: {{
        stellantis_machine: {{source:"PSA-DIAG / Stellantis", example:"leitura_defeitos_relatorio-de-diagnostico-do-veiculo", note:"Copiar existencia de defeitos e lista/codigos relevantes."}},
        autel: {{source:"Autel", example:"leitura_defeitos_global", note:"Quando existir tabela, copiar codigo, sistema, estado e descricao no campo lista."}},
        other: {{source:"Outro relatorio tecnico", example:"Relatorio de diagnostico", note:"Guardar resumo de defeitos mesmo quando o formato nao for normalizado."}}
      }},
      remote_download: {{
        stellantis_machine: {{source:"PSA-DIAG / Stellantis", example:"identificacao_telecarregamento_informacao-ecu", note:"Focar referencia de software, data e numero de telecarregamentos."}},
        autel: {{source:"Autel", example:"identificacao_telecarregamento_referencia-do-material", note:"Validar se a referencia e da ECU/software antes de fechar."}},
        other: {{source:"Outro relatorio tecnico", example:"Identificacao / telecarregamento", note:"Usar quando houver dados de software ou telecarregamento."}}
      }},
      other_reading: {{
        stellantis_machine: {{source:"PSA-DIAG / Stellantis", example:"outro_versao-programa", note:"Descrever area/sistema e parametros principais."}},
        autel: {{source:"Autel", example:"outro_2-sistemas-analisados", note:"Resumir sistemas analisados e anexar o link como evidencia."}},
        other: {{source:"Outro relatorio", example:"Leitura tecnica sem categoria", note:"Criar titulo claro e preencher parametros observados."}}
      }}
    }};
    function extractionMeta(report) {{
      if (!report) return {{}};
      const origin = payloadValue("#reportOrigin") || "stellantis_machine";
      return (REPORT_EXTRACTION_GUIDES[report.code] || {{}})[origin] || (REPORT_EXTRACTION_GUIDES[report.code] || {{}}).other || {{}};
    }}
    function reportFieldInfo(report, field) {{
      const origin = payloadValue("#reportOrigin") || "stellantis_machine";
      const meta = extractionMeta(report);
      const unit = field.unit ? ` (${{field.unit}})` : "";
      return `${{label(origin)}} · ${{meta.source || "Relatorio tecnico"}}. Procurar no original: ${{field.label}}${{unit}}. Preencher este campo CarFast com o valor correspondente. Exemplo de referencia: ${{meta.example || report?.label || "relatorio tecnico"}}. ${{meta.note || ""}}`;
    }}
    function renderExtractionGuide(report, fields) {{
      const guide = document.querySelector("#reportExtractionGuide");
      if (!guide) return;
      guide.style.display = "none";
      guide.innerHTML = "";
    }}
    function renderReportFields() {{
      const report = selectedReportConfig();
      const fields = report?.fields || [];
      document.querySelector("#reportHint").textContent = report ? `${{report.description}} O link fica guardado como evidência; os valores devem ser preenchidos nos campos abaixo ou no JSON.` : "";
      renderExtractionGuide(report, fields);
      document.querySelector("#reportFieldGrid").innerHTML = fields.map(field => {{
        const info = reportFieldInfo(report, field);
        return `
        <label>
          <span>${{safe(field.label)}}${{field.unit ? ` (${{field.unit}})` : ""}}</span>
          <input data-report-field="${{field.code}}" placeholder="${{field.repeatable ? "Lista ou resumo" : field.label}}">
          <button class="field-info" type="button" title="${{safe(info)}}" data-info="${{safe(info)}}" onclick="showFieldInfo(this.dataset.info)">i</button>
        </label>
      `}}).join("");
      if (!selectedReportId && report?.code === "maintenance_plan_validation") {{
        const requested = document.querySelector('[data-report-field="requested_service"]');
        if (requested) requested.value = processData?.services_label || processData?.title || "";
      }}
      document.querySelector("#reportValues").value = "";
      document.querySelector("#validateValues").value = "";
    }}
    function collectReportValues() {{
      const values = {{}};
      document.querySelectorAll("[data-report-field]").forEach(input => {{
        const value = input.value.trim();
        if (value) values[input.dataset.reportField] = value;
      }});
      const manual = jsonValue("#reportValues");
      return Array.isArray(manual) ? manual : {{...values, ...(manual || {{}})}};
    }}
    function prepareReportValues() {{
      const values = collectReportValues();
      const serialized = JSON.stringify(values, null, 2);
      document.querySelector("#reportValues").value = serialized;
      document.querySelector("#validateValues").value = serialized;
      showResult(true, "Valores extraídos copiados para validação.");
      return values;
    }}
    function showResult(ok, message) {{ result.className = `result active ${{ok ? "ok" : "err"}}`; result.textContent = typeof message === "string" ? message : JSON.stringify(message); }}
    async function requestJson(url, method, body) {{ const r = await fetch(url, {{method, headers:{{"Content-Type":"application/json"}}, body:JSON.stringify(body)}}); const data = await r.json(); if(!r.ok) throw new Error(JSON.stringify(data.detail || data)); await loadProcess(); return data; }}
    async function post(url, body) {{ return requestJson(url, "POST", body); }}
    async function patch(url, body) {{ return requestJson(url, "PATCH", body); }}
    document.querySelector("#phaseTabs").addEventListener("click", event => {{
      const tab = event.target.closest(".tab");
      if (!tab) return;
      activateTab(tab.dataset.tab);
      renderPhaseTabs(tab.dataset.tab);
      if (tab.dataset.tab === "reports" && processData?.technical_reports?.length) {{
        const reports = selectedReportType ? processData.technical_reports.filter(report => report.report_code === selectedReportType) : processData.technical_reports;
        const first = [...reports].sort((a,b) => (a.status === "pending_validation" ? -1 : 0) - (b.status === "pending_validation" ? -1 : 0) || b.id - a.id)[0];
        if (first) selectReport(first.id);
      }}
    }});
    const STATUS = {{
      completed:["Concluído","done"], completed_with_pending_items:["Concluído com pendências","review"], validated:["Validado","done"],
      ok:["OK","done"], in_progress:["Em curso","progress"], pending_review:["Por rever","review"], reception_pending:["Receção pendente","review"],
      pending_definition:["Por definir","review"], pending:["Pendente","review"], open:["Aberto","review"], added:["Adicionado","progress"],
      pending_validation:["Por validar","review"], corrected_manually:["Corrigido manualmente","review"], unable_to_read:["Falha na leitura","danger"],
      not_applicable:["Não aplicável","neutral"], not_started:["Não iniciado","neutral"], cancelled:["Cancelado","danger"], high:["Alta","danger"], critical:["Crítica","danger"], defined:["Definida","done"]
    }};
    const PHASES = {{
      process_creation:"Criação do processo", administrative_reception:"Receção administrativa", history_check:"Verificações",
      technical_phase:"Fase técnica", diagnosis_decision:"Diagnóstico e decisão", budget_approval:"Orçamento / aprovação",
      internal_repair_execution:"Reparação interna / execução", final_closure:"Fecho definitivo"
    }};
    const VALUES = {{yes:"Sim", no:"Não", pending_review:"Por rever", none:"Não existem", not_ok:"Não OK", not_applicable:"Não aplicável", evidence_link:"Link para print", low:"Baixa", medium:"Média", high:"Alta", critical:"Crítica", normal:"Normal", urgent:"Urgente", initial:"Inicial", final:"Final", stellantis_machine:"Máquina Stellantis", autel:"Autel", other:"Outro", free:"Livre", in_contract:"Em contrato", in_preparation:"Em preparação", blocked:"Bloqueada", in_maintenance:"Em manutenção", for_sale:"Em venda", immobilized:"Imobilizada"}};
    function safe(value) {{
      return String(value ?? "-").replace(/[&<>"']/g, c => c === "&" ? "&amp;" : c === "<" ? "&lt;" : c === ">" ? "&gt;" : c === '"' ? "&quot;" : "&#39;");
    }}
    function label(value) {{ return VALUES[value] || value || "-"; }}
    function statusMeta(code) {{ return STATUS[code] || [code || "-", "neutral"]; }}
    function chip(code) {{ const meta = statusMeta(code); return `<span class="chip ${{meta[1]}}">${{safe(meta[0])}}</span>`; }}
    function phaseData(code) {{ return (processData.phases.find(p => p.phase_code === code) || {{}}).data || {{}}; }}
    function phaseByCode(code) {{ return processData?.phases?.find(p => p.phase_code === code) || null; }}
    function alertsForPhase(phase) {{
      if (!phase) return [];
      return (processData?.alerts || []).filter(alert => alert.phase_id === phase.id || alert.source === phase.phase_code);
    }}
    function tabStateClass(phase, alerts) {{
      if (!phase) return "";
      if (alerts.length || ["pending_review","pending_definition","with_incidents","completed_with_pending_items"].includes(phase.status)) return "incomplete";
      if (["completed","validated"].includes(phase.status)) return "complete";
      return "";
    }}
    function tabStateText(tab, phase) {{
      if (tab.id === "services") return `${{processData?.services?.length || 0}} serviços`;
      if (tab.id === "reports") {{
        const reports = processData?.technical_reports || [];
        const pending = reports.filter(report => ["pending_validation","added","pending"].includes(report.status)).length;
        return `${{reports.length}} relatórios${{pending ? ` · ${{pending}} por validar` : ""}}`;
      }}
      return phase ? statusMeta(phase.status)[0] : "Aberto";
    }}
    function renderPhaseTabs(activeTabId = document.querySelector(".tab.active")?.dataset.tab || "reception") {{
      const holder = document.querySelector("#phaseTabs");
      if (!holder || !processData) return;
      holder.innerHTML = TAB_CONFIG.map(tab => {{
        const phase = tab.phase ? phaseByCode(tab.phase) : null;
        const alerts = alertsForPhase(phase);
        const active = tab.id === activeTabId;
        return `<button class="tab ${{active ? "active" : ""}} ${{tabStateClass(phase, alerts)}}" data-tab="${{tab.id}}" title="${{alerts.map(alert => safe(alert.message)).join(" · ")}}">
          <span class="tab-title">${{safe(tab.label)}}</span>
          ${{alerts.length ? `<span class="tab-alert">${{alerts.length}}</span>` : ""}}
          <span class="tab-state">${{safe(tabStateText(tab, phase))}}</span>
        </button>`;
      }}).join("");
    }}
    function hasData(data) {{ return data && Object.keys(data).some(k => data[k] !== null && data[k] !== "" && data[k] !== undefined); }}
    function dateLabel(value) {{
      if (!value) return "-";
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return value;
      return `${{date.toLocaleDateString("pt-PT")}}, ${{date.toLocaleTimeString("pt-PT", {{hour:"2-digit", minute:"2-digit"}})}}`;
    }}
    function setValue(id, value) {{ const el = document.querySelector(id); if (el && value !== null && value !== undefined) el.value = value; }}
    function setChecked(id, value) {{ const el = document.querySelector(id); if (el) el.checked = Boolean(value); }}
    function setButton(id, fresh, update) {{ const el = document.querySelector(id); if (el) el.textContent = update ? `Atualizar ${{fresh}}` : `Confirmar ${{fresh}}`; }}
    const SERVICE_FIELD_RULES = {{
      revision_maintenance: {{zone:"Sistema / plano", zonePlaceholder:"Motor, filtros, plano A/B...", detail:"Intervenção prevista", detailPlaceholder:"Revisão por plano, óleo, filtros...", observation:"Referência / evidência", observationPlaceholder:"Plano Service Box, KM, motivo da revisão...", hint:"Registar plano aplicável e evidência que justifica a manutenção."}},
      tires: {{zone:"Posição", zonePlaceholder:"Frente, traseira, frente esq., traseira dir....", detail:"Medida / intervenção", detailPlaceholder:"205/55 R16, trocar 2 pneus, alinhar direção...", observation:"Estado / evidência", observationPlaceholder:"Piso, DOT, dano, pressão, foto associada..."}},
      brakes: {{zone:"Eixo / posição", zonePlaceholder:"Frente, traseira, roda esq./dir....", detail:"Componente", detailPlaceholder:"Pastilhas, discos, óleo travões, sensor...", observation:"Sintoma / medição", observationPlaceholder:"Ruído, espessura, aviso painel, evidência técnica..."}},
      dashboard_warning: {{zone:"Sistema afetado", zonePlaceholder:"Motor, AdBlue, bateria, travagem...", detail:"Aviso apresentado", detailPlaceholder:"Mensagem/luz no painel, código se existir...", observation:"Condição de ocorrência", observationPlaceholder:"Quando apareceu, se pode circular, foto do painel..."}},
      battery: {{zone:"Tipo / localização", zonePlaceholder:"Bateria principal, auxiliar, chave...", detail:"Teste / intervenção", detailPlaceholder:"Teste bateria, substituição, carga, alternador...", observation:"Resultado do teste", observationPlaceholder:"Tensão, SOH, CCA, evidência do teste..."}},
      mechanics: {{zone:"Sistema", zonePlaceholder:"Motor, caixa, suspensão, direção...", detail:"Sintoma / trabalho", detailPlaceholder:"Diagnosticar fuga, ruído, vibração, avaria...", observation:"Condição / evidência", observationPlaceholder:"Quando ocorre, severidade, links/fotos..."}},
      body_paint: {{zone:"Painel / zona", zonePlaceholder:"Para-choques, porta, guarda-lamas...", detail:"Tipo de intervenção", detailPlaceholder:"Pintura, polimento, reparação chapa...", observation:"Dano / evidência", observationPlaceholder:"Descrição do dano, fotos, responsabilidade..."}},
      damage: {{zone:"Zona do dano", zonePlaceholder:"Frente, lateral dir., interior, jante...", detail:"Descrição do dano", detailPlaceholder:"Risco, amolgadela, quebra, falta peça...", observation:"Origem / evidência", observationPlaceholder:"Sinistro, entrega, cliente, fotos, orçamento..."}},
      warranty: {{zone:"Sistema / peça", zonePlaceholder:"Motor, multimédia, bateria, caixa...", detail:"Sintoma para garantia", detailPlaceholder:"Falha reportada, peça suspeita, campanha...", observation:"Condições garantia", observationPlaceholder:"Data, KM, recorrência, evidência, consulta fabricante..."}},
      sale_preparation: {{zone:"Área", zonePlaceholder:"Interior, exterior, mecânica, documentação...", detail:"Preparação necessária", detailPlaceholder:"Limpeza, detalhe, revisão, fotos, documentos...", observation:"Critério de entrega", observationPlaceholder:"Requisitos para venda, pendências, prioridade..."}},
      other: {{zone:"Área", zonePlaceholder:"Área ou sistema afetado", detail:"Descrição do serviço", detailPlaceholder:"Descrever trabalho a executar", observation:"Motivo / evidência", observationPlaceholder:"Motivo, evidência, responsável..."}},
    }};
    function updateServiceFormFields() {{
      const code = payloadValue("#serviceCode");
      const rule = SERVICE_FIELD_RULES[code] || SERVICE_FIELD_RULES.other;
      const zoneLabel = document.querySelector("#serviceZoneLabel");
      const detailLabel = document.querySelector("#serviceDetailLabel");
      const observationLabel = document.querySelector("#serviceObservationLabel");
      const zone = document.querySelector("#serviceZone");
      const detail = document.querySelector("#serviceDetail");
      const observation = document.querySelector("#serviceObservation");
      const hint = document.querySelector("#serviceFormHint");
      if (zoneLabel) zoneLabel.firstChild.textContent = rule.zone;
      if (detailLabel) detailLabel.firstChild.textContent = rule.detail;
      if (observationLabel) observationLabel.firstChild.textContent = rule.observation;
      if (zone) zone.placeholder = rule.zonePlaceholder || "";
      if (detail) {{ detail.placeholder = rule.detailPlaceholder || ""; detail.required = code === "other"; }}
      if (observation) observation.placeholder = rule.observationPlaceholder || "";
      if (hint) hint.textContent = rule.hint || "";
    }}
    function memory(id, rows) {{
      const cleanRows = rows.filter(r => r[1] !== null && r[1] !== undefined && r[1] !== "");
      const el = document.querySelector(id);
      if (!el) return;
      if (!cleanRows.length) {{ el.className = "memory"; el.innerHTML = ""; return; }}
      el.className = "memory active";
      el.innerHTML = `<div class="memory-grid">${{cleanRows.map(r => `<div><span>${{safe(r[0])}}</span><strong>${{safe(label(r[1]))}}</strong></div>`).join("")}}</div>`;
    }}
    function renderServices() {{
      const list = document.querySelector("#serviceList");
      if (!list) return;
      list.innerHTML = processData.services.map(service => `
        <li>
          <span>${{safe(service.service_label)}}<br><small class="muted">${{safe([service.zone, service.detail, service.short_observation].filter(Boolean).join(" · "))}}</small></span>
          <span class="chip">#${{service.sort_order || service.id}}</span>
        </li>
      `).join("") || "<li>Sem serviços registados</li>";
    }}
    function reportStatusSummary(reports) {{
      if (!reports.length) return "0 relatórios";
      const validated = reports.filter(report => ["validated","corrected_manually"].includes(report.status)).length;
      const pending = reports.filter(report => ["pending_validation","added","pending"].includes(report.status)).length;
      return `${{validated}} validados${{pending ? ` · ${{pending}} por validar` : ""}}`;
    }}
    function renderReportInstanceList() {{
      const holder = document.querySelector("#reportInstanceList");
      if (!holder) return;
      const reports = (processData?.technical_reports || []).filter(report => report.report_code === selectedReportType);
      if (!selectedReportType) {{
        holder.innerHTML = "";
        return;
      }}
      holder.innerHTML = reports.map(report => `
        <button type="button" class="${{String(report.id) === String(selectedReportId) ? "active" : ""}}" onclick="selectReport(${{report.id}})">
          <span>#${{report.id}} ${{safe(report.report_name)}}</span>
          <small>${{safe(label(report.reading_origin))}}</small>
          ${{chip(report.status)}}
        </button>
      `).join("") || `<button type="button" onclick="newReportDraft()">Novo ${{safe(reportTypeLabel(selectedReportType))}}</button>`;
    }}
    function renderReportTypeCards() {{
      const holder = document.querySelector("#reportTypeCards");
      if (!holder || !config) return;
      const reports = processData?.technical_reports || [];
      document.querySelector("#reportTabCount").textContent = reports.length;
      holder.innerHTML = (config.stellantis_reports || []).map(type => {{
        const typeReports = reports.filter(report => report.report_code === type.code);
        const active = selectedReportType === type.code;
        return `<button type="button" class="report-type-card ${{active ? "active" : ""}}" onclick="selectReportType('${{safe(type.code)}}')">
          <strong>${{safe(type.label)}}</strong>
          <span>${{typeReports.length}} relatório${{typeReports.length === 1 ? "" : "s"}}</span>
          <span>${{safe(reportStatusSummary(typeReports))}}</span>
        </button>`;
      }}).join("");
      renderReportInstanceList();
    }}
    function renderVehicle() {{
      const v = processData.vehicle || {{}};
      const model = [v.brand, v.model, v.version].filter(Boolean).join(" ") || "-";
      document.querySelector("#vehicleStrip").innerHTML = `
        <div class="vehicle-thumb">${{safe(v.plate || processData.plate || "Viatura")}}</div>
        <div class="vehicle-main">
          <div>
            <strong>${{safe(v.plate || processData.plate || "-")}}</strong>
            <p class="subtitle" style="margin:4px 0 0">${{safe(model)}} · Unit ${{safe(v.rentway_unit_nr)}}</p>
          </div>
          <div class="vehicle-facts">
            <div><span>VIN</span><strong>${{safe(v.vin)}}</strong></div>
            <div><span>KM entrada</span><strong>${{safe(processData.initial_km)}}</strong></div>
            <div><span>Entrada</span><strong>${{safe(dateLabel(processData.created_at))}}</strong></div>
          </div>
        </div>
        <div class="vehicle-state">
          <span>Estado operacional</span>
          <strong>${{safe(label(v.operational_status))}}</strong>
          <span>Prioridade</span>
          <strong>${{safe(label(processData.priority))}}</strong>
        </div>
      `;
    }}
    function renderSummary() {{
      const status = statusMeta(processData.status);
      const statusChip = document.querySelector("#statusChip");
      statusChip.textContent = status[0];
      statusChip.className = `chip ${{status[1]}}`;
      const alerts = Array.from(new Map(processData.alerts.map(a => [`${{a.code}}:${{a.message}}`, a])).values());
      document.querySelector("#summary").innerHTML = `
        <div class="summary-block">
          <div class="summary-title"><h3>Alertas</h3><span class="chip warn">${{alerts.length}}</span></div>
          <ul class="plain-list">${{alerts.map(a => `<li><span>${{safe(a.message)}}</span>${{chip(a.status || a.severity)}}</li>`).join("") || "<li>Sem alertas abertos</li>"}}</ul>
        </div>
      `;
    }}
    function renderDocumentFolder() {{
      const folder = processData.document_folder || {{}};
      const path = folder.path || "";
      const holder = document.querySelector("#documentFolder");
      if (!holder) return;
      holder.innerHTML = `
        <div class="summary-block">
          <div class="summary-title"><h3>Pasta documental</h3>${{chip(folder.status || "defined")}}</div>
          <ul class="plain-list"><li style="display:block"><span>Pasta documental</span><br><small class="muted">${{safe(path || "Pasta por definir")}}</small></li></ul>
          <div class="grid2"><button type="button" onclick="copyDocumentFolder()">Abrir pasta</button><button type="button" onclick="copyDocumentFolder()">Copiar caminho</button></div>
        </div>
      `;
    }}
    async function copyDocumentFolder() {{
      const path = processData?.document_folder?.path || "";
      if (!path) return showResult(false, "Pasta documental por definir.");
      try {{
        await navigator.clipboard.writeText(path);
        showResult(true, "Caminho da pasta copiado.");
      }} catch {{
        showResult(false, path);
      }}
    }}
    function renderPhaseMemory() {{
      const reception = phaseData("administrative_reception");
      memory("#receptionMemory", [["KM entrada", reception.km_entry], ["Foto quadrante", reception.quadrant_photo_link], ["Estado visual", reception.visible_damage_status], ["Danos", reception.damage_description], ["Observação", reception.initial_observation]]);
      setValue("#recKm", reception.km_entry); setValue("#recPhoto", reception.quadrant_photo_link); setValue("#recObs", reception.initial_observation); setValue("#recVisual", reception.visible_damage_status); setValue("#recDamage", reception.damage_description); setButton("#receptionButton", "receção", hasData(reception));
      const history = phaseData("history_check");
      memory("#historyMemory", [["Histórico interno", history.internal_history_checked], ["Accident reports", history.open_accident_reports], ["Detalhe", history.accident_reports_detail], ["Processos anteriores", history.previous_processes_reviewed], ["Incidência repetida", history.repeated_incidence], ["Service Box", history.service_box_checked], ["Print Service Box", history.service_box_link], ["Campanhas", history.campaigns_checked], ["Print campanhas", history.campaigns_link], ["Plano manutenção", history.maintenance_plan_checked], ["Print plano", history.maintenance_plan_link], ["Observação", history.history_observation]]);
      setValue("#histInternal", history.internal_history_checked); setValue("#histAccidents", history.open_accident_reports); setValue("#histAccidentsDetail", history.accident_reports_detail); setValue("#histPrev", history.previous_processes_reviewed); setValue("#histRepeat", history.repeated_incidence); setValue("#histServiceBox", history.service_box_checked); setValue("#histServiceBoxLink", history.service_box_link); setValue("#histCampaigns", history.campaigns_checked); setValue("#histCampaignsLink", history.campaigns_link); setValue("#histMaintenancePlan", history.maintenance_plan_checked); setValue("#histMaintenancePlanLink", history.maintenance_plan_link); updateVerificationLinks(); setValue("#histObs", history.history_observation); setButton("#historyButton", "verificações", hasData(history));
      const decision = phaseData("diagnosis_decision");
      memory("#decisionMemory", [["Diagnóstico", decision.main_diagnosis], ["Tipo intervenção", decision.intervention_type], ["Sistema", decision.affected_system], ["Gravidade", decision.severity], ["Pode circular", decision.vehicle_can_circulate], ["Próxima ação", decision.next_action], ["Cobrança cliente", decision.potential_customer_charge ? "Sim" : null]]);
      setValue("#decisionDiagnosis", decision.main_diagnosis); setValue("#decisionType", decision.intervention_type); setValue("#decisionSystem", decision.affected_system); setValue("#decisionSeverity", decision.severity); setValue("#decisionCause", decision.probable_cause); setValue("#decisionObs", decision.diagnosis_observation || decision.decision_observation); setValue("#decisionCirculate", decision.vehicle_can_circulate); setValue("#decisionNext", decision.next_action); setChecked("#decisionNeedsRepair", decision.needs_repair); setChecked("#decisionNeedsBudget", decision.needs_budget); setChecked("#decisionNeedsApproval", decision.needs_approval); setChecked("#decisionCharge", decision.potential_customer_charge); setChecked("#decisionWarranty", decision.warranty); setButton("#decisionButton", "decisão", hasData(decision));
      const budget = phaseData("budget_approval");
      memory("#budgetMemory", [["Fornecedor", budget.supplier], ["Valor", budget.estimated_value], ["Aprovação", budget.approval_status], ["Resultado", budget.final_result], ["Observação", budget.observation]]);
      setValue("#budgetSupplier", budget.supplier); setValue("#budgetValue", budget.estimated_value); setValue("#budgetApproval", budget.approval_status); setValue("#budgetDescription", budget.request_description); setValue("#budgetLink", budget.budget_link); setValue("#budgetResult", budget.final_result); setValue("#budgetObs", budget.observation); setChecked("#budgetReceived", budget.budget_received); setChecked("#budgetNeedsApproval", budget.needs_approval); if (hasData(budget)) document.querySelector("#budgetButton").textContent = "Atualizar orçamento";
      const repair = phaseData("internal_repair_execution");
      memory("#repairMemory", [["Tipo execução", repair.execution_type], ["Resultado", repair.result], ["Intervenção", repair.intervention_description], ["Foto quadrante final", repair.final_quadrant_photo_link], ["KM final", repair.final_km_visible]]);
      setValue("#repairType", repair.execution_type); setValue("#repairResult", repair.result); setValue("#repairDescription", repair.intervention_description); setValue("#repairFinalPhoto", repair.final_quadrant_photo_link); setValue("#repairFinalKm", repair.final_km_visible); if (hasData(repair)) document.querySelector("#repairButton").textContent = "Atualizar reparação";
      const closure = phaseData("final_closure");
      memory("#closeMemory", [["Resultado", closure.final_result], ["Viatura pronta", closure.vehicle_ready], ["Novo estado", closure.new_vehicle_operational_status], ["KM final", closure.final_km], ["Observação", closure.final_observation]]);
      setValue("#closeResult", closure.final_result); setValue("#closeReady", closure.vehicle_ready); setValue("#closeStatus", closure.new_vehicle_operational_status); setValue("#closeObs", closure.final_observation); setChecked("#closePending", closure.close_with_pending_items); if (hasData(closure)) document.querySelector("#closeButton").textContent = "Atualizar fecho";
    }}
    async function loadConfig() {{
      config = await (await fetch("/api/workshop/process-config")).json();
      document.querySelector("#reportCode").innerHTML = config.stellantis_reports.map(r => `<option value="${{r.code}}">${{r.label}}</option>`).join("");
      document.querySelector("#checkCode").innerHTML = config.technical_checks.map(c => `<option value="${{c.code}}">${{c.label}}</option>`).join("");
      document.querySelector("#serviceCode").innerHTML = config.services.map(s => `<option value="${{s.code}}">${{s.label}}</option>`).join("");
      document.querySelector("#serviceCode").addEventListener("change", updateServiceFormFields);
      document.querySelector("#reportCode").addEventListener("change", () => {{ selectedReportId = null; selectedReportType = payloadValue("#reportCode"); renderReportTypeCards(); renderReportFields(); updateReportActions(); }});
      document.querySelector("#reportOrigin").addEventListener("change", renderReportFields);
      document.querySelector("#reportLink").addEventListener("input", updateReportPreview);
      document.querySelector("#histServiceBoxLink").addEventListener("input", updateVerificationLinks);
      document.querySelector("#histCampaignsLink").addEventListener("input", updateVerificationLinks);
      document.querySelector("#histMaintenancePlanLink").addEventListener("input", updateVerificationLinks);
      ["#histServiceBox","#histCampaigns","#histMaintenancePlan","#histInternal"].forEach(id => {{
        const el = document.querySelector(id);
        if (el) el.addEventListener("change", renderVerificationCards);
      }});
      renderReportFields();
      updateServiceFormFields();
      updateReportPreview();
    }}
    async function loadProcess() {{ processData = await (await fetch(`/api/workshop/processes/${{processId}}`)).json(); const v = processData.vehicle || {{}}; const status = statusMeta(processData.status); const model = [v.brand, v.model, v.version].filter(Boolean).join(" "); const currentPhase = PHASES[processData.current_phase_code] || processData.current_phase_code || "-"; const activeTab = document.querySelector(".tab.active")?.dataset.tab || "history"; document.querySelector("#header").innerHTML = `<div class="process-heading"><a class="back-button" href="/workshop/processes-ui" title="Voltar">‹</a><div><div class="process-titleline"><h1>Oficina - Processo #${{processData.id}}</h1>${{chip(processData.status)}}</div><div class="process-meta"><span>▱ ${{safe(v.plate || processData.plate || "-")}}</span><span>|</span><span>${{safe(model || "Dados da viatura por completar")}}</span><span>|</span><span>Unidade ${{safe(v.rentway_unit_nr || "-")}}</span><span>|</span><span>${{safe(processData.initial_km || "-")}} km</span><span>|</span><span>Fase atual: <strong>${{safe(currentPhase)}}</strong></span></div></div></div><div class="top-actions"><button type="button" class="button secondary" onclick="copyDocumentFolder()">▣ Abrir pasta do processo</button><button type="button" class="button ghost" title="Ações">⋮</button></div>`; renderVehicle(); renderServices(); renderDocumentFolder(); renderSummary(); renderPhaseTabs(activeTab); renderPhaseMemory(); renderReportTypeCards(); activateTab(activeTab); if (!selectedReportType && processData.technical_reports?.length) {{ const first = [...processData.technical_reports].sort((a,b) => (a.status === "pending_validation" ? -1 : 0) - (b.status === "pending_validation" ? -1 : 0) || b.id - a.id)[0]; selectedReportType = first.report_code; if (document.querySelector("#reports").classList.contains("active")) selectReport(first.id); else renderReportTypeCards(); }} }}
    async function confirmReception() {{ try {{ await post(`/api/workshop/processes/${{processId}}/reception`, {{km_entry:Number(payloadValue("#recKm")) || null, quadrant_photo_link:payloadValue("#recPhoto"), initial_observation:payloadValue("#recObs"), visible_damage_status:payloadValue("#recVisual"), damage_description:payloadValue("#recDamage")}}); showResult(true, "Receção confirmada."); }} catch(e) {{ showResult(false, e.message); }} }}
    async function confirmHistory() {{ try {{ await post(`/api/workshop/processes/${{processId}}/history-check`, {{internal_history_checked:payloadValue("#histInternal"), open_accident_reports:payloadValue("#histAccidents"), accident_reports_detail:payloadValue("#histAccidentsDetail"), previous_processes_reviewed:payloadValue("#histPrev"), relevant_interventions_identified:"no", repeated_incidence:payloadValue("#histRepeat"), service_box_checked:payloadValue("#histServiceBox"), service_box_link:payloadValue("#histServiceBoxLink"), campaigns_checked:payloadValue("#histCampaigns"), campaigns_link:payloadValue("#histCampaignsLink"), maintenance_plan_checked:payloadValue("#histMaintenancePlan"), maintenance_plan_link:payloadValue("#histMaintenancePlanLink"), history_observation:payloadValue("#histObs")}}); showResult(true, "Verificações confirmadas."); }} catch(e) {{ showResult(false, e.message); }} }}
    async function addService() {{ try {{ await post(`/api/workshop/processes/${{processId}}/services`, {{service_code:payloadValue("#serviceCode"), detail:payloadValue("#serviceDetail"), zone:payloadValue("#serviceZone"), short_observation:payloadValue("#serviceObservation")}}); document.querySelector("#serviceDetail").value = ""; document.querySelector("#serviceZone").value = ""; document.querySelector("#serviceObservation").value = ""; showResult(true, "Serviço adicionado ao processo."); }} catch(e) {{ showResult(false, e.message); }} }}
    async function saveReportDraft() {{ try {{ const extractedValues = collectReportValues(); document.querySelector("#reportValues").value = JSON.stringify(extractedValues, null, 2); const body = {{report_code:payloadValue("#reportCode"), report_moment:payloadValue("#reportMoment"), reading_origin:payloadValue("#reportOrigin"), original_link:payloadValue("#reportLink"), extracted_values:extractedValues}}; const existing = selectedReportId ? null : matchingReportDraft(); const reportId = selectedReportId || existing?.id; const updating = Boolean(reportId); const data = updating ? await patch(`/api/workshop/technical-reports/${{reportId}}`, body) : await post(`/api/workshop/processes/${{processId}}/technical-reports`, body); selectedReportId = data.id; document.querySelector("#validateReportId").value = data.id; document.querySelector("#validateValues").value = JSON.stringify(extractedValues, null, 2); updateReportActions(); renderReportTypeCards(); selectReport(data.id); showResult(true, updating ? `Relatório #${{data.id}} atualizado. Fica pendente de validação.` : `Relatório #${{data.id}} adicionado. Fica pendente de validação.`); }} catch(e) {{ showResult(false, e.message); }} }}
    async function validateReport() {{ try {{ const reportId = payloadValue("#validateReportId") || selectedReportId || matchingReportDraft()?.id; if (!reportId) throw new Error("Seleciona ou adiciona um relatório antes de validar."); const validatedValues = payloadValue("#validateValues") ? jsonValue("#validateValues") : collectReportValues(); document.querySelector("#validateValues").value = JSON.stringify(validatedValues || {{}}, null, 2); await post(`/api/workshop/technical-reports/${{reportId}}/validate`, {{validated_values:validatedValues || {{}}}}); selectedReportId = Number(reportId); showResult(true, `Relatório #${{reportId}} validado como revisto.`); }} catch(e) {{ showResult(false, e.message); }} }}
    async function saveCheck() {{ try {{ await post(`/api/workshop/processes/${{processId}}/technical-checks`, {{check_code:payloadValue("#checkCode"), status:payloadValue("#checkStatus"), observation:payloadValue("#checkObs"), evidence_link:payloadValue("#checkEvidence"), creates_task:document.querySelector("#checkTask").checked, potential_customer_charge:document.querySelector("#checkCharge").checked, task_title:payloadValue("#checkTaskTitle")}}); showResult(true, "Verificação guardada."); }} catch(e) {{ showResult(false, e.message); }} }}
    async function createIncident() {{ try {{ await post(`/api/workshop/processes/${{processId}}/incidents`, {{incident_type:payloadValue("#incidentType"), severity:payloadValue("#incidentSeverity"), vehicle_can_circulate:payloadValue("#incidentCirculate"), description:payloadValue("#incidentDescription")}}); showResult(true, "Incidente criado."); }} catch(e) {{ showResult(false, e.message); }} }}
    async function saveDecision() {{ try {{ await post(`/api/workshop/processes/${{processId}}/diagnosis-decision`, {{main_diagnosis:payloadValue("#decisionDiagnosis"), intervention_type:payloadValue("#decisionType"), affected_system:payloadValue("#decisionSystem"), severity:payloadValue("#decisionSeverity"), probable_cause:payloadValue("#decisionCause"), diagnosis_observation:payloadValue("#decisionObs"), vehicle_can_circulate:payloadValue("#decisionCirculate"), needs_repair:document.querySelector("#decisionNeedsRepair").checked, needs_budget:document.querySelector("#decisionNeedsBudget").checked, needs_approval:document.querySelector("#decisionNeedsApproval").checked, potential_customer_charge:document.querySelector("#decisionCharge").checked, warranty:document.querySelector("#decisionWarranty").checked, charge_reason:payloadValue("#decisionChargeReason"), customer_contract:payloadValue("#decisionContract"), charge_evidence_link:payloadValue("#decisionChargeEvidence"), next_action:payloadValue("#decisionNext"), create_task:document.querySelector("#decisionCreateTask").checked, next_action_responsible_user_id:Number(payloadValue("#decisionResponsible")) || null, decision_observation:payloadValue("#decisionObs")}}); showResult(true, "Decisão confirmada."); }} catch(e) {{ showResult(false, e.message); }} }}
    async function saveBudget() {{ try {{ await post(`/api/workshop/processes/${{processId}}/budget-approval`, {{supplier:payloadValue("#budgetSupplier"), request_description:payloadValue("#budgetDescription"), budget_received:document.querySelector("#budgetReceived").checked, estimated_value:Number(payloadValue("#budgetValue")) || null, budget_link:payloadValue("#budgetLink"), needs_approval:document.querySelector("#budgetNeedsApproval").checked, approval_status:payloadValue("#budgetApproval"), final_result:payloadValue("#budgetResult"), observation:payloadValue("#budgetObs")}}); showResult(true, "Orçamento guardado."); }} catch(e) {{ showResult(false, e.message); }} }}
    async function saveRepair() {{ try {{ await post(`/api/workshop/processes/${{processId}}/internal-repair`, {{execution_type:payloadValue("#repairType"), result:payloadValue("#repairResult"), intervention_description:payloadValue("#repairDescription"), final_quadrant_photo_link:payloadValue("#repairFinalPhoto"), final_km_visible:Number(payloadValue("#repairFinalKm")) || null}}); showResult(true, "Reparação guardada."); }} catch(e) {{ showResult(false, e.message); }} }}
    async function closeProcess() {{ try {{ await post(`/api/workshop/processes/${{processId}}/close`, {{final_result:payloadValue("#closeResult"), vehicle_ready:payloadValue("#closeReady"), new_vehicle_operational_status:payloadValue("#closeStatus"), final_observation:payloadValue("#closeObs") || "Fecho validado", close_with_pending_items:document.querySelector("#closePending").checked, pending_justification:payloadValue("#closePendingJustification")}}); showResult(true, "Processo fechado."); }} catch(e) {{ showResult(false, e.message); }} }}
    loadConfig().then(loadProcess).catch(e => showResult(false, e.message));
  </script>
</body>
</html>"""


@router.get("/processes-ui/{process_id}/manage-v2", response_class=HTMLResponse)
def workshop_process_manage_v2_page(process_id: int) -> str:
    return f"""<!doctype html>
<html lang="pt">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Oficina - Processo #{process_id}</title>
  <style>
    :root {{
      --bg:#f5f7f8; --panel:#fff; --line:#d9e0e5; --line2:#b8c3cc; --text:#07152d; --muted:#607083;
      --brand:#b24a34; --brand-soft:#fbf1ee; --green:#2f7d50; --green-soft:#edf7ef; --amber:#9a6711;
      --amber-soft:#fff6df; --red:#b42318; --red-soft:#fff4f2; --blue:#2f5d8c; --blue-soft:#eef5fb;
      font-family: Inter, "Segoe UI", Arial, sans-serif;
    }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--text); font-size:14px; letter-spacing:0; }}
    button, input, select, textarea, a.button {{ font:inherit; }}
    .shell {{ min-height:100vh; }}
    .topbar {{ display:flex; justify-content:space-between; gap:18px; align-items:center; padding:22px 28px; background:#fff; border-bottom:1px solid var(--line); }}
    .heading {{ display:grid; grid-template-columns:42px minmax(0,1fr); gap:16px; align-items:center; min-width:0; }}
    .back {{ display:grid; place-items:center; width:38px; height:38px; border:0; border-radius:8px; background:#fff; color:var(--text); text-decoration:none; font-size:30px; line-height:1; }}
    .back:hover {{ background:var(--brand-soft); color:#7d2f1f; }}
    h1 {{ margin:0 0 6px; font-size:26px; line-height:1.1; }}
    h2 {{ margin:0; font-size:21px; }}
    h3 {{ margin:0; font-size:17px; }}
    p {{ margin:0; }}
    .meta {{ display:flex; flex-wrap:wrap; gap:10px; align-items:center; color:var(--muted); font-weight:750; min-width:0; }}
    .meta strong {{ color:var(--text); }}
    .actions {{ display:flex; gap:10px; align-items:center; flex-wrap:wrap; justify-content:flex-end; flex:0 0 auto; }}
    .button, button {{ min-height:42px; border:1px solid var(--line2); border-radius:8px; background:#fff; color:var(--text); padding:9px 14px; font-weight:850; text-decoration:none; cursor:pointer; display:inline-flex; align-items:center; justify-content:center; gap:8px; white-space:nowrap; }}
    .button[aria-disabled="true"] {{ opacity:.48; pointer-events:none; }}
    .primary {{ background:var(--brand); border-color:var(--brand); color:#fff; }}
    .ghost {{ border-color:transparent; background:#fff; font-size:22px; width:44px; padding:0; }}
    .content {{ display:block; padding:22px 28px 42px; }}
    .main {{ display:grid; gap:16px; width:100%; }}
    .tabs {{ display:grid; grid-template-columns:repeat(8,minmax(88px,1fr)); border:1px solid var(--line); border-radius:8px; overflow:hidden; background:#fff; }}
    .tab {{ min-height:46px; border:0; border-left:1px solid var(--line); border-radius:0; background:#fff; font-size:15px; color:var(--text); position:relative; padding:8px 9px; }}
    .tab:first-child {{ border-left:0; }}
    .tab.active {{ background:var(--brand-soft); box-shadow:inset 0 0 0 1px var(--brand); color:#7d2f1f; }}
    .tab.incomplete {{ background:#fffaf1; }}
    .tab.done-phase {{ color:var(--green); background:#fbfffc; }}
    .tab-count {{ position:absolute; top:8px; right:8px; min-width:30px; height:22px; border-radius:999px; display:inline-flex; align-items:center; justify-content:center; gap:4px; padding:0 7px; background:var(--amber-soft); color:var(--amber); font-size:12px; font-weight:950; }}
    .alert-triangle {{ display:inline-block; width:0; height:0; border-left:5px solid transparent; border-right:5px solid transparent; border-bottom:9px solid var(--amber); }}
    .panel {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:20px; }}
    .phase {{ display:none; }}
    .phase.active {{ display:grid; gap:16px; }}
    .section-head {{ display:flex; justify-content:space-between; gap:12px; align-items:flex-start; }}
    .muted {{ color:var(--muted); line-height:1.45; }}
    .phase-alerts {{ display:none; border:1px solid #efd69d; border-radius:8px; background:#fffaf1; color:var(--amber); padding:10px 12px; font-weight:850; }}
    .phase-alerts.active {{ display:block; }}
    .field-alert {{ border-color:#d99b1f !important; box-shadow:0 0 0 2px rgba(217,155,31,.16); }}
    .field-note {{ display:none; color:var(--amber); font-size:12px; font-weight:850; }}
    .field-note.active {{ display:block; }}
    .form-card {{ display:grid; gap:16px; border:1px solid var(--line); border-radius:8px; background:#fff; padding:16px; }}
    .accordion {{ border:1px solid var(--line); border-radius:8px; background:#fbfcfd; padding:12px 14px; }}
    .accordion summary {{ cursor:pointer; font-weight:950; }}
    .accordion-body {{ display:grid; gap:12px; margin-top:12px; }}
    .cards {{ display:grid; grid-template-columns:repeat(2,minmax(260px,1fr)); gap:16px; }}
    .doc-card {{ display:grid; gap:14px; align-content:start; min-height:260px; border:1px solid var(--line); border-radius:8px; background:#fff; padding:18px; transition:border-color .15s, box-shadow .15s, background .15s; }}
    .doc-card.done-card {{ border-color:#cce4d2; background:#fbfffc; }}
    .doc-card.review-card {{ border-color:#efd69d; background:#fffdf8; }}
    .doc-card.danger-card {{ border-color:#e4b8b1; background:#fffafa; box-shadow:inset 4px 0 0 var(--red); }}
    .doc-top {{ display:flex; justify-content:space-between; gap:12px; align-items:flex-start; }}
    .doc-title {{ display:flex; align-items:center; gap:12px; font-size:20px; font-weight:950; }}
    .icon {{ display:grid; place-items:center; width:30px; height:30px; border:1px solid var(--line2); border-radius:7px; color:#1b2a3c; font-size:13px; font-weight:950; line-height:1; }}
    .note {{ border-radius:8px; background:#f7f8f9; padding:11px 12px; color:var(--muted); font-weight:750; }}
    .warn-note {{ background:var(--amber-soft); color:var(--amber); }}
    .mini-meta {{ display:flex; flex-wrap:wrap; gap:8px 12px; color:var(--muted); font-size:12px; font-weight:850; }}
    .compare {{ display:grid; gap:7px; border:1px solid var(--line); border-radius:8px; background:#fbfcfd; padding:10px 12px; }}
    .compare div {{ display:flex; justify-content:space-between; gap:12px; }}
    .compare strong {{ color:#c94f3d; text-align:right; }}
    .doc-controls {{ display:grid; grid-template-columns:180px minmax(0,1fr); gap:10px; }}
    .doc-controls input {{ display:none; }}
    .doc-controls.need-link input {{ display:block; }}
    label {{ display:grid; gap:6px; color:var(--muted); font-weight:800; }}
    input, select, textarea {{ width:100%; min-height:42px; border:1px solid var(--line2); border-radius:8px; background:#fff; color:var(--text); padding:9px 11px; font-weight:750; }}
    textarea {{ min-height:88px; resize:vertical; }}
    .doc-actions {{ display:flex; gap:10px; flex-wrap:wrap; margin-top:auto; }}
    .doc-actions > * {{ flex:1 1 150px; }}
    .side {{ display:none; }}
    .side .panel {{ padding:18px; }}
    .side-title {{ display:flex; align-items:center; gap:10px; margin-bottom:14px; }}
    .chip {{ display:inline-flex; align-items:center; justify-content:center; width:max-content; max-width:100%; min-height:28px; border-radius:999px; padding:4px 11px; background:#eef1f3; color:var(--muted); font-size:12px; font-weight:900; }}
    .done {{ color:var(--green); background:var(--green-soft); }}
    .review {{ color:var(--amber); background:var(--amber-soft); }}
    .danger {{ color:var(--red); background:var(--red-soft); }}
    .progress {{ color:var(--blue); background:var(--blue-soft); }}
    .neutral {{ color:var(--muted); background:#eef1f3; }}
    .list {{ display:grid; gap:10px; margin:0; padding:0; list-style:none; }}
    .list li {{ display:flex; justify-content:space-between; align-items:center; gap:12px; border:1px solid var(--line); border-radius:8px; background:#fbfcfd; padding:12px; font-weight:800; }}
    .alert-item {{ display:grid !important; grid-template-columns:10px minmax(0,1fr) auto; align-items:center; }}
    .alert-dot {{ width:8px; height:8px; border-radius:50%; background:var(--amber); }}
    .alert-item.danger-alert .alert-dot {{ background:var(--red); }}
    .folder-path {{ border:1px solid var(--line); border-radius:8px; background:#fbfcfd; padding:12px; overflow-wrap:anywhere; color:var(--text); font-weight:800; font-size:13px; line-height:1.35; }}
    .grid2 {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }}
    .grid3 {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; }}
    .service-row, .report-row {{ display:flex; justify-content:space-between; gap:12px; align-items:center; border:1px solid var(--line); border-radius:8px; padding:12px; background:#fbfcfd; }}
    .result {{ display:none; border-radius:8px; border:1px solid var(--line); padding:12px; }}
    .result.active {{ display:block; }}
    .result.ok {{ background:var(--green-soft); border-color:#b7d7be; }}
    .result.err {{ background:var(--red-soft); border-color:#e2b7b3; }}
    .placeholder {{ border:1px dashed var(--line2); border-radius:8px; padding:20px; background:#fbfcfd; color:var(--muted); font-weight:800; }}
    @media (max-width:1200px) {{ .tabs {{ grid-template-columns:repeat(4,1fr); }} }}
    @media (max-width:820px) {{ .topbar,.section-head {{ display:grid; }} .content {{ padding:16px; }} .cards,.grid2,.grid3,.doc-controls {{ grid-template-columns:1fr; }} .tabs {{ grid-template-columns:1fr 1fr; }} }}
  </style>
</head>
<body>
  <div class="shell">
    <header class="topbar">
      <div id="header" class="heading"><a class="back" href="/workshop/processes-ui">‹</a><div><h1>Oficina - Processo #{process_id}</h1><div class="meta">A carregar...</div></div></div>
      <div class="actions"><button type="button" onclick="copyFolder()"><span class="icon">PA</span>Abrir pasta</button><button type="button" onclick="copyFolder()">Copiar caminho</button><button class="ghost" type="button">...</button></div>
    </header>
    <main class="content">
      <div class="main">
        <nav id="tabs" class="tabs"></nav>
        <section id="history" class="panel phase">
          <div class="section-head"><div><h2>Documentos esperados</h2><p class="muted">Anexe e valide os documentos necessários para esta fase.</p></div><button class="primary" type="button" onclick="saveHistory()">Guardar verificações</button></div>
          <div id="historyAlerts" class="phase-alerts"></div>
          <div class="cards">
            <article id="serviceBoxCard" class="doc-card">
              <div class="doc-top"><div class="doc-title"><span class="icon">SB</span>Service Box</div><span id="serviceBoxChip" class="chip review">Em falta</span></div>
              <p class="muted">Comprovativo da consulta do Service Box da viatura.</p>
              <div id="serviceBoxMeta" class="mini-meta">Sem documento anexado</div>
              <div class="note">Obrigatório para viaturas Stellantis.</div>
              <div id="serviceBoxControls" class="doc-controls"><label>Estado<select id="serviceBox"><option value="pending_review">Por rever</option><option value="no">Não</option><option value="not_applicable">Não aplicável</option><option value="evidence_link">Link para print</option></select></label><label>Print<input id="serviceBoxLink" placeholder="https://..."></label></div>
              <div class="doc-actions"><button class="primary" type="button" onclick="markLink('serviceBox')">Anexar print</button><a id="serviceBoxOpen" class="button" target="_blank" rel="noopener">Abrir documento</a></div>
            </article>
            <article id="campaignsCard" class="doc-card">
              <div class="doc-top"><div class="doc-title"><span class="icon">CP</span>Campanhas</div><span id="campaignsChip" class="chip review">Por validar</span></div>
              <p class="muted">Comprovativo da verificação de campanhas em aberto.</p>
              <div id="campaignsMeta" class="mini-meta">Sem documento anexado</div>
              <div class="note">Registar print ou indicar que não existem campanhas aplicáveis.</div>
              <div id="campaignsControls" class="doc-controls"><label>Estado<select id="campaigns"><option value="pending_review">Por rever</option><option value="no">Não</option><option value="not_applicable">Não aplicável</option><option value="evidence_link">Link para print</option></select></label><label>Print<input id="campaignsLink" placeholder="https://..."></label></div>
              <div class="doc-actions"><button class="primary" type="button" onclick="saveHistory()">Validar</button><a id="campaignsOpen" class="button" target="_blank" rel="noopener">Abrir documento</a></div>
            </article>
            <article id="planCard" class="doc-card">
              <div class="doc-top"><div class="doc-title"><span class="icon">PM</span>Plano manutenção</div><span id="planChip" class="chip review">Por rever</span></div>
              <p class="muted">Plano de manutenção da marca vs. plano parametrizado no Rentway.</p>
              <div id="planMeta" class="mini-meta">Sem documento anexado</div>
              <div id="planCompare" class="compare"><div><span>Service Box</span><strong>Por validar</strong></div><div><span>Rentway</span><strong>Por validar</strong></div></div>
              <div id="planNote" class="note warn-note">Valide o relatório de plano para confirmar se existe divergência.</div>
              <div id="planControls" class="doc-controls"><label>Estado<select id="plan"><option value="pending_review">Por rever</option><option value="no">Não</option><option value="not_applicable">Não aplicável</option><option value="evidence_link">Link para print</option></select></label><label>Print<input id="planLink" placeholder="https://..."></label></div>
              <div class="doc-actions"><button class="primary" type="button" onclick="markLink('plan')">Anexar plano</button><a id="planOpen" class="button" target="_blank" rel="noopener">Abrir documento</a></div>
            </article>
            <article id="internalCard" class="doc-card">
              <div class="doc-top"><div class="doc-title"><span class="icon">HI</span>Histórico interno</div><span id="internalChip" class="chip review">Por rever</span></div>
              <p class="muted">Relatório do histórico interno da viatura e intervenções relevantes.</p>
              <div id="internalMeta" class="mini-meta">A validar pela equipa</div>
              <div class="doc-controls"><label>Consulta<select id="internal"><option value="pending_review">Por rever</option><option value="yes">Sim</option><option value="no">Não</option></select></label></div>
              <div class="doc-actions"><button class="primary" type="button" onclick="saveHistory()">Validar</button></div>
            </article>
          </div>
          <details class="panel" style="padding:14px"><summary style="font-weight:900;cursor:pointer">Outras verificações</summary><div class="grid2" style="margin-top:14px"><label>Accident reports<select id="accidents"><option value="no">Não</option><option value="yes">Sim</option><option value="pending_review">Por rever</option></select></label><label>Processos anteriores<select id="previous"><option value="yes">Sim</option><option value="none">Não existem</option><option value="pending_review">Por rever</option></select></label></div><label>Detalhe accident reports<input id="accidentsDetail"></label><div class="grid2"><label>Incidência repetida<select id="repeat"><option value="no">Não</option><option value="yes">Sim</option><option value="pending_review">Por avaliar</option></select></label><label>Observação<textarea id="historyObs"></textarea></label></div></details>
        </section>
        <section id="services" class="panel phase"><div class="section-head"><div><h2>Serviços a executar</h2><p class="muted">Adicionar trabalhos que surjam depois da criação do processo.</p></div><button class="primary" onclick="addService()">Adicionar serviço</button></div><div id="servicesAlerts" class="phase-alerts"></div><div id="serviceList" class="list"></div><div class="grid3"><label>Serviço<select id="serviceCode"></select></label><label>Zona / sistema<input id="serviceZone" placeholder="Motor, travagem, pneus..."></label><label>Detalhe<input id="serviceDetail" placeholder="Descrição do trabalho"></label></div><label>Observação curta<textarea id="serviceObservation" placeholder="Motivo, evidência, indicação do técnico..."></textarea></label></section>
        <section id="reports" class="panel phase"><div class="section-head"><div><h2>Relatórios técnicos</h2><p class="muted">Selecione um relatório existente ou adicione um novo para validação.</p></div></div><div id="reportsAlerts" class="phase-alerts"></div><div id="reportList" class="list"></div><div class="grid3"><label>Relatório<select id="reportCode"></select></label><label>Momento<select id="reportMoment"><option value="initial">Inicial</option><option value="final">Final</option></select></label><label>Origem<select id="reportOrigin"><option value="stellantis_machine">Máquina Stellantis</option><option value="autel">Autel</option><option value="other">Outro</option></select></label></div><label>Link relatório original<input id="reportLink" placeholder="https://..."></label><div class="grid2"><label>Valores extraídos JSON<textarea id="reportValues" placeholder='{{"campo":"valor"}}'></textarea></label><label>Valores validados JSON<textarea id="validateValues" placeholder='{{"campo":"valor"}}'></textarea></label></div><div class="actions" style="justify-content:flex-start"><button class="primary" onclick="addReport()">Adicionar relatório</button><button onclick="validateSelectedReport()">Validar selecionado</button><a id="reportOpen" class="button" target="_blank" rel="noopener">Abrir original</a></div></section>
        <section id="reception" class="panel phase active">
          <div class="section-head"><div><h2>Receção</h2><p class="muted">Registar apenas os dados necessários para iniciar o processo.</p></div><div class="actions"><button onclick="saveReception()">Guardar</button><button class="primary" onclick="advanceReception()">Avançar</button></div></div>
          <div id="receptionAlerts" class="phase-alerts"></div>
          <div class="form-card">
            <h3>Dados principais</h3>
            <div class="grid3">
              <label>Responsável<input id="recResponsible" placeholder="Responsável pela receção"><span id="recResponsibleNote" class="field-note">Responsável em falta.</span></label>
              <label>Data entrada<input id="recDate" readonly></label>
              <label>Quilómetros<input id="recKm" type="number" min="0"><span id="recKmNote" class="field-note">Quilómetros em falta.</span></label>
            </div>
            <label>Observação inicial<textarea id="recObs" placeholder="Observação curta da entrada"></textarea><span id="recObsNote" class="field-note">Observação inicial em falta.</span></label>
          </div>
          <details class="accordion"><summary>Dados do cliente</summary><div class="accordion-body grid2"><label>Origem<input id="recOrigin" readonly></label><label>Unidade Rentway<input id="recUnit" readonly></label></div></details>
          <details class="accordion"><summary>Estado da viatura</summary><div class="accordion-body grid2"><label>Estado visual<select id="recVisual"><option value="">Selecionar</option><option>Sem danos aparentes</option><option>Com danos ligeiros</option><option>Com danos relevantes</option><option>Não verificado</option></select></label><label>Descrição danos<input id="recDamage" placeholder="Descrição resumida"></label></div></details>
          <details class="accordion"><summary>Fotografias</summary><div class="accordion-body"><label>Foto quadrante inicial<input id="recPhoto" placeholder="https://..."><span id="recPhotoNote" class="field-note">Foto do quadrante em falta.</span></label></div></details>
          <details class="accordion"><summary>Outros dados da receção</summary><div class="accordion-body"><div class="placeholder">Campos administrativos adicionais podem ser migrados aqui sem pesar a entrada principal.</div></div></details>
        </section>
        <section id="decision" class="panel phase"><h2>Decisão</h2><div class="placeholder">Diagnóstico e decisão serão migrados para cartões de decisão e responsabilidade.</div></section>
        <section id="budget" class="panel phase"><h2>Orçamento</h2><div class="placeholder">Orçamentos e aprovações serão migrados para uma grelha compacta.</div></section>
        <section id="repair" class="panel phase"><h2>Reparação</h2><div class="placeholder">Execução e evidências finais serão migradas mantendo os mesmos endpoints.</div></section>
        <section id="close" class="panel phase"><h2>Fecho</h2><div class="placeholder">Fecho definitivo e relatório de saída serão migrados no mesmo layout.</div></section>
        <div id="result" class="result"></div>
      </div>
    </main>
  </div>
  <script>
    const processId = {process_id};
    let processData = null;
    let config = null;
    let selectedReportId = null;
    let selectedReportType = null;
    const tabs = [
      ["reception","Receção","administrative_reception"], ["services","Serviços",null], ["history","Verificações","history_check"], ["reports","Relatórios","technical_phase"],
      ["decision","Decisão","diagnosis_decision"], ["budget","Orçamento","budget_approval"], ["repair","Reparação","internal_repair_execution"], ["close","Fecho","final_closure"]
    ];
    const phaseLabels = {{process_creation:"Criação do processo", administrative_reception:"Receção administrativa", history_check:"Verificações", technical_phase:"Fase técnica", diagnosis_decision:"Diagnóstico e decisão", budget_approval:"Orçamento / aprovação", internal_repair_execution:"Reparação interna / execução", final_closure:"Fecho definitivo"}};
    const statusLabels = {{completed:["Concluído","done"], completed_with_pending_items:["Concluído com pendências","review"], validated:["Validado","done"], open:["Aberto","review"], in_progress:["Em curso","progress"], pending_review:["Por rever","review"], pending_validation:["Por validar","review"], added:["Adicionado","progress"], not_applicable:["Não aplicável","neutral"], not_started:["Não iniciado","neutral"], defined:["Definida","done"], high:["Alta","danger"], critical:["Crítica","danger"]}};
    const valueLabels = {{yes:"Sim", no:"Não", none:"Não existem", pending_review:"Por rever", not_applicable:"Não aplicável", evidence_link:"Link para print", initial:"Inicial", final:"Final", stellantis_machine:"Máquina Stellantis", autel:"Autel", other:"Outro"}};
    const $ = (id) => document.querySelector(id);
    function safe(value) {{ return String(value ?? "-").replace(/[&<>"']/g, c => c === "&" ? "&amp;" : c === "<" ? "&lt;" : c === ">" ? "&gt;" : c === '"' ? "&quot;" : "&#39;"); }}
    function value(id) {{ return $(id)?.value || ""; }}
    function setValue(id, val) {{ const el = $(id); if (el && val !== null && val !== undefined) el.value = val; }}
    function meta(code) {{ return statusLabels[code] || [code || "-", "neutral"]; }}
    function chip(code) {{ const m = meta(code); return `<span class="chip ${{m[1]}}">${{safe(m[0])}}</span>`; }}
    function label(v) {{ return valueLabels[v] || v || "-"; }}
    function objectValues(v) {{ return v && typeof v === "object" && !Array.isArray(v) ? v : {{}}; }}
    function showResult(ok, message) {{ const r = $("#result"); r.className = `result active ${{ok ? "ok" : "err"}}`; r.textContent = typeof message === "string" ? message : JSON.stringify(message); }}
    async function requestJson(url, method, body) {{ const res = await fetch(url, {{method, headers:{{"Content-Type":"application/json"}}, body:JSON.stringify(body)}}); const data = await res.json(); if(!res.ok) throw new Error(JSON.stringify(data.detail || data)); await loadProcess(); return data; }}
    function phaseByCode(code) {{ return processData?.phases?.find(p => p.phase_code === code) || null; }}
    function alertsForPhase(code) {{ const phase = phaseByCode(code); return (processData?.alerts || []).filter(a => a.phase_id === phase?.id || a.source === code); }}
    function tabForPhase(code) {{ return tabs.find(([, , phase]) => phase === code)?.[0] || "reception"; }}
    function phaseStatus(code) {{ return phaseByCode(code)?.status || ""; }}
    function renderTabs(active=tabForPhase(processData?.current_phase_code)) {{ $("#tabs").innerHTML = tabs.map(([id,labelText,phase]) => {{ const alerts = phase ? alertsForPhase(phase) : []; const done = phase && ["completed","validated","completed_with_pending_items"].includes(phaseStatus(phase)); return `<button class="tab ${{id === active ? "active" : ""}} ${{alerts.length ? "incomplete" : ""}} ${{done ? "done-phase" : ""}}" onclick="showTab('${{id}}')">${{done ? "✓ " : ""}}${{safe(labelText)}}${{alerts.length ? `<span class="tab-count" aria-label="${{alerts.length}} alertas"><span class="alert-triangle"></span>${{alerts.length}}</span>` : ""}}</button>`; }}).join(""); }}
    function renderPhaseAlerts(id) {{
      const tab = tabs.find(item => item[0] === id);
      const phase = tab?.[2];
      const holder = $(`#${{id}}Alerts`);
      if (!holder) return;
      const alerts = phase ? alertsForPhase(phase) : [];
      holder.classList.toggle("active", Boolean(alerts.length));
      holder.textContent = alerts.length ? alerts.map(a => a.message).join(" · ") : "";
    }}
    function setFieldAlert(fieldId, noteId, active) {{
      const field = $(fieldId);
      const note = $(noteId);
      if (field) field.classList.toggle("field-alert", Boolean(active));
      if (note) note.classList.toggle("active", Boolean(active));
    }}
    function highlightMissingFields(id) {{
      setFieldAlert("#recObs", "#recObsNote", false);
      setFieldAlert("#recPhoto", "#recPhotoNote", false);
      setFieldAlert("#recKm", "#recKmNote", false);
      setFieldAlert("#recResponsible", "#recResponsibleNote", false);
      if (id !== "reception") return;
      const alerts = alertsForPhase("administrative_reception");
      const text = alerts.map(a => `${{a.code || ""}} ${{a.message || ""}}`).join(" ").toLowerCase();
      setFieldAlert("#recObs", "#recObsNote", text.includes("observ"));
      setFieldAlert("#recPhoto", "#recPhotoNote", text.includes("foto") || text.includes("quadrante"));
      setFieldAlert("#recKm", "#recKmNote", text.includes("km") || text.includes("quil"));
      setFieldAlert("#recResponsible", "#recResponsibleNote", text.includes("respons"));
    }}
    function showTab(id) {{
      document.querySelectorAll(".phase,.tab").forEach(el => el.classList.remove("active"));
      $(`#${{id}}`)?.classList.add("active");
      renderTabs(id);
      renderPhaseAlerts(id);
      highlightMissingFields(id);
    }}
    function docStatus(value, link, emptyLabel="Em falta") {{ if (value === "not_applicable") return ["Não aplicável","neutral"]; if (value === "no" || value === "yes") return ["Validado","done"]; if (value === "evidence_link" && link) return ["Por validar","review"]; if (value === "evidence_link") return [emptyLabel,"danger"]; return [emptyLabel,"review"]; }}
    function setChip(id, data) {{ const el = $(id); if (!el) return; el.textContent = data[0]; el.className = `chip ${{data[1]}}`; }}
    function setCardState(id, tone) {{
      const el = $(id);
      if (!el) return;
      el.classList.remove("done-card", "review-card", "danger-card");
      el.classList.add(tone === "done" ? "done-card" : tone === "danger" ? "danger-card" : "review-card");
    }}
    function setMeta(id, text) {{ const el = $(id); if (el) el.textContent = text; }}
    function updateOpen(id, link) {{
      const a = $(id);
      if (!a) return;
      if (link) {{ a.href = link; a.removeAttribute("aria-disabled"); }}
      else {{ a.removeAttribute("href"); a.setAttribute("aria-disabled", "true"); }}
    }}
    function renderVerificationCards() {{
      [["#serviceBox","#serviceBoxControls"],["#campaigns","#campaignsControls"],["#plan","#planControls"]].forEach(([select,controls]) => $(controls)?.classList.toggle("need-link", value(select) === "evidence_link"));
      const serviceBoxStatus = docStatus(value("#serviceBox"), value("#serviceBoxLink"));
      const campaignsStatus = docStatus(value("#campaigns"), value("#campaignsLink"));
      const internalStatus = docStatus(value("#internal"), "", "Por rever");
      setChip("#serviceBoxChip", serviceBoxStatus);
      setChip("#campaignsChip", campaignsStatus);
      setChip("#internalChip", internalStatus);
      setCardState("#serviceBoxCard", serviceBoxStatus[1]);
      setCardState("#campaignsCard", campaignsStatus[1]);
      setCardState("#internalCard", internalStatus[1]);
      setMeta("#serviceBoxMeta", value("#serviceBoxLink") ? "Documento anexado para validação" : "Sem documento anexado");
      setMeta("#campaignsMeta", value("#campaignsLink") ? "Documento anexado para validação" : "Sem documento anexado");
      setMeta("#internalMeta", value("#internal") === "yes" ? "Verificação interna confirmada" : value("#internal") === "no" ? "Não validado" : "A validar pela equipa");
      const report = [...(processData?.technical_reports || [])].filter(r => r.report_code === "maintenance_plan_validation").sort((a,b) => b.id - a.id)[0];
      const vals = objectValues(report?.validated_values || report?.extracted_values);
      const serviceBox = [vals.servicebox_plan, vals.servicebox_interval_km ? `${{vals.servicebox_interval_km}} km` : "", vals.servicebox_interval_months ? `${{vals.servicebox_interval_months}} meses` : ""].filter(Boolean).join(" / ") || "Por validar";
      const rentway = [vals.rentway_plan, vals.rentway_interval_km ? `${{vals.rentway_interval_km}} km` : "", vals.rentway_interval_months ? `${{vals.rentway_interval_months}} meses` : ""].filter(Boolean).join(" / ") || "Por validar";
      $("#planCompare").innerHTML = `<div><span>Service Box</span><strong>${{safe(serviceBox)}}</strong></div><div><span>Rentway</span><strong>${{safe(rentway)}}</strong></div>`;
      const mismatch = (processData?.alerts || []).some(a => ["rentway_maintenance_plan_mismatch","maintenance_request_plan_mismatch"].includes(a.code));
      const planStatus = mismatch ? ["Divergente","danger"] : docStatus(value("#plan"), value("#planLink"));
      setChip("#planChip", planStatus);
      setCardState("#planCard", planStatus[1]);
      setMeta("#planMeta", value("#planLink") ? "Documento anexado para validação" : (report ? "Relatório de plano registado" : "Sem documento anexado"));
      $("#planNote").textContent = mismatch ? "Existe divergência entre os planos." : (report ? "Plano registado. Confirme se bate certo com Rentway." : "Valide o relatório de plano para confirmar se existe divergência.");
      updateOpen("#serviceBoxOpen", value("#serviceBoxLink")); updateOpen("#campaignsOpen", value("#campaignsLink")); updateOpen("#planOpen", value("#planLink")); updateOpen("#reportOpen", value("#reportLink"));
    }}
    function markLink(prefix) {{ $(`#${{prefix}}`).value = "evidence_link"; renderVerificationCards(); }}
    function renderHeader() {{ const v = processData.vehicle || {{}}; const model = [v.brand, v.model, v.version].filter(Boolean).join(" "); const status = meta(processData.status); const current = phaseLabels[processData.current_phase_code] || processData.current_phase_code || "-"; $("#header").innerHTML = `<a class="back" href="/workshop/processes-ui">‹</a><div><h1>Oficina - Processo #${{processData.id}}</h1><div class="meta"><span><strong>${{safe(v.plate || processData.plate)}}</strong></span><span>|</span><span>VIN ${{safe(v.vin || "-")}}</span><span>|</span><span>${{safe(model || "Dados da viatura por completar")}}</span><span>|</span><span>Unidade ${{safe(v.rentway_unit_nr || "-")}}</span><span>|</span><span>${{safe(processData.initial_km || "-")}} km</span><span>|</span><span>Estado: <strong>${{safe(status[0])}}</strong></span><span>|</span><span>Fase atual: <strong>${{safe(current)}}</strong></span></div></div>`; }}
    function renderSidebar() {{
      const folder = processData.document_folder || {{}};
      if ($("#folderPath")) $("#folderPath").textContent = folder.path || "Pasta por definir";
      if ($("#alertCount")) $("#alertCount").textContent = processData.alerts?.length || 0;
      if ($("#alerts")) $("#alerts").innerHTML = "";
      if ($("#documentCount")) $("#documentCount").textContent = processData.technical_reports?.length || 0;
    }}
    function renderServices() {{ $("#serviceList").innerHTML = (processData.services || []).map(s => `<div class="service-row"><div><strong>${{safe(s.service_label)}}</strong><p class="muted">${{safe([s.zone,s.detail,s.short_observation].filter(Boolean).join(" · "))}}</p></div><span class="chip neutral">#${{s.sort_order || s.id}}</span></div>`).join("") || `<div class="placeholder">Sem serviços registados.</div>`; }}
    function reportName(code) {{ return (config?.stellantis_reports || []).find(r => r.code === code)?.label || code || "Relatório"; }}
    function renderReports() {{ const reports = processData.technical_reports || []; $("#reportList").innerHTML = reports.map(r => `<button class="report-row" onclick="selectReport(${{r.id}})"><span><strong>#${{r.id}} ${{safe(r.report_name || reportName(r.report_code))}}</strong><p class="muted">${{safe(label(r.report_moment))}} · ${{safe(label(r.reading_origin))}}</p></span>${{chip(r.status)}}</button>`).join("") || `<div class="placeholder">Sem relatórios registados.</div>`; }}
    function renderReceptionValues() {{
      const v = processData.vehicle || {{}};
      const r = phaseByCode("administrative_reception")?.data || {{}};
      setValue("#recResponsible", r.responsible_name || "");
      setValue("#recDate", r.entry_date || processData.created_at || "");
      setValue("#recKm", r.km_entry || processData.initial_km || "");
      setValue("#recObs", r.initial_observation || "");
      setValue("#recOrigin", processData.source || "");
      setValue("#recUnit", v.rentway_unit_nr || "");
      setValue("#recVisual", r.visible_damage_status || "");
      setValue("#recDamage", r.damage_description || "");
      setValue("#recPhoto", r.quadrant_photo_link || "");
    }}
    function renderHistoryValues() {{ const h = phaseByCode("history_check")?.data || {{}}; setValue("#internal", h.internal_history_checked || "pending_review"); setValue("#accidents", h.open_accident_reports || "no"); setValue("#accidentsDetail", h.accident_reports_detail); setValue("#previous", h.previous_processes_reviewed || "yes"); setValue("#repeat", h.repeated_incidence || "no"); setValue("#historyObs", h.history_observation); setValue("#serviceBox", h.service_box_checked || "pending_review"); setValue("#serviceBoxLink", h.service_box_link); setValue("#campaigns", h.campaigns_checked || "pending_review"); setValue("#campaignsLink", h.campaigns_link); setValue("#plan", h.maintenance_plan_checked || "pending_review"); setValue("#planLink", h.maintenance_plan_link); renderVerificationCards(); }}
    async function loadConfig() {{ config = await (await fetch("/api/workshop/process-config")).json(); $("#serviceCode").innerHTML = (config.services || []).map(s => `<option value="${{s.code}}">${{safe(s.label)}}</option>`).join(""); $("#reportCode").innerHTML = (config.stellantis_reports || []).map(r => `<option value="${{r.code}}">${{safe(r.label)}}</option>`).join(""); ["#serviceBox","#serviceBoxLink","#campaigns","#campaignsLink","#plan","#planLink","#internal","#reportLink"].forEach(id => $(id)?.addEventListener("input", renderVerificationCards)); }}
    async function loadProcess() {{ processData = await (await fetch(`/api/workshop/processes/${{processId}}`)).json(); const active = document.querySelector(".phase.active")?.id || tabForPhase(processData.current_phase_code); renderHeader(); renderSidebar(); renderServices(); renderReports(); renderReceptionValues(); renderHistoryValues(); showTab(active); }}
    async function copyFolder() {{ const path = processData?.document_folder?.path || ""; if (!path) return showResult(false, "Pasta documental por definir."); try {{ await navigator.clipboard.writeText(path); showResult(true, "Caminho da pasta copiado."); }} catch {{ showResult(false, path); }} }}
    async function saveHistory() {{ try {{ await requestJson(`/api/workshop/processes/${{processId}}/history-check`, "POST", {{internal_history_checked:value("#internal"), open_accident_reports:value("#accidents"), accident_reports_detail:value("#accidentsDetail"), previous_processes_reviewed:value("#previous"), relevant_interventions_identified:"no", repeated_incidence:value("#repeat"), service_box_checked:value("#serviceBox"), service_box_link:value("#serviceBoxLink"), campaigns_checked:value("#campaigns"), campaigns_link:value("#campaignsLink"), maintenance_plan_checked:value("#plan"), maintenance_plan_link:value("#planLink"), history_observation:value("#historyObs")}}); showResult(true, "Verificações guardadas."); }} catch(e) {{ showResult(false, e.message); }} }}
    async function saveReception() {{ try {{ await requestJson(`/api/workshop/processes/${{processId}}/reception`, "POST", {{km_entry:Number(value("#recKm")) || null, quadrant_photo_link:value("#recPhoto"), initial_observation:value("#recObs"), visible_damage_status:value("#recVisual"), damage_description:value("#recDamage")}}); showResult(true, "Receção guardada."); }} catch(e) {{ showResult(false, e.message); }} }}
    async function advanceReception() {{ await saveReception(); showTab("services"); }}
    async function addService() {{ try {{ await requestJson(`/api/workshop/processes/${{processId}}/services`, "POST", {{service_code:value("#serviceCode"), zone:value("#serviceZone"), detail:value("#serviceDetail"), short_observation:value("#serviceObservation")}}); setValue("#serviceZone",""); setValue("#serviceDetail",""); setValue("#serviceObservation",""); showResult(true, "Serviço adicionado."); }} catch(e) {{ showResult(false, e.message); }} }}
    function parseJson(id) {{ const raw = value(id); if (!raw) return {{}}; return JSON.parse(raw); }}
    function selectReport(id) {{ const r = (processData.technical_reports || []).find(item => item.id === id); if (!r) return; selectedReportId = id; setValue("#reportCode", r.report_code); setValue("#reportMoment", r.report_moment); setValue("#reportOrigin", r.reading_origin); setValue("#reportLink", r.original_link); setValue("#reportValues", JSON.stringify(r.extracted_values || {{}}, null, 2)); setValue("#validateValues", JSON.stringify(r.validated_values || r.extracted_values || {{}}, null, 2)); renderVerificationCards(); showTab("reports"); }}
    async function addReport() {{ try {{ const data = await requestJson(`/api/workshop/processes/${{processId}}/technical-reports`, "POST", {{report_code:value("#reportCode"), report_moment:value("#reportMoment"), reading_origin:value("#reportOrigin"), original_link:value("#reportLink"), extracted_values:parseJson("#reportValues")}}); selectedReportId = data.id; showResult(true, `Relatório #${{data.id}} adicionado.`); }} catch(e) {{ showResult(false, e.message); }} }}
    async function validateSelectedReport() {{ try {{ if (!selectedReportId) throw new Error("Selecione um relatório antes de validar."); await requestJson(`/api/workshop/technical-reports/${{selectedReportId}}/validate`, "POST", {{validated_values:parseJson("#validateValues")}}); showResult(true, `Relatório #${{selectedReportId}} validado.`); }} catch(e) {{ showResult(false, e.message); }} }}
    loadConfig().then(loadProcess).catch(e => showResult(false, e.message));
  </script>
</body>
</html>"""


@router.get("/processes-ui/{process_id}/manage-v3", response_class=HTMLResponse)
def workshop_process_manage_v3_page(process_id: int) -> str:
    html = """<!doctype html>
<html lang="pt">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Oficina - Processo #__PROCESS_ID__</title>
  <style>
    :root {
      --bg:#f5f7f8; --surface:#fff; --surface-soft:#f9fafb; --line:#dce2e7; --line-strong:#b8c3cc;
      --text:#07152d; --muted:#607083; --brand:#b24a34; --brand-soft:#fbf1ee;
      --green:#2f7d50; --green-soft:#edf7ef; --amber:#9a6711; --amber-soft:#fff6df;
      --red:#b42318; --red-soft:#fff4f2; --blue:#2f5d8c; --blue-soft:#eef5fb;
      font-family:Inter, "Segoe UI", Arial, sans-serif;
    }
    * { box-sizing:border-box; }
    body { margin:0; background:var(--bg); color:var(--text); font-size:14px; letter-spacing:0; }
    button, input, select, textarea, a { font:inherit; }
    button, .button {
      min-height:38px; border:1px solid var(--line-strong); border-radius:8px; background:#fff; color:var(--text);
      padding:8px 14px; font-weight:800; text-decoration:none; cursor:pointer; display:inline-flex; align-items:center; justify-content:center; gap:8px;
    }
    button.primary, .button.primary { background:var(--brand); border-color:var(--brand); color:#fff; }
    button.ghost { border-color:transparent; background:transparent; }
    button:disabled, .button[aria-disabled="true"] { opacity:.45; pointer-events:none; }
    h1, h2, h3, p { margin:0; }
    h1 { font-size:30px; line-height:1.12; }
    h2 { font-size:21px; }
    h3 { font-size:16px; }
    label { display:grid; gap:7px; color:var(--text); font-weight:850; }
    label .required { color:#d63f32; }
    input, select, textarea {
      width:100%; min-height:44px; border:1px solid var(--line-strong); border-radius:8px; background:#fff;
      color:var(--text); padding:10px 12px; font-weight:700;
    }
    textarea { min-height:92px; resize:vertical; }
    details { border:1px solid var(--line); border-radius:8px; background:#fff; padding:0; overflow:hidden; }
    summary { cursor:pointer; font-weight:900; list-style:none; min-height:52px; display:flex; align-items:center; justify-content:space-between; padding:0 18px; }
    summary::-webkit-details-marker { display:none; }
    summary::after { content:"⌄"; font-size:22px; color:var(--text); line-height:1; }
    summary span { display:inline-flex; align-items:center; gap:12px; }
    .shell { min-height:100vh; }
    .brandbar {
      height:58px; display:grid; grid-template-columns:auto minmax(0,1fr) auto; gap:18px; align-items:center;
      padding:0 22px; background:#fff; border-bottom:1px solid var(--line); box-shadow:0 1px 4px rgba(15,23,42,.04);
    }
    .hamburger { width:28px; min-height:28px; border:0; padding:0; background:transparent; font-size:26px; font-weight:900; }
    .brand { color:#d83228; font-size:28px; font-weight:950; letter-spacing:.02em; line-height:1; }
    .brand-actions { display:flex; gap:10px; align-items:center; justify-content:flex-end; }
    .brand-actions button, .brand-actions .button { min-width:142px; min-height:46px; background:#fff; border-color:var(--line); box-shadow:0 1px 3px rgba(15,23,42,.05); }
    .brand-actions .ghost { min-width:36px; width:36px; border-color:transparent; box-shadow:none; font-size:24px; padding:0; }
    .topbar {
      display:grid; grid-template-columns:minmax(0,1fr); gap:16px; align-items:start;
      padding:28px 30px 26px; background:#fff; border-bottom:1px solid var(--line);
    }
    .titlebar { display:grid; grid-template-columns:auto minmax(0,1fr); gap:12px; align-items:start; min-width:0; }
    .back {
      width:34px; min-height:42px; padding:0; border-color:transparent; background:#fff; color:var(--text);
      border-radius:8px; font-size:34px; font-weight:400; line-height:1;
    }
    .back:hover { background:var(--brand-soft); color:#7d2f1f; }
    .meta {
      display:flex; flex-wrap:wrap; gap:8px 10px; align-items:center; margin-top:6px;
      color:var(--muted); font-weight:760; line-height:1.45;
    }
    .meta strong { color:var(--text); }
    .actions { display:flex; gap:8px; align-items:center; justify-content:flex-end; flex-wrap:wrap; }
    .content { padding:0 0 38px; }
    .workspace { display:grid; gap:22px; max-width:none; margin:0; }
    .stepper {
      display:grid; grid-template-columns:repeat(8,minmax(108px,1fr)); overflow:hidden;
      border:0; border-bottom:1px solid var(--line); border-radius:0; background:#fff; padding:22px 30px 0;
    }
    .step {
      position:relative; min-height:138px; border:0; border-radius:0; background:#fff;
      color:var(--text); padding:0 8px 30px; font-size:14px; font-weight:800; white-space:nowrap;
      display:grid; justify-items:center; align-content:start; gap:12px;
    }
    .step::before { content:""; position:absolute; top:30px; left:-50%; right:50%; height:2px; background:#e2e7ec; z-index:0; }
    .step:first-child::before { display:none; }
    .step.active { color:var(--brand); }
    .step.active::after { content:""; position:absolute; left:0; right:0; bottom:0; height:4px; background:#dc3328; }
    .step.done { color:var(--green); }
    .step.warn { background:#fffdf8; }
    .step-icon {
      position:relative; z-index:1; display:grid; place-items:center; width:62px; height:62px; border-radius:50%;
      border:2px solid #dfe5ea; background:#fff; color:#172033; font-size:22px; font-weight:800;
      box-shadow:0 1px 3px rgba(15,23,42,.04);
    }
    .step.active .step-icon { border-color:#dc3328; color:#dc3328; box-shadow:0 0 0 4px #fff; }
    .step-label { font-weight:850; font-size:15px; }
    .step .count {
      position:absolute; top:26px; right:18%; min-width:24px; height:21px; border-radius:999px;
      display:inline-flex; align-items:center; justify-content:center; gap:4px; padding:0 6px;
      background:transparent; color:var(--amber); font-size:14px; font-weight:950; z-index:2;
    }
    .tri { width:0; height:0; border-left:5px solid transparent; border-right:5px solid transparent; border-bottom:9px solid var(--amber); }
    .panel { background:#fff; border:1px solid var(--line); border-radius:8px; padding:24px 26px; margin:0 28px; }
    .phase { display:none; }
    .phase.active { display:grid; gap:16px; }
    .phase-head { display:flex; justify-content:space-between; align-items:flex-start; gap:16px; }
    .phase-title { display:grid; grid-template-columns:56px minmax(0,1fr); gap:14px; align-items:center; }
    .phase-title-icon { display:grid; place-items:center; width:44px; height:44px; border-radius:50%; background:#dc3328; color:#fff; font-size:22px; }
    .muted { color:var(--muted); line-height:1.45; }
    .chip {
      display:inline-flex; align-items:center; justify-content:center; width:max-content; max-width:100%;
      min-height:26px; border-radius:999px; padding:4px 10px; background:#eef1f3; color:var(--muted);
      font-size:12px; font-weight:900;
    }
    .chip.done { color:var(--green); background:var(--green-soft); }
    .chip.review { color:var(--amber); background:var(--amber-soft); }
    .chip.danger { color:var(--red); background:var(--red-soft); }
    .chip.progress { color:var(--blue); background:var(--blue-soft); }
    .alert-line {
      display:none; align-items:flex-start; gap:10px; border:1px solid #efd69d; border-radius:8px;
      background:#fffaf1; color:var(--amber); padding:10px 12px; font-weight:850;
    }
    .alert-line.active { display:flex; }
    .grid2 { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }
    .grid3 { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:28px; }
    .main-card { display:grid; gap:18px; border:1px solid var(--line); border-radius:8px; background:#fff; padding:20px 24px; }
    .accordion-body { display:grid; gap:12px; padding:14px 16px; border-top:1px solid var(--line); }
    .field-control {
      display:grid; grid-template-columns:28px minmax(0,1fr) auto; align-items:center; gap:10px;
      min-height:46px; border:1px solid var(--line-strong); border-radius:8px; background:#fff; padding:0 12px;
    }
    .field-control input, .field-control select {
      min-height:44px; border:0; border-radius:0; background:transparent; padding:0; outline:0;
    }
    .field-control:focus-within { border-color:#9eaab5; box-shadow:0 0 0 2px rgba(96,112,131,.12); }
    .field-icon { color:#2a3648; font-size:20px; line-height:1; text-align:center; }
    .field-extra { color:var(--muted); font-weight:800; padding-left:8px; }
    .textarea-wrap { position:relative; display:grid; }
    .textarea-wrap textarea { padding-bottom:32px; }
    .char-count { position:absolute; right:14px; bottom:10px; color:var(--muted); font-size:12px; font-weight:900; }
    .accordion-icon { width:22px; color:#172033; font-size:20px; text-align:center; }
    .field-missing { border-color:#d99b1f !important; box-shadow:0 0 0 2px rgba(217,155,31,.16); }
    .field-note { display:none; color:var(--amber); font-size:12px; font-weight:850; }
    .field-note.active { display:block; }
    .list { display:grid; gap:8px; margin:0; padding:0; list-style:none; }
    .row {
      display:flex; justify-content:space-between; gap:12px; align-items:center;
      border:1px solid var(--line); border-radius:8px; background:var(--surface-soft); padding:12px;
    }
    .doc-grid { display:grid; grid-template-columns:repeat(4,minmax(190px,1fr)); gap:12px; }
    .doc {
      display:grid; gap:10px; align-content:start; border:1px solid var(--line); border-radius:8px; background:#fff; padding:14px;
    }
    .doc.review { border-color:#efd69d; background:#fffdf8; }
    .doc.done { border-color:#cce4d2; background:#fbfffc; }
    .doc.danger { border-color:#e4b8b1; background:#fffafa; box-shadow:inset 4px 0 0 var(--red); }
    .doc-title { display:flex; justify-content:space-between; gap:10px; align-items:flex-start; }
    .doc-title strong { font-size:16px; }
    .doc-code { display:grid; place-items:center; width:30px; height:30px; border:1px solid var(--line-strong); border-radius:7px; font-size:12px; font-weight:950; }
    .doc-actions { display:flex; gap:8px; flex-wrap:wrap; margin-top:auto; }
    .doc-actions > * { flex:1 1 120px; }
    .verification-board { display:grid; gap:10px; }
    .verification-stack { display:grid; grid-template-columns:repeat(2,minmax(320px,1fr)); gap:16px; align-items:start; }
    .verification-group { border:1px solid var(--line); border-radius:8px; background:#fff; padding:16px; }
    .board-title { display:flex; justify-content:space-between; align-items:flex-start; gap:12px; margin-bottom:14px; }
    .board-title h3 { margin:0; }
    .board-title p { margin-top:4px; }
    .verification-head { display:none; }
    .verification-row { display:grid; grid-template-columns:1fr; gap:0; align-items:stretch; border:1px solid var(--line); border-radius:8px; background:#fff; overflow:hidden; }
    .verification-head {
      background:var(--surface-soft); color:var(--muted); font-size:12px; font-weight:950; text-transform:uppercase;
      border-bottom:1px solid var(--line);
    }
    .verification-head span, .verification-cell { padding:12px 14px; border-bottom:1px solid var(--line); }
    .verification-cell:last-child { border-bottom:0; }
    .verification-row.done { background:#fbfffc; }
    .verification-row.review { background:#fffdf8; }
    .verification-row.danger { background:#fffafa; }
    .verification-title { display:flex; gap:12px; align-items:flex-start; }
    .verification-title p { margin-top:5px; }
    .verification-actions { display:grid; grid-template-columns:1fr 1fr; gap:8px; align-content:center; }
    .link-input { display:none; }
    .link-input.needs-link { display:grid; }
    .report-field-grid { border:1px solid var(--line); border-radius:8px; background:#fff; overflow:hidden; }
    .report-field-grid:empty { display:none; }
    .report-table-head, .report-field {
      display:grid; grid-template-columns:minmax(260px,.75fr) minmax(280px,1fr); gap:0; align-items:stretch;
    }
    .report-table-head {
      background:var(--surface-soft); color:var(--muted); font-size:12px; font-weight:950; text-transform:uppercase;
      border-bottom:1px solid var(--line);
    }
    .report-table-head span, .report-field > span, .report-field > label { padding:11px 14px; }
    .report-field { border-bottom:1px solid var(--line); }
    .report-field:last-child { border-bottom:0; }
    .report-field > span { display:grid; gap:4px; color:var(--text); font-weight:850; border-right:1px solid var(--line); }
    .report-field small { color:var(--muted); font-size:12px; font-weight:750; }
    .report-field label { display:grid; gap:6px; color:var(--muted); font-size:12px; font-weight:850; }
    .report-field input { min-height:38px; }
    .report-description { border:1px solid var(--line); border-radius:8px; background:var(--surface-soft); padding:11px 12px; color:var(--muted); font-weight:750; }
    .report-type-grid { display:grid; grid-template-columns:repeat(5,minmax(145px,1fr)); gap:8px; margin-bottom:12px; }
    .report-type-card {
      display:grid; grid-template-columns:minmax(0,1fr) auto; gap:4px 8px; align-items:center; min-height:64px;
      text-align:left; border:1px solid var(--line); border-radius:8px; background:#fff; padding:9px 10px; cursor:pointer;
    }
    .report-type-card:hover { border-color:var(--line-strong); background:var(--surface-soft); }
    .report-type-card.active { border-color:var(--brand); background:#fff8f5; box-shadow:inset 3px 0 0 var(--brand); }
    .report-type-card strong { min-width:0; font-size:13px; line-height:1.2; }
    .report-type-card .report-count { grid-row:1 / span 2; grid-column:2; font-size:22px; line-height:1; font-weight:950; color:var(--text); }
    .report-type-card .report-status-line { grid-column:1; display:block; min-width:0; color:var(--muted); font-size:11px; line-height:1.2; font-weight:850; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
    .report-instance-strip { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:14px; }
    .report-instance-strip button { min-height:34px; border-radius:999px; padding:6px 11px; font-size:12px; }
    .report-instance-strip button.active { border-color:var(--brand); background:#fff4ee; color:#7d2f1f; }
    .inline-checks { display:flex; flex-wrap:wrap; gap:12px 18px; }
    .inline-checks label { display:flex; flex-direction:row; align-items:center; gap:8px; color:var(--text); }
    .inline-checks input { width:18px; min-height:18px; }
    .phase-actions { display:flex; gap:8px; justify-content:flex-end; flex-wrap:wrap; }
    .soft-card { display:grid; gap:12px; border:1px solid var(--line); border-radius:8px; background:#fff; padding:16px; }
    .result { display:none; border:1px solid var(--line); border-radius:8px; padding:11px 12px; }
    .result.active { display:block; }
    .result.ok { background:var(--green-soft); border-color:#b7d7be; }
    .result.err { background:var(--red-soft); border-color:#e2b7b3; }
    .placeholder { border:1px dashed var(--line-strong); border-radius:8px; background:var(--surface-soft); padding:18px; color:var(--muted); font-weight:800; }
    @media (max-width:1120px) { .stepper { grid-template-columns:repeat(4,1fr); } .doc-grid { grid-template-columns:repeat(2,1fr); } .brand-actions button, .brand-actions .button { min-width:auto; } }
    @media (max-width:760px) {
      .brandbar { grid-template-columns:auto 1fr; height:auto; padding:12px 14px; }
      .brand-actions { grid-column:1 / -1; justify-content:stretch; }
      .brand-actions button, .brand-actions .button { flex:1; }
      .topbar, .phase-head { grid-template-columns:1fr; display:grid; padding:18px 14px; }
      .content { padding:0 0 24px; }
      .grid2, .grid3, .doc-grid, .report-type-grid, .report-table-head, .report-field, .verification-stack, .verification-head, .verification-row { grid-template-columns:1fr; }
      .report-field > span { border-right:0; border-bottom:1px solid var(--line); }
      .verification-head { display:none; }
      .verification-cell { border-right:0; border-bottom:1px solid var(--line); }
      .verification-cell:last-child { border-bottom:0; }
      .stepper { grid-template-columns:1fr 1fr; padding:12px 14px 0; }
      .step { min-height:112px; }
      .panel { margin:0 14px; padding:18px; }
      .actions { justify-content:flex-start; }
    }
  </style>
</head>
<body>
  <div class="shell" data-view="manage-v3">
    <header class="brandbar">
      <button class="hamburger" type="button" title="Menu">☰</button>
      <div class="brand">CARFAST</div>
      <div class="brand-actions">
        <a class="button" href="/">Menu principal</a>
        <a class="button" href="/workshop">Oficina</a>
        <a class="button" href="/workshop/processes-ui">Lista de processos</a>
        <button type="button" onclick="openFolder()">▭ Abrir pasta</button>
        <button type="button" onclick="copyFolder()">▣ Copiar caminho</button>
        <button class="ghost" type="button" title="Mais opções">⋮</button>
      </div>
    </header>
    <header class="topbar">
      <div class="titlebar">
        <button class="back" type="button" onclick="location.href='/workshop/processes-ui'" title="Voltar">‹</button>
        <div>
          <h1 id="title">Oficina - Processo #__PROCESS_ID__</h1>
          <div id="meta" class="meta">A carregar dados do processo...</div>
        </div>
      </div>
    </header>
    <main class="content">
      <div class="workspace">
        <nav id="stepper" class="stepper" aria-label="Fases do processo"></nav>

        <section id="reception" class="panel phase active">
          <div class="phase-head">
            <div class="phase-title"><span class="phase-title-icon">□</span><div><h2>Receção</h2><p class="muted">Registe as informações iniciais da entrada da viatura.</p></div></div>
            <div class="actions"><button type="button" onclick="saveReception()">Guardar</button><button class="primary" type="button" onclick="advanceReception()">Avançar</button></div>
          </div>
          <div id="receptionAlerts" class="alert-line"></div>
          <div class="main-card">
            <h3>Dados principais</h3>
            <div class="grid3">
              <label>Responsável <span class="required">*</span><span class="field-control"><span class="field-icon">♙</span><input id="recResponsible" placeholder="Selecione o responsável"><span class="field-extra">⌄</span></span><span id="recResponsibleNote" class="field-note">Responsável em falta.</span></label>
              <label>Data entrada <span class="required">*</span><span class="field-control"><span class="field-icon">▣</span><input id="recDate" readonly><span class="field-extra">▣</span></span></label>
              <label>Quilómetros <span class="required">*</span><span class="field-control"><span class="field-icon">◴</span><input id="recKm" type="number" min="0"><span class="field-extra">km</span></span><span id="recKmNote" class="field-note">Quilómetros em falta.</span></label>
            </div>
            <label>Observação inicial <span class="required">*</span><span class="textarea-wrap"><textarea id="recObs" maxlength="500" placeholder="Descreva a situação reportada pelo cliente, sintomas ou informações relevantes."></textarea><span id="recObsCounter" class="char-count">0 / 500</span></span><span id="recObsNote" class="field-note">Observação inicial em falta.</span></label>
          </div>
          <details><summary><span><span class="accordion-icon">♙</span>Dados do cliente</span></summary><div class="accordion-body grid2"><label>Origem<input id="recOrigin" readonly></label><label>Unidade Rentway<input id="recUnit" readonly></label></div></details>
          <details><summary><span><span class="accordion-icon">▱</span>Estado da viatura</span></summary><div class="accordion-body grid2"><label>Estado visual<select id="recVisual"><option value="">Selecionar</option><option>Sem danos aparentes</option><option>Com danos ligeiros</option><option>Com danos relevantes</option><option>Não verificado</option></select></label><label>Descrição danos<input id="recDamage" placeholder="Danos visíveis"></label></div></details>
          <details><summary><span><span class="accordion-icon">▣</span>Fotografias</span></summary><div class="accordion-body"><label>Foto quadrante<input id="recPhoto" placeholder="https://..."><span id="recPhotoNote" class="field-note">Foto do quadrante em falta.</span></label></div></details>
          <details><summary><span><span class="accordion-icon">＋</span>Outros dados relevantes</span></summary><div class="accordion-body"><div class="placeholder">Campos administrativos extra ficam aqui para não pesar a entrada principal.</div></div></details>
        </section>

        <section id="services" class="panel phase">
          <div class="phase-head"><div><h2>Serviços</h2><p class="muted">Trabalhos atuais e novos serviços a adicionar ao processo.</p></div><button class="primary" type="button" onclick="addService()">Adicionar serviço</button></div>
          <div id="servicesAlerts" class="alert-line"></div>
          <div id="serviceList" class="list"></div>
          <div class="grid3"><label>Serviço<select id="serviceCode"></select></label><label>Zona / sistema<input id="serviceZone" placeholder="Motor, travagem, pneus..."></label><label>Detalhe<input id="serviceDetail" placeholder="Descrição do trabalho"></label></div>
          <label>Observação curta<textarea id="serviceObservation" placeholder="Motivo, evidência, indicação do técnico..."></textarea></label>
        </section>

        <section id="checks" class="panel phase">
          <div class="phase-head"><div><h2>Verificações</h2><p class="muted">Documentos e validações esperadas nesta fase.</p></div><button class="primary" type="button" onclick="saveChecks()">Guardar verificações</button></div>
          <div id="checksAlerts" class="alert-line"></div>
          <div class="verification-stack">
            <div class="verification-group">
              <div class="board-title"><div><h3>Marca e manutenção</h3><p class="muted">Aplicável conforme marca/modelo. Se não se aplicar, marcar como Não aplicável.</p></div></div>
              <div class="verification-board">
                <div class="verification-head"><span>Documento</span><span>Aplicabilidade / estado</span><span>Evidência</span><span>Ações</span></div>
                <div id="serviceBoxCard" class="verification-row">
                  <div class="verification-cell verification-title"><span class="doc-code">SB</span><div><strong>Service Box</strong><p class="muted">Consulta Service Box ou print anexado.</p></div></div>
                  <div class="verification-cell"><label>Estado<select id="serviceBox"><option value="pending_review">Por rever</option><option value="no">Não</option><option value="not_applicable">Não aplicável</option><option value="evidence_link">Link para print</option></select></label></div>
                  <div class="verification-cell"><label id="serviceBoxLinkWrap" class="link-input">Link<input id="serviceBoxLink" placeholder="https://..."></label><span id="serviceBoxChip" class="chip review">Por rever</span></div>
                  <div class="verification-cell verification-actions"><button type="button" onclick="markEvidence('serviceBox')">Anexar print</button><a id="serviceBoxOpen" class="button" target="_blank" rel="noopener">Abrir</a></div>
                </div>
                <div id="campaignsCard" class="verification-row">
                  <div class="verification-cell verification-title"><span class="doc-code">CP</span><div><strong>Campanhas</strong><p class="muted">Campanhas em aberto, ou confirmação de inexistência.</p></div></div>
                  <div class="verification-cell"><label>Estado<select id="campaigns"><option value="pending_review">Por rever</option><option value="no">Não</option><option value="not_applicable">Não aplicável</option><option value="evidence_link">Link para print</option></select></label></div>
                  <div class="verification-cell"><label id="campaignsLinkWrap" class="link-input">Link<input id="campaignsLink" placeholder="https://..."></label><span id="campaignsChip" class="chip review">Por rever</span></div>
                  <div class="verification-cell verification-actions"><button type="button" onclick="markEvidence('campaigns')">Anexar print</button><a id="campaignsOpen" class="button" target="_blank" rel="noopener">Abrir</a></div>
                </div>
                <div id="planCard" class="verification-row">
                  <div class="verification-cell verification-title"><span class="doc-code">PM</span><div><strong>Plano manutenção</strong><p class="muted">Plano da marca comparado com Rentway.</p></div></div>
                  <div class="verification-cell"><label>Estado<select id="plan"><option value="pending_review">Por rever</option><option value="no">Não</option><option value="not_applicable">Não aplicável</option><option value="evidence_link">Link para print</option></select></label></div>
                  <div class="verification-cell"><label id="planLinkWrap" class="link-input">Link<input id="planLink" placeholder="https://..."></label><span id="planChip" class="chip review">Por rever</span><div id="planCompare" class="muted"></div></div>
                  <div class="verification-cell verification-actions"><button type="button" onclick="markEvidence('plan')">Anexar plano</button><a id="planOpen" class="button" target="_blank" rel="noopener">Abrir</a></div>
                </div>
              </div>
            </div>
            <div class="verification-group">
              <div class="board-title"><div><h3>Histórico e contexto</h3><p class="muted">Verificações internas e sinais de repetição/incidência.</p></div></div>
              <div class="verification-board">
                <div class="verification-head"><span>Verificação</span><span>Estado</span><span>Detalhe</span><span>Ações</span></div>
                <div id="internalCard" class="verification-row">
                  <div class="verification-cell verification-title"><span class="doc-code">HI</span><div><strong>Histórico interno</strong><p class="muted">Consulta interna e intervenções relevantes.</p></div></div>
                  <div class="verification-cell"><label>Consulta<select id="internal"><option value="pending_review">Por rever</option><option value="yes">Sim</option><option value="no">Não</option><option value="not_applicable">Não aplicável</option></select></label></div>
                  <div class="verification-cell"><span id="internalChip" class="chip review">Por rever</span></div>
                  <div class="verification-cell verification-actions"><button type="button" onclick="saveChecks()">Validar</button></div>
                </div>
                <div class="verification-row">
                  <div class="verification-cell verification-title"><span class="doc-code">AR</span><div><strong>Accident reports</strong><p class="muted">Existem ocorrências abertas ou relevantes?</p></div></div>
                  <div class="verification-cell"><label>Estado<select id="accidents"><option value="no">Não</option><option value="yes">Sim</option><option value="pending_review">Por rever</option><option value="not_applicable">Não aplicável</option></select></label></div>
                  <div class="verification-cell"><label>Detalhe<input id="accidentsDetail" placeholder="Resumo ou referência"></label></div>
                  <div class="verification-cell verification-actions"><button type="button" onclick="saveChecks()">Guardar</button></div>
                </div>
                <div class="verification-row">
                  <div class="verification-cell verification-title"><span class="doc-code">PA</span><div><strong>Processos anteriores</strong><p class="muted">Rever histórico de processos anteriores da viatura.</p></div></div>
                  <div class="verification-cell"><label>Estado<select id="previous"><option value="yes">Sim</option><option value="none">Não existem</option><option value="pending_review">Por rever</option><option value="not_applicable">Não aplicável</option></select></label></div>
                  <div class="verification-cell"><span class="chip neutral">Histórico</span></div>
                  <div class="verification-cell verification-actions"><button type="button" onclick="saveChecks()">Guardar</button></div>
                </div>
                <div class="verification-row">
                  <div class="verification-cell verification-title"><span class="doc-code">IR</span><div><strong>Incidência repetida</strong><p class="muted">Confirmar se o motivo se repete.</p></div></div>
                  <div class="verification-cell"><label>Estado<select id="repeat"><option value="no">Não</option><option value="yes">Sim</option><option value="pending_review">Por avaliar</option><option value="not_applicable">Não aplicável</option></select></label></div>
                  <div class="verification-cell"><label>Observação<input id="historyObs" placeholder="Notas de histórico"></label></div>
                  <div class="verification-cell verification-actions"><button type="button" onclick="saveChecks()">Guardar</button></div>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section id="reports" class="panel phase">
          <div class="phase-head"><div><h2>Relatórios</h2><p class="muted">Preencha os campos esperados do relatório selecionado. O JSON é preparado automaticamente.</p></div><button id="reportSaveButton" class="primary" type="button" onclick="saveReport()">Adicionar relatório</button></div>
          <div id="reportsAlerts" class="alert-line"></div>
          <div id="reportTypeCards" class="report-type-grid"></div>
          <div id="reportList" class="report-instance-strip"></div>
          <div class="grid3"><label>Tipo<select id="reportCode"></select></label><label>Momento<select id="reportMoment"><option value="initial">Inicial</option><option value="final">Final</option></select></label><label>Origem<select id="reportOrigin"><option value="stellantis_machine">Máquina Stellantis</option><option value="autel">Autel</option><option value="other">Outro</option></select></label></div>
          <div id="reportDescription" class="report-description"></div>
          <label>Link original<input id="reportLink" placeholder="https://..."></label>
          <div id="reportFieldGrid" class="report-field-grid"></div>
          <details><summary><span><span class="accordion-icon">▤</span>JSON preparado</span></summary><div class="accordion-body grid2"><label>Valores extraídos JSON<textarea id="reportValues" placeholder='{"campo":"valor"}'></textarea></label><label>Valores validados JSON<textarea id="validateValues" placeholder='{"campo":"valor"}'></textarea></label></div></details>
          <div class="actions" style="justify-content:flex-start"><button type="button" onclick="newReportDraft()">Novo relatório</button><button type="button" onclick="validateReport()">Validar selecionado</button><a id="reportOpen" class="button" target="_blank" rel="noopener">Abrir original</a></div>
        </section>

        <section id="decision" class="panel phase">
          <div class="phase-head"><div><h2>Decisão</h2><p class="muted">Registe diagnóstico, impacto operacional e próxima ação.</p></div><button class="primary" type="button" onclick="saveDecision()">Guardar decisão</button></div>
          <div id="decisionAlerts" class="alert-line"></div>
          <div class="grid3"><label>Diagnóstico principal<input id="decisionDiagnosis" placeholder="Resumo do diagnóstico"></label><label>Tipo intervenção<input id="decisionType" placeholder="Interna, externa, garantia..."></label><label>Sistema afetado<input id="decisionSystem" placeholder="Motor, travagem, elétrica..."></label></div>
          <div class="grid3"><label>Gravidade<select id="decisionSeverity"><option value="medium">Média</option><option value="low">Baixa</option><option value="high">Alta</option><option value="critical">Crítica</option></select></label><label>Viatura pode circular?<select id="decisionCirculate"><option value="yes">Sim</option><option value="no">Não</option><option value="conditional">Com restrições</option></select></label><label>Próxima ação<input id="decisionNext" placeholder="Ação seguinte"></label></div>
          <div class="inline-checks"><label><input id="decisionNeedsRepair" type="checkbox">Precisa reparação</label><label><input id="decisionNeedsBudget" type="checkbox">Precisa orçamento</label><label><input id="decisionNeedsApproval" type="checkbox">Precisa aprovação</label><label><input id="decisionCharge" type="checkbox">Possível cobrança cliente</label><label><input id="decisionWarranty" type="checkbox">Garantia</label><label><input id="decisionCreateTask" type="checkbox">Criar tarefa</label></div>
          <details><summary><span><span class="accordion-icon">＋</span>Detalhes da decisão</span></summary><div class="accordion-body grid2"><label>Causa provável<input id="decisionCause"></label><label>Evidência cobrança<input id="decisionChargeEvidence" placeholder="https://..."></label><label>Contrato cliente<input id="decisionContract"></label><label>Valor estimado cobrança<input id="decisionChargeValue" type="number" step="0.01"></label><label>Responsável próxima ação<input id="decisionResponsible" type="number" min="1"></label><label>Data limite<input id="decisionDue" type="datetime-local"></label><label>Observação<textarea id="decisionObs"></textarea></label></div></details>
        </section>

        <section id="budget" class="panel phase">
          <div class="phase-head"><div><h2>Orçamento</h2><p class="muted">Pedido, receção e decisão de aprovação do orçamento.</p></div><button class="primary" type="button" onclick="saveBudget()">Guardar orçamento</button></div>
          <div id="budgetAlerts" class="alert-line"></div>
          <div class="grid3"><label>Fornecedor / oficina<input id="budgetSupplier" placeholder="Fornecedor"></label><label>Descrição do pedido<input id="budgetRequest" placeholder="Pedido enviado"></label><label>Prazo fornecedor<input id="budgetDeadline" type="datetime-local"></label></div>
          <div class="inline-checks"><label><input id="budgetReceived" type="checkbox">Orçamento recebido</label><label><input id="budgetVat" type="checkbox">IVA incluído</label><label><input id="budgetNeedsApproval" type="checkbox" checked>Precisa aprovação</label></div>
          <div class="grid3"><label>Valor estimado<input id="budgetValue" type="number" step="0.01"></label><label>Link orçamento<input id="budgetLink" placeholder="https://..."></label><label>Estado aprovação<select id="budgetApproval"><option value="pending">Pendente</option><option value="approved">Aprovado</option><option value="rejected">Rejeitado</option></select></label></div>
          <details><summary><span><span class="accordion-icon">＋</span>Resultado e observações</span></summary><div class="accordion-body grid2"><label>Descrição orçamento<textarea id="budgetDescription"></textarea></label><label>Resultado final<input id="budgetResult" placeholder="Aprovado para reparação, rejeitado..."></label><label>Valor aprovado<input id="budgetApprovedValue" type="number" step="0.01"></label><label>Motivo rejeição<input id="budgetRejection"></label><label>Próxima ação<input id="budgetNext"></label><label>Observação<textarea id="budgetObs"></textarea></label></div></details>
        </section>

        <section id="repair" class="panel phase">
          <div class="phase-head"><div><h2>Reparação</h2><p class="muted">Execução interna, resultado e evidências finais.</p></div><button class="primary" type="button" onclick="saveRepair()">Guardar reparação</button></div>
          <div id="repairAlerts" class="alert-line"></div>
          <div class="grid3"><label>Tipo execução<select id="repairType"><option value="internal">Interna</option><option value="external">Externa</option><option value="no_intervention">Sem intervenção</option></select></label><label>Resultado<select id="repairResult"><option value="">Selecionar</option><option value="completed">Concluída</option><option value="partial">Parcial</option><option value="no_intervention_needed">Sem intervenção necessária</option></select></label><label>KM final visível<input id="repairKm" type="number" min="0"></label></div>
          <label>Descrição da intervenção<textarea id="repairDescription" placeholder="Trabalho executado"></textarea></label>
          <div class="grid2"><label>Foto final quadrante<input id="repairPhoto" placeholder="https://..."></label><label>Observação final<textarea id="repairObs"></textarea></label></div>
        </section>

        <section id="close" class="panel phase">
          <div class="phase-head"><div><h2>Fecho</h2><p class="muted">Validação final, estado operacional e encerramento.</p></div><button class="primary" type="button" onclick="closeProcess()">Fechar processo</button></div>
          <div id="closeAlerts" class="alert-line"></div>
          <div class="grid3"><label>Resultado final<input id="closeResult" placeholder="Processo concluído"></label><label>Viatura pronta?<select id="closeReady"><option value="yes">Sim</option><option value="no">Não</option><option value="conditional">Com pendências</option></select></label><label>Novo estado operacional<input id="closeStatus" placeholder="operational, maintenance..."></label></div>
          <div class="grid3"><label>Teste final<select id="closeTest"><option value="yes">Sim</option><option value="no">Não</option><option value="not_applicable">Não aplicável</option></select></label><label>Regressar à frota?<select id="closeFleet"><option value="yes">Sim</option><option value="no">Não</option><option value="conditional">Com restrições</option></select></label><label>KM final<input id="closeKm" type="number" min="0"></label></div>
          <label>Observação final<textarea id="closeObs" placeholder="Resumo final do processo"></textarea></label>
          <details><summary><span><span class="accordion-icon">＋</span>Fechar com pendências</span></summary><div class="accordion-body grid2"><label><span class="inline-checks"><span><input id="closePending" type="checkbox"> Fechar com pendências</span></span></label><label>Justificação<input id="closePendingReason"></label><label>Responsável pendência<input id="closePendingResponsible" type="number" min="1"></label><label>Prazo pendência<input id="closePendingDue" type="datetime-local"></label></div></details>
        </section>
        <div id="result" class="result"></div>
      </div>
    </main>
  </div>
  <script>
    const processId = __PROCESS_ID__;
    const previewMode = new URLSearchParams(window.location.search).get("preview") === "1";
    let processData = null;
    let config = null;
    let selectedReportId = null;
    let selectedReportType = null;
    const tabs = [
      ["reception", "Receção", "administrative_reception"],
      ["services", "Serviços", null],
      ["checks", "Verificações", "history_check"],
      ["reports", "Relatórios", "technical_phase"],
      ["decision", "Decisão", "diagnosis_decision"],
      ["budget", "Orçamento", "budget_approval"],
      ["repair", "Reparação", "internal_repair_execution"],
      ["close", "Fecho", "final_closure"]
    ];
    const phaseIcons = {reception:"□", services:"⌕", checks:"○", reports:"▤", decision:"⚖", budget:"▦", repair:"⚙", close:"⚑"};
    const phaseLabels = {administrative_reception:"Receção", history_check:"Verificações", technical_phase:"Relatórios", diagnosis_decision:"Decisão", budget_approval:"Orçamento", internal_repair_execution:"Reparação", final_closure:"Fecho"};
    const statusLabels = {open:["Aberto","review"], pending:["Pendente","review"], pending_review:["Por rever","review"], pending_validation:["Por validar","review"], in_progress:["Em curso","progress"], completed:["Concluído","done"], validated:["Validado","done"], completed_with_pending_items:["Concluído com pendências","review"], added:["Adicionado","progress"], not_started:["Não iniciado","neutral"], not_applicable:["Não aplicável","neutral"], high:["Alta","danger"], critical:["Crítica","danger"]};
    const valueLabels = {yes:"Sim", no:"Não", none:"Não existem", pending_review:"Por rever", not_applicable:"Não aplicável", evidence_link:"Link para print", initial:"Inicial", final:"Final", stellantis_machine:"Máquina Stellantis", autel:"Autel", other:"Outro"};
    const demoConfig = {
      services: [
        {code:"revision_maintenance", label:"Revisão / manutenção"},
        {code:"tyres", label:"Pneus"},
        {code:"brakes", label:"Travões"},
        {code:"other", label:"Outro"}
      ],
      stellantis_reports: [
        {code:"maintenance_information", label:"Informações manutenção", description:"KM, dias e limites de manutenção.", fields:[
          {code:"km_before_next_maintenance", label:"Km antes próxima manutenção", unit:"km"},
          {code:"days_before_next_maintenance", label:"Dias restantes", unit:"dias"},
          {code:"maintenance_key_display", label:"Chave de manutenção", unit:null}
        ]},
        {code:"maintenance_plan_validation", label:"Validação plano manutenção", description:"Comparar plano Service Box com Rentway.", fields:[
          {code:"requested_service", label:"Solicitação do processo", unit:null},
          {code:"servicebox_interval_km", label:"Intervalo Service Box", unit:"km"},
          {code:"rentway_interval_km", label:"Intervalo Rentway", unit:"km"},
          {code:"request_matches_servicebox_plan", label:"Solicitação bate certo?", unit:null},
          {code:"rentway_matches_servicebox_plan", label:"Rentway correto?", unit:null},
          {code:"validation_notes", label:"Notas", unit:null}
        ]},
        {code:"fault_reading", label:"Leitura defeitos", description:"Defeitos e códigos encontrados.", fields:[
          {code:"faults_found", label:"Defeitos encontrados?", unit:null},
          {code:"faults", label:"Lista de defeitos", unit:null}
        ]}
      ]
    };
    const demoProcess = {
      id: processId,
      title: "Revisão e verificações de entrada",
      status: "open",
      current_phase_code: "administrative_reception",
      plate: "BC-98-FA",
      origin: "Rentway",
      initial_km: 119657,
      initial_observation: "Entrada para revisão e validação de plano.",
      created_at: "2026-06-04",
      document_folder: {path:"C:\\\\Users\\\\andre\\\\OneDrive - D'accord Invest - Serviços Partilhados SA\\\\CARFAST - OFICINA - OFICINA\\\\CarFast v2 - Oficina\\\\Documentos Processos"},
      vehicle: {plate:"BC-98-FA", vin:"VF7XXXXXXXXXXXXXX", brand:"CITROEN", model:"BERLINGO XL", version:"1.5 BH 100 S&S CVM6", rentway_unit_nr:"251"},
      services: [{id:1, sort_order:1, service_label:"Revisão / manutenção", zone:"Motor", detail:"Plano de manutenção", short_observation:"Confirmar Service Box"}],
      phases: [
        {id:11, phase_code:"administrative_reception", status:"pending_review", data:{km_entry:119657, initial_observation:"Entrada para revisão e validação de plano."}},
        {id:12, phase_code:"history_check", status:"not_started", data:{}},
        {id:13, phase_code:"technical_phase", status:"not_started", data:{}},
        {id:14, phase_code:"diagnosis_decision", status:"not_started", data:{main_diagnosis:"A validar plano de manutenção", vehicle_can_circulate:"yes", severity:"medium", next_action:"Confirmar orçamento se houver divergência"}},
        {id:15, phase_code:"budget_approval", status:"not_started", data:{}},
        {id:16, phase_code:"internal_repair_execution", status:"not_started", data:{}},
        {id:17, phase_code:"final_closure", status:"not_started", data:{}}
      ],
      alerts: [
        {code:"quadrant_photo_missing", message:"Foto do quadrante em falta", severity:"medium", source:"administrative_reception", phase_id:11},
        {code:"service_box_checked_pending", message:"Consulta Service Box por confirmar", severity:"high", source:"history_check", phase_id:12}
      ],
      technical_reports: [{id:34, report_code:"maintenance_plan_validation", report_name:"Validação plano manutenção", reading_origin:"stellantis_machine", report_moment:"initial", status:"pending_validation", original_link:"https://example.com/relatorio.pdf", extracted_values:{requested_service:"Revisão / manutenção", servicebox_interval_km:"30000", rentway_interval_km:"20000"}, validated_values:null}]
    };
    const $ = (selector) => document.querySelector(selector);
    function safe(value) { return String(value ?? "-").replace(/[&<>"']/g, c => c === "&" ? "&amp;" : c === "<" ? "&lt;" : c === ">" ? "&gt;" : c === '"' ? "&quot;" : "&#39;"); }
    function val(id) { return $(id)?.value || ""; }
    function setVal(id, value) { const el = $(id); if (el && value !== undefined && value !== null) el.value = value; }
    function meta(code) { return statusLabels[code] || [code || "-", "neutral"]; }
    function chip(code) { const m = meta(code); return `<span class="chip ${m[1]}">${safe(m[0])}</span>`; }
    function label(value) { return valueLabels[value] || value || "-"; }
    function phase(code) { return (processData?.phases || []).find(item => item.phase_code === code) || null; }
    function alertsFor(code) { const p = phase(code); return (processData?.alerts || []).filter(alert => alert.phase_id === p?.id || alert.source === code); }
    function tabForPhase(code) { return tabs.find(([, , phaseCode]) => phaseCode === code)?.[0] || "reception"; }
    function showResult(ok, message) { const el = $("#result"); el.className = `result active ${ok ? "ok" : "err"}`; el.textContent = message; }
    function objectValues(value) { return value && typeof value === "object" && !Array.isArray(value) ? value : {}; }
    function jsonFrom(id) { const raw = val(id).trim(); return raw ? JSON.parse(raw) : {}; }
    async function requestJson(url, method, body) {
      const response = await fetch(url, {method, headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)});
      const data = await response.json();
      if (!response.ok) throw new Error(JSON.stringify(data.detail || data));
      await loadProcess();
      return data;
    }
    async function fetchJson(url, timeoutMs=10000) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), timeoutMs);
      try {
        const response = await fetch(url, {signal:controller.signal});
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return await response.json();
      } finally {
        clearTimeout(timer);
      }
    }
    function renderHeader() {
      const v = processData.vehicle || {};
      const model = [v.brand, v.model, v.version].filter(Boolean).join(" ");
      const status = meta(processData.status);
      const current = phaseLabels[processData.current_phase_code] || processData.current_phase_code || "-";
      $("#title").textContent = `Oficina - Processo #${processData.id}`;
      $("#meta").innerHTML = [
        `<strong>▱ ${safe(v.plate || processData.plate || "-")}</strong>`,
        `VIN ${safe(v.vin || "-")}`,
        safe(model || "Dados da viatura por completar"),
        `Unidade ${safe(v.rentway_unit_nr || "-")}`,
        `${safe(processData.initial_km || "-")} km`,
        `Estado: <strong>${safe(status[0])}</strong>`,
        `Fase atual: <strong>${safe(current)}</strong>`
      ].map(item => `<span>${item}</span>`).join("<span>|</span>");
    }
    function renderStepper(active) {
      $("#stepper").innerHTML = tabs.map(([id, text, phaseCode]) => {
        const alerts = phaseCode ? alertsFor(phaseCode) : [];
        const done = phaseCode && ["completed", "validated", "completed_with_pending_items"].includes(phase(phaseCode)?.status);
        return `<button type="button" class="step ${id === active ? "active" : ""} ${done ? "done" : ""} ${alerts.length ? "warn" : ""}" onclick="showPhase('${id}')"><span class="step-icon">${done ? "✓" : safe(phaseIcons[id] || "·")}</span>${alerts.length ? `<span class="count"><span class="tri"></span>${alerts.length}</span>` : ""}<span class="step-label">${safe(text)}</span></button>`;
      }).join("");
    }
    function renderAlerts(id) {
      const phaseCode = tabs.find(item => item[0] === id)?.[2];
      const holder = $(`#${id}Alerts`);
      if (!holder) return;
      const alerts = phaseCode ? alertsFor(phaseCode) : [];
      holder.classList.toggle("active", Boolean(alerts.length));
      holder.innerHTML = alerts.length ? `<span class="tri"></span><span>${alerts.map(alert => safe(alert.message)).join(" · ")}</span>` : "";
    }
    function markMissing(field, note, active) {
      const control = $(field);
      const target = control?.closest(".field-control") || control;
      target?.classList.toggle("field-missing", Boolean(active));
      $(note)?.classList.toggle("active", Boolean(active));
    }
    function updateObservationCounter() {
      const field = $("#recObs");
      const counter = $("#recObsCounter");
      if (field && counter) counter.textContent = `${field.value.length} / 500`;
    }
    function highlightReception() {
      const text = alertsFor("administrative_reception").map(a => `${a.code || ""} ${a.message || ""}`).join(" ").toLowerCase();
      markMissing("#recKm", "#recKmNote", text.includes("km") || text.includes("quil"));
      markMissing("#recObs", "#recObsNote", text.includes("observ"));
      markMissing("#recPhoto", "#recPhotoNote", text.includes("foto") || text.includes("quadrante"));
      markMissing("#recResponsible", "#recResponsibleNote", text.includes("respons"));
    }
    function showPhase(id) {
      document.querySelectorAll(".phase").forEach(el => el.classList.remove("active"));
      $(`#${id}`)?.classList.add("active");
      renderStepper(id);
      tabs.forEach(([tabId]) => renderAlerts(tabId));
      highlightReception();
    }
    function renderServices() {
      const services = processData.services || [];
      $("#serviceList").innerHTML = services.map(service => `<div class="row"><div><strong>${safe(service.service_label)}</strong><p class="muted">${safe([service.zone, service.detail, service.short_observation].filter(Boolean).join(" · ") || "Sem detalhe")}</p></div><span class="chip">${safe(service.sort_order || service.id)}</span></div>`).join("") || `<div class="placeholder">Sem serviços registados.</div>`;
    }
    function reportName(code) { return (config?.stellantis_reports || []).find(report => report.code === code)?.label || code || "Relatório"; }
    function reportConfig(code=val("#reportCode")) { return (config?.stellantis_reports || []).find(report => report.code === code) || null; }
    function reportIsValidated(report) {
      return ["validated", "corrected_manually"].includes(report.status);
    }
    function reportIsPending(report) {
      return ["pending_validation", "added", "pending", "not_started"].includes(report.status);
    }
    function renderReports() {
      const reports = processData.technical_reports || [];
      const types = config?.stellantis_reports || [];
      const codes = [...new Set([...types.map(type => type.code), ...reports.map(report => report.report_code).filter(Boolean)])];
      if (!selectedReportType) {
        const firstPending = [...reports].sort((a,b) => (reportIsPending(a) ? -1 : 0) - (reportIsPending(b) ? -1 : 0) || b.id - a.id)[0];
        selectedReportType = firstPending?.report_code || codes[0] || null;
      }
      $("#reportTypeCards").innerHTML = codes.map(code => {
        const typeReports = reports.filter(report => report.report_code === code);
        const validated = typeReports.filter(reportIsValidated).length;
        const pending = typeReports.filter(reportIsPending).length;
        const active = selectedReportType === code;
        const summary = typeReports.length
          ? `${validated} validado${validated === 1 ? "" : "s"}${pending ? ` · ${pending} por validar` : ""}`
          : "Sem relatórios anexados";
        return `<button type="button" class="report-type-card ${active ? "active" : ""}" onclick="selectReportType('${safe(code)}')">
          <strong>${safe(reportName(code))}</strong>
          <span class="report-count">${typeReports.length}</span>
          <span class="report-status-line">${safe(summary)}</span>
        </button>`;
      }).join("") || `<div class="placeholder">Sem tipos de relatório configurados.</div>`;
      const selectedReports = reports.filter(report => report.report_code === selectedReportType);
      $("#reportList").innerHTML = selectedReports.map(report => `<button type="button" class="${report.id === selectedReportId ? "active" : ""}" onclick="selectReport(${report.id})">#${report.id} · ${safe(label(report.report_moment))} · ${safe(label(report.reading_origin))} · ${safe(meta(report.status)[0])}</button>`).join("") || `<button type="button" onclick="newReportDraft()">Novo ${safe(reportName(selectedReportType))}</button>`;
    }
    function selectReportType(code) {
      selectedReportType = code;
      setVal("#reportCode", code);
      const reports = (processData.technical_reports || []).filter(report => report.report_code === code);
      const first = [...reports].sort((a,b) => (reportIsPending(a) ? -1 : 0) - (reportIsPending(b) ? -1 : 0) || b.id - a.id)[0];
      if (first) selectReport(first.id, false);
      else newReportDraft();
      renderReports();
    }
    function normalizedKey(value) {
      return String(value || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
    }
    function fieldValue(values, field) {
      const map = objectValues(values);
      const candidates = [field.code, field.label, `${field.label} ${field.unit || ""}`, normalizedKey(field.label), normalizedKey(`${field.label} ${field.unit || ""}`)];
      for (const key of candidates) {
        if (Object.prototype.hasOwnProperty.call(map, key) && map[key] !== null && map[key] !== undefined) return map[key];
      }
      return "";
    }
    function renderReportFields(values={}) {
      const report = reportConfig();
      const fields = report?.fields || [];
      $("#reportDescription").textContent = report?.description || "Escolha um tipo de relatório para ver os campos esperados.";
      $("#reportFieldGrid").innerHTML = fields.length ? `
        <div class="report-table-head"><span>Descrição</span><span>Dados a validar</span></div>
        ${fields.map(field => `
          <div class="report-field">
            <span>${safe(field.label)}${field.unit ? `<small>Unidade: ${safe(field.unit)}</small>` : `<small>Sem unidade definida</small>`}</span>
            <label>Valor encontrado no relatório<input data-report-field="${safe(field.code)}" data-report-label="${safe(field.label)}" value="${safe(fieldValue(values, field))}" placeholder="Preencher valor a validar"></label>
          </div>
        `).join("")}
      ` : "";
      if (report?.code === "maintenance_plan_validation" && !fieldValue(values, {code:"requested_service", label:"Solicitação do processo"})) {
        const requested = document.querySelector('[data-report-field="requested_service"]');
        if (requested) requested.value = processData?.services_label || processData?.title || "";
      }
      document.querySelectorAll("[data-report-field]").forEach(input => input.addEventListener("input", syncReportJsonFromFields));
      syncReportJsonFromFields();
    }
    function collectReportFieldValues() {
      const values = {};
      document.querySelectorAll("[data-report-field]").forEach(input => {
        if (input.value.trim()) values[input.dataset.reportField] = input.value.trim();
      });
      return values;
    }
    function syncReportJsonFromFields() {
      const values = collectReportFieldValues();
      setVal("#reportValues", JSON.stringify(values, null, 2));
      if (!val("#validateValues") || val("#validateValues") === "{}") setVal("#validateValues", JSON.stringify(values, null, 2));
    }
    function setChecked(id, value) { const el = $(id); if (el) el.checked = Boolean(value); }
    function numeric(id) { const raw = val(id); return raw === "" ? null : Number(raw); }
    function dateTimeValue(id) { return val(id) || null; }
    function docStatus(value, link, empty="Por rever") {
      if (value === "not_applicable") return ["Não aplicável", "done"];
      if (value === "yes" || value === "no") return ["Validado", "done"];
      if (value === "evidence_link" && link) return ["Com evidência", "review"];
      if (value === "evidence_link") return ["Falta link", "danger"];
      return [empty, "review"];
    }
    function setDoc(prefix, status) {
      const card = $(`#${prefix}Card`);
      const chipEl = $(`#${prefix}Chip`);
      card?.classList.remove("done", "review", "danger");
      card?.classList.add(status[1]);
      if (chipEl) { chipEl.textContent = status[0]; chipEl.className = `chip ${status[1]}`; }
    }
    function updateLink(prefix, link) {
      $(`#${prefix}LinkWrap`)?.classList.toggle("needs-link", val(`#${prefix}`) === "evidence_link");
      const open = $(`#${prefix}Open`);
      if (!open) return;
      if (link) { open.href = link; open.removeAttribute("aria-disabled"); }
      else { open.removeAttribute("href"); open.setAttribute("aria-disabled", "true"); }
    }
    function renderChecks() {
      ["serviceBox", "campaigns", "plan"].forEach(prefix => updateLink(prefix, val(`#${prefix}Link`)));
      setDoc("serviceBox", docStatus(val("#serviceBox"), val("#serviceBoxLink")));
      setDoc("campaigns", docStatus(val("#campaigns"), val("#campaignsLink")));
      setDoc("plan", docStatus(val("#plan"), val("#planLink")));
      setDoc("internal", docStatus(val("#internal"), ""));
      const report = [...(processData.technical_reports || [])].filter(r => r.report_code === "maintenance_plan_validation").sort((a,b) => b.id - a.id)[0];
      const values = objectValues(report?.validated_values || report?.extracted_values);
      $("#planCompare").textContent = report ? `Service Box: ${values.servicebox_interval_km || "-"} km · Rentway: ${values.rentway_interval_km || "-"} km` : "Sem relatório de plano validado.";
    }
    function renderValues() {
      const v = processData.vehicle || {};
      const r = phase("administrative_reception")?.data || {};
      const h = phase("history_check")?.data || {};
      const d = phase("diagnosis_decision")?.data || {};
      const b = phase("budget_approval")?.data || {};
      const repair = phase("internal_repair_execution")?.data || {};
      const closure = phase("final_closure")?.data || {};
      setVal("#recDate", r.entry_date || processData.created_at || "");
      setVal("#recKm", r.km_entry || processData.initial_km || "");
      setVal("#recObs", r.initial_observation || processData.initial_observation || "");
      updateObservationCounter();
      setVal("#recOrigin", processData.origin || "");
      setVal("#recUnit", v.rentway_unit_nr || "");
      setVal("#recVisual", r.visible_damage_status || "");
      setVal("#recDamage", r.damage_description || "");
      setVal("#recPhoto", r.quadrant_photo_link || "");
      setVal("#internal", h.internal_history_checked || "pending_review");
      setVal("#accidents", h.open_accident_reports || "no");
      setVal("#accidentsDetail", h.accident_reports_detail || "");
      setVal("#previous", h.previous_processes_reviewed || "yes");
      setVal("#repeat", h.repeated_incidence || "no");
      setVal("#historyObs", h.history_observation || "");
      setVal("#serviceBox", h.service_box_checked || "pending_review");
      setVal("#serviceBoxLink", h.service_box_link || "");
      setVal("#campaigns", h.campaigns_checked || "pending_review");
      setVal("#campaignsLink", h.campaigns_link || "");
      setVal("#plan", h.maintenance_plan_checked || "pending_review");
      setVal("#planLink", h.maintenance_plan_link || "");
      renderChecks();
      setVal("#decisionDiagnosis", d.main_diagnosis || "");
      setVal("#decisionType", d.intervention_type || "");
      setVal("#decisionSystem", d.affected_system || "");
      setVal("#decisionSeverity", d.severity || "medium");
      setVal("#decisionCirculate", d.vehicle_can_circulate || "yes");
      setVal("#decisionNext", d.next_action || "");
      setVal("#decisionCause", d.probable_cause || "");
      setVal("#decisionChargeEvidence", d.charge_evidence_link || "");
      setVal("#decisionContract", d.customer_contract || "");
      setVal("#decisionChargeValue", d.estimated_charge_value || "");
      setVal("#decisionResponsible", d.next_action_responsible_user_id || "");
      setVal("#decisionDue", (d.next_action_due_at || "").slice(0, 16));
      setVal("#decisionObs", d.decision_observation || d.diagnosis_observation || "");
      setChecked("#decisionNeedsRepair", d.needs_repair);
      setChecked("#decisionNeedsBudget", d.needs_budget);
      setChecked("#decisionNeedsApproval", d.needs_approval);
      setChecked("#decisionCharge", d.potential_customer_charge);
      setChecked("#decisionWarranty", d.warranty);
      setVal("#budgetSupplier", b.supplier || "");
      setVal("#budgetRequest", b.request_description || "");
      setVal("#budgetDeadline", (b.supplier_deadline_at || "").slice(0, 16));
      setChecked("#budgetReceived", b.budget_received);
      setChecked("#budgetVat", b.vat_included);
      setChecked("#budgetNeedsApproval", b.needs_approval !== false);
      setVal("#budgetValue", b.estimated_value || "");
      setVal("#budgetLink", b.budget_link || "");
      setVal("#budgetApproval", b.approval_status || "pending");
      setVal("#budgetDescription", b.budget_description || "");
      setVal("#budgetResult", b.final_result || "");
      setVal("#budgetApprovedValue", b.approved_value || "");
      setVal("#budgetRejection", b.rejection_reason || "");
      setVal("#budgetNext", b.next_action || "");
      setVal("#budgetObs", b.observation || "");
      setVal("#repairType", repair.execution_type || "");
      setVal("#repairResult", repair.result || "");
      setVal("#repairKm", repair.final_km_visible || "");
      setVal("#repairDescription", repair.intervention_description || "");
      setVal("#repairPhoto", repair.final_quadrant_photo_link || "");
      setVal("#repairObs", repair.final_observation || "");
      setVal("#closeResult", closure.final_result || "");
      setVal("#closeReady", closure.vehicle_ready || "yes");
      setVal("#closeStatus", closure.new_vehicle_operational_status || processData.vehicle?.operational_status || "operational");
      setVal("#closeTest", closure.final_test_done || "yes");
      setVal("#closeFleet", closure.can_return_to_fleet || "yes");
      setVal("#closeKm", closure.final_km || processData.initial_km || "");
      setVal("#closeObs", closure.final_observation || "");
      setChecked("#closePending", closure.close_with_pending_items);
    }
    async function loadConfig() {
      config = previewMode ? demoConfig : await fetchJson("/api/workshop/process-config");
      $("#serviceCode").innerHTML = (config.services || []).map(service => `<option value="${service.code}">${safe(service.label)}</option>`).join("");
      $("#reportCode").innerHTML = (config.stellantis_reports || []).map(report => `<option value="${report.code}">${safe(report.label)}</option>`).join("");
      ["#serviceBox", "#serviceBoxLink", "#campaigns", "#campaignsLink", "#plan", "#planLink", "#internal"].forEach(id => $(id)?.addEventListener("input", renderChecks));
      $("#reportLink")?.addEventListener("input", () => updateReportOpen());
      $("#reportCode")?.addEventListener("change", () => {
        selectedReportId = null;
        selectedReportType = val("#reportCode");
        $("#reportSaveButton").textContent = "Adicionar relatório";
        renderReportFields({});
        renderReports();
      });
      $("#recObs")?.addEventListener("input", updateObservationCounter);
    }
    async function loadProcess() {
      processData = previewMode ? demoProcess : await fetchJson(`/api/workshop/processes/${processId}`);
      const active = document.querySelector(".phase.active")?.id || tabForPhase(processData.current_phase_code);
      renderHeader();
      renderServices();
      renderReports();
      renderValues();
      if (!selectedReportId) {
        const first = [...(processData.technical_reports || [])].sort((a,b) => (a.status === "pending_validation" ? -1 : 0) - (b.status === "pending_validation" ? -1 : 0) || b.id - a.id)[0];
        if (first) selectReport(first.id, false);
        else renderReportFields({});
      }
      showPhase(active);
    }
    function updateReportOpen() {
      const open = $("#reportOpen");
      if (val("#reportLink")) { open.href = val("#reportLink"); open.removeAttribute("aria-disabled"); }
      else { open.removeAttribute("href"); open.setAttribute("aria-disabled", "true"); }
    }
    async function copyFolder() {
      const path = processData?.document_folder?.path || "";
      if (!path) return showResult(false, "Caminho documental por definir.");
      try { await navigator.clipboard.writeText(path); showResult(true, "Caminho da pasta copiado."); }
      catch { showResult(false, path); }
    }
    async function openFolder() {
      await copyFolder();
      showResult(true, "Caminho copiado. Abre no Explorador do Windows se o browser bloquear pastas locais.");
    }
    function markEvidence(prefix) { setVal(`#${prefix}`, "evidence_link"); renderChecks(); }
    async function saveReception() {
      try {
        await requestJson(`/api/workshop/processes/${processId}/reception`, "POST", {km_entry:Number(val("#recKm")) || null, quadrant_photo_link:val("#recPhoto"), initial_observation:val("#recObs"), visible_damage_status:val("#recVisual"), damage_description:val("#recDamage")});
        showResult(true, "Receção guardada.");
      } catch (err) { showResult(false, err.message); }
    }
    async function advanceReception() { await saveReception(); showPhase("services"); }
    async function addService() {
      try {
        await requestJson(`/api/workshop/processes/${processId}/services`, "POST", {service_code:val("#serviceCode"), zone:val("#serviceZone"), detail:val("#serviceDetail"), short_observation:val("#serviceObservation")});
        setVal("#serviceZone", ""); setVal("#serviceDetail", ""); setVal("#serviceObservation", "");
        showResult(true, "Serviço adicionado.");
      } catch (err) { showResult(false, err.message); }
    }
    async function saveChecks() {
      try {
        await requestJson(`/api/workshop/processes/${processId}/history-check`, "POST", {internal_history_checked:val("#internal"), open_accident_reports:val("#accidents"), accident_reports_detail:val("#accidentsDetail"), previous_processes_reviewed:val("#previous"), relevant_interventions_identified:"no", repeated_incidence:val("#repeat"), service_box_checked:val("#serviceBox"), service_box_link:val("#serviceBoxLink"), campaigns_checked:val("#campaigns"), campaigns_link:val("#campaignsLink"), maintenance_plan_checked:val("#plan"), maintenance_plan_link:val("#planLink"), history_observation:val("#historyObs")});
        showResult(true, "Verificações guardadas.");
      } catch (err) { showResult(false, err.message); }
    }
    async function saveDecision() {
      try {
        await requestJson(`/api/workshop/processes/${processId}/diagnosis-decision`, "POST", {
          main_diagnosis: val("#decisionDiagnosis"),
          intervention_type: val("#decisionType"),
          affected_system: val("#decisionSystem"),
          severity: val("#decisionSeverity"),
          probable_cause: val("#decisionCause"),
          diagnosis_observation: val("#decisionObs"),
          vehicle_can_circulate: val("#decisionCirculate"),
          needs_repair: $("#decisionNeedsRepair").checked,
          needs_budget: $("#decisionNeedsBudget").checked,
          needs_approval: $("#decisionNeedsApproval").checked,
          potential_customer_charge: $("#decisionCharge").checked,
          warranty: $("#decisionWarranty").checked,
          customer_contract: val("#decisionContract"),
          estimated_charge_value: numeric("#decisionChargeValue"),
          charge_evidence_link: val("#decisionChargeEvidence"),
          next_action: val("#decisionNext"),
          next_action_responsible_user_id: numeric("#decisionResponsible"),
          next_action_due_at: dateTimeValue("#decisionDue"),
          decision_observation: val("#decisionObs"),
          create_task: $("#decisionCreateTask").checked
        });
        showResult(true, "Decisão guardada.");
      } catch (err) { showResult(false, err.message); }
    }
    async function saveBudget() {
      try {
        await requestJson(`/api/workshop/processes/${processId}/budget-approval`, "POST", {
          supplier: val("#budgetSupplier"),
          request_description: val("#budgetRequest"),
          supplier_deadline_at: dateTimeValue("#budgetDeadline"),
          budget_received: $("#budgetReceived").checked,
          estimated_value: numeric("#budgetValue"),
          vat_included: $("#budgetVat").checked,
          budget_description: val("#budgetDescription"),
          budget_link: val("#budgetLink"),
          needs_approval: $("#budgetNeedsApproval").checked,
          approval_status: val("#budgetApproval"),
          approved_value: numeric("#budgetApprovedValue"),
          rejection_reason: val("#budgetRejection"),
          final_result: val("#budgetResult"),
          next_action: val("#budgetNext"),
          observation: val("#budgetObs")
        });
        showResult(true, "Orçamento guardado.");
      } catch (err) { showResult(false, err.message); }
    }
    async function saveRepair() {
      try {
        await requestJson(`/api/workshop/processes/${processId}/internal-repair`, "POST", {
          execution_type: val("#repairType"),
          intervention_description: val("#repairDescription"),
          result: val("#repairResult"),
          final_quadrant_photo_link: val("#repairPhoto"),
          final_km_visible: numeric("#repairKm"),
          final_observation: val("#repairObs"),
          parts_used: [],
          final_evidence_links: {}
        });
        showResult(true, "Reparação guardada.");
      } catch (err) { showResult(false, err.message); }
    }
    async function closeProcess() {
      try {
        await requestJson(`/api/workshop/processes/${processId}/close`, "POST", {
          final_result: val("#closeResult"),
          vehicle_ready: val("#closeReady"),
          final_test_done: val("#closeTest"),
          can_return_to_fleet: val("#closeFleet"),
          final_km: numeric("#closeKm"),
          new_vehicle_operational_status: val("#closeStatus"),
          final_observation: val("#closeObs"),
          close_with_pending_items: $("#closePending").checked,
          pending_justification: val("#closePendingReason"),
          pending_responsible_user_id: numeric("#closePendingResponsible"),
          pending_due_at: dateTimeValue("#closePendingDue")
        });
        showResult(true, "Processo fechado.");
      } catch (err) { showResult(false, err.message); }
    }
    function selectReport(id, switchTab=true) {
      const report = (processData.technical_reports || []).find(item => item.id === id);
      if (!report) return;
      selectedReportId = id;
      selectedReportType = report.report_code;
      $("#reportSaveButton").textContent = "Guardar alterações";
      setVal("#reportCode", report.report_code);
      setVal("#reportMoment", report.report_moment);
      setVal("#reportOrigin", report.reading_origin);
      setVal("#reportLink", report.original_link || "");
      setVal("#reportValues", JSON.stringify(report.extracted_values || {}, null, 2));
      setVal("#validateValues", JSON.stringify(report.validated_values || report.extracted_values || {}, null, 2));
      renderReportFields(report.extracted_values || report.validated_values || {});
      updateReportOpen();
      renderReports();
      if (switchTab) showPhase("reports");
    }
    function newReportDraft() {
      selectedReportId = null;
      selectedReportType = val("#reportCode") || selectedReportType;
      if (selectedReportType) setVal("#reportCode", selectedReportType);
      $("#reportSaveButton").textContent = "Adicionar relatório";
      setVal("#reportLink", "");
      setVal("#reportValues", "{}");
      setVal("#validateValues", "{}");
      renderReportFields({});
      updateReportOpen();
      renderReports();
    }
    async function saveReport() {
      try {
        syncReportJsonFromFields();
        const payload = {report_code:val("#reportCode"), report_moment:val("#reportMoment"), reading_origin:val("#reportOrigin"), original_link:val("#reportLink"), extracted_values:jsonFrom("#reportValues")};
        const data = selectedReportId
          ? await requestJson(`/api/workshop/technical-reports/${selectedReportId}`, "PATCH", payload)
          : await requestJson(`/api/workshop/processes/${processId}/technical-reports`, "POST", payload);
        selectedReportId = data.id || selectedReportId;
        selectedReportType = payload.report_code;
        const existingIndex = (processData.technical_reports || []).findIndex(report => report.id === selectedReportId);
        if (existingIndex >= 0) processData.technical_reports[existingIndex] = data;
        else processData.technical_reports = [...(processData.technical_reports || []), data];
        $("#reportSaveButton").textContent = "Guardar alterações";
        renderReports();
        showResult(true, selectedReportId ? `Relatório #${selectedReportId} guardado.` : "Relatório guardado.");
      } catch (err) { showResult(false, err.message); }
    }
    async function validateReport() {
      try {
        if (!selectedReportId) throw new Error("Seleciona um relatório antes de validar.");
        syncReportJsonFromFields();
        const validated = val("#validateValues") ? jsonFrom("#validateValues") : jsonFrom("#reportValues");
        const data = await requestJson(`/api/workshop/technical-reports/${selectedReportId}/validate`, "POST", {validated_values:validated});
        const existingIndex = (processData.technical_reports || []).findIndex(report => report.id === selectedReportId);
        if (existingIndex >= 0) processData.technical_reports[existingIndex] = data;
        renderReports();
        showResult(true, `Relatório #${selectedReportId} validado.`);
      } catch (err) { showResult(false, err.message); }
    }
    loadConfig().then(loadProcess).catch(err => showResult(false, err.message));
  </script>
</body>
</html>"""
    return html.replace("__PROCESS_ID__", str(process_id))
