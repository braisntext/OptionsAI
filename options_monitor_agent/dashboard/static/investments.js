/* investments.js — Frontend logic for Gestión de Inversiones */
'use strict';

const CSRF = document.querySelector('meta[name="csrf-token"]')?.content || '';
let accounts = [];
let selectedSymbol = null;
let priceChart = null;
let searchTimeout = null;

// ── Helpers ──────────────────────────────────────────────────────────────────

function api(url, opts = {}) {
  const headers = { 'X-CSRF-Token': CSRF, ...(opts.headers || {}) };
  if (opts.body && typeof opts.body === 'object' && !(opts.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(opts.body);
  }
  return fetch(url, { ...opts, headers }).then(r => r.json());
}

function fmt(n, decimals = 2) {
  if (n == null || isNaN(n)) return '—';
  return new Intl.NumberFormat('es-ES', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(n);
}

function fmtEur(n) {
  if (n == null || isNaN(n)) return '—';
  return fmt(n) + ' €';
}

function plClass(n) {
  if (n == null || isNaN(n)) return '';
  return n >= 0 ? 'pl-positive' : 'pl-negative';
}

function summaryClass(n) {
  if (n == null || isNaN(n)) return '';
  return n >= 0 ? 'positive' : 'negative';
}

function showToast(msg, type = 'success') {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast ' + type;
  t.style.display = 'block';
  setTimeout(() => { t.style.display = 'none'; }, 3000);
}

// ── Init ─────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('year').textContent = new Date().getFullYear();

  // Nav toggle
  const toggle = document.getElementById('menuToggle');
  const menu = document.getElementById('navMenu');
  toggle.addEventListener('click', () => {
    const open = menu.classList.toggle('active');
    toggle.classList.toggle('active');
    toggle.setAttribute('aria-expanded', open);
  });
  menu.querySelectorAll('a').forEach(l => l.addEventListener('click', () => {
    menu.classList.remove('active');
    toggle.classList.remove('active');
  }));

  // Close search on outside click
  document.addEventListener('click', e => {
    document.querySelectorAll('.search-results').forEach(el => {
      if (!el.parentElement.contains(e.target)) el.classList.remove('active');
    });
  });

  // Set default date to today
  const today = new Date().toISOString().split('T')[0];
  const txDate = document.getElementById('txDate');
  const divDate = document.getElementById('divDate');
  if (txDate) txDate.value = today;
  if (divDate) divDate.value = today;

  refreshAll();
});

// ── Core data loading ────────────────────────────────────────────────────────

async function refreshAll() {
  await loadAccounts();
  loadSummary();
  loadPositions();
  loadTransactions();
  loadDividends();
  loadClosed();
}

async function loadAccounts() {
  const res = await api('/api/investments/accounts');
  if (res.status === 'ok') {
    accounts = res.accounts;
    populateAccountSelects();
  }
}

function populateAccountSelects() {
  const selects = ['txAccount', 'divAccount'];
  selects.forEach(id => {
    const sel = document.getElementById(id);
    if (!sel) return;
    sel.innerHTML = accounts.map(a =>
      `<option value="${a.id}">${a.broker}${a.account_name ? ' — ' + a.account_name : ''}</option>`
    ).join('');
    if (!accounts.length) {
      sel.innerHTML = '<option value="">Sin cuentas — crea una primero</option>';
    }
  });
}

async function loadSummary() {
  const res = await api('/api/investments/portfolio/summary');
  if (res.status !== 'ok') return;

  document.getElementById('sumInvested').textContent = fmtEur(res.total_invested_eur);
  const mv = document.getElementById('sumMarketValue');
  mv.textContent = fmtEur(res.total_market_value_eur);

  const ur = document.getElementById('sumUnrealized');
  ur.textContent = fmtEur(res.total_unrealized_pl_eur);
  ur.className = 'value ' + summaryClass(res.total_unrealized_pl_eur);

  const rl = document.getElementById('sumRealized');
  rl.textContent = fmtEur(res.total_realized_pl_eur);
  rl.className = 'value ' + summaryClass(res.total_realized_pl_eur);

  document.getElementById('sumDividends').textContent = fmtEur(res.total_dividends_eur);
  document.getElementById('sumPositions').textContent = res.positions_count || '0';
}

