/**
 * Albion Quant System (AQS) — 2026 Cockpit Terminal Script
 * Sidebar Cockpit Navigation • Zero Overlaps • Instant 60 FPS Response
 */

// Application State Store
const state = {
  activeTab: 'all',
  viewMode: 'cards', // 'cards' | 'table'
  currentPage: 1,
  pageSize: 24,
  opportunities: {},
  settings: {},
  stats: {},
  filters: {
    search: '',
    category: 'all',
    tier: 0,
    enchantment: 'all',
    quality: 0,
    sourceCity: '',
    destCity: '',
    latestOnly: false,
    safeOnly: false,
    highRoiOnly: false,
    highVolOnly: false,
    highTierOnly: false,
    enchantedOnly: false,
    maxInvestment: 0,
    minProfit: 0,
    minRoi: 0,
    minVolume: 0,
    sortBy: 'score', // 'score', 'profit', 'roi', 'cost_asc', 'cost_desc', 'volume', 'weight_eff'
  },
  volumeOverrides: {}, // { opp_key: quantity }
  isScanning: false,
  dismissedIds: new Set(JSON.parse(sessionStorage.getItem('aqs_dismissed_ids') || '[]')),
};

function saveDismissedIds() {
  try {
    sessionStorage.setItem('aqs_dismissed_ids', JSON.stringify(Array.from(state.dismissedIds)));
  } catch (e) {}
}

// Debounce helper
function debounce(fn, delay = 150) {
  let timer = null;
  return function(...args) {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => fn.apply(this, args), delay);
  };
}

// Official Albion Render Icon Helper
function getItemIconUrl(itemId, quality = 1, size = 128) {
  if (!itemId || itemId === 'undefined' || itemId === 'null') return 'https://render.albiononline.com/v1/item/T4_BAG.png';
  let cleanId = String(itemId).trim();
  if (cleanId.toLowerCase().endsWith('.png')) cleanId = cleanId.slice(0, -4);
  
  // Uppercase base item ID while preserving enchantment numbers after @
  if (cleanId.includes('@')) {
    const parts = cleanId.split('@');
    cleanId = `${parts[0].toUpperCase()}@${parts[1]}`;
  } else {
    cleanId = cleanId.toUpperCase();
  }

  // Preserve '@' in the path for Albion render service routing (do not encode to %40)
  const safeIdentifier = encodeURIComponent(cleanId).replace(/%40/g, '@');
  const q = Math.max(1, Math.min(5, parseInt(quality || 1)));
  const s = Math.max(32, Math.min(217, parseInt(size || 128)));
  return `https://render.albiononline.com/v1/item/${safeIdentifier}.png?quality=${q}&size=${s}`;
}

// Graceful icon error fallback (try base item without enchantment, then fallback)
function handleIconError(img, itemId, quality = 1) {
  if (!img) return;
  img.onerror = null;
  const cleanId = String(itemId || '').trim();
  if (cleanId.includes('@')) {
    const baseId = cleanId.split('@')[0].toUpperCase();
    img.src = `https://render.albiononline.com/v1/item/${baseId}.png?quality=${quality}&size=128`;
    img.onerror = function() {
      img.onerror = null;
      img.src = 'https://render.albiononline.com/v1/item/T4_BAG.png';
    };
  } else {
    img.src = 'https://render.albiononline.com/v1/item/T4_BAG.png';
  }
}

// Numerical & Currency Formatter
function fmtK(num) {
  if (num === null || num === undefined || isNaN(num)) return '0';
  const n = Number(num);
  const absN = Math.abs(n);
  const sign = n < 0 ? '-' : '';
  if (absN >= 1000000) return sign + (absN / 1000000).toFixed(2) + 'M';
  if (absN >= 1000) return sign + (absN / 1000).toFixed(1) + 'k';
  return Math.round(n).toLocaleString();
}

function fmtProfit(num) {
  if (num === null || num === undefined || isNaN(num)) return '0';
  const n = Number(num);
  if (n > 0) return `+${fmtK(n)}`;
  if (n < 0) return `-${fmtK(Math.abs(n))}`;
  return '0';
}

function fmtAge(seconds) {
  if (!seconds || seconds <= 0) return '<1m';
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

// City Visual Palette
const CITY_COLORS = {
  'Bridgewatch': 'var(--city-bw)',
  'Martlock': 'var(--city-ml)',
  'Lymhurst': 'var(--city-ly)',
  'Fort Sterling': 'var(--city-fs)',
  'Thetford': 'var(--city-tf)',
  'Caerleon': 'var(--city-cl)',
  'Brecilien': 'var(--city-br)',
  'Black Market': 'var(--city-bm)',
  'Island': '#3fb950',
};

// Toast Notifications
function showToast(msg, isSuccess = true) {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = 'toast-msg';
  toast.innerHTML = `<span>${isSuccess ? '⚡' : '⚠️'}</span> <span>${msg}</span>`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(20px)';
    toast.style.transition = 'all 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}

// ═══════════════════════════════════════════════════════════════
// UI SYNCHRONIZATION & SETTINGS DISPATCHERS
// ═══════════════════════════════════════════════════════════════
// NOTE: updateSettingsUI() and updateStatsUI() are defined in the
// "UI SYNCHRONIZATION & RENDERING" section below.




async function fetchSettings() {
  try {
    const res = await fetch('/api/v1/system/settings');
    if (!res.ok) throw new Error('Failed to load settings');
    state.settings = await res.json();
    updateSettingsUI();
  } catch (err) {
    console.error('Settings load error:', err);
  }
}

async function fetchStats() {
  try {
    const res = await fetch('/api/v1/system/stats');
    if (!res.ok) throw new Error('Failed to load stats');
    state.stats = await res.json();
    updateStatsUI();
  } catch (err) {
    console.error('Stats load error:', err);
  }
}

async function fetchOpportunities(silent = false) {
  try {
    const res = await fetch('/api/v1/system/opportunities?category=all');
    if (!res.ok) throw new Error('Failed to load opportunities');
    const data = await res.json();
    const rawCategories = data.categories || {};
    
    // Purge any locally dismissed items
    const filteredCategories = {};
    for (const [k, list] of Object.entries(rawCategories)) {
      if (Array.isArray(list)) {
        filteredCategories[k] = list.filter(o => {
          const idUpper = String(o.item_id || o.target_item_id || '').toUpperCase();
          return !state.dismissedIds.has(idUpper);
        });
      } else {
        filteredCategories[k] = list;
      }
    }

    const newTotal = Object.values(filteredCategories).flat().length;
    const oldTotal = Object.values(state.opportunities).flat().length;
    const isFirstLoad = oldTotal === 0 && newTotal > 0;

    state.opportunities = filteredCategories;
    updateTabCounts();
    
    // If silent periodic poll and total count hasn't changed, update KPIs in-place to prevent DOM reload blips/stutter
    if (silent && !isFirstLoad && newTotal === oldTotal) {
      updateKpisInPlace();
      return;
    }

    renderViews();
  } catch (err) {
    console.error('Opportunities load error:', err);
  }
}

async function toggleDiscordAlerts(enabled) {
  try {
    const res = await fetch('/api/v1/system/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ discord_alerts_enabled: enabled }),
    });
    if (!res.ok) throw new Error('Failed to update alert settings');
    state.settings = await res.json();
    updateSettingsUI();
    showToast(
      enabled
        ? 'Discord Webhook Broadcast: ARMED 🟢'
        : 'Discord Webhook Broadcast: MUTED 🔴',
      enabled
    );
  } catch (err) {
    console.error('Toggle error:', err);
    showToast('Failed to update alert settings', false);
  }
}

async function toggleContinuousScan(enabled) {
  try {
    const res = await fetch('/api/v1/system/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ standby_mode: !enabled }),
    });
    if (!res.ok) throw new Error('Failed to update auto-scan settings');
    state.settings = await res.json();
    updateSettingsUI();
    showToast(
      enabled
        ? 'Live Auto-Scan: ACTIVE 🟢 (Continuous background ingestion)'
        : 'Live Auto-Scan: PAUSED ⏸️ (On-Demand Mode)',
      enabled
    );
  } catch (err) {
    console.error('Auto-scan toggle error:', err);
    showToast('Failed to toggle auto-scan', false);
  }
}

async function togglePremiumStatus(enabled) {
  try {
    const res = await fetch('/api/v1/system/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_premium: enabled }),
    });
    if (!res.ok) throw new Error('Failed to update premium status');
    state.settings = await res.json();
    updateSettingsUI();
    showToast(
      enabled
        ? '👑 Premium Mode Active: Market sales tax set to 4.0%'
        : 'Non-Premium Mode: Market sales tax set to 8.0%',
      enabled
    );
    renderViews();
  } catch (err) {
    console.error('Premium toggle error:', err);
    showToast('Failed to update premium status', false);
  }
}

async function stopTool() {
  const choice = confirm(
    '🛑 Stop Live Scanning & Tool\n\n' +
    'Click OK to pause all background scanning cycles and place the engine in STANDBY mode.\n' +
    '(You can resume anytime by toggling Live Auto-Scan or clicking Scan Now).'
  );
  if (!choice) return;

  // Instantly unlock and restore button states in 0ms
  state.isScanning = false;
  const scanBtn = document.getElementById('scan-now-btn');
  if (scanBtn) {
    scanBtn.innerHTML = '⚡ Scan Now';
    scanBtn.disabled = false;
  }
  const clearBtn = document.getElementById('clear-data-btn');
  if (clearBtn) {
    clearBtn.innerHTML = '🧹 Clear Data';
    clearBtn.disabled = false;
  }

  try {
    const res = await fetch('/api/v1/system/stop', { method: 'POST' });
    if (!res.ok) throw new Error('Failed to stop tool');
    state.settings = await res.json();
    updateSettingsUI();
    showToast('🛑 All background scanning stopped. Engine is now in STANDBY mode.', false);
  } catch (err) {
    console.error('Stop error:', err);
    showToast('Failed to stop background scanning on server', false);
  }
}

async function shutdownApp(force = false) {
  if (!force) {
    const choice = confirm(
      '⏻ Stop AQS & Terminate Server Process (Ctrl+C)\n\n' +
      'Are you sure you want to stop all background workers and safely exit the server process?'
    );
    if (!choice) return;
  }

  showToast('⏻ Terminating AQS server process (SIGINT / Ctrl+C)...', 'warning');

  // Disable UI buttons
  ['scan-now-btn', 'clear-data-btn', 'stop-tool-btn', 'shutdown-app-btn'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.disabled = true;
  });

  // Display Full-Screen Termination Overlay
  const overlay = document.getElementById('shutdown-overlay');
  if (overlay) {
    overlay.style.display = 'flex';
  }

  try {
    await fetch('/api/v1/system/shutdown', { method: 'POST' });
  } catch (err) {
    console.warn('Shutdown signal dispatched:', err);
  }
}


async function switchServer(server) {
  try {
    const res = await fetch('/api/v1/system/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ active_server: server }),
    });
    if (!res.ok) throw new Error('Failed to switch server');
    state.settings = await res.json();
    updateSettingsUI();
    showToast(`Switched active gateway to: ${server.toUpperCase()}`);
    await fetchStats();
    await fetchOpportunities();
  } catch (err) {
    console.error('Server switch error:', err);
  }
}

