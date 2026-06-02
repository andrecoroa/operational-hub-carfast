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
      .grid-3 { grid-template-columns: 1fr; }
      .actions { left: 0; padding: 12px 16px; }
    }
  </style>
</head>
<body>
  <div class="app">
    <aside>
      <div class="brand">CarFast v2</div>
      <nav class="nav-group">
        <a class="nav-item" href="/">Inicio</a>
        <a class="nav-item" href="/fleet">Frota</a>
        <a class="nav-item active" href="/workshop">Oficina</a>
        <a class="nav-sub" href="/workshop/manage">Processos atuais</a>
        <a class="nav-sub" href="/workshop/processes-ui">Processos por Fases</a>
        <a class="nav-sub active" href="/workshop/new-process">Novo Processo</a>
        <a class="nav-item" href="/task-board">Tarefas</a>
        <a class="nav-item" href="/documents">Documentos</a>
        <a class="nav-item" href="/task-board/manage?workspace=management">Gestao</a>
        <a class="nav-item" href="/admin">Administracao</a>
      </nav>
    </aside>
    <main>
      <div class="topbar">
        <div>
          <h1>Novo Processo Oficina por Fases</h1>
          <p class="subtitle">Criação leve, serviços múltiplos e fases automáticas.</p>
        </div>
        <div class="top-actions">
          <a class="top-link" href="/workshop">Oficina</a>
          <a class="top-link" href="/workshop/manage">Processos atuais</a>
          <a class="top-link" href="/workshop/processes-ui">Por fases</a>
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
                <input id="plate" name="plate" placeholder="AA-00-AA" required>
              </label>
              <label>Km atual
                <input id="kmCurrent" name="km_current" type="number" min="0" placeholder="Opcional">
              </label>
            </div>
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
    };

    const els = {
      form: document.querySelector("#processForm"),
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
      els.origin.addEventListener("change", updateUiState);
      ["plate", "manualTitle", "otherDetail", "originDetail", "scheduledAt"].forEach((id) => {
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
        ["Matrícula / Viatura", Boolean(document.querySelector("#plate").value.trim()), true],
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
      els.submitButton.disabled = true;
      els.result.className = "result";
      els.result.textContent = "";

      const services = selectedServices().map(servicePayload);
      const payload = {
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
        els.result.innerHTML = `<strong>Processo criado:</strong><br>${data.title}<br><span class="hint">Estado: ${data.status}. Fase atual: ${data.current_phase_code}.</span><br><br><a href="/workshop/processes-ui/${data.id}">Abrir processo</a>`;
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
      process_creation:"Criação do processo", administrative_reception:"Receção administrativa", history_check:"Verificação de histórico",
      technical_phase:"Fase técnica", diagnosis_decision:"Diagnóstico e decisão", budget_approval:"Orçamento / aprovação",
      internal_repair_execution:"Reparação interna / execução", final_closure:"Fecho definitivo"
    }};
    const VALUES = {{normal:"Normal", high:"Alta", urgent:"Urgente", reception:"Receção", appointment:"Marcação", station:"Estação", customer_driver:"Cliente / condutor", rentway_alert:"Alerta Rentway", internal_preparation:"Preparação interna", other:"Outro"}};
    function safe(value) {{ return String(value ?? "-").replace(/[&<>"']/g, c => ({{"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"}}[c])); }}
    function label(value) {{ return VALUES[value] || value || "-"; }}
    function statusMeta(status) {{ return STATUS[status] || [status || "-", "neutral"]; }}
    function chip(status) {{ const meta = statusMeta(status); return `<span class="chip ${{meta[1]}}">${{safe(meta[0])}}</span>`; }}

    function render(process) {{
      const activePhase = process.current_phase_code;
      const v = process.vehicle || {{}};
      const status = statusMeta(process.status);
      const model = [v.brand, v.model, v.version].filter(Boolean).join(" ");
      const alerts = Array.from(new Map(process.alerts.filter(a => a.status !== "resolved").map(a => [a.message, a])).values());
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
    :root { --bg:#f5f7f8; --panel:#fff; --line:#d9e0e5; --text:#07152d; --muted:#5c6c7b; --brand:#b24a34; --brand-soft:#fbf1ee; --green:#2f7d50; --green-soft:#edf7ef; --blue:#1d5f94; --blue-soft:#eaf3fb; --amber:#9a6711; --amber-soft:#fff6df; --red:#b42318; --red-soft:#fff4f2; font-family:Inter,"Segoe UI",Arial,sans-serif; }
    *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--text);font-size:14px;letter-spacing:0}.app{display:grid;grid-template-columns:248px minmax(0,1fr);min-height:100vh}aside{background:#10202c;color:#d9e7ef;padding:20px 14px}.brand{font-weight:800;font-size:18px;padding:8px 10px 20px;color:#fff}.nav{display:grid;gap:4px}.nav a{min-height:36px;padding:8px 10px;border-radius:8px;color:#d9e7ef;text-decoration:none;font-weight:650}.nav .sub{margin-left:18px;color:#b6cad5}.nav .active{background:#f4ebe7;color:#7d2f1f}main{padding:22px 28px}h1{margin:0 0 4px;font-size:25px}.subtitle{margin:0;color:var(--muted)}.topbar{display:flex;justify-content:space-between;gap:16px;align-items:start;margin-bottom:18px}.top-actions{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:8px}.button{display:inline-flex;align-items:center;justify-content:center;min-height:40px;border-radius:8px;padding:9px 14px;background:var(--brand);color:#fff;text-decoration:none;font-weight:800}.button.secondary{background:#fff;color:var(--text);border:1px solid var(--line)}.summary-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-bottom:14px}.kpi{background:#fff;border:1px solid var(--line);border-radius:8px;padding:12px}.kpi span{display:block;color:var(--muted);font-size:12px;font-weight:800}.kpi strong{display:block;margin-top:4px;font-size:22px}.list{display:grid;gap:10px}.process-card{position:relative;display:grid;grid-template-columns:190px minmax(0,1fr) 340px auto;gap:18px;align-items:center;background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:16px 16px 16px 20px;box-shadow:0 1px 2px rgba(16,32,44,.04)}.process-card:before{content:"";position:absolute;left:0;top:0;bottom:0;width:5px;background:var(--brand);border-radius:8px 0 0 8px}.plate{font-size:24px;font-weight:900;letter-spacing:0}.small{font-size:12px;color:var(--muted);line-height:1.45}.title{font-size:17px;font-weight:900;margin-bottom:5px}.meta{display:flex;flex-wrap:wrap;gap:8px}.chip{display:inline-flex;align-items:center;border-radius:999px;min-height:26px;padding:4px 10px;background:#eef1f3;color:var(--muted);font-size:12px;font-weight:850}.chip.done{color:var(--green);background:var(--green-soft)}.chip.progress{color:var(--blue);background:var(--blue-soft)}.chip.review{color:var(--amber);background:var(--amber-soft)}.chip.danger{color:var(--red);background:var(--red-soft)}.phase-progress{display:grid;gap:7px}.phase-name{font-weight:850}.steps{display:grid;grid-template-columns:repeat(8,1fr);gap:5px}.step{height:7px;border-radius:999px;background:#e7ecef}.step.done{background:var(--green)}.step.active{background:var(--brand)}.empty{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:24px;color:var(--muted)}@media(max-width:1100px){.process-card{grid-template-columns:170px minmax(0,1fr) auto}.phase-progress{grid-column:1/-1}.summary-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:900px){.app{grid-template-columns:1fr}aside{display:none}main{padding:18px 16px}.topbar{display:grid}.summary-grid,.process-card{grid-template-columns:1fr}.process-card .button{width:100%}}
  </style>
</head>
<body>
  <div class="app">
    <aside><div class="brand">CarFast v2</div><nav class="nav"><a href="/">Início</a><a href="/fleet">Frota</a><a href="/workshop">Oficina</a><a class="sub" href="/workshop/manage">Processos atuais</a><a class="sub active" href="/workshop/processes-ui">Processos por fases</a><a class="sub" href="/workshop/new-process">Novo processo por fases</a><a href="/task-board">Tarefas</a><a href="/documents">Documentos</a></nav></aside>
    <main>
      <div class="topbar"><div><h1>Oficina - Processos por fases</h1><p class="subtitle">Acompanhar processos criados no novo modelo por blocos.</p></div><div class="top-actions"><a class="button secondary" href="/workshop">Oficina</a><a class="button secondary" href="/workshop/manage">Processos atuais</a><a class="button secondary" href="/fleet">Frota</a><a class="button" href="/workshop/new-process">+ Novo processo por fases</a></div></div>
      <div id="summaryCards" class="summary-grid"></div>
      <div id="rows" class="list"><div class="empty">A carregar processos...</div></div>
    </main>
  </div>
  <script>
    const rows = document.querySelector("#rows");
    const STATUS = {
      completed:["Concluído","done"], completed_with_pending_items:["Concluído com pendências","review"], validated:["Validado","done"],
      in_progress:["Em curso","progress"], pending_review:["Por rever","review"], reception_pending:["Receção pendente","review"],
      pending_definition:["Por definir","review"], not_started:["Não iniciado","neutral"], open:["Aberto","review"], cancelled:["Cancelado","danger"]
    };
    const PHASES = {
      process_creation:"Criação do processo", administrative_reception:"Receção administrativa", history_check:"Verificação de histórico",
      technical_phase:"Fase técnica", diagnosis_decision:"Diagnóstico e decisão", budget_approval:"Orçamento / aprovação",
      internal_repair_execution:"Reparação interna / execução", final_closure:"Fecho definitivo"
    };
    const PRIORITY = {low:"Baixa", normal:"Normal", high:"Alta", urgent:"Urgente"};
    const ORDER = ["process_creation","administrative_reception","history_check","technical_phase","diagnosis_decision","budget_approval","internal_repair_execution","final_closure"];
    function meta(map, code) { return map[code] || [code || "-", "neutral"]; }
    function vehicleName(v) { return [v?.brand, v?.model, v?.version].filter(Boolean).join(" ") || "Dados da viatura por completar"; }
    function unitLine(v) { return [v?.rentway_unit_nr ? `Unit ${v.rentway_unit_nr}` : null, v?.vin ? `VIN ${v.vin}` : null].filter(Boolean).join(" · ") || "Sem Unit/VIN registado"; }
    function card(p) {
      const v = p.vehicle || {};
      const status = meta(STATUS, p.status);
      const phase = PHASES[p.current_phase_code] || p.current_phase_code || "-";
      const service = p.services_label || p.title || "Processo oficina";
      const activeIndex = Math.max(0, ORDER.indexOf(p.current_phase_code));
      return `<article class="process-card">
        <div><div class="plate">${v.plate || p.plate || "-"}</div><div class="small">${unitLine(v)}</div></div>
        <div><div class="title">${service}</div><div class="small">${vehicleName(v)}</div><div class="meta"><span class="chip ${status[1]}">${status[0]}</span><span class="chip">Prioridade ${PRIORITY[p.priority] || p.priority || "-"}</span></div></div>
        <div class="phase-progress"><div class="phase-name">${phase}</div><div class="steps">${ORDER.map((_, i) => `<span class="step ${i < activeIndex ? "done" : i === activeIndex ? "active" : ""}"></span>`).join("")}</div></div>
        <a class="button" href="/workshop/processes-ui/${p.id}/manage">Abrir processo</a>
      </article>`;
    }
    function renderSummary(items) {
      const review = items.filter(p => ["pending_review","reception_pending","pending_definition"].includes(p.status)).length;
      const progress = items.filter(p => p.status === "in_progress").length;
      const closed = items.filter(p => ["completed","completed_with_pending_items"].includes(p.status)).length;
      document.querySelector("#summaryCards").innerHTML = [
        ["Total processos", items.length],
        ["Por rever / pendentes", review],
        ["Em curso", progress],
        ["Fechados", closed],
      ].map(k => `<div class="kpi"><span>${k[0]}</span><strong>${k[1]}</strong></div>`).join("");
    }
    fetch("/api/workshop/processes").then(r => r.json()).then((items) => {
      renderSummary(items);
      rows.innerHTML = items.map(card).join("") || `<div class="empty">Ainda não existem processos por fases.</div>`;
    }).catch((e) => { rows.innerHTML = `<div class="empty">${e.message}</div>`; });
  </script>
</body>
</html>"""


@router.get("/processes-ui/{process_id}/manage", response_class=HTMLResponse)
def workshop_process_manage_page(process_id: int) -> str:
    return f"""<!doctype html>
<html lang="pt">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Operar Processo Oficina #{process_id}</title>
  <style>
    :root{{--bg:#f5f7f8;--panel:#fff;--line:#d9e0e5;--line2:#b9c5cc;--text:#07152d;--muted:#5c6c7b;--brand:#b24a34;--soft:#fbf1ee;--green:#2f7d50;--green-soft:#edf7ef;--amber:#9a6711;--amber-soft:#fff6df;--red:#b42318;--red-soft:#fff4f2;font-family:Inter,"Segoe UI",Arial,sans-serif}}
    *{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font-size:14px;letter-spacing:0}}.app{{display:grid;grid-template-columns:248px minmax(0,1fr);min-height:100vh}}aside{{background:#10202c;color:#d9e7ef;padding:20px 14px}}.brand{{font-weight:800;font-size:18px;padding:8px 10px 20px;color:#fff}}.nav{{display:grid;gap:4px}}.nav a{{min-height:36px;padding:8px 10px;border-radius:8px;color:#d9e7ef;text-decoration:none;font-weight:650}}.nav .sub{{margin-left:18px;color:#b6cad5}}.nav .active{{background:#f4ebe7;color:#7d2f1f}}main{{padding:22px 28px 44px}}h1{{margin:0 0 4px;font-size:25px}}h2{{margin:0 0 14px;font-size:17px}}h3{{margin:0 0 10px;font-size:15px}}.subtitle,.muted{{color:var(--muted)}}.topbar{{display:flex;justify-content:space-between;gap:16px;align-items:start;margin-bottom:14px}}.top-actions{{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:8px}}.process-hero{{background:#fff;border:1px solid var(--line);border-radius:8px;padding:16px;margin-bottom:14px;box-shadow:0 1px 2px rgba(16,32,44,.04)}}.vehicle-strip{{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:10px;background:#fff;border:1px solid var(--line);border-radius:8px;padding:14px 16px;margin:0 0 18px}}.vehicle-strip div{{display:grid;gap:3px}}.vehicle-strip span,.memory span{{display:block;color:var(--muted);font-size:12px;font-weight:750}}.vehicle-strip strong,.memory strong{{display:block;font-size:14px;line-height:1.25}}.layout{{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:18px;align-items:start}}.stack{{display:grid;gap:14px}}section,.panel{{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:18px}}.panel{{position:sticky;top:18px}}.section-title{{display:flex;justify-content:space-between;gap:12px;align-items:center;margin-bottom:14px}}.grid2{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}}.grid3{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}}label{{display:grid;gap:6px;color:var(--muted);font-weight:650}}input,textarea,select{{width:100%;min-height:38px;border:1px solid var(--line2);border-radius:8px;padding:9px 10px;color:var(--text);background:#fff;font:inherit}}textarea{{min-height:76px;resize:vertical}}button,.button{{min-height:38px;border:1px solid var(--line2);border-radius:8px;padding:8px 12px;background:#fff;color:var(--text);font:inherit;font-weight:800;cursor:pointer;text-decoration:none}}button.primary,.button.primary{{background:var(--brand);border-color:var(--brand);color:#fff}}.button.secondary{{background:#fff;color:var(--text);border-color:var(--line2)}}.chip{{display:inline-flex;border-radius:999px;min-height:26px;padding:4px 10px;background:#eef1f3;color:var(--muted);font-size:12px;font-weight:800}}.chip.ok,.chip.done{{color:var(--green);background:var(--green-soft)}}.chip.progress{{color:#1d5f94;background:#eaf3fb}}.chip.warn,.chip.review{{color:var(--amber);background:var(--amber-soft)}}.chip.neutral{{color:var(--muted);background:#eef1f3}}.chip.danger{{color:var(--red);background:var(--red-soft)}}.phase-list,.plain-list{{display:grid;gap:8px;margin:0;padding:0;list-style:none}}.phase-list li,.plain-list li{{display:flex;justify-content:space-between;gap:12px;align-items:center;padding:10px;border:1px solid var(--line);border-radius:8px;background:#fbfcfd;font-weight:700}}.phase-list li.active{{border-color:var(--brand);background:var(--soft);box-shadow:inset 4px 0 0 var(--brand)}}.tabs{{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:16px;padding-bottom:12px;border-bottom:1px solid var(--line)}}.tab{{border:1px solid var(--line);border-radius:8px;background:#fff;padding:8px 10px;font-weight:800;cursor:pointer}}.tab.active{{background:var(--soft);border-color:var(--brand);color:#7d2f1f}}.form-section{{display:none}}.form-section.active{{display:block}}.memory{{display:none;margin:0 0 14px;padding:12px;border:1px solid #cfe2d2;background:#f8fbf8;border-radius:8px}}.memory.active{{display:block}}.memory-grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}}.memory-grid div{{display:grid;gap:3px;padding:8px;border:1px solid #e2ebe3;border-radius:8px;background:#fff}}.result{{display:none;margin-top:10px;border-radius:8px;padding:10px;border:1px solid var(--line)}}.result.active{{display:block}}.result.ok{{background:var(--green-soft);border-color:#b7d7be}}.result.err{{background:var(--red-soft);border-color:#e2b7b3}}@media(max-width:980px){{.app{{grid-template-columns:1fr}}aside{{display:none}}main{{padding:18px 16px}}.topbar{{display:grid}}.vehicle-strip,.layout,.grid2,.grid3,.memory-grid{{grid-template-columns:1fr}}.panel{{position:static}}}}
  </style>
</head>
<body>
  <div class="app">
    <aside><div class="brand">CarFast v2</div><nav class="nav"><a href="/">Início</a><a href="/fleet">Frota</a><a href="/workshop">Oficina</a><a class="sub" href="/workshop/manage">Processos atuais</a><a class="sub active" href="/workshop/processes-ui">Processos por fases</a><a class="sub" href="/workshop/new-process">Novo processo por fases</a><a href="/task-board">Tarefas</a><a href="/documents">Documentos</a></nav></aside>
    <main>
      <div id="header" class="process-hero"><div class="topbar"><div><h1>Processo Oficina</h1><p class="subtitle">A carregar...</p></div><div class="top-actions"><a class="button secondary" href="/workshop">Oficina</a><a class="button secondary" href="/workshop/manage">Processos atuais</a><a class="button secondary" href="/fleet">Frota</a><a class="button" href="/workshop/processes-ui">Lista por fases</a></div></div></div>
      <div class="layout">
        <div class="stack">
          <div id="vehicleStrip" class="vehicle-strip"></div>
          <section>
            <div class="tabs">
              <button class="tab active" data-tab="reception">Receção</button><button class="tab" data-tab="history">Histórico</button><button class="tab" data-tab="reports">Relatórios</button><button class="tab" data-tab="checks">Verificações</button><button class="tab" data-tab="decision">Decisão</button><button class="tab" data-tab="budget">Orçamento</button><button class="tab" data-tab="repair">Reparação</button><button class="tab" data-tab="close">Fecho</button>
            </div>
            <div id="reception" class="form-section active">
              <h2>Receção Administrativa</h2>
              <div id="receptionMemory" class="memory"></div>
              <div class="grid2"><label>KM entrada<input id="recKm" type="number" min="0"></label><label>Foto quadrante inicial<input id="recPhoto" placeholder="https://..."></label></div>
              <label>Observação inicial<textarea id="recObs"></textarea></label>
              <div class="grid2"><label>Estado visual<select id="recVisual"><option value="">Selecionar</option><option>Sem danos aparentes</option><option>Com danos ligeiros</option><option>Com danos relevantes</option><option>Não verificado</option></select></label><label>Descrição danos<input id="recDamage"></label></div>
              <button id="receptionButton" class="primary" onclick="confirmReception()">Confirmar receção</button>
            </div>
            <div id="history" class="form-section">
              <h2>Verificação de Histórico</h2>
              <div id="historyMemory" class="memory"></div>
              <div class="grid2"><label>Histórico interno<select id="histInternal"><option value="yes">Sim</option><option value="no">Não</option><option value="pending_review">Por rever</option></select></label><label>Accident reports<select id="histAccidents"><option value="no">Não</option><option value="yes">Sim</option><option value="pending_review">Por rever</option></select></label></div>
              <label>Detalhe accident reports<input id="histAccidentsDetail"></label>
              <div class="grid2"><label>Processos anteriores<select id="histPrev"><option value="yes">Sim</option><option value="none">Não existem</option><option value="pending_review">Por rever</option></select></label><label>Incidência repetida<select id="histRepeat"><option value="no">Não</option><option value="yes">Sim</option><option value="pending_review">Por avaliar</option></select></label></div>
              <label>Observação histórico<textarea id="histObs"></textarea></label>
              <button id="historyButton" class="primary" onclick="confirmHistory()">Confirmar histórico</button>
            </div>
            <div id="reports" class="form-section">
              <h2>Relatórios Técnicos</h2>
              <div class="grid3"><label>Relatório<select id="reportCode"></select></label><label>Momento<select id="reportMoment"><option value="initial">Inicial</option><option value="final">Final</option></select></label><label>Origem<select id="reportOrigin"><option value="stellantis_machine">Máquina Stellantis</option><option value="autel">Autel</option><option value="other">Outro</option></select></label></div>
              <label>Link relatório original<input id="reportLink" placeholder="https://..."></label><label>Valores extraídos JSON<textarea id="reportValues" placeholder='{{"campo":"valor"}}'></textarea></label>
              <button class="primary" onclick="addReport()">Adicionar relatório</button>
              <h3 style="margin-top:16px">Validar relatório</h3>
              <div class="grid2"><label>ID relatório<input id="validateReportId" type="number"></label><label>Valores validados JSON<input id="validateValues" placeholder='{{"campo":"valor"}}'></label></div>
              <button onclick="validateReport()">Validar</button>
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
        <div class="panel"><div class="section-title"><h2>Resumo</h2><span id="statusChip" class="chip">-</span></div><div id="summary"></div></div>
      </div>
    </main>
  </div>
  <script>
    const processId = {process_id}; let processData = null; let config = null; const result = document.querySelector("#result");
    function payloadValue(id) {{ return document.querySelector(id).value || null; }}
    function jsonValue(id) {{ const v = payloadValue(id); if (!v) return null; try {{ return JSON.parse(v); }} catch {{ throw new Error(`JSON inválido em ${{id}}`); }} }}
    function showResult(ok, message) {{ result.className = `result active ${{ok ? "ok" : "err"}}`; result.textContent = typeof message === "string" ? message : JSON.stringify(message); }}
    async function post(url, body) {{ const r = await fetch(url, {{method:"POST", headers:{{"Content-Type":"application/json"}}, body:JSON.stringify(body)}}); const data = await r.json(); if(!r.ok) throw new Error(JSON.stringify(data.detail || data)); await loadProcess(); return data; }}
    document.querySelectorAll(".tab").forEach(t => t.addEventListener("click", () => {{ document.querySelectorAll(".tab,.form-section").forEach(x => x.classList.remove("active")); t.classList.add("active"); document.querySelector(`#${{t.dataset.tab}}`).classList.add("active"); }}));
    const STATUS = {{
      completed:["Concluído","done"], completed_with_pending_items:["Concluído com pendências","review"], validated:["Validado","done"],
      ok:["OK","done"], in_progress:["Em curso","progress"], pending_review:["Por rever","review"], reception_pending:["Receção pendente","review"],
      pending_definition:["Por definir","review"], pending:["Pendente","review"], open:["Aberto","review"], added:["Adicionado","progress"],
      pending_validation:["Por validar","review"], corrected_manually:["Corrigido manualmente","review"], unable_to_read:["Falha na leitura","danger"],
      not_applicable:["Não aplicável","neutral"], not_started:["Não iniciado","neutral"], cancelled:["Cancelado","danger"], high:["Alta","danger"], critical:["Crítica","danger"]
    }};
    const PHASES = {{
      process_creation:"Criação do processo", administrative_reception:"Receção administrativa", history_check:"Verificação de histórico",
      technical_phase:"Fase técnica", diagnosis_decision:"Diagnóstico e decisão", budget_approval:"Orçamento / aprovação",
      internal_repair_execution:"Reparação interna / execução", final_closure:"Fecho definitivo"
    }};
    const VALUES = {{yes:"Sim", no:"Não", pending_review:"Por rever", none:"Não existem", not_ok:"Não OK", low:"Baixa", medium:"Média", high:"Alta", critical:"Crítica", normal:"Normal", urgent:"Urgente", initial:"Inicial", final:"Final", stellantis_machine:"Máquina Stellantis", autel:"Autel", other:"Outro", free:"Livre", in_contract:"Em contrato", in_preparation:"Em preparação", blocked:"Bloqueada", in_maintenance:"Em manutenção", for_sale:"Em venda", immobilized:"Imobilizada"}};
    function safe(value) {{ return String(value ?? "-").replace(/[&<>"']/g, c => ({{"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"}}[c])); }}
    function label(value) {{ return VALUES[value] || value || "-"; }}
    function statusMeta(code) {{ return STATUS[code] || [code || "-", "neutral"]; }}
    function chip(code) {{ const meta = statusMeta(code); return `<span class="chip ${{meta[1]}}">${{safe(meta[0])}}</span>`; }}
    function phaseData(code) {{ return (processData.phases.find(p => p.phase_code === code) || {{}}).data || {{}}; }}
    function hasData(data) {{ return data && Object.keys(data).some(k => data[k] !== null && data[k] !== "" && data[k] !== undefined); }}
    function setValue(id, value) {{ const el = document.querySelector(id); if (el && value !== null && value !== undefined) el.value = value; }}
    function setChecked(id, value) {{ const el = document.querySelector(id); if (el) el.checked = Boolean(value); }}
    function setButton(id, fresh, update) {{ const el = document.querySelector(id); if (el) el.textContent = update ? `Atualizar ${{fresh}}` : `Confirmar ${{fresh}}`; }}
    function memory(id, rows) {{
      const cleanRows = rows.filter(r => r[1] !== null && r[1] !== undefined && r[1] !== "");
      const el = document.querySelector(id);
      if (!el) return;
      if (!cleanRows.length) {{ el.className = "memory"; el.innerHTML = ""; return; }}
      el.className = "memory active";
      el.innerHTML = `<div class="memory-grid">${{cleanRows.map(r => `<div><span>${{safe(r[0])}}</span><strong>${{safe(label(r[1]))}}</strong></div>`).join("")}}</div>`;
    }}
    function renderVehicle() {{
      const v = processData.vehicle || {{}};
      const model = [v.brand, v.model, v.version].filter(Boolean).join(" ") || "-";
      document.querySelector("#vehicleStrip").innerHTML = [
        ["Matrícula", v.plate || processData.plate],
        ["Marca / modelo", model],
        ["Unit Rentway", v.rentway_unit_nr],
        ["VIN", v.vin],
        ["KM entrada", processData.initial_km],
        ["Estado operacional", label(v.operational_status)],
      ].map(item => `<div><span>${{safe(item[0])}}</span><strong>${{safe(item[1])}}</strong></div>`).join("");
    }}
    function renderSummary() {{
      const status = statusMeta(processData.status);
      const statusChip = document.querySelector("#statusChip");
      statusChip.textContent = status[0];
      statusChip.className = `chip ${{status[1]}}`;
      const alerts = Array.from(new Map(processData.alerts.filter(a => a.status !== "resolved").map(a => [a.message, a])).values());
      document.querySelector("#summary").innerHTML = `<ul class="phase-list">${{processData.phases.map(p => `<li class="${{p.phase_code === processData.current_phase_code ? "active" : ""}}"><span>${{p.sort_order}}. ${{safe(PHASES[p.phase_code] || p.name)}}</span>${{chip(p.status)}}</li>`).join("")}}</ul><h3 style="margin-top:16px">Alertas</h3><ul class="plain-list">${{alerts.map(a => `<li><span>${{safe(a.message)}}</span>${{chip(a.status || a.severity)}}</li>`).join("") || "<li>Sem alertas</li>"}}</ul><h3 style="margin-top:16px">Relatórios</h3><ul class="plain-list">${{processData.technical_reports.map(r => `<li><span>#${{r.id}} ${{safe(r.report_name)}}<br><small class="muted">${{safe(label(r.report_moment))}} · ${{safe(label(r.reading_origin))}}</small></span>${{chip(r.status)}}</li>`).join("") || "<li>Sem relatórios</li>"}}</ul>`;
    }}
    function renderPhaseMemory() {{
      const reception = phaseData("administrative_reception");
      memory("#receptionMemory", [["KM entrada", reception.km_entry], ["Foto quadrante", reception.quadrant_photo_link], ["Estado visual", reception.visible_damage_status], ["Danos", reception.damage_description], ["Observação", reception.initial_observation]]);
      setValue("#recKm", reception.km_entry); setValue("#recPhoto", reception.quadrant_photo_link); setValue("#recObs", reception.initial_observation); setValue("#recVisual", reception.visible_damage_status); setValue("#recDamage", reception.damage_description); setButton("#receptionButton", "receção", hasData(reception));
      const history = phaseData("history_check");
      memory("#historyMemory", [["Histórico interno", history.internal_history_checked], ["Accident reports", history.open_accident_reports], ["Detalhe", history.accident_reports_detail], ["Processos anteriores", history.previous_processes_reviewed], ["Incidência repetida", history.repeated_incidence], ["Observação", history.history_observation]]);
      setValue("#histInternal", history.internal_history_checked); setValue("#histAccidents", history.open_accident_reports); setValue("#histAccidentsDetail", history.accident_reports_detail); setValue("#histPrev", history.previous_processes_reviewed); setValue("#histRepeat", history.repeated_incidence); setValue("#histObs", history.history_observation); setButton("#historyButton", "histórico", hasData(history));
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
    async function loadConfig() {{ config = await (await fetch("/api/workshop/process-config")).json(); document.querySelector("#reportCode").innerHTML = config.stellantis_reports.map(r => `<option value="${{r.code}}">${{r.label}}</option>`).join(""); document.querySelector("#checkCode").innerHTML = config.technical_checks.map(c => `<option value="${{c.code}}">${{c.label}}</option>`).join(""); }}
    async function loadProcess() {{ processData = await (await fetch(`/api/workshop/processes/${{processId}}`)).json(); const v = processData.vehicle || {{}}; const status = statusMeta(processData.status); const model = [v.brand, v.model, v.version].filter(Boolean).join(" "); document.querySelector("#header").innerHTML = `<div class="topbar"><div><h1>${{safe(processData.services_label || processData.title)}}</h1><p class="subtitle">${{safe(v.plate || processData.plate || "-")}} · ${{safe(model || "Dados da viatura por completar")}} · ${{safe(status[0])}}</p></div><div class="top-actions"><a class="button secondary" href="/workshop">Oficina</a><a class="button secondary" href="/workshop/manage">Processos atuais</a><a class="button secondary" href="/fleet">Frota</a><a class="button" href="/workshop/processes-ui">Processos por fases</a></div></div>`; renderVehicle(); renderSummary(); renderPhaseMemory(); }}
    async function confirmReception() {{ try {{ await post(`/api/workshop/processes/${{processId}}/reception`, {{km_entry:Number(payloadValue("#recKm")) || null, quadrant_photo_link:payloadValue("#recPhoto"), initial_observation:payloadValue("#recObs"), visible_damage_status:payloadValue("#recVisual"), damage_description:payloadValue("#recDamage")}}); showResult(true, "Receção confirmada."); }} catch(e) {{ showResult(false, e.message); }} }}
    async function confirmHistory() {{ try {{ await post(`/api/workshop/processes/${{processId}}/history-check`, {{internal_history_checked:payloadValue("#histInternal"), open_accident_reports:payloadValue("#histAccidents"), accident_reports_detail:payloadValue("#histAccidentsDetail"), previous_processes_reviewed:payloadValue("#histPrev"), relevant_interventions_identified:"no", repeated_incidence:payloadValue("#histRepeat"), history_observation:payloadValue("#histObs")}}); showResult(true, "Histórico confirmado."); }} catch(e) {{ showResult(false, e.message); }} }}
    async function addReport() {{ try {{ const data = await post(`/api/workshop/processes/${{processId}}/technical-reports`, {{report_code:payloadValue("#reportCode"), report_moment:payloadValue("#reportMoment"), reading_origin:payloadValue("#reportOrigin"), original_link:payloadValue("#reportLink"), extracted_values:jsonValue("#reportValues")}}); document.querySelector("#validateReportId").value = data.id; showResult(true, `Relatório adicionado #${{data.id}}.`); }} catch(e) {{ showResult(false, e.message); }} }}
    async function validateReport() {{ try {{ await post(`/api/workshop/technical-reports/${{payloadValue("#validateReportId")}}/validate`, {{validated_values:jsonValue("#validateValues") || {{}}}}); showResult(true, "Relatório validado."); }} catch(e) {{ showResult(false, e.message); }} }}
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