// ── Positions ────────────────────────────────────────────────────────────────

async function loadPositions() {
  const container = document.getElementById('positionsContainer');
  const res = await api('/api/investments/positions');
  if (res.status !== 'ok') {
    container.innerHTML = '<div class="empty-state"><div class="empty-icon">📊</div><p>Error cargando posiciones</p></div>';
    return;
  }

  if (!res.positions.length) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">📊</div>
        <h3>Sin posiciones abiertas</h3>
        <p>Añade tu primera operación de compra o importa datos desde el módulo Fiscal para empezar.</p>
        <button class="btn btn-primary" onclick="openAddTxModal()" style="margin-top:1rem;">+ Nueva Operación</button>
      </div>`;
    return;
  }

  let html = '<div class="positions-list">';
  for (const p of res.positions) {
    const plEur = p.unrealized_pl_eur;
    const plPct = p.unrealized_pl_pct;
    html += `
      <div class="position-row" onclick="openDetail('${p.symbol}')">
        <div>
          <div class="sym">${p.symbol}</div>
          <div class="sym-name">${p.symbol_name || p.broker || ''}</div>
        </div>
        <div>
          <div class="cell-label">Cantidad</div>
          <div class="cell-value">${fmt(p.quantity, 4)}</div>
        </div>
        <div>
          <div class="cell-label">Coste Medio</div>
          <div class="cell-value">${fmtEur(p.avg_cost_eur)}</div>
        </div>
        <div>
          <div class="cell-label">Valor Mercado</div>
          <div class="cell-value">${fmtEur(p.market_value_eur)}</div>
        </div>
        <div>
          <div class="cell-label">P&L</div>
          <div class="cell-value ${plClass(plEur)}">${fmtEur(plEur)} (${plPct != null ? fmt(plPct, 1) + '%' : '—'})</div>
        </div>
        <button class="expand-btn" title="Ver detalle">▸</button>
      </div>`;
  }
  html += '</div>';
  container.innerHTML = html;
}

// ── Position Detail ──────────────────────────────────────────────────────────

async function openDetail(symbol) {
  selectedSymbol = symbol;
  const panel = document.getElementById('detailPanel');
  panel.classList.add('active');
  document.getElementById('detailTitle').textContent = symbol + ' — Detalle';

  // Load detail data
  const res = await api('/api/investments/positions/' + encodeURIComponent(symbol));
  if (res.status !== 'ok') return;

  // Lots table
  const lotsHtml = res.lots.length ? `
    <table class="data-table">
      <thead><tr><th>Fecha compra</th><th>Broker</th><th>Cantidad</th><th>Coste/ud €</th></tr></thead>
      <tbody>${res.lots.map(l => `
        <tr>
          <td>${l.buy_date}</td>
          <td>${l.broker || ''}</td>
          <td>${fmt(l.remaining_quantity, 4)}</td>
          <td>${fmtEur(l.cost_per_unit_eur)}</td>
        </tr>`).join('')}
      </tbody>
    </table>` : '<p style="font-size:.85rem;color:var(--text-muted)">Sin lotes abiertos</p>';
  document.getElementById('lotsTable').innerHTML = lotsHtml;

  // Recent transactions
  const txHtml = res.transactions.length ? `
    <table class="data-table">
      <thead><tr><th>Fecha</th><th>Tipo</th><th>Cant.</th><th>Precio</th><th>Broker</th></tr></thead>
      <tbody>${res.transactions.slice(0, 10).map(t => `
        <tr>
          <td>${t.tx_date}</td>
          <td>${t.tx_type}</td>
          <td>${fmt(t.quantity, 4)}</td>
          <td>${fmtEur(t.price_eur || t.price)}</td>
          <td>${t.broker || ''}</td>
        </tr>`).join('')}
      </tbody>
    </table>` : '<p style="font-size:.85rem;color:var(--text-muted)">Sin operaciones</p>';
  document.getElementById('detailTxTable').innerHTML = txHtml;

  // Dividends
  const divHtml = res.dividends.length ? `
    <table class="data-table">
      <thead><tr><th>Fecha</th><th>Importe €</th><th>Retención €</th></tr></thead>
      <tbody>${res.dividends.map(d => `
        <tr>
          <td>${d.pay_date}</td>
          <td>${fmtEur(d.amount_eur)}</td>
          <td>${fmtEur(d.withholding_eur)}</td>
        </tr>`).join('')}
      </tbody>
    </table>` : '<p style="font-size:.85rem;color:var(--text-muted)">Sin dividendos</p>';
  document.getElementById('detailDivTable').innerHTML = divHtml;

  // Load chart
  loadChart(symbol, '1y');

  // Scroll to panel
  panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function closeDetail() {
  document.getElementById('detailPanel').classList.remove('active');
  selectedSymbol = null;
}

// ── Charts ───────────────────────────────────────────────────────────────────

async function loadChart(symbol, period) {
  // Update active button
  document.querySelectorAll('#chartControls button').forEach(b => {
    b.classList.toggle('active', b.textContent.toLowerCase().includes(
      period === '1m' ? '1m' : period === '3m' ? '3m' : period === '6m' ? '6m' :
      period === '1y' ? '1a' : period === '5y' ? '5a' : 'max'
    ));
  });

  const res = await api('/api/investments/chart/' + encodeURIComponent(symbol) + '?period=' + period);
  if (res.status !== 'ok' || !res.data || !res.data.length) return;

  const ctx = document.getElementById('priceChart').getContext('2d');
  if (priceChart) priceChart.destroy();

  const labels = res.data.map(d => d.date);
  const prices = res.data.map(d => d.close_eur || d.close);

  priceChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [{
        label: symbol + ' (€)',
        data: prices,
        borderColor: getComputedStyle(document.documentElement).getPropertyValue('--primary-text').trim() || '#6366f1',
        backgroundColor: 'transparent',
        borderWidth: 2,
        pointRadius: 0,
        tension: 0.3,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => fmt(ctx.parsed.y) + ' €'
          }
        }
      },
      scales: {
        x: {
          display: true,
          ticks: { maxTicksLimit: 8, font: { size: 10 } },
          grid: { display: false },
        },
        y: {
          ticks: { font: { size: 10 }, callback: v => fmt(v) + '€' },
          grid: { color: 'rgba(0,0,0,.06)' },
        }
      },
      interaction: { mode: 'index', intersect: false },
    }
  });
}

// ── Transactions ─────────────────────────────────────────────────────────────

async function loadTransactions() {
  const container = document.getElementById('transactionsContainer');
  const res = await api('/api/investments/transactions?per_page=100');
  if (res.status !== 'ok') return;

  if (!res.transactions.length) {
    container.innerHTML = '<div class="empty-state"><div class="empty-icon">📋</div><h3>Sin operaciones</h3><p>Añade tu primera operación o importa desde Fiscal.</p></div>';
    return;
  }

  let html = `
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr>
          <th>Fecha</th><th>Tipo</th><th>Símbolo</th><th>Cantidad</th>
          <th>Precio</th><th>Comisión</th><th>Broker</th><th>Fuente</th><th></th>
        </tr></thead>
        <tbody>`;
  for (const t of res.transactions) {
    html += `<tr>
      <td>${t.tx_date}</td>
      <td><span style="text-transform:capitalize">${t.tx_type}</span></td>
      <td><strong>${t.symbol}</strong></td>
      <td>${fmt(t.quantity, 4)}</td>
      <td>${fmtEur(t.price_eur || t.price)}</td>
      <td>${t.commission_eur ? fmtEur(t.commission_eur) : '—'}</td>
      <td>${t.broker || ''}</td>
      <td><span style="font-size:.75rem;color:var(--text-muted)">${t.source || ''}</span></td>
      <td><button class="btn btn-sm" style="background:transparent;color:var(--danger);border:1px solid var(--danger);padding:2px 8px;font-size:.7rem;" onclick="deleteTx(${t.id})">✕</button></td>
    </tr>`;
  }
  html += '</tbody></table></div>';
  if (res.total > 100) html += `<p style="text-align:center;font-size:.8rem;color:var(--text-muted);margin-top:.5rem;">Mostrando 100 de ${res.total} operaciones</p>`;
  container.innerHTML = html;
}

async function deleteTx(id) {
  if (!confirm('¿Eliminar esta operación? Se recalculará el FIFO.')) return;
  const res = await api('/api/investments/transactions/' + id, { method: 'DELETE' });
  if (res.status === 'ok') {
    showToast('Operación eliminada');
    refreshAll();
  } else {
    showToast(res.message || 'Error', 'error');
  }
}

// ── Dividends ────────────────────────────────────────────────────────────────

async function loadDividends() {
  const container = document.getElementById('dividendsContainer');
  const res = await api('/api/investments/dividends?per_page=100');
  if (res.status !== 'ok') return;

  if (!res.dividends.length) {
    container.innerHTML = '<div class="empty-state"><div class="empty-icon">💰</div><h3>Sin dividendos</h3><p>Registra dividendos manualmente o importa desde Fiscal.</p></div>';
    return;
  }

  let html = `
    <div style="margin-bottom:1rem;font-weight:600;">Total dividendos: <span style="color:var(--success)">${fmtEur(res.total_amount_eur)}</span></div>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr>
          <th>Fecha</th><th>Símbolo</th><th>Importe</th><th>Importe €</th>
          <th>Retención €</th><th>Broker</th><th>Fuente</th>
        </tr></thead>
        <tbody>`;
  for (const d of res.dividends) {
    html += `<tr>
      <td>${d.pay_date}</td>
      <td><strong>${d.symbol}</strong></td>
      <td>${fmt(d.amount)} ${d.currency}</td>
      <td>${fmtEur(d.amount_eur)}</td>
      <td>${d.withholding_eur ? fmtEur(d.withholding_eur) : '—'}</td>
      <td>${d.broker || ''}</td>
      <td><span style="font-size:.75rem;color:var(--text-muted)">${d.source || ''}</span></td>
    </tr>`;
  }
  html += '</tbody></table></div>';
  container.innerHTML = html;
}

// ── Closed Positions ─────────────────────────────────────────────────────────

async function loadClosed() {
  const container = document.getElementById('closedContainer');
  const res = await api('/api/investments/closed');
  if (res.status !== 'ok') return;

  if (!res.closed.length) {
    container.innerHTML = '<div class="empty-state"><div class="empty-icon">✅</div><h3>Sin posiciones cerradas</h3><p>Las posiciones cerradas aparecerán cuando registres ventas.</p></div>';
    return;
  }

  let html = `
    <div style="margin-bottom:1rem;font-weight:600;">P&L realizado total: <span class="${plClass(res.total_realized_pl_eur)}">${fmtEur(res.total_realized_pl_eur)}</span></div>
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr>
          <th>Símbolo</th><th>Compra</th><th>Venta</th><th>Cant.</th>
          <th>Coste €</th><th>Ingreso €</th><th>P&L €</th><th>Días</th><th>Broker</th>
        </tr></thead>
        <tbody>`;
  for (const c of res.closed) {
    html += `<tr>
      <td><strong>${c.symbol}</strong></td>
      <td>${c.buy_date}</td>
      <td>${c.sell_date}</td>
      <td>${fmt(c.quantity, 4)}</td>
      <td>${fmtEur(c.cost_eur)}</td>
      <td>${fmtEur(c.proceeds_eur)}</td>
      <td class="${plClass(c.realized_pl_eur)}">${fmtEur(c.realized_pl_eur)}</td>
      <td>${c.holding_days}</td>
      <td>${c.broker || ''}</td>
    </tr>`;
  }
  html += '</tbody></table></div>';
  container.innerHTML = html;
}

// ── Tabs ─────────────────────────────────────────────────────────────────────

function switchTab(tab) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
  document.querySelectorAll('.tab-content').forEach(c => c.classList.toggle('active', c.id === 'tab-' + tab));
}

// ── Modals ───────────────────────────────────────────────────────────────────

function openModal(id) { document.getElementById(id).classList.add('active'); }
function closeModal(id) { document.getElementById(id).classList.remove('active'); }

function openAddTxModal() {
  if (!accounts.length) {
    showToast('Primero crea una cuenta de inversión', 'error');
    openAccountsModal();
    return;
  }
  document.getElementById('txForm').reset();
  document.getElementById('txDate').value = new Date().toISOString().split('T')[0];
  openModal('txModal');
}

function openAddDivModal() {
  if (!accounts.length) {
    showToast('Primero crea una cuenta', 'error');
    openAccountsModal();
    return;
  }
  document.getElementById('divForm').reset();
  document.getElementById('divDate').value = new Date().toISOString().split('T')[0];
  openModal('divModal');
}

function openAccountsModal() {
  renderAccountsList();
  openModal('accountsModal');
}

async function openImportModal() {
  openModal('importModal');
  const container = document.getElementById('fiscalStatements');
  container.innerHTML = '<div class="loading"><div class="spinner"></div></div>';

  const res = await api('/api/investments/import/fiscal/available');
  if (res.status !== 'ok' || !res.statements.length) {
    container.innerHTML = '<p style="color:var(--text-muted);font-size:.9rem;">No hay extractos fiscales disponibles para importar. Sube primero un extracto en el <a href="/fiscal" style="color:var(--primary-text)">Importador Fiscal</a>.</p>';
    document.getElementById('importBtn').disabled = true;
    return;
  }

  let html = '';
  for (const s of res.statements) {
    const imported = s.already_imported;
    html += `
      <div class="fiscal-stmt-item ${imported ? 'imported' : ''}">
        <div class="fiscal-stmt-info">
          <div><span class="broker">${s.broker}</span> — Año fiscal ${s.tax_year}</div>
          <div class="meta">${s.trade_count} operaciones, ${s.dividend_count} dividendos${imported ? ' · Ya importado ✓' : ''}</div>
        </div>
        <label style="display:flex;align-items:center;gap:.5rem;">
          <input type="checkbox" class="fiscal-import-cb" value="${s.id}" ${imported ? 'disabled' : ''}>
          ${imported ? 'Importado' : 'Seleccionar'}
        </label>
      </div>`;
  }
  container.innerHTML = html;

  // Enable/disable import button based on selection
  container.querySelectorAll('.fiscal-import-cb').forEach(cb => {
    cb.addEventListener('change', () => {
      const anyChecked = container.querySelector('.fiscal-import-cb:checked');
      document.getElementById('importBtn').disabled = !anyChecked;
    });
  });
  document.getElementById('importBtn').disabled = true;
}

// ── Form submissions ─────────────────────────────────────────────────────────

async function submitTx(e) {
  e.preventDefault();
  const account_id = parseInt(document.getElementById('txAccount').value);
  if (!account_id) { showToast('Selecciona una cuenta', 'error'); return false; }

  const body = {
    account_id,
    symbol: document.getElementById('txSymbol').value.trim().toUpperCase(),
    tx_type: document.getElementById('txType').value,
    tx_date: document.getElementById('txDate').value,
    quantity: parseFloat(document.getElementById('txQty').value),
    price: parseFloat(document.getElementById('txPrice').value),
    currency: document.getElementById('txCurrency').value,
    commission: parseFloat(document.getElementById('txCommission').value) || 0,
    notes: document.getElementById('txNotes').value.trim(),
  };

  const res = await api('/api/investments/transactions', { method: 'POST', body });
  if (res.status === 'ok') {
    showToast('Operación registrada');
    closeModal('txModal');
    refreshAll();
  } else {
    showToast(res.message || 'Error', 'error');
  }
  return false;
}

async function submitDiv(e) {
  e.preventDefault();
  const account_id = parseInt(document.getElementById('divAccount').value);
  if (!account_id) { showToast('Selecciona una cuenta', 'error'); return false; }

  const body = {
    account_id,
    symbol: document.getElementById('divSymbol').value.trim().toUpperCase(),
    pay_date: document.getElementById('divDate').value,
    amount: parseFloat(document.getElementById('divAmount').value),
    currency: document.getElementById('divCurrency').value,
    withholding: parseFloat(document.getElementById('divWithholding').value) || 0,
  };

  const res = await api('/api/investments/dividends', { method: 'POST', body });
  if (res.status === 'ok') {
    showToast('Dividendo registrado');
    closeModal('divModal');
    refreshAll();
  } else {
    showToast(res.message || 'Error', 'error');
  }
  return false;
}

async function submitAccount(e) {
  e.preventDefault();
  const broker = document.getElementById('acctBroker').value.trim();
  const account_name = document.getElementById('acctName').value.trim();

  if (!broker) { showToast('Broker requerido', 'error'); return false; }

  const res = await api('/api/investments/accounts', { method: 'POST', body: { broker, account_name } });
  if (res.status === 'ok') {
    showToast('Cuenta creada');
    await loadAccounts();
    document.getElementById('accountForm').reset();
    renderAccountsList();
  } else {
    showToast(res.message || 'Error', 'error');
  }
  return false;
}

async function deleteAccount(id) {
  if (!confirm('¿Eliminar esta cuenta? Se borrarán TODAS sus operaciones, posiciones y dividendos.')) return;
  const res = await api('/api/investments/accounts/' + id, { method: 'DELETE' });
  if (res.status === 'ok') {
    showToast('Cuenta eliminada');
    await loadAccounts();
    renderAccountsList();
    refreshAll();
  } else {
    showToast(res.message || 'Error', 'error');
  }
}

function renderAccountsList() {
  const container = document.getElementById('accountsList');
  if (!accounts.length) {
    container.innerHTML = '<p style="color:var(--text-muted);font-size:.9rem;">No tienes cuentas de inversión.</p>';
    return;
  }
  container.innerHTML = accounts.map(a => `
    <div style="display:flex;justify-content:space-between;align-items:center;padding:.5rem 0;border-bottom:1px solid var(--border);">
      <div>
        <strong>${a.broker}</strong>${a.account_name ? ' — ' + a.account_name : ''}
        <div style="font-size:.75rem;color:var(--text-muted);">Creada: ${a.created_at ? a.created_at.split('T')[0] : ''}</div>
      </div>
      <button class="btn btn-sm" style="background:transparent;color:var(--danger);border:1px solid var(--danger);font-size:.75rem;padding:2px 8px;"
              onclick="deleteAccount(${a.id})">Eliminar</button>
    </div>`).join('');
}

// ── Fiscal Import ────────────────────────────────────────────────────────────

async function doFiscalImport() {
  const checkboxes = document.querySelectorAll('.fiscal-import-cb:checked');
  const ids = Array.from(checkboxes).map(cb => parseInt(cb.value));
  if (!ids.length) return;

  document.getElementById('importBtn').disabled = true;
  document.getElementById('importBtn').textContent = 'Importando...';

  const res = await api('/api/investments/import/fiscal', { method: 'POST', body: { statement_ids: ids } });
  if (res.status === 'ok') {
    const imp = res.imported;
    showToast(`Importado: ${imp.transactions} operaciones, ${imp.dividends} dividendos`);
    closeModal('importModal');
    refreshAll();
  } else {
    showToast(res.message || 'Error al importar', 'error');
  }

  document.getElementById('importBtn').textContent = 'Importar seleccionados';
  document.getElementById('importBtn').disabled = false;
}

// ── Symbol Search ────────────────────────────────────────────────────────────

function searchSymbol(query) {
  _doSearch(query, 'symbolResults', 'txSymbol');
}

function searchSymbolDiv(query) {
  _doSearch(query, 'symbolResultsDiv', 'divSymbol');
}

function _doSearch(query, resultsId, inputId) {
  const container = document.getElementById(resultsId);
  if (!query || query.length < 1) {
    container.classList.remove('active');
    return;
  }
  clearTimeout(searchTimeout);
  searchTimeout = setTimeout(async () => {
    const res = await api('/api/investments/search?q=' + encodeURIComponent(query));
    if (res.status !== 'ok' || !res.results.length) {
      container.classList.remove('active');
      return;
    }
    container.innerHTML = res.results.map(r => `
      <div class="search-result-item" onclick="selectSymbol('${r.symbol}', '${inputId}', '${resultsId}')">
        <span class="sr-symbol">${r.symbol}</span>
        <span class="sr-name">${r.name || ''} · ${r.exchange || ''}</span>
      </div>`).join('');
    container.classList.add('active');
  }, 300);
}

function selectSymbol(symbol, inputId, resultsId) {
  document.getElementById(inputId).value = symbol;
  document.getElementById(resultsId).classList.remove('active');
}