async function triggerScan() {
  if (state.isScanning) return;
  state.isScanning = true;
  const btn = document.getElementById('scan-now-btn');
  const isAuto = state.settings && state.settings.standby_mode === false;
  if (btn) {
    btn.innerHTML = '⏳ Scanning Universe...';
    btn.disabled = true;
  }

  showToast('Ingesting live orderbooks & evaluating verified alpha...');
  try {
    const res = await fetch('/api/v1/system/scan', { method: 'POST' });
    if (!res.ok) throw new Error('Scan failed');
    const data = await res.json();
    showToast(`Scan Complete: Found ${data.total_opportunities} verified opportunities.`);
    await fetchOpportunities();
    await fetchStats();
  } catch (err) {
    console.error('Scan trigger error:', err);
    showToast('Market scan encountered an issue', false);
  } finally {
    state.isScanning = false;
    if (btn) {
      btn.innerHTML = isAuto ? '⚡ Force Rescan' : '⚡ Scan Now';
      btn.disabled = false;
    }
  }
}


async function clearData() {
  const btn = document.getElementById('clear-data-btn');
  if (btn) {
    btn.innerHTML = '⏳ Clearing...';
    btn.disabled = true;
  }
  try {
    // 1. Instantly reset local UI state & empty cards/tables in 0ms
    state.opportunities = {};
    state.currentPage = 1;
    renderViews();
    updateTabCounts();

    // 2. Synchronize with backend to purge cached alpha records
    const res = await fetch('/api/v1/system/opportunities/clear', { method: 'POST' });
    if (!res.ok) throw new Error('Clear failed on server');

    showToast('🧹 Opportunity cache and tables cleared. Click ⚡ Scan Now when ready.', 'success');
  } catch (err) {
    console.error('Clear error:', err);
    showToast('Opportunity tables cleared locally.', 'info');
  } finally {
    if (btn) {
      btn.innerHTML = '🧹 Clear Data';
      btn.disabled = false;
    }
  }
}

// ═══════════════════════════════════════════════════════════════
// DYNAMIC VOLUME MATHEMATICAL ENGINE
// ═══════════════════════════════════════════════════════════════

function calculateScaledMetrics(opp, qty) {
  const isPremium = state.settings && state.settings.is_premium === true;
  const currentTaxRate = isPremium ? 0.04 : 0.08;
  
  // Tax rate embedded in the opportunity when scanned
  const oppTaxRate = opp.tax_rate !== undefined ? Number(opp.tax_rate) : (opp.is_premium === false ? 0.08 : 0.04);

  let unitProfit = Number(opp.net_profit || opp.profit || opp.estimated_profit || 0);
  const unitCost = Number(
    opp.mode === "CRAFT+RUN"
      ? (opp.craft_cost || opp.effective_cost || opp.total_cost || opp.buy_price)
      : (opp.total_cost || opp.effective_cost || opp.craft_cost || opp.buy_price || opp.material_cost_gross || 1)
  );
  const unitRevenue = Number(opp.sell_price || opp.bm_buy_price || opp.revenue_net || 0);
  const dailyVol = Number(opp.daily_volume || 10);
  const safeLimit = Number(opp.safe_limit || 1);
  
  // Real-time tax adjustment when user toggles Premium (4% vs 8% sales tax across all markets)
  if (unitRevenue > 0 && Math.abs(oppTaxRate - currentTaxRate) > 0.001) {
    const taxDelta = unitRevenue * (oppTaxRate - currentTaxRate);
    unitProfit = Math.round(unitProfit + taxDelta);
  }

  const unitWeight = Number(opp.profit_per_kg ? (unitProfit / opp.profit_per_kg) : 1.5);
  
  const batchProfit = Math.round(unitProfit * qty);
  const batchCost = Math.round(unitCost * qty);
  const batchRevenue = Math.round(unitRevenue * qty);
  const batchWeight = Number((unitWeight * qty).toFixed(1));
  const batchRoi = batchCost > 0 ? Number(((batchProfit / batchCost) * 100).toFixed(2)) : 0;

  // Slippage = 0.158 * sqrt(qty / max(dailyVol, 1))
  const slippagePct = Number((0.158 * Math.sqrt(qty / Math.max(dailyVol, 1)) * 100).toFixed(1));
  const isOverSafeLimit = qty > safeLimit;

  return {
    qty,
    unitProfit,
    batchProfit,
    unitCost,
    batchCost,
    unitRevenue,
    batchRevenue,
    batchWeight,
    batchRoi,
    slippagePct,
    isOverSafeLimit,
    safeLimit,
    dailyVol,
  };
}

// ═══════════════════════════════════════════════════════════════
// UI SYNCHRONIZATION & RENDERING
// ═══════════════════════════════════════════════════════════════

function updateSettingsUI() {
  const premToggle = document.getElementById('premium-status-toggle');
  const premLabel = document.getElementById('premium-status-label');
  if (premToggle) {
    const isPrem = state.settings.is_premium === true;
    premToggle.checked = isPrem;
    if (premLabel) {
      premLabel.textContent = isPrem ? 'Premium (4% Tax)' : 'Non-Prem (8% Tax)';
    }
  }

  const toggle = document.getElementById('discord-alerts-toggle');
  if (toggle) {
    toggle.checked = state.settings.discord_alerts_enabled !== false;
  }

  const contToggle = document.getElementById('continuous-scan-toggle');
  if (contToggle) {
    contToggle.checked = state.settings.standby_mode === false;
  }

  const scanBtn = document.getElementById('scan-now-btn');
  if (scanBtn && !state.isScanning) {
    const isAuto = state.settings.standby_mode === false;
    scanBtn.innerHTML = isAuto ? '⚡ Force Rescan' : '⚡ Scan Now';
    scanBtn.title = isAuto
      ? 'Instantly trigger a fresh scan cycle and refresh active opportunities'
      : 'Execute full-universe orderbook scan on-demand';
  }

  const serverSelect = document.getElementById('server-select');
  if (serverSelect && state.settings.active_server) {
    serverSelect.value = state.settings.active_server;
  }
}

function updateStatsUI() {
  const itemsCount = Number(state.stats.items_in_database || 11805).toLocaleString();
  const totalItemsEl = document.getElementById('stat-total-items');
  if (totalItemsEl) totalItemsEl.textContent = itemsCount;
  const totalItemsSidebar = document.getElementById('stat-total-items-sidebar');
  if (totalItemsSidebar) totalItemsSidebar.textContent = `${itemsCount} items`;

  const priceEl = document.getElementById('stat-price-records');
  if (priceEl) priceEl.textContent = Number(state.stats.regional_prices_loaded || 0).toLocaleString();
  
  const sub = document.getElementById('stat-price-sub');
  if (sub) {
    const lobCount = Number(state.stats.nats_lob_depth || 0);
    sub.textContent = lobCount > 0 
      ? `Live L2 Orderbook: ${lobCount.toLocaleString()} active live quotes` 
      : 'Live L2 & regional price snapshots';
  }

  const natsBadge = document.getElementById('stat-nats-status');
  if (natsBadge) {
    natsBadge.innerHTML = state.stats.nats_streaming_active 
      ? '<span class="status-dot"></span><span class="font-mono">Live L2 Feed</span>'
      : '<span class="status-dot" style="background:#6e7681;"></span><span class="font-mono">Polling</span>';
  }
}

function getActiveFiltersList() {
  const active = [];
  const { search, category, tier, enchantment, quality, sourceCity, destCity, safeOnly, highRoiOnly, highVolOnly, highTierOnly, latestOnly, maxInvestment, minProfit, minRoi, minVolume } = state.filters;
  if (search.trim()) active.push(`Search: "${search.trim()}"`);
  if (category && category !== 'all') active.push(`Cat: ${category.toUpperCase()}`);
  if (tier > 0) active.push(`Tier T${tier}`);
  if (highTierOnly) active.push(`T7 - T8 Tag`);
  if (enchantment !== 'all') active.push(`Enchant .${enchantment}`);
  if (quality > 0) active.push(`Quality Q${quality}`);
  if (sourceCity) active.push(`Source: ${sourceCity}`);
  if (destCity) active.push(`Dest: ${destCity}`);
  if (safeOnly) active.push(`Safe Routes Only`);
  if (highRoiOnly) active.push(`High ROI (>10%)`);
  if (highVolOnly) active.push(`High Vol (>50)`);
  if (latestOnly) active.push(`Latest Batch Only`);
  if (maxInvestment > 0) active.push(`Max Budget: < ${fmtK(maxInvestment)}s`);
  if (minProfit > 0) active.push(`Min Profit: ${fmtK(minProfit)}s`);
  if (minRoi > 0) active.push(`Min ROI: ${minRoi}%`);
  if (minVolume > 0) active.push(`Min Vol: ${minVolume}+`);
  return active;
}

window.resetAllFilters = function() {
  state.filters.search = '';
  state.filters.category = 'all';
  state.filters.tier = 0;
  state.filters.enchantment = 'all';
  state.filters.quality = 0;
  state.filters.sourceCity = '';
  state.filters.destCity = '';
  state.filters.safeOnly = false;
  state.filters.highRoiOnly = false;
  state.filters.highVolOnly = false;
  state.filters.highTierOnly = false;
  state.filters.latestOnly = false;
  state.filters.maxInvestment = 0;
  state.filters.minProfit = 0;
  state.filters.minRoi = 0;
  state.filters.minVolume = 0;

  const searchInput = document.getElementById('search-input');
  if (searchInput) searchInput.value = '';

  const catFilter = document.getElementById('category-filter');
  if (catFilter) catFilter.value = 'all';

  const tierFilter = document.getElementById('tier-filter');
  if (tierFilter) tierFilter.value = '0';

  const enchFilter = document.getElementById('enchant-filter');
  if (enchFilter) enchFilter.value = 'all';

  const maxCostFilter = document.getElementById('max-cost-filter');
  if (maxCostFilter) maxCostFilter.value = '0';

  const minProfitFilter = document.getElementById('min-profit-filter');
  if (minProfitFilter) minProfitFilter.value = '0';

  const minRoiFilter = document.getElementById('min-roi-filter');
  if (minRoiFilter) minRoiFilter.value = '0';

  const minVolFilter = document.getElementById('min-vol-filter');
  if (minVolFilter) minVolFilter.value = '0';

  const srcCityFilter = document.getElementById('source-city-filter');
  if (srcCityFilter) srcCityFilter.value = '';

  const dstCityFilter = document.getElementById('dest-city-filter');
  if (dstCityFilter) dstCityFilter.value = '';

  ['tag-latest-only', 'tag-safe-only', 'tag-high-roi', 'tag-high-vol', 'tag-high-tier'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.classList.remove('active');
  });

  document.querySelectorAll('.cat-pill-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.cat === 'all');
  });

  state.currentPage = 1;
  renderViews();
  updateTabCounts();
  showToast('All active filters reset');
};

function updateTabCounts() {
  let allCount = 0;
  const hasSubSectors = Boolean(state.opportunities.potions || state.opportunities.cooking || state.opportunities.farming);

  for (const [key, list] of Object.entries(state.opportunities)) {
    const count = (list || []).length;
    if (!(hasSubSectors && key === 'island')) {
      allCount += count;
    }
    const badge = document.getElementById(`count-${key}`);
    if (badge) badge.textContent = count;
  }
  const allBadge = document.getElementById('count-all');
  if (allBadge) allBadge.textContent = allCount;
}

// Master Render with Virtual Pagination
function updateKpisInPlace() {
  const filtered = getFilteredOpportunities();
  const totalEl = document.getElementById('stat-total-opps');
  if (totalEl) totalEl.textContent = filtered.length.toLocaleString();
  let pipelineProfit = 0;
  for (let i = 0; i < filtered.length; i++) {
    const m = calculateScaledMetrics(filtered[i], 1);
    pipelineProfit += m.unitProfit;
  }
  const profitEl = document.getElementById('stat-pipeline-profit');
  if (profitEl) profitEl.textContent = (pipelineProfit >= 0 ? '+' : '') + fmtK(pipelineProfit) + ' s';
}

function renderViews() {
  const filtered = getFilteredOpportunities();
  updateKpisInPlace();

  // Compute pagination
  const totalPages = Math.max(1, Math.ceil(filtered.length / state.pageSize));
  if (state.currentPage > totalPages) state.currentPage = totalPages;
  if (state.currentPage < 1) state.currentPage = 1;

  const startIdx = (state.currentPage - 1) * state.pageSize;
  const pageSlice = filtered.slice(startIdx, startIdx + state.pageSize);

  renderPaginationControls(totalPages, filtered.length);

  if (state.viewMode === 'cards') {
    document.getElementById('cards-view').style.display = 'grid';
    document.getElementById('table-view').style.display = 'none';
    renderCardsView(pageSlice, startIdx);
  } else {
    document.getElementById('cards-view').style.display = 'none';
    document.getElementById('table-view').style.display = 'block';
    renderTableView(pageSlice, startIdx);
  }
}

// Pagination Controls Bar
function renderPaginationControls(totalPages, totalItems) {
  const pContainer = document.getElementById('pagination-bar');
  if (!pContainer) return;

  if (totalItems === 0) {
    pContainer.innerHTML = '';
    return;
  }

  const startItem = (state.currentPage - 1) * state.pageSize + 1;
  const endItem = Math.min(totalItems, state.currentPage * state.pageSize);

  pContainer.innerHTML = `
    <div class="page-info-txt font-mono">
      Showing <strong>${startItem}–${endItem}</strong> of <strong>${totalItems.toLocaleString()}</strong> routes
    </div>
    <div class="page-btn-group">
      <button class="p-btn" ${state.currentPage === 1 ? 'disabled' : ''} onclick="goToPage(1)">«</button>
      <button class="p-btn" ${state.currentPage === 1 ? 'disabled' : ''} onclick="goToPage(${state.currentPage - 1})">‹ Prev</button>
      <span class="p-counter">Page <strong>${state.currentPage}</strong> / ${totalPages}</span>
      <button class="p-btn" ${state.currentPage >= totalPages ? 'disabled' : ''} onclick="goToPage(${state.currentPage + 1})">Next ›</button>
      <button class="p-btn" ${state.currentPage >= totalPages ? 'disabled' : ''} onclick="goToPage(${totalPages})">»</button>
      <select class="p-size-select" onchange="changePageSize(this.value)">
        <option value="24" ${state.pageSize === 24 ? 'selected' : ''}>24 / page</option>
        <option value="48" ${state.pageSize === 48 ? 'selected' : ''}>48 / page</option>
        <option value="96" ${state.pageSize === 96 ? 'selected' : ''}>96 / page</option>
      </select>
    </div>
  `;
}

window.goToPage = function(page) {
  state.currentPage = page;
  renderViews();
  window.scrollTo({ top: 120, behavior: 'smooth' });
};

window.changePageSize = function(size) {
  state.pageSize = parseInt(size) || 24;
  state.currentPage = 1;
  renderViews();
};

const CATEGORY_META = {
  bm_arbitrage: { label: '⚡ BM Arbitrage', color: '#f85149', bg: 'rgba(248,81,73,0.15)' },
  bm_enchanting: { label: '✨ Caerleon BM Enchant', color: '#d2a8ff', bg: 'rgba(210,168,255,0.15)' },
  bm_market_making: { label: '📊 Caerleon Spread', color: '#79c0ff', bg: 'rgba(121,192,255,0.15)' },
  arbitrage: { label: '🏰 Royal Safe Arbitrage', color: '#388bfd', bg: 'rgba(56,139,253,0.15)' },
  market_making: { label: '📈 Station Market Making', color: '#58a6ff', bg: 'rgba(88,166,255,0.15)' },
  crafting: { label: '⚒️ Equipment Craft (+15%)', color: '#e3b341', bg: 'rgba(227,179,65,0.15)' },
  refining: { label: '🌲 Resource Refining (+40%)', color: '#56d364', bg: 'rgba(86,211,100,0.15)' },
  enchanting: { label: '🔮 Artifact Enchanting', color: '#bc8cff', bg: 'rgba(188,140,255,0.15)' },
  transmutation: { label: '⚗️ Transmutation', color: '#f0883e', bg: 'rgba(240,136,62,0.15)' },
  quality_inversion: { label: '⭐ Quality Inversions', color: '#ffd700', bg: 'rgba(255,215,0,0.15)' },
  potions: { label: '🧪 Alchemy & Potions', color: '#39d353', bg: 'rgba(57,211,83,0.15)' },
  cooking: { label: '🍲 Cookery & Buff Meals', color: '#ffb703', bg: 'rgba(255,183,3,0.15)' },
  farming: { label: '🌾 Island Farming & Herbs', color: '#7ee787', bg: 'rgba(126,231,135,0.15)' },
  mounts: { label: '🐴 Mounts & Saddling', color: '#a371f7', bg: 'rgba(163,113,247,0.15)' },
  island: { label: '🌾 Island & Mounts', color: '#7ee787', bg: 'rgba(126,231,135,0.15)' },
};

function getCategoryMeta(key, opp) {
  if (key && CATEGORY_META[key]) return CATEGORY_META[key];
  const type = String((opp && (opp.category_key || opp.type || opp.category)) || '').toLowerCase();
  for (const [k, v] of Object.entries(CATEGORY_META)) {
    if (type.includes(k)) return v;
  }
  return { label: '⚡ Arbitrage', color: '#8b949e', bg: 'rgba(139,148,158,0.15)' };
}

function isLethalRoute(opp, srcCity, dstCity) {
  if (opp && opp.is_dangerous_route === true) return true;
  const src = String(srcCity || opp?.buy_city || opp?.source_city || opp?.craft_city || opp?.refine_city || opp?.base_city || '').trim().toLowerCase();
  const dst = String(dstCity || opp?.sell_city || opp?.destination_city || '').trim().toLowerCase();

  if (src === 'caerleon' && (dst === 'black market' || dst === 'caerleon' || dst === '')) {
    return false;
  }
  if (dst === 'black market' || dst === 'caerleon' || src === 'caerleon') {
    return true;
  }
  return false;
}

function getRouteZoneMeta(opp, srcCity, dstCity) {
  if (opp && opp.is_dangerous_route === true) {
    return { isLethal: true, label: '⚠️ LETHAL RED ZONE', badgeClass: 'badge-danger-route', type: 'Red Zone Run' };
  }
  const src = String(srcCity || opp?.buy_city || opp?.source_city || opp?.craft_city || opp?.refine_city || opp?.base_city || '').trim().toLowerCase();
  const dst = String(dstCity || opp?.sell_city || opp?.destination_city || '').trim().toLowerCase();

  if (src === 'caerleon' && (dst === 'black market' || dst === 'caerleon' || dst === '')) {
    return { isLethal: false, label: '🏰 CAERLEON SAFE', badgeClass: 'badge-caerleon-safe', type: 'City Safe' };
  }
  if (dst === 'black market' || dst === 'caerleon' || src === 'caerleon') {
    return { isLethal: true, label: '⚠️ LETHAL RED ZONE', badgeClass: 'badge-danger-route', type: 'Red Zone Run' };
  }
  return { isLethal: false, label: '🛡️ ROYAL SAFE', badgeClass: 'badge-safe-route', type: 'Continental Safe' };
}

function getEffectiveDataAge(opp) {
  if (!opp) return 0;
  // For Black Market trades, the primary target quote is the Black Market buy order
  if (opp.data_age_bm !== undefined && opp.data_age_bm !== null && Number(opp.data_age_bm) > 0) {
    return Number(opp.data_age_bm);
  }
  if (opp.data_age_sell !== undefined && opp.data_age_sell !== null && Number(opp.data_age_sell) > 0) {
    return Number(opp.data_age_sell);
  }
  return Number(opp.data_age_seconds || opp.data_age_buy || opp.data_age_base || 0);
}

// Render Visual Cards Grid View (Clean, No Overlaps!)
function renderCardsView(pageSlice, offset) {
  const container = document.getElementById('cards-view');
  if (!container) return;

  if (pageSlice.length === 0) {
    const activeFilters = getActiveFiltersList();
    const currentTabTotal = state.activeTab === 'all'
      ? Object.values(state.opportunities).flat().length
      : (state.opportunities[state.activeTab] || []).length;

    const catMeta = getCategoryMeta(state.activeTab);
    const catLabel = state.activeTab === 'all' ? 'total' : catMeta.label;

    let emptyTitle = 'No opportunities matched these filters';
    let emptySub = 'Adjust search filters or click "Scan Now".';

    if (currentTabTotal > 0 && activeFilters.length > 0) {
      emptyTitle = `${currentTabTotal} ${catLabel} opportunities exist, but are hidden by active filters`;
      emptySub = `Active Filters: <strong style="color: var(--accent-gold-bright);">${activeFilters.join(' • ')}</strong>`;
    }

    container.innerHTML = `
      <div style="grid-column: 1 / -1; text-align: center; padding: 4rem 1rem; color: var(--text-muted);">
        <div style="font-size: 2.5rem; margin-bottom: 0.5rem;">🔍</div>
        <h3 style="color: #fff; font-size: 1.1rem;">${emptyTitle}</h3>
        <p style="font-size: 0.85rem; margin-top: 0.35rem; color: #a0aec0;">${emptySub}</p>
        ${activeFilters.length > 0 ? `
          <button class="btn-scan-primary" style="margin-top: 1.25rem; padding: 0.45rem 1.25rem; font-size: 0.8rem; background: var(--accent-gold); color: #000; font-weight: 700; border-radius: 6px; cursor: pointer; border: none;" onclick="resetAllFilters()">
            🧹 Clear Active Filters
          </button>
        ` : ''}
      </div>
    `;
    return;
  }

  let html = '';
  for (let i = 0; i < pageSlice.length; i++) {
    const opp = pageSlice[i];
    const globalIdx = offset + i;
    const oppKey = `${opp.item_id}_${globalIdx}`;
    const initialQty = state.volumeOverrides[oppKey] !== undefined ? state.volumeOverrides[oppKey] : (opp.safe_limit || 1);
    const m = calculateScaledMetrics(opp, initialQty);

    const itemId = opp.item_id || opp.target_item_id || opp.base_item_id || 'T4_BAG';
    const tier = itemId.startsWith('T') ? itemId.slice(0, 2) : 'T4';
    const tierNum = itemId.startsWith('T') ? itemId[1] : '4';
    const quality = opp.quality || 1;
    const enchant = itemId.includes('@') ? itemId.split('@')[1] : '0';
    const enchantLabel = enchant !== '0' ? `.${enchant}` : '';

    const srcCity = opp.buy_city || opp.source_city || opp.craft_city || opp.refine_city || opp.base_city || 'Martlock';
    const dstCity = opp.sell_city || opp.destination_city || (opp.craft_city ? opp.craft_city : 'Caerleon');
    const isDangerous = isLethalRoute(opp, srcCity, dstCity);
    const zoneMeta = getRouteZoneMeta(opp, srcCity, dstCity);
    const catMeta = getCategoryMeta(opp.category_key || state.activeTab, opp);

    const bmAge = Number(opp.data_age_bm || opp.data_age_sell || 0);
    const baseAge = Number(opp.data_age_base || opp.data_age_buy || 0);

    const qualityNames = { 1: '', 2: 'Good', 3: 'Out', 4: 'Exc', 5: 'MP' };
    const stars = '★'.repeat(quality);
    const iconUrl = getItemIconUrl(itemId, quality, 128);

    html += `
      <div class="opp-card tier-t${tierNum}" data-key="${oppKey}" data-item-id="${itemId.toUpperCase()}">
        
        <!-- Header: High-Res Albion Icon with Quality Overlay + Name + Tags -->
        <div class="card-top-row">
          <div class="item-icon-wrap tier-border-t${tierNum}">
            <img class="item-icon-img" src="${iconUrl}" alt="${opp.item_name || itemId}" loading="lazy" decoding="async" onerror="handleIconError(this, '${itemId}', ${quality})" />
            ${quality > 1 ? `<div class="item-quality-pill quality-q${quality}" title="Quality: ${qualityNames[quality]}">${qualityNames[quality]}</div>` : ''}
          </div>
          <div class="card-meta-block">
            <div class="card-item-title" title="${opp.item_name || itemId}">${opp.item_name || itemId}</div>
            <div class="card-tags-row">
              <span class="badge-tag badge-tier tier-color-t${tierNum}">${tier}${enchantLabel}</span>
              <span class="badge-tag badge-category" style="color: ${catMeta.color}; background: ${catMeta.bg}; border-color: ${catMeta.color}40;">${catMeta.label}</span>
              <span class="badge-tag ${zoneMeta.badgeClass}">${zoneMeta.label}</span>
              ${bmAge > 0 ? `
                <span class="badge-tag badge-freshness ${bmAge <= 600 ? 'fresh-green' : 'fresh-amber'}" title="Black Market Target Buy Order Age: ${fmtAge(bmAge)}">
                  <span class="pulse-dot"></span>BM: ${fmtAge(bmAge)}
                </span>
              ` : `
                <span class="badge-tag badge-freshness" title="Data Age: ${fmtAge(getEffectiveDataAge(opp))}">
                  <span class="pulse-dot"></span>${fmtAge(getEffectiveDataAge(opp))}
                </span>
              `}
            </div>
          </div>
        </div>

        <!-- Profit Hero: Batch Net Profit + ROI Margin -->
        <div class="card-profit-hero">
          <div class="profit-hero-left">
            <span class="profit-hero-label">Net Profit (${m.qty}x Batch)</span>
            <span class="profit-hero-val font-mono" style="color: ${m.batchProfit >= 0 ? 'var(--accent-emerald)' : 'var(--accent-danger)'};" id="profit-${oppKey}">${fmtProfit(m.batchProfit)}</span>
          </div>
          <div class="profit-hero-right">
            <span class="roi-badge-pill font-mono" id="roi-${oppKey}">+${m.batchRoi}% ROI</span>
            <span class="profit-meta-sub font-mono">${fmtK(m.unitCost)} cost • ${m.batchWeight} kg</span>
          </div>
        </div>

        <!-- Route Visual Lane -->
        <div class="card-route-lane">
          <div class="route-lane-node">
            <span class="node-role-lbl">SOURCE / BUY</span>
            <span class="node-city" style="color: ${CITY_COLORS[srcCity] || '#fff'};">${srcCity}</span>
            <span class="node-price font-mono">${fmtK(m.unitCost)} silver</span>
            ${baseAge > 0 ? `<span class="node-age-sub font-mono">Listed: ${fmtAge(baseAge)}</span>` : ''}
          </div>
          <div class="route-lane-arrow-wrap">
            <span class="route-lane-arrow">➔</span>
            <span class="route-lane-zone-tag">${zoneMeta.type}</span>
          </div>
          <div class="route-lane-node" style="text-align: right;">
            <span class="node-role-lbl">DEST / SELL</span>
            <span class="node-city" style="color: ${CITY_COLORS[dstCity] || '#ffd700'};">${dstCity}</span>
            <span class="node-price font-mono" style="color: var(--accent-gold-bright);">${fmtK(m.unitRevenue)} silver</span>
            ${bmAge > 0 ? `<span class="node-age-sub font-mono" style="color: var(--accent-emerald);">BM Order: ${fmtAge(bmAge)}</span>` : ''}
          </div>
        </div>

        <!-- Volume Stepper & Sizing Controls -->
        <div class="card-volume-bar">
          <span class="volume-cap-lbl font-mono">Safe Depth: <strong>${m.safeLimit}x</strong></span>
          <div class="volume-stepper">
            <button class="vol-step-btn" onclick="stepVolume('${oppKey}', -1)">-</button>
            <input type="number" class="vol-input font-mono" id="vol-${oppKey}" value="${m.qty}" min="1" max="10000" onchange="setVolume('${oppKey}', this.value)" />
            <button class="vol-step-btn" onclick="stepVolume('${oppKey}', 1)">+</button>
            <button class="vol-step-btn ${m.qty === 5 ? 'active' : ''}" onclick="setVolume('${oppKey}', 5)">5x</button>
            <button class="vol-step-btn ${m.qty === 10 ? 'active' : ''}" onclick="setVolume('${oppKey}', 10)">10x</button>
            <button class="vol-step-btn ${m.qty === m.safeLimit ? 'active' : ''}" onclick="setVolume('${oppKey}', ${m.safeLimit})">Max</button>
          </div>
        </div>

        <div id="slip-box-${oppKey}">
          ${m.isOverSafeLimit ? `
            <div class="card-slippage-alert font-mono">
              <span>⚠️</span>
              <span>Exceeds top book! Est. Slippage: <strong>~${m.slippagePct}%</strong></span>
            </div>
          ` : ''}
        </div>

        <!-- Actions Bar -->
        <div class="card-actions-bar">
          <span class="card-ev-score font-mono">Score: <strong style="color: var(--accent-gold-bright);">${Math.round(opp.score !== undefined ? opp.score : (opp.ev_score || 0))}</strong></span>
          <div style="display: flex; gap: 0.4rem;">
            <button class="btn-dismiss-sub" onclick="dismissOpportunity('${opp.item_id}', '${opp.category_key || state.activeTab}', event, ${opp.data_age_bm || opp.data_age_sell || 0}, ${opp.bm_buy_price || opp.sell_price || 0}, ${opp.quality || 1})" title="Mark as filled or dismiss">✓ Filled</button>
            <button class="btn-blueprint-action" onclick="openDetailModal(${globalIdx}, '${opp.category_key || state.activeTab}')">🔍 Blueprint & Math</button>
          </div>
        </div>

      </div>
    `;
  }

  container.innerHTML = html;
}

// Render Dense Quant Data Table View
function renderTableView(pageSlice, offset) {
  const tbody = document.getElementById('dense-table-body');
  if (!tbody) return;

  if (pageSlice.length === 0) {
    tbody.innerHTML = `<tr><td colspan="10" style="text-align: center; padding: 3rem; color: var(--text-muted);">No matching opportunities found.</td></tr>`;
    return;
  }

  let html = '';
  for (let i = 0; i < pageSlice.length; i++) {
    const opp = pageSlice[i];
    const globalIdx = offset + i;
    const oppKey = `${opp.item_id}_${globalIdx}`;
    const initialQty = state.volumeOverrides[oppKey] !== undefined ? state.volumeOverrides[oppKey] : (opp.safe_limit || 1);
    const m = calculateScaledMetrics(opp, initialQty);

    const itemId = opp.item_id || opp.target_item_id || opp.base_item_id || 'T4_BAG';
    const tier = itemId.startsWith('T') ? itemId.slice(0, 2) : 'T4';
    const tierNum = itemId.startsWith('T') ? itemId[1] : '4';
    const quality = opp.quality || 1;
    const enchant = itemId.includes('@') ? itemId.split('@')[1] : '0';
    const enchantLabel = enchant !== '0' ? `.${enchant}` : '';

    const srcCity = opp.buy_city || opp.source_city || opp.craft_city || opp.refine_city || opp.base_city || 'Martlock';
    const dstCity = opp.sell_city || opp.destination_city || 'Caerleon';
    const isDangerous = isLethalRoute(opp, srcCity, dstCity);
    const zoneMeta = getRouteZoneMeta(opp, srcCity, dstCity);
    const catMeta = getCategoryMeta(opp.category_key || state.activeTab, opp);

    html += `
      <tr data-key="${oppKey}" data-item-id="${itemId.toUpperCase()}">
        <td>
          <div style="display: flex; align-items: center; gap: 0.6rem;">
            <div class="item-icon-wrap" style="width: 38px; height: 38px; border-radius: 4px;">
              <img class="item-icon-img" src="${getItemIconUrl(itemId, quality, 64)}" loading="lazy" decoding="async" onerror="handleIconError(this, '${itemId}', ${quality})" />
            </div>
            <div>
              <div style="font-weight: 700; color: #fff; display: flex; align-items: center; gap: 0.35rem;">
                <span class="badge-tag badge-tier" style="font-size: 0.62rem;">${tier}${enchantLabel}</span>
                <span>${opp.item_name || itemId}</span>
              </div>
              <div style="font-size: 0.68rem; color: var(--text-muted); display: flex; align-items: center; gap: 0.35rem; margin-top: 2px;">
                <span>Q${quality} • ${fmtAge(getEffectiveDataAge(opp))}</span>
              </div>
            </div>
          </div>
        </td>
        <td>
          <span class="badge-tag badge-category" style="color: ${catMeta.color}; background: ${catMeta.bg}; border-color: ${catMeta.color}40;">${catMeta.label}</span>
        </td>
        <td>
          <div style="font-weight: 600; font-size: 0.78rem; display: flex; align-items: center; gap: 0.35rem;">
            <span>${srcCity} ➔ ${dstCity}</span>
            <span class="badge-tag ${zoneMeta.badgeClass}" style="font-size: 0.6rem; padding: 1px 4px;">${zoneMeta.label}</span>
          </div>
        </td>
        <td>
          <div style="display: flex; gap: 2px;">
            <button class="vol-step-btn" style="padding: 2px 5px; font-size: 0.75rem;" onclick="stepVolume('${oppKey}', -1)">-</button>
            <input type="number" class="font-mono" style="width: 38px; text-align:center; background: var(--bg-surface-2); border: 1px solid var(--border-subtle); color: #fff; font-size: 0.75rem; border-radius: 3px;" id="tbl-vol-${oppKey}" value="${m.qty}" onchange="setVolume('${oppKey}', this.value)" />
            <button class="vol-step-btn" style="padding: 2px 5px; font-size: 0.75rem;" onclick="stepVolume('${oppKey}', 1)">+</button>
          </div>
        </td>
        <td style="color: ${m.batchProfit >= 0 ? 'var(--accent-emerald)' : 'var(--accent-danger)'}; font-weight: 800; font-family: 'JetBrains Mono', monospace; font-size: 0.88rem;" id="tbl-profit-${oppKey}">
          ${fmtProfit(m.batchProfit)}
        </td>
        <td style="color: var(--accent-gold-bright); font-weight: 600; font-family: 'JetBrains Mono', monospace;" id="tbl-cost-${oppKey}">
          ${fmtK(m.batchCost)}
        </td>
        <td>
          <span class="roi-badge-pill font-mono" id="tbl-roi-${oppKey}">+${m.batchRoi}%</span>
        </td>
        <td style="color: var(--text-secondary); font-family: 'JetBrains Mono', monospace;" id="tbl-weight-${oppKey}">
          ${m.batchWeight} kg
        </td>
        <td>
          <div id="tbl-slip-${oppKey}" style="font-size: 0.7rem; color: ${m.isOverSafeLimit ? 'var(--accent-danger)' : 'var(--accent-emerald)'}; font-weight: 700;">
            ${m.isOverSafeLimit ? `⚠️ ~${m.slippagePct}%` : '🟢 Safe'}
          </div>
        </td>
        <td style="white-space: nowrap;">
          <button class="btn-dismiss-sub" style="padding: 0.25rem 0.5rem; font-size: 0.7rem; margin-right: 0.3rem;" onclick="dismissOpportunity('${opp.item_id}', '${opp.category_key || state.activeTab}', event, ${opp.data_age_bm || opp.data_age_sell || 0}, ${opp.bm_buy_price || opp.sell_price || 0}, ${opp.quality || 1})" title="Mark as filled">✓</button>
          <button class="btn-blueprint-action" style="padding: 0.25rem 0.5rem; font-size: 0.7rem;" onclick="openDetailModal(${globalIdx}, '${opp.category_key || state.activeTab}')">Blueprint</button>
        </td>
      </tr>
    `;
  }

  tbody.innerHTML = html;
}

window.dismissOpportunity = async function(itemId, categoryKey, event, dataAgeBm = 0, bmPrice = 0, quality = 1) {
  if (!itemId) return;
  const idUpper = itemId.trim().toUpperCase();
  const isBm = (categoryKey || '').includes('black_market') || (categoryKey || '').includes('b_') || categoryKey === 'bm';

  // 1. Instantly register in local dismissed set & storage
  state.dismissedIds.add(idUpper);
  saveDismissedIds();

  // 2. Smoothly animate & dismiss the specific card or table row in the DOM
  if (event && event.target) {
    const cardEl = event.target.closest('.opp-card, tr[data-key]');
    if (cardEl) {
      cardEl.classList.add(cardEl.tagName === 'TR' ? 'table-row-dismissing' : 'card-dismissing');
    }
  } else {
    document.querySelectorAll(`.opp-card[data-item-id="${idUpper}"], tr[data-item-id="${idUpper}"]`).forEach(el => {
      el.classList.add(el.tagName === 'TR' ? 'table-row-dismissing' : 'card-dismissing');
    });
  }

  // 3. Optimistic instant removal from all local state arrays in 0ms
  for (const k of Object.keys(state.opportunities)) {
    if (Array.isArray(state.opportunities[k])) {
      state.opportunities[k] = state.opportunities[k].filter(o => {
        const oId = String(o.item_id || o.target_item_id || '').toUpperCase();
        return oId !== idUpper;
      });
    }
  }

  // 4. Update badge counters & KPIs immediately with zero page jump
  updateTabCounts();
  updateKpisInPlace();
  showToast(`✓ Marked ${itemId} as filled${isBm ? ' (suppressed until fresh BM scan arrives)' : ' (15m)'}.`, true);

  // 5. Cleanly update the view after smooth transition completes
  setTimeout(() => {
    renderViews();
  }, 220);

  // 6. Synchronize asynchronously with backend dismiss endpoint
  try {
    fetch('/api/v1/system/opportunities/dismiss', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        item_id: itemId,
        category_key: categoryKey || 'all',
        data_age_bm: dataAgeBm || 0,
        bm_price: bmPrice || 0,
        quality: quality || 1
      })
    }).catch(e => console.warn('[AQS] Dismiss sync notice:', e));
  } catch (e) {
    console.warn('[AQS] Dismiss API call warning:', e);
  }
};

// ═══════════════════════════════════════════════════════════════
// IN-PLACE VOLUME MUTATIONS (ZERO-LAG)
// ═══════════════════════════════════════════════════════════════

window.stepVolume = function(oppKey, delta) {
  const current = state.volumeOverrides[oppKey] !== undefined ? state.volumeOverrides[oppKey] : 1;
  const next = Math.max(1, current + delta);
  state.volumeOverrides[oppKey] = next;
  updateCardMetricsInPlace(oppKey, next);
};

window.setVolume = function(oppKey, val) {
  const next = Math.max(1, parseInt(val) || 1);
  state.volumeOverrides[oppKey] = next;
  updateCardMetricsInPlace(oppKey, next);
};

function updateCardMetricsInPlace(oppKey, qty) {
  const globalIdx = parseInt(oppKey.split('_').pop());
  const allList = getFilteredOpportunities();
  const opp = allList[globalIdx];
  if (!opp) return;

  const m = calculateScaledMetrics(opp, qty);

  // Update Card View elements
  const input = document.getElementById(`vol-${oppKey}`);
  if (input) input.value = qty;

  const profitEl = document.getElementById(`profit-${oppKey}`);
  if (profitEl) {
    profitEl.textContent = fmtProfit(m.batchProfit);
    profitEl.style.color = m.batchProfit >= 0 ? 'var(--accent-emerald)' : 'var(--accent-danger)';
  }

  const costEl = document.getElementById(`cost-${oppKey}`);
  if (costEl) costEl.textContent = fmtK(m.batchCost);

  const roiEl = document.getElementById(`roi-${oppKey}`);
  if (roiEl) {
    roiEl.textContent = `${m.batchRoi}%`;
    roiEl.style.color = m.batchRoi >= 0 ? '#fff' : 'var(--accent-danger)';
  }

  const weightEl = document.getElementById(`weight-${oppKey}`);
  if (weightEl) weightEl.textContent = `${m.batchWeight} kg`;

  const slipBox = document.getElementById(`slip-box-${oppKey}`);
  if (slipBox) {
    slipBox.innerHTML = m.isOverSafeLimit ? `
      <div class="slip-box">
        <span>⚠️</span>
        <span>Exceeds top book! Est. Slippage: <strong>~${m.slippagePct}%</strong></span>
      </div>
    ` : '';
  }

  // Update Table View elements
  const tblInput = document.getElementById(`tbl-vol-${oppKey}`);
  if (tblInput) tblInput.value = qty;

  const tblProfit = document.getElementById(`tbl-profit-${oppKey}`);
  if (tblProfit) {
    tblProfit.textContent = fmtProfit(m.batchProfit);
    tblProfit.style.color = m.batchProfit >= 0 ? 'var(--accent-emerald)' : 'var(--accent-danger)';
  }

  const tblCost = document.getElementById(`tbl-cost-${oppKey}`);
  if (tblCost) tblCost.textContent = fmtK(m.batchCost);

  const tblRoi = document.getElementById(`tbl-roi-${oppKey}`);
  if (tblRoi) tblRoi.textContent = `${m.batchRoi}%`;

  const tblWeight = document.getElementById(`tbl-weight-${oppKey}`);
  if (tblWeight) tblWeight.textContent = `${m.batchWeight} kg`;

  const tblSlip = document.getElementById(`tbl-slip-${oppKey}`);
  if (tblSlip) {
    tblSlip.style.color = m.isOverSafeLimit ? 'var(--accent-danger)' : 'var(--text-secondary)';
    tblSlip.innerHTML = m.isOverSafeLimit ? `⚠️ ~${m.slippagePct}%` : '🟢 Safe';
  }
}

function passesOpportunityFilter(opp) {
  if (!opp) return false;
  try {
    const { search, category, tier, enchantment, quality, sourceCity, destCity, safeOnly, highRoiOnly, highVolOnly, highTierOnly, latestOnly, maxInvestment, minProfit, minRoi, minVolume } = state.filters;
    const sLower = search.trim().toLowerCase();

    const rawProfit = Number(opp.net_profit || opp.profit || opp.estimated_profit || 0);
    const m = calculateScaledMetrics(opp, 1);
    if (rawProfit <= 0 && m.unitProfit <= 0) return false;
    if (minProfit > 0 && m.unitProfit < minProfit) return false;
    if (minRoi > 0 && m.batchRoi < minRoi) return false;
    if (maxInvestment > 0 && m.unitCost > maxInvestment) return false;
    if (minVolume > 0 && Number(opp.daily_volume || 0) < minVolume) return false;
    if (highRoiOnly && m.batchRoi < 10.0) return false;

    const itemId = String(opp.item_id || '').toUpperCase();
    const itemName = String(opp.item_name || '').toLowerCase();

    if (sLower && !itemId.toLowerCase().includes(sLower) && !itemName.includes(sLower)) return false;

    // Category Filter
    if (category && category !== 'all') {
      const oppCat = String(opp.category || opp.item_category || opp.subcategory || '').toLowerCase();
      let match = false;
      if (category === 'weapons') {
        match = oppCat.includes('weapon') || itemId.includes('_2H_') || itemId.includes('_MAIN_') || itemId.includes('_SWORD') || itemId.includes('_AXE') || itemId.includes('_BOW') || itemId.includes('_CROSSBOW') || itemId.includes('_STAFF') || itemId.includes('_HAMMER') || itemId.includes('_MACE') || itemId.includes('_SPEAR') || itemId.includes('_DAGGER') || itemId.includes('_QUARTERSTAFF') || itemId.includes('_KNUCKLES') || itemId.includes('_SHAPESHIFTER');
      } else if (category === 'armors') {
        match = oppCat.includes('armor') || itemId.includes('_ARMOR_') || itemId.includes('_ROBE_') || itemId.includes('_JACKET_');
      } else if (category === 'head') {
        match = oppCat.includes('head') || oppCat.includes('helmet') || itemId.includes('_HEAD_') || itemId.includes('_HELMET_') || itemId.includes('_HOOD_') || itemId.includes('_COWL_');
      } else if (category === 'shoes') {
        match = oppCat.includes('shoes') || oppCat.includes('boots') || itemId.includes('_SHOES_') || itemId.includes('_BOOTS_');
      } else if (category === 'offhands') {
        match = oppCat.includes('offhand') || itemId.includes('_OFF_') || itemId.includes('_SHIELD') || itemId.includes('_BOOK') || itemId.includes('_TORCH') || itemId.includes('_HORN') || itemId.includes('_TOTEM') || itemId.includes('_ORB');
      } else if (category === 'capes') {
        match = oppCat.includes('cape') || itemId.includes('_CAPE');
      } else if (category === 'bags') {
        match = oppCat.includes('bag') || itemId.includes('_BAG');
      } else if (category === 'consumables') {
        match = oppCat.includes('consumable') || oppCat.includes('potion') || oppCat.includes('food') || itemId.includes('_POTION_') || itemId.includes('_MEAL_') || itemId.includes('_FISH_');
      } else if (category === 'mounts') {
        match = oppCat.includes('mount') || itemId.includes('_MOUNT_');
      } else if (category === 'crafting') {
        match = oppCat.includes('crafting') || oppCat.includes('resource') || itemId.includes('_BAR') || itemId.includes('_PLANKS') || itemId.includes('_LEATHER') || itemId.includes('_CLOTH') || itemId.includes('_STONEBLOCK') || itemId.includes('_ORE') || itemId.includes('_WOOD') || itemId.includes('_HIDE') || itemId.includes('_FIBER') || itemId.includes('_ROCK');
      } else if (category === 'artefacts') {
        match = oppCat.includes('artefact') || itemId.includes('_RUNE') || itemId.includes('_SOUL') || itemId.includes('_RELIC') || itemId.includes('_SHARD') || itemId.includes('_ARTEFACT_');
      } else if (category === 'token') {
        match = oppCat.includes('token') || itemId.includes('TOKEN') || itemId.includes('SIGIL') || itemId.includes('CREST');
      }
      if (!match) return false;
    }

    if (tier > 0 && !itemId.startsWith(`T${tier}`)) return false;
    if (highTierOnly && !itemId.startsWith('T7') && !itemId.startsWith('T8')) return false;

    const e = itemId.includes('@') ? itemId.split('@')[1] : '0';
    if (enchantment !== 'all' && e !== enchantment) return false;
    if (quality > 0 && (opp.quality || 1) !== parseInt(quality)) return false;

    const src = String(opp.buy_city || opp.source_city || opp.craft_city || opp.refine_city || '').toLowerCase();
    const dst = String(opp.sell_city || opp.destination_city || '').toLowerCase();
    if (sourceCity && !src.includes(sourceCity.toLowerCase())) return false;
    if (destCity && !dst.includes(destCity.toLowerCase())) return false;

    if (safeOnly && isLethalRoute(opp, src, dst)) return false;

    const vol = Number(opp.daily_volume || 0);
    if (highVolOnly && vol < 50) return false;

    if (latestOnly) {
      const ageSec = Number(getEffectiveDataAge(opp));
      if (ageSec > 900) return false;
    }

    return true;
  } catch (err) {
    console.error("Filter evaluation error:", err);
    return false;
  }
}

function getFilteredOpportunities() {
  let pool = [];
  const hasSubSectors = Boolean(state.opportunities.potions || state.opportunities.cooking || state.opportunities.farming);

  if (state.activeTab === 'all') {
    for (const [catKey, list] of Object.entries(state.opportunities)) {
      if (hasSubSectors && catKey === 'island') continue;
      for (let i = 0; i < (list || []).length; i++) {
        pool.push({ ...list[i], category_key: list[i].category_key || catKey });
      }
    }
  } else {
    const list = state.opportunities[state.activeTab] || [];
    for (let i = 0; i < list.length; i++) {
      pool.push({ ...list[i], category_key: state.activeTab });
    }
  }

  const filtered = pool.filter(opp => passesOpportunityFilter(opp));

  // Sorting
  const sortBy = (state.filters && state.filters.sortBy) ? state.filters.sortBy : 'score';
  filtered.sort((a, b) => {
    if (sortBy === 'profit') {
      const pA = Number(a.net_profit || a.profit || a.estimated_profit || 0);
      const pB = Number(b.net_profit || b.profit || b.estimated_profit || 0);
      return pB - pA;
    }
    if (sortBy === 'roi') {
      const rA = Number(a.roi || a.profit_pct || a.estimated_margin || 0);
      const rB = Number(b.roi || b.profit_pct || b.estimated_margin || 0);
      return rB - rA;
    }
    if (sortBy === 'cost_asc') {
      const cA = Number(a.total_cost || a.effective_cost || a.craft_cost || a.buy_price || 0);
      const cB = Number(b.total_cost || b.effective_cost || b.craft_cost || b.buy_price || 0);
      return cA - cB;
    }
    if (sortBy === 'cost_desc') {
      const cA = Number(a.total_cost || a.effective_cost || a.craft_cost || a.buy_price || 0);
      const cB = Number(b.total_cost || b.effective_cost || b.craft_cost || b.buy_price || 0);
      return cB - cA;
    }
    if (sortBy === 'volume') {
      return (Number(b.daily_volume) || 0) - (Number(a.daily_volume) || 0);
    }
    if (sortBy === 'weight_eff') {
      return (Number(b.profit_per_kg) || 0) - (Number(a.profit_per_kg) || 0);
    }
    const sA = Number(a.score !== undefined ? a.score : (a.ev_score || 0));
    const sB = Number(b.score !== undefined ? b.score : (b.ev_score || 0));
    return sB - sA;
  });

  return filtered;
}

// ═══════════════════════════════════════════════════════════════
// MODAL RECIPE INSPECTOR
// ═══════════════════════════════════════════════════════════════

window.openDetailModal = function(globalIdx, catKey) {
  const list = getFilteredOpportunities();
  const opp = list[globalIdx];
  if (!opp) return;

  const oppKey = `${opp.item_id}_${globalIdx}`;
  const qty = state.volumeOverrides[oppKey] || (opp.safe_limit || 1);
  const m = calculateScaledMetrics(opp, qty);

  const modal = document.getElementById('detail-modal');
  const modalBody = document.getElementById('modal-body');

  const itemId = opp.item_id || opp.target_item_id || 'T4_BAG';
  const tier = itemId.startsWith('T') ? itemId.slice(0, 2) : 'T4';
  const quality = opp.quality || 1;
  const stars = '★'.repeat(quality);
  const cat = opp.category_key || catKey || state.activeTab;
  const catMeta = getCategoryMeta(cat, opp);
  const srcCity = opp.buy_city || opp.source_city || opp.craft_city || opp.refine_city || opp.base_city || 'Local';
  const dstCity = opp.sell_city || opp.destination_city || 'Marketplace';
  const isDangerous = isLethalRoute(opp, srcCity, dstCity);

  // ─── Dynamic Recipe / Blueprint Breakdown for All Categories ───
  let blueprintHtml = '';

  // 1. Enchanting (BM & Royal Enchanting)
  if (cat.includes('enchant') || opp.material_id || opp.base_item_id) {
    const baseId = opp.base_item_id || itemId.split('@')[0];
    const basePrice = Number(opp.base_price || 0);
    const matId = opp.material_id || (itemId.startsWith('T') ? `T${itemId[1]}_SOUL` : 'T4_SOUL');
    const matQty = Number(opp.material_qty || 96);
    const matPrice = Number(opp.material_price || 0);
    const totalMatCost = matPrice * matQty * qty;
    const totalBaseCost = basePrice * qty;

    blueprintHtml = `
      <h4 style="margin-top: 1.25rem; font-size: 0.9rem; color: var(--accent-gold-bright); font-family: 'Outfit', sans-serif;">🔮 Artifact Foundry Enchanting Recipe (${qty}x Batch):</h4>
      <div style="margin-top: 0.6rem; display: flex; flex-direction: column; gap: 0.4rem;">
        <!-- Base Item -->
        <div style="display: flex; align-items: center; justify-content: space-between; background: var(--bg-surface-1); padding: 0.6rem 0.8rem; border-radius: 6px; border: 1px solid var(--border-subtle);">
          <div style="display: flex; align-items: center; gap: 0.6rem;">
            <img src="${getItemIconUrl(baseId, opp.base_quality || quality, 64)}" style="width: 32px; height: 32px; border-radius: 4px;" loading="lazy" decoding="async" onerror="handleIconError(this, '${baseId}', ${opp.base_quality || quality})" />
            <div>
              <div style="font-weight: 700; font-size: 0.84rem; color: #fff;">${baseId} (Base Item)</div>
              <div style="font-size: 0.7rem; color: var(--text-muted);">Sourced at: <strong>${srcCity}</strong> @ ${fmtK(basePrice)} silver</div>
            </div>
          </div>
          <div style="text-align: right;">
            <div style="font-weight: 800; color: var(--accent-gold-bright); font-family: 'JetBrains Mono', monospace; font-size: 0.85rem;">${qty.toLocaleString()}x</div>
            <div style="font-size: 0.7rem; color: var(--text-secondary);">${fmtK(totalBaseCost)} silver</div>
          </div>
        </div>
        <!-- Enchanting Materials -->
        <div style="display: flex; align-items: center; justify-content: space-between; background: var(--bg-surface-1); padding: 0.6rem 0.8rem; border-radius: 6px; border: 1px solid var(--border-subtle);">
          <div style="display: flex; align-items: center; gap: 0.6rem;">
            <img src="${getItemIconUrl(matId, 1, 64)}" style="width: 32px; height: 32px; border-radius: 4px;" loading="lazy" decoding="async" onerror="handleIconError(this, '${matId}', 1)" />
            <div>
              <div style="font-weight: 700; font-size: 0.84rem; color: #fff;">${matId} (Enchanting Material)</div>
              <div style="font-size: 0.7rem; color: var(--text-muted);">Sourced at: <strong>${srcCity}</strong> @ ${fmtK(matPrice)} silver/ea (${matQty} per item)</div>
            </div>
          </div>
          <div style="text-align: right;">
            <div style="font-weight: 800; color: var(--accent-gold-bright); font-family: 'JetBrains Mono', monospace; font-size: 0.85rem;">${(matQty * qty).toLocaleString()}x</div>
            <div style="font-size: 0.7rem; color: var(--text-secondary);">${fmtK(totalMatCost)} silver</div>
          </div>
        </div>
      </div>
      <div style="margin-top: 0.5rem; font-size: 0.72rem; color: var(--accent-cyan); background: rgba(56, 189, 248, 0.08); padding: 0.45rem 0.75rem; border-radius: 5px; border: 1px solid rgba(56, 189, 248, 0.2);">
        ⚡ <strong>Execution:</strong> Buy base item and materials in <strong>${srcCity}</strong> ➔ Walk to local Artifact Foundry (0% loss risk, instant enchant) ➔ List or Sell at <strong>${dstCity}</strong> for <strong>${fmtK(m.unitRevenue)}</strong> silver.
      </div>
    `;
  }
  // 2. Crafting, Refining & Island Farming
  else if (opp.ingredients && opp.ingredients.length > 0) {
    blueprintHtml = `
      <h4 style="margin-top: 1.25rem; font-size: 0.9rem; color: var(--accent-gold-bright); font-family: 'Outfit', sans-serif;">⚒️ Required Ingredients & Resources (${qty}x Batch):</h4>
      <div style="margin-top: 0.6rem; display: flex; flex-direction: column; gap: 0.4rem;">
        ${opp.ingredients.map(ing => `
          <div style="display: flex; align-items: center; justify-content: space-between; background: var(--bg-surface-1); padding: 0.55rem 0.75rem; border-radius: 6px; border: 1px solid var(--border-subtle);">
            <div style="display: flex; align-items: center; gap: 0.55rem;">
              <img src="${getItemIconUrl(ing.item_id, 1, 64)}" style="width: 28px; height: 28px; border-radius: 4px;" loading="lazy" decoding="async" onerror="handleIconError(this, '${ing.item_id}', 1)" />
              <div>
                <div style="font-weight: 700; font-size: 0.82rem; color: #fff;">${ing.name || ing.item_id}</div>
                <div style="font-size: 0.68rem; color: var(--text-muted);">Buy at: <strong>${ing.buy_city || srcCity}</strong> @ ${fmtK(ing.unit_price)} s</div>
              </div>
            </div>
            <div style="text-align: right;">
              <div style="font-weight: 800; color: var(--accent-gold-bright); font-family: 'JetBrains Mono', monospace; font-size: 0.85rem;">${(ing.quantity * qty).toLocaleString()}x</div>
              <div style="font-size: 0.68rem; color: var(--text-secondary);">${fmtK(ing.unit_price * ing.quantity * qty)} silver</div>
            </div>
          </div>
        `).join('')}
      </div>
    `;
  }
  // 3. Transmutation
  else if (cat.includes('transmute') || opp.source_item_id) {
    const srcId = opp.source_item_id || 'T4_WOOD';
    const srcPrice = Number(opp.source_price || 0);
    const fee = Number(opp.transmutation_fee || 0);

    blueprintHtml = `
      <h4 style="margin-top: 1.25rem; font-size: 0.9rem; color: var(--accent-gold-bright); font-family: 'Outfit', sans-serif;">⚗️ Transmutation Breakdown (${qty}x Batch):</h4>
      <div style="margin-top: 0.6rem; display: flex; flex-direction: column; gap: 0.4rem;">
        <div style="display: flex; align-items: center; justify-content: space-between; background: var(--bg-surface-1); padding: 0.6rem 0.8rem; border-radius: 6px; border: 1px solid var(--border-subtle);">
          <div style="display: flex; align-items: center; gap: 0.6rem;">
            <img src="${getItemIconUrl(srcId, 1, 64)}" style="width: 32px; height: 32px; border-radius: 4px;" loading="lazy" decoding="async" onerror="handleIconError(this, '${srcId}', 1)" />
            <div>
              <div style="font-weight: 700; font-size: 0.84rem; color: #fff;">${opp.source_item_name || srcId} (Source Resource)</div>
              <div style="font-size: 0.7rem; color: var(--text-muted);">Sourced at: <strong>${srcCity}</strong> @ ${fmtK(srcPrice)} silver</div>
            </div>
          </div>
          <div style="text-align: right;">
            <div style="font-weight: 800; color: var(--accent-gold-bright); font-family: 'JetBrains Mono', monospace; font-size: 0.85rem;">${qty.toLocaleString()}x</div>
            <div style="font-size: 0.7rem; color: var(--text-secondary);">${fmtK(srcPrice * qty)} silver</div>
          </div>
        </div>
        <div style="display: flex; align-items: center; justify-content: space-between; background: var(--bg-surface-1); padding: 0.6rem 0.8rem; border-radius: 6px; border: 1px solid var(--border-subtle);">
          <div>
            <div style="font-weight: 700; font-size: 0.84rem; color: #fff;">🏛️ Transmutator Station Silver Fee</div>
            <div style="font-size: 0.7rem; color: var(--text-muted);">Direct game station fee @ ${fmtK(fee)} silver/unit</div>
          </div>
          <div style="text-align: right;">
            <div style="font-weight: 800; color: #f85149; font-family: 'JetBrains Mono', monospace; font-size: 0.85rem;">${fmtK(fee * qty)} silver</div>
          </div>
        </div>
      </div>
    `;
  }
  // 4. Quality Inversion
  else if (cat.includes('quality') || opp.buy_quality_name) {
    blueprintHtml = `
      <h4 style="margin-top: 1.25rem; font-size: 0.9rem; color: var(--accent-gold-bright); font-family: 'Outfit', sans-serif;">⭐ Quality Mispricing Arbitrage Blueprint (${qty}x Batch):</h4>
      <div style="margin-top: 0.6rem; display: flex; flex-direction: column; gap: 0.4rem;">
        <div style="display: flex; align-items: center; justify-content: space-between; background: var(--bg-surface-1); padding: 0.6rem 0.8rem; border-radius: 6px; border: 1px solid var(--border-subtle);">
          <div>
            <div style="font-weight: 700; font-size: 0.84rem; color: #fff;">1. Buy Higher Quality: ${opp.buy_quality_name || ('Q' + (opp.buy_quality || 2))}</div>
            <div style="font-size: 0.7rem; color: var(--text-muted);">Listed in <strong>${opp.city || srcCity}</strong> marketplace @ ${fmtK(opp.buy_price)} s</div>
          </div>
          <div style="text-align: right;">
            <div style="font-weight: 800; color: var(--accent-gold-bright); font-family: 'JetBrains Mono', monospace; font-size: 0.85rem;">${fmtK(m.batchCost)} s</div>
          </div>
        </div>
        <div style="display: flex; align-items: center; justify-content: space-between; background: var(--bg-surface-1); padding: 0.6rem 0.8rem; border-radius: 6px; border: 1px solid var(--border-subtle);">
          <div>
            <div style="font-weight: 700; font-size: 0.84rem; color: #fff;">2. Benchmark Lower Quality: ${opp.reference_quality_name || ('Q' + (opp.reference_quality || 1))}</div>
            <div style="font-size: 0.7rem; color: var(--text-muted);">Inferior quality listed higher @ ${fmtK(opp.reference_price)} s</div>
          </div>
          <div style="text-align: right;">
            <div style="font-weight: 800; color: #58a6ff; font-family: 'JetBrains Mono', monospace; font-size: 0.85rem;">${fmtK(m.batchRevenue)} s</div>
          </div>
        </div>
      </div>
    `;
  }
  // 5. Arbitrage & Black Market Transport Flips
  else {
    blueprintHtml = `
      <h4 style="margin-top: 1.25rem; font-size: 0.9rem; color: var(--accent-gold-bright); font-family: 'Outfit', sans-serif;">🚛 Transport & Execution Route Blueprint (${qty}x Batch):</h4>
      <div style="margin-top: 0.6rem; display: flex; flex-direction: column; gap: 0.4rem;">
        <div style="display: flex; align-items: center; justify-content: space-between; background: var(--bg-surface-1); padding: 0.6rem 0.8rem; border-radius: 6px; border: 1px solid var(--border-subtle);">
          <div>
            <div style="font-weight: 700; font-size: 0.84rem; color: #fff;">1. Purchase in ${srcCity}</div>
            <div style="font-size: 0.7rem; color: var(--text-muted);">Buy ${qty}x @ ${fmtK(m.unitCost)} s / unit</div>
          </div>
          <div style="text-align: right;">
            <div style="font-weight: 800; color: var(--accent-gold-bright); font-family: 'JetBrains Mono', monospace; font-size: 0.85rem;">${fmtK(m.batchCost)} silver</div>
          </div>
        </div>
        <div style="display: flex; align-items: center; justify-content: space-between; background: var(--bg-surface-1); padding: 0.6rem 0.8rem; border-radius: 6px; border: 1px solid var(--border-subtle);">
          <div>
            <div style="font-weight: 700; font-size: 0.84rem; color: #fff;">2. Transport to ${dstCity}</div>
            <div style="font-size: 0.7rem; color: var(--text-muted);">Total Cargo Weight: <strong>${m.batchWeight} kg</strong> ${isDangerous ? '• <span style="color: var(--accent-danger); font-weight:700;">⚠️ Red/Black Zone Risk</span>' : '• <span style="color: var(--accent-emerald); font-weight:700;">🛡️ Safe Blue/Yellow Continental Lane</span>'}</div>
          </div>
          <div style="text-align: right;">
            <div style="font-size: 0.75rem; color: var(--text-secondary); font-family: 'JetBrains Mono', monospace;">Safe Cap: ${m.safeLimit}x</div>
          </div>
        </div>
        <div style="display: flex; align-items: center; justify-content: space-between; background: var(--bg-surface-1); padding: 0.6rem 0.8rem; border-radius: 6px; border: 1px solid var(--border-subtle);">
          <div>
            <div style="font-weight: 700; font-size: 0.84rem; color: #fff;">3. Liquidate in ${dstCity}</div>
            <div style="font-size: 0.7rem; color: var(--text-muted);">Sell ${qty}x @ ${fmtK(m.unitRevenue)} s / unit</div>
          </div>
          <div style="text-align: right;">
            <div style="font-weight: 800; color: #58a6ff; font-family: 'JetBrains Mono', monospace; font-size: 0.85rem;">${fmtK(m.batchRevenue)} silver</div>
          </div>
        </div>
      </div>
    `;
  }

  modalBody.innerHTML = `
    <!-- Top Header -->
    <div style="display: flex; align-items: center; gap: 0.85rem; margin-bottom: 1.1rem;">
      <div class="icon-frame-clean" style="width: 58px; height: 58px;">
        <img class="icon-img-clean" src="${getItemIconUrl(itemId, quality, 128)}" loading="lazy" decoding="async" onerror="handleIconError(this, '${itemId}', ${quality})" />
      </div>
      <div>
        <div style="display: flex; align-items: center; gap: 0.45rem; flex-wrap: wrap;">
          <h2 style="font-size: 1.18rem; font-weight: 800; color: #fff; font-family: 'Outfit', sans-serif; margin: 0;">${opp.item_name || itemId}</h2>
          <span class="cat-badge-card" style="color: ${catMeta.color}; background: ${catMeta.bg}; border: 1px solid ${catMeta.color}40; padding: 0.1rem 0.45rem; border-radius: 4px; font-weight: 700; font-size: 0.7rem;">${catMeta.label}</span>
        </div>
        <div style="font-size: 0.74rem; color: var(--text-muted); margin-top: 3px; display: flex; align-items: center; gap: 0.4rem;">
          <span class="font-mono">${itemId}</span>
          <span>•</span>
          <span class="stars-gold">${stars}</span>
          <span>•</span>
          <span>${srcCity} ➔ ${dstCity}</span>
          ${isDangerous ? '<span style="color: var(--accent-danger); font-weight:700;">• ⚠️ LETHAL</span>' : '<span style="color: var(--accent-emerald); font-weight:700;">• 🛡️ SAFE</span>'}
        </div>
      </div>
    </div>

    <!-- Core Financial Overview Grid -->
    <div style="background: var(--bg-surface-1); padding: 0.95rem; border-radius: 8px; border: 1px solid var(--border-subtle); display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.75rem;">
      <div>
        <div style="font-size: 0.66rem; color: var(--text-muted); text-transform: uppercase; font-weight: 700;">Unit Cost (Buy/Craft)</div>
        <div style="font-size: 1.05rem; font-weight: 800; color: var(--text-secondary); font-family: 'JetBrains Mono', monospace;">${fmtK(m.unitCost)} silver</div>
      </div>
      <div>
        <div style="font-size: 0.66rem; color: #79c0ff; text-transform: uppercase; font-weight: 700;">Sell Target (Unit)</div>
        <div style="font-size: 1.05rem; font-weight: 800; color: #79c0ff; font-family: 'JetBrains Mono', monospace;">${fmtK(m.unitRevenue)} silver</div>
      </div>
      <div>
        <div style="font-size: 0.66rem; color: var(--accent-emerald); text-transform: uppercase; font-weight: 700;">Net Unit Profit</div>
        <div style="font-size: 1.05rem; font-weight: 800; color: ${m.unitProfit >= 0 ? 'var(--accent-emerald)' : 'var(--accent-danger)'}; font-family: 'JetBrains Mono', monospace;">${fmtProfit(m.unitProfit)} silver</div>
      </div>

      <div style="border-top: 1px solid var(--border-subtle); padding-top: 0.5rem;">
        <div style="font-size: 0.66rem; color: var(--text-muted); text-transform: uppercase; font-weight: 700;">Batch Cost (${qty}x)</div>
        <div style="font-size: 0.95rem; font-weight: 700; color: #fff; font-family: 'JetBrains Mono', monospace;">${fmtK(m.batchCost)} silver</div>
      </div>
      <div style="border-top: 1px solid var(--border-subtle); padding-top: 0.5rem;">
        <div style="font-size: 0.66rem; color: var(--text-muted); text-transform: uppercase; font-weight: 700;">Batch Net Profit</div>
        <div style="font-size: 0.95rem; font-weight: 800; color: ${m.batchProfit >= 0 ? 'var(--accent-emerald)' : 'var(--accent-danger)'}; font-family: 'JetBrains Mono', monospace;">${fmtProfit(m.batchProfit)} silver</div>
      </div>
      <div style="border-top: 1px solid var(--border-subtle); padding-top: 0.5rem;">
        <div style="font-size: 0.66rem; color: var(--text-muted); text-transform: uppercase; font-weight: 700;">ROI Margin</div>
        <div style="font-size: 0.95rem; font-weight: 800; color: #fff; font-family: 'JetBrains Mono', monospace;">${m.batchRoi}%</div>
      </div>
    </div>

    ${blueprintHtml}

    <div style="margin-top: 1.25rem; display: flex; justify-content: flex-end; gap: 0.55rem;">
      <a href="https://albiononline2d.com/en/item/id/${itemId}" target="_blank" class="tag-btn" style="text-decoration: none; padding: 0.4rem 0.8rem; font-size: 0.78rem;">🌐 View on Albion2D</a>
      <button class="btn-scan-primary" style="padding: 0.4rem 1rem; font-size: 0.78rem;" onclick="closeDetailModal()">Close</button>
    </div>
  `;

  modal.classList.add('open');
};

window.closeDetailModal = function() {
  const modal = document.getElementById('detail-modal');
  if (modal) modal.classList.remove('open');
};

// ═══════════════════════════════════════════════════════════════
// INITIALIZATION & EVENT LISTENERS
// ═══════════════════════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', () => {
  // Sidebar Category Tabs
  document.querySelectorAll('.sidebar-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.sidebar-tab').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.activeTab = btn.dataset.tab;
      state.currentPage = 1;
      renderViews();
    });
  });

  // Fast Category Switcher Pills
  document.querySelectorAll('.cat-pill-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.cat-pill-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const cat = btn.dataset.cat || 'all';
      state.filters.category = cat;
      const catSelect = document.getElementById('category-filter');
      if (catSelect) catSelect.value = cat;
      state.currentPage = 1;
      renderViews();
    });
  });

  // View Mode Buttons (Cards vs Table)
  const viewCardsBtn = document.getElementById('view-cards-btn');
  const viewTableBtn = document.getElementById('view-table-btn');
  if (viewCardsBtn && viewTableBtn) {
    viewCardsBtn.addEventListener('click', () => {
      state.viewMode = 'cards';
      viewCardsBtn.classList.add('active');
      viewTableBtn.classList.remove('active');
      renderViews();
    });
    viewTableBtn.addEventListener('click', () => {
      state.viewMode = 'table';
      viewTableBtn.classList.add('active');
      viewCardsBtn.classList.remove('active');
      renderViews();
    });
  }

  // Quick Filter Tags
  const setupTag = (id, filterKey) => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener('click', () => {
        state.filters[filterKey] = !state.filters[filterKey];
        el.classList.toggle('active', state.filters[filterKey]);
        state.currentPage = 1;
        renderViews();
      });
    }
  };

  setupTag('tag-latest-only', 'latestOnly');
  setupTag('tag-safe-only', 'safeOnly');
  setupTag('tag-high-roi', 'highRoiOnly');
  setupTag('tag-high-vol', 'highVolOnly');
  setupTag('tag-high-tier', 'highTierOnly');

  // Search (Debounced + Global Shortcut)
  const searchInput = document.getElementById('search-input');
  if (searchInput) {
    const debouncedSearch = debounce((val) => {
      state.filters.search = val;
      state.currentPage = 1;
      renderViews();
    }, 150);

    searchInput.addEventListener('input', (e) => {
      debouncedSearch(e.target.value);
    });

    window.addEventListener('keydown', (e) => {
      if (e.key === '/' && document.activeElement !== searchInput && !['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement.tagName)) {
        e.preventDefault();
        searchInput.focus();
        searchInput.select();
      } else if (e.key === 'Escape' && document.activeElement === searchInput) {
        searchInput.blur();
      }
    });
  }

  const catFilter = document.getElementById('category-filter');
  if (catFilter) {
    catFilter.addEventListener('change', (e) => {
      state.filters.category = e.target.value;
      document.querySelectorAll('.cat-pill-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.cat === e.target.value);
      });
      state.currentPage = 1;
      renderViews();
    });
  }

  const tierFilter = document.getElementById('tier-filter');
  if (tierFilter) {
    tierFilter.addEventListener('change', (e) => {
      state.filters.tier = parseInt(e.target.value) || 0;
      state.currentPage = 1;
      renderViews();
    });
  }

  const enchFilter = document.getElementById('enchant-filter');
  if (enchFilter) {
    enchFilter.addEventListener('change', (e) => {
      state.filters.enchantment = e.target.value;
      state.currentPage = 1;
      renderViews();
    });
  }

  const srcCityFilter = document.getElementById('source-city-filter');
  if (srcCityFilter) {
    srcCityFilter.addEventListener('change', (e) => {
      state.filters.sourceCity = e.target.value;
      state.currentPage = 1;
      renderViews();
    });
  }

  const dstCityFilter = document.getElementById('dest-city-filter');
  if (dstCityFilter) {
    dstCityFilter.addEventListener('change', (e) => {
      state.filters.destCity = e.target.value;
      state.currentPage = 1;
      renderViews();
    });
  }

  const maxCostFilter = document.getElementById('max-cost-filter');
  if (maxCostFilter) {
    maxCostFilter.addEventListener('change', (e) => {
      state.filters.maxInvestment = parseInt(e.target.value) || 0;
      state.currentPage = 1;
      renderViews();
    });
  }

  const minProfitFilter = document.getElementById('min-profit-filter');
  if (minProfitFilter) {
    minProfitFilter.addEventListener('change', (e) => {
      state.filters.minProfit = parseInt(e.target.value) || 0;
      state.currentPage = 1;
      renderViews();
    });
  }

  const minRoiFilter = document.getElementById('min-roi-filter');
  if (minRoiFilter) {
    minRoiFilter.addEventListener('change', (e) => {
      state.filters.minRoi = parseFloat(e.target.value) || 0;
      state.currentPage = 1;
      renderViews();
    });
  }

  const minVolFilter = document.getElementById('min-vol-filter');
  if (minVolFilter) {
    minVolFilter.addEventListener('change', (e) => {
      state.filters.minVolume = parseInt(e.target.value) || 0;
      state.currentPage = 1;
      renderViews();
    });
  }

  const sortSelect = document.getElementById('sort-by-select');
  if (sortSelect) {
    sortSelect.addEventListener('change', (e) => {
      state.filters.sortBy = e.target.value;
      state.currentPage = 1;
      renderViews();
    });
  }

  // Premium Status Toggle Switch
  const premToggle = document.getElementById('premium-status-toggle');
  if (premToggle) {
    premToggle.addEventListener('change', (e) => {
      togglePremiumStatus(e.target.checked);
    });
  }

  // Discord Alerts Toggle Switch
  const discordToggle = document.getElementById('discord-alerts-toggle');
  if (discordToggle) {
    discordToggle.addEventListener('change', (e) => {
      toggleDiscordAlerts(e.target.checked);
    });
  }

  // Continuous Auto-Scan Toggle Switch
  const contToggle = document.getElementById('continuous-scan-toggle');
  if (contToggle) {
    contToggle.addEventListener('change', (e) => {
      toggleContinuousScan(e.target.checked);
    });
  }

  // Stop Tool Button
  const stopBtn = document.getElementById('stop-tool-btn');
  if (stopBtn) {
    stopBtn.addEventListener('click', stopTool);
  }

  // Shutdown / Exit App Button
  const shutdownBtn = document.getElementById('shutdown-app-btn');
  if (shutdownBtn) {
    shutdownBtn.addEventListener('click', shutdownApp);
  }


  // Server Switcher
  const serverSelect = document.getElementById('server-select');
  if (serverSelect) {
    serverSelect.addEventListener('change', (e) => {
      switchServer(e.target.value);
    });
  }

  // Clear Data Button
  const clearBtn = document.getElementById('clear-data-btn');
  if (clearBtn) {
    clearBtn.addEventListener('click', clearData);
  }

  // Scan Now Button
  const scanBtn = document.getElementById('scan-now-btn');
  if (scanBtn) {
    scanBtn.addEventListener('click', triggerScan);
  }


  // Close modal on backdrop click
  const modal = document.getElementById('detail-modal');
  if (modal) {
    modal.addEventListener('click', (e) => {
      if (e.target === modal) closeDetailModal();
    });
  }

  // Global Keyboard Shortcuts
  window.addEventListener('keydown', (e) => {
    // Escape key closes inspection modal
    if (e.key === 'Escape') {
      closeDetailModal();
      return;
    }

    // '/' key focuses global search input
    if (e.key === '/' && document.activeElement !== searchInput) {
      e.preventDefault();
      if (searchInput) {
        searchInput.focus();
        searchInput.select();
      }
      return;
    }

    // Ctrl+C (or Cmd+C) keyboard shortcut for graceful exit
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'c') {
      const activeEl = document.activeElement;
      const isInput = activeEl && (activeEl.tagName === 'INPUT' || activeEl.tagName === 'TEXTAREA' || activeEl.isContentEditable);
      const hasSelection = window.getSelection() && window.getSelection().toString().length > 0;
      
      // If typing in input or copying selected text, allow normal clipboard copy
      if (isInput || hasSelection) {
        return;
      }

      e.preventDefault();
      shutdownApp(false);
    }
  });

  // Initial Load
  fetchSettings();
  fetchStats();
  fetchOpportunities();

  // Periodic Refresh (every 45s, silent non-destructive poll)
  setInterval(() => {
    fetchStats();
    fetchOpportunities(true);
  }, 45000);
});
