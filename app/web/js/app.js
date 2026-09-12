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
    islandCity: '',
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
  filteredList: [],
  filterDirty: true,
};

function markFilterDirty() {
  state.filterDirty = true;
}

function saveDismissedIds() {
  try {
    sessionStorage.setItem('aqs_dismissed_ids', JSON.stringify(Array.from(state.dismissedIds)));
  } catch (e) {}
}

// Pre-indexing helper to enrich opportunity objects once on ingestion
function enrichOpportunity(o, catKey) {
  o.category_key = o.category_key || catKey;
  const itemId = String(o.item_id || o.target_item_id || o.base_item_id || 'T4_BAG').trim();
  o._itemId = itemId;
  o._itemIdUpper = itemId.toUpperCase();
  o._itemNameLower = String(o.item_name || '').toLowerCase();
  o._searchStr = `${o._itemIdUpper.toLowerCase()} ${o._itemNameLower}`;
  
  let tierNum = 4;
  if (o._itemIdUpper.startsWith('T')) {
    const t = parseInt(o._itemIdUpper[1]);
    if (!isNaN(t)) tierNum = t;
  }
  o._tierNum = tierNum;
  o._enchant = o._itemIdUpper.includes('@') ? o._itemIdUpper.split('@')[1] : '0';
  
  const isBm = String(catKey).includes('bm') || (o.destination_city && o.destination_city.toLowerCase() === 'black market');
  const srcCity = o.buy_city || o.source_city || o.craft_city || o.refine_city || o.base_city || 'Martlock';
  const dstCity = o.sell_city || o.destination_city || (isBm ? 'Black Market' : srcCity);
  o._srcCity = srcCity;
  o._dstCity = dstCity;
  o._srcCityLower = srcCity.toLowerCase();
  o._dstCityLower = dstCity.toLowerCase();
  o._isLethal = isLethalRoute(o, srcCity, dstCity);
  
  const islandCity = String(o.island_city || o.craft_city || o.buy_city || '')
    .replace('Personal Island (', '')
    .replace(')', '')
    .replace(' Island', '')
    .trim();
  o._islandCity = islandCity;
  
  o._catStr = String(o.category || o.item_category || o.subcategory || catKey || '').toLowerCase();

  const unitProfit = Number(o.net_profit || o.profit || o.estimated_profit || 0);
  const unitCost = Number(
    o.mode === "CRAFT+RUN"
      ? (o.craft_cost || o.effective_cost || o.total_cost || o.buy_price)
      : (o.total_cost || o.effective_cost || o.craft_cost || o.buy_price || o.material_cost_gross || 1)
  );
  // For consumables (potions/meals), sell_price is per-item but profit is per-batch.
  // Scale unitRevenue to match the batch context so Revenue - Cost = Profit makes sense.
  const outputQty = Number(o.output_qty || 1);
  const rawUnitRevenue = Number(o.sell_price || o.bm_buy_price || o.revenue_net || 0);
  const unitRevenue = outputQty > 1 ? rawUnitRevenue * outputQty : rawUnitRevenue;
  const dailyVol = Number(o.daily_volume || 10);
  const safeLimit = Number(o.safe_limit || 1);
  const unitWeight = Number(o.profit_per_kg ? (unitProfit / o.profit_per_kg) : 1.5);
  const batchRoi = unitCost > 0 ? Number(((unitProfit / unitCost) * 100).toFixed(2)) : 0;

  o._unitProfit = unitProfit;
  o._unitCost = unitCost;
  o._unitRevenue = unitRevenue;
  o._rawSellPrice = rawUnitRevenue;  // Keep the per-item price for display
  o._dailyVol = dailyVol;
  o._safeLimit = safeLimit;
  o._unitWeight = unitWeight;
  o._baseRoi = batchRoi;
  o._score = Number(o.score !== undefined ? o.score : (o.ev_score || 0));
  return o;
}

function matchesItemCategory(opp, category) {
  const c = opp._catStr || '';
  const id = opp._itemIdUpper || '';
  switch (category) {
    case 'weapons':
      return c.includes('weapon') || id.includes('_2H_') || id.includes('_MAIN_') || id.includes('_SWORD') || id.includes('_AXE') || id.includes('_BOW') || id.includes('_CROSSBOW') || id.includes('_STAFF') || id.includes('_HAMMER') || id.includes('_MACE') || id.includes('_SPEAR') || id.includes('_DAGGER') || id.includes('_QUARTERSTAFF') || id.includes('_KNUCKLES') || id.includes('_SHAPESHIFTER');
    case 'armors':
      return c.includes('armor') || id.includes('_ARMOR_') || id.includes('_ROBE_') || id.includes('_JACKET_');
    case 'head':
      return c.includes('head') || c.includes('helmet') || id.includes('_HEAD_') || id.includes('_HELMET_') || id.includes('_HOOD_') || id.includes('_COWL_');
    case 'shoes':
      return c.includes('shoes') || c.includes('boots') || id.includes('_SHOES_') || id.includes('_BOOTS_');
    case 'offhands':
      return c.includes('offhand') || id.includes('_OFF_') || id.includes('_SHIELD') || id.includes('_BOOK') || id.includes('_TORCH') || id.includes('_HORN') || id.includes('_TOTEM') || id.includes('_ORB');
    case 'capes':
      return c.includes('cape') || id.includes('_CAPE');
    case 'bags':
      return c.includes('bag') || id.includes('_BAG');
    case 'consumables':
      return c.includes('consumable') || c.includes('potion') || c.includes('food') || id.includes('_POTION_') || id.includes('_MEAL_') || id.includes('_FISH_');
    case 'mounts':
      return c.includes('mount') || id.includes('_MOUNT_');
    case 'crafting':
      return c.includes('crafting') || c.includes('resource') || id.includes('_BAR') || id.includes('_PLANKS') || id.includes('_LEATHER') || id.includes('_CLOTH') || id.includes('_STONEBLOCK') || id.includes('_ORE') || id.includes('_WOOD') || id.includes('_HIDE') || id.includes('_FIBER') || id.includes('_ROCK');
    case 'artefacts':
      return c.includes('artefact') || id.includes('_RUNE') || id.includes('_SOUL') || id.includes('_RELIC') || id.includes('_SHARD') || id.includes('_ARTEFACT_');
    case 'token':
      return c.includes('token') || id.includes('TOKEN') || id.includes('SIGIL') || id.includes('CREST');
    default:
      return true;
  }
}

// Debounce helper
function debounce(fn, delay = 60) {
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
  
  // High-performance static Cloudflare edge caching:
  // For standard quality (1), direct static URLs without query parameters hit Cloudflare CDN edge cache in <50ms with 99.9% uptime.
  // This completely avoids Albion's dynamic image scaler backend which returns HTTP 502 Bad Gateway under concurrent card/table requests.
  if (q > 1) {
    return `https://render.albiononline.com/v1/item/${safeIdentifier}.png?quality=${q}`;
  }
  return `https://render.albiononline.com/v1/item/${safeIdentifier}.png`;
}

function handleIconError(img, itemId, quality = 1) {
  if (!img) return;
  const currentSrc = img.src || '';
  if (currentSrc.includes('T4_BAG.png') || img.dataset.fallbackExhausted === 'true') return;

  img.onerror = null;
  const cleanId = String(itemId || '').trim();
  const safeIdentifier = encodeURIComponent(cleanId).replace(/%40/g, '@');

  const fallbacks = [];

  // Fallback 1: Try raw static asset URL without query params (direct static Cloudflare edge hit)
  fallbacks.push(`https://render.albiononline.com/v1/item/${safeIdentifier}.png`);

  // Fallback 2: If enchanted (@1, @2, @3, @4), strip enchantment and try base item static URL
  if (cleanId.includes('@')) {
    const baseId = cleanId.split('@')[0].toUpperCase();
    fallbacks.push(`https://render.albiononline.com/v1/item/${encodeURIComponent(baseId)}.png`);
  }

  // Fallback 4: Category-appropriate placeholder (prevent showing a bag on raw meat, crops, or potions)
  const upper = cleanId.toUpperCase();
  if (upper.includes('_MEAT') || upper.includes('_SOUP') || upper.includes('_STEW') || upper.includes('_PIE') || upper.includes('_ROAST') || upper.includes('_OMELETTE') || upper.includes('_SANDWICH') || upper.includes('_SALAD') || upper.includes('_BUTCHER')) {
    fallbacks.push('https://render.albiononline.com/v1/item/T4_MEAT.png');
  } else if (upper.includes('_POTION_') || upper.includes('POTION') || upper.includes('FLASK')) {
    fallbacks.push('https://render.albiononline.com/v1/item/T4_POTION_HEAL.png');
  } else if (upper.includes('_CARROT') || upper.includes('_BEAN') || upper.includes('_WHEAT') || upper.includes('_TURNIP') || upper.includes('_CABBAGE') || upper.includes('_POTATO') || upper.includes('_CORN') || upper.includes('_PUMPKIN') || upper.includes('_SEED') || upper.includes('_EGG') || upper.includes('_MILK') || upper.includes('_AGARIC') || upper.includes('_COMFREY') || upper.includes('_BURDOCK') || upper.includes('_TEASEL') || upper.includes('_FOXGLOVE') || upper.includes('_MULLEIN') || upper.includes('_YARROW')) {
    fallbacks.push('https://render.albiononline.com/v1/item/T1_CARROT.png');
  } else if (upper.includes('_MOUNT') || upper.includes('HORSE') || upper.includes('OX') || upper.includes('STAG') || upper.includes('RAM')) {
    fallbacks.push('https://render.albiononline.com/v1/item/T3_MOUNT_HORSE.png');
  } else {
    fallbacks.push('https://render.albiononline.com/v1/item/T4_BAG.png');
  }

  // Filter out current failed src to prevent looping
  const uniqueFallbacks = fallbacks.filter(url => url !== currentSrc);

  let fallbackIndex = 0;
  img.onerror = function() {
    if (fallbackIndex < uniqueFallbacks.length) {
      img.src = uniqueFallbacks[fallbackIndex++];
    } else {
      img.onerror = null;
      img.dataset.fallbackExhausted = 'true';
    }
  };

  if (uniqueFallbacks.length > 0) {
    img.src = uniqueFallbacks[fallbackIndex++];
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
    
    // Purge any locally dismissed items and enrich in-place
    const filteredCategories = {};
    for (const [k, list] of Object.entries(rawCategories)) {
      if (Array.isArray(list)) {
        const kept = [];
        for (let i = 0; i < list.length; i++) {
          const o = list[i];
          const idUpper = String(o.item_id || o.target_item_id || '').toUpperCase();
          if (!state.dismissedIds.has(idUpper)) {
            enrichOpportunity(o, k);
            kept.push(o);
          }
        }
        filteredCategories[k] = kept;
      } else {
        filteredCategories[k] = list;
      }
    }

    let newTotal = 0;
    for (const k in filteredCategories) {
      if (Array.isArray(filteredCategories[k])) newTotal += filteredCategories[k].length;
    }
    let oldTotal = 0;
    for (const k in state.opportunities) {
      if (Array.isArray(state.opportunities[k])) oldTotal += state.opportunities[k].length;
    }
    const isFirstLoad = oldTotal === 0 && newTotal > 0;

    state.opportunities = filteredCategories;
    state.filterDirty = true;
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

async function togglePrivacyMode(enabled) {
  try {
    const res = await fetch(`/api/v1/system/privacy-toggle?enabled=${enabled}`, {
      method: 'POST',
      headers: { 'Accept': 'application/json' }
    });
    if (!res.ok) throw new Error('Failed to update privacy settings');
    const data = await res.json();
    state.settings.privacy_mode_enabled = data.privacy_mode_enabled;
    updateSettingsUI();
    showToast(
      enabled
        ? 'Privacy Mode: ENABLED 🔒'
        : 'Privacy Mode: DISABLED 🌐',
      enabled
    );
  } catch (err) {
    console.error('Privacy Toggle error:', err);
    showToast('Failed to update privacy mode', false);
    // revert
    const toggle = document.getElementById('privacy-mode-toggle');
    if (toggle) toggle.checked = !enabled;
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
    if (enabled) {
      await fetchStats();
      await fetchOpportunities();
    }
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
    state.filterDirty = true;
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
    const res = await fetch('/api/v1/system/scan?quick=true', { method: 'POST' });
    if (!res.ok) throw new Error('Scan failed with server status ' + res.status);
    const data = await res.json();
    const totalCount = data.total_opportunities !== undefined ? data.total_opportunities : (data.total_matched || 0);
    showToast(`Scan Complete: Found ${totalCount} verified opportunities.`, true);
    await fetchOpportunities();
    await fetchStats();
  } catch (err) {
    console.error('Scan trigger error:', err);
    showToast('Market scan encountered an issue: ' + (err.message || 'Error'), false);
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

  let unitProfit = opp._unitProfit !== undefined ? opp._unitProfit : Number(opp.net_profit || opp.profit || opp.estimated_profit || 0);
  const unitCost = opp._unitCost !== undefined ? opp._unitCost : Number(
    opp.mode === "CRAFT+RUN"
      ? (opp.craft_cost || opp.effective_cost || opp.total_cost || opp.buy_price)
      : (opp.total_cost || opp.effective_cost || opp.craft_cost || opp.buy_price || opp.material_cost_gross || 1)
  );
  // unitRevenue already accounts for output_qty (5x potions / 10x meals) from normalization
  const unitRevenue = opp._unitRevenue !== undefined ? opp._unitRevenue : (() => {
    const rawRev = Number(opp.sell_price || opp.bm_buy_price || opp.revenue_net || 0);
    const oq = Number(opp.output_qty || 1);
    return oq > 1 ? rawRev * oq : rawRev;
  })();
  const dailyVol = opp._dailyVol !== undefined ? opp._dailyVol : Number(opp.daily_volume || 10);
  const safeLimit = opp._safeLimit !== undefined ? opp._safeLimit : Number(opp.safe_limit || 1);
  
  // Real-time tax adjustment when user toggles Premium (4% vs 8% sales tax across all markets)
  if (unitRevenue > 0 && Math.abs(oppTaxRate - currentTaxRate) > 0.001) {
    const taxDelta = unitRevenue * (oppTaxRate - currentTaxRate);
    unitProfit = Math.round(unitProfit + taxDelta);
  }

  const unitWeight = opp._unitWeight !== undefined ? opp._unitWeight : Number(opp.profit_per_kg ? (unitProfit / opp.profit_per_kg) : 1.5);
  
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
    batchRevenueNet: Math.round(batchProfit + batchCost),  // Revenue - Cost = Profit, always consistent
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

  const privToggle = document.getElementById('privacy-mode-toggle');
  if (privToggle) {
    privToggle.checked = state.settings.privacy_mode_enabled === true;
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
  if (search.trim()) active.push({ key: 'search', label: `Search: "${search.trim()}"` });
  if (category && category !== 'all') active.push({ key: 'category', label: `Cat: ${category.toUpperCase()}` });
  if (tier > 0) active.push({ key: 'tier', label: `Tier T${tier}` });
  if (highTierOnly) active.push({ key: 'highTierOnly', label: `T7 - T8 Whales` });
  if (enchantment !== 'all') active.push({ key: 'enchantment', label: `Enchant .${enchantment}` });
  if (quality > 0) active.push({ key: 'quality', label: `Quality Q${quality}` });
  if (sourceCity) active.push({ key: 'sourceCity', label: `Source: ${sourceCity}` });
  if (destCity) active.push({ key: 'destCity', label: `Dest: ${destCity}` });
  if (state.filters.islandCity) active.push({ key: 'islandCity', label: `🏝️ Island: ${state.filters.islandCity}` });
  if (safeOnly) active.push({ key: 'safeOnly', label: `Safe Routes Only` });
  if (highRoiOnly) active.push({ key: 'highRoiOnly', label: `High ROI (>25%)` });
  if (highVolOnly) active.push({ key: 'highVolOnly', label: `High Vol (>50)` });
  if (latestOnly) active.push({ key: 'latestOnly', label: `Fresh (<15m)` });
  if (maxInvestment > 0) active.push({ key: 'maxInvestment', label: `Max Budget: < ${fmtK(maxInvestment)}s` });
  if (minProfit > 0) active.push({ key: 'minProfit', label: `Min Profit: ${fmtK(minProfit)}s` });
  if (minRoi > 0) active.push({ key: 'minRoi', label: `Min ROI: ${minRoi}%` });
  if (minVolume > 0) active.push({ key: 'minVolume', label: `Min Vol: ${minVolume}+` });
  return active;
}

function updateActiveFilterChipsUI() {
  const active = getActiveFiltersList();
  const drawerWrap = document.getElementById('active-filter-chips-wrap');
  const compactStrip = document.getElementById('compact-active-filters-strip');
  const compactWrap = document.getElementById('compact-filter-chips');
  const countBadge = document.getElementById('active-filters-count');

  if (countBadge) {
    if (active.length > 0) {
      countBadge.textContent = active.length;
      countBadge.style.display = 'inline-block';
    } else {
      countBadge.style.display = 'none';
    }
  }

  const chipsHtml = active.map(f => `
    <span class="filter-chip">
      <span>${f.label}</span>
      <span class="filter-chip-remove" onclick="removeFilter('${f.key}')" title="Remove filter">✕</span>
    </span>
  `).join('');

  if (drawerWrap) drawerWrap.innerHTML = chipsHtml;
  if (compactWrap) compactWrap.innerHTML = chipsHtml;
  if (compactStrip) compactStrip.style.display = active.length > 0 ? 'flex' : 'none';
}

window.toggleAdvancedFilters = function() {
  const drawer = document.getElementById('advanced-filters-drawer');
  const btn = document.getElementById('toggle-filters-btn');
  if (!drawer) return;
  const isHidden = drawer.style.display === 'none';
  drawer.style.display = isHidden ? 'block' : 'none';
  if (btn) btn.classList.toggle('active', isHidden);
};

window.removeFilter = function(key) {
  if (key === 'search') {
    state.filters.search = '';
    const el = document.getElementById('search-input');
    if (el) el.value = '';
  } else if (key === 'category') {
    state.filters.category = 'all';
    const el = document.getElementById('category-filter');
    if (el) el.value = 'all';
    document.querySelectorAll('.cat-pill-btn').forEach(b => {
      b.classList.toggle('active', b.dataset.cat === 'all');
    });
  } else if (key === 'tier') {
    state.filters.tier = 0;
    const el = document.getElementById('tier-filter');
    if (el) el.value = '0';
  } else if (key === 'enchantment') {
    state.filters.enchantment = 'all';
    const el = document.getElementById('enchant-filter');
    if (el) el.value = 'all';
  } else if (key === 'sourceCity') {
    state.filters.sourceCity = '';
    const el = document.getElementById('source-city-filter');
    if (el) el.value = '';
  } else if (key === 'destCity') {
    state.filters.destCity = '';
    const el = document.getElementById('dest-city-filter');
    if (el) el.value = '';
  } else if (key === 'islandCity') {
    state.filters.islandCity = '';
    const el = document.getElementById('island-city-filter');
    if (el) el.value = '';
  } else if (key === 'maxInvestment') {
    state.filters.maxInvestment = 0;
    const el = document.getElementById('max-cost-filter');
    if (el) el.value = '0';
  } else if (key === 'minProfit') {
    state.filters.minProfit = 0;
    const el = document.getElementById('min-profit-filter');
    if (el) el.value = '0';
  } else if (key === 'minRoi') {
    state.filters.minRoi = 0;
    const el = document.getElementById('min-roi-filter');
    if (el) el.value = '0';
  } else if (key === 'minVolume') {
    state.filters.minVolume = 0;
    const el = document.getElementById('min-vol-filter');
    if (el) el.value = '0';
  } else if (['latestOnly', 'safeOnly', 'highRoiOnly', 'highVolOnly', 'highTierOnly'].includes(key)) {
    state.filters[key] = false;
    const tagMap = {
      latestOnly: 'tag-latest-only',
      safeOnly: 'tag-safe-only',
      highRoiOnly: 'tag-high-roi',
      highVolOnly: 'tag-high-vol',
      highTierOnly: 'tag-high-tier',
    };
    const el = document.getElementById(tagMap[key]);
    if (el) el.classList.remove('active');
  }

  state.filterDirty = true;
  state.currentPage = 1;
  renderViews();
  updateActiveFilterChipsUI();
};

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

  state.filters.islandCity = '';
  const islCityFilter = document.getElementById('island-city-filter');
  if (islCityFilter) islCityFilter.value = '';

  ['tag-latest-only', 'tag-safe-only', 'tag-high-roi', 'tag-high-vol', 'tag-high-tier'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.classList.remove('active');
  });

  document.querySelectorAll('.cat-pill-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.cat === 'all');
  });

  state.filterDirty = true;
  state.currentPage = 1;
  renderViews();
  updateTabCounts();
  updateActiveFilterChipsUI();
  showToast('All active filters reset');
};

const KNOWN_ITEM_NAMES = {
  // Rare Fish
  'T7_FISH_FRESHWATER_FOREST_RARE': 'Deadwater Eel',
  'T8_FISH_FRESHWATER_HIGHLANDS_RARE': 'Puremist Snapper',
  'T7_FISH_FRESHWATER_SWAMP_RARE': 'Dustcrawler Crab',
  'T8_FISH_FRESHWATER_SWAMP_RARE': 'Ghostclaws Crab',
  'T7_FISH_SALTWATER_ALL_RARE': 'Blackbog Clam',
  'T8_FISH_SALTWATER_ALL_RARE': 'Kraken',
  'T6_FISH_FRESHWATER_FOREST_RARE': 'Thunderfall Eel',
  'T5_FISH_FRESHWATER_FOREST_RARE': 'Redspring Eel',
  'T3_FISH_FRESHWATER_FOREST_RARE': 'Greenriver Eel',
  'T7_FISH_FRESHWATER_MOUNTAIN_RARE': 'Frostpeak Salmon',
  'T8_FISH_FRESHWATER_MOUNTAIN_RARE': 'Whitefog Snapper',
  'T7_FISH_FRESHWATER_STEPPE_RARE': 'Stonestream Lurch',
  'T8_FISH_FRESHWATER_STEPPE_RARE': 'Sunken City Carp',
  'T7_FISH_FRESHWATER_HIGHLANDS_RARE': 'Deepwater Bream',
  // Common Fish
  'T1_FISH_FRESHWATER_ALL_COMMON': 'Common Rudd',
  'T2_FISH_FRESHWATER_ALL_COMMON': 'Striped Carp',
  'T3_FISH_FRESHWATER_ALL_COMMON': 'Albion Perch',
  'T4_FISH_FRESHWATER_ALL_COMMON': 'Bluescale Pike',
  'T5_FISH_FRESHWATER_ALL_COMMON': 'Spotted Trout',
  'T6_FISH_FRESHWATER_ALL_COMMON': 'Brightscale Zander',
  'T7_FISH_FRESHWATER_ALL_COMMON': 'Danglemouth Catfish',
  'T8_FISH_FRESHWATER_ALL_COMMON': 'River Sturgeon',
  // Farming & Crops
  'T1_CARROT': 'Carrots',
  'T2_BEAN': 'Beans',
  'T3_WHEAT': 'Wheat',
  'T4_TURNIP': 'Turnips',
  'T5_CABBAGE': 'Cabbage',
  'T6_POTATO': 'Potatoes',
  'T7_CORN': 'Corn',
  'T8_PUMPKIN': 'Pumpkin',
  // Herbs
  'T2_AGARIC': 'Arcane Agaric',
  'T3_COMFREY': 'Brightleaf Comfrey',
  'T4_BURDOCK': 'Crenellated Burdock',
  'T5_TEASEL': 'Dragon Teasel',
  'T6_FOXGLOVE': 'Elusive Foxglove',
  'T7_MULLEIN': 'Fire Lily',
  'T8_YARROW': 'Ghirshill Yarrow',
  // Livestock & Animal Produce
  'T3_MEAT': 'Raw Chicken',
  'T4_MEAT': 'Raw Goat',
  'T5_MEAT': 'Raw Goose',
  'T6_MEAT': 'Raw Mutton',
  'T7_MEAT': 'Raw Pork',
  'T8_MEAT': 'Raw Beef',
  'T3_EGG': "Hen's Egg",
  'T5_EGG': "Goose Egg",
  'T4_MILK': "Goat's Milk",
  'T6_MILK': "Sheep's Milk",
  'T8_MILK': "Cow's Milk",
  'T4_BUTTER': "Goat's Butter",
  'T6_BUTTER': "Sheep's Butter",
  'T8_BUTTER': "Cow's Butter",
  'T6_ALCOHOL': 'Potato Schnapps',
  'T7_ALCOHOL': 'Corn Hooch',
  'T8_ALCOHOL': 'Pumpkin Moonshine',
  'T4_FLOUR': 'Flour',
  'T4_BREAD': 'Bread',
};

function formatItemName(rawId) {
  if (!rawId) return '';
  const parts = String(rawId).split('@');
  const clean = parts[0];
  const enchant = (parts.length > 1 && parts[1] && parts[1] !== '0') ? `.${parts[1]}` : '';

  let name = '';
  if (KNOWN_ITEM_NAMES[rawId]) {
    return KNOWN_ITEM_NAMES[rawId];
  } else if (KNOWN_ITEM_NAMES[clean]) {
    name = KNOWN_ITEM_NAMES[clean];
  } else if (/^T\d+_/.test(clean)) {
    const tier = clean.slice(0, 2);
    const rest = clean.slice(3).replace(/_/g, ' ').toLowerCase();
    const capitalized = rest.split(' ').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
    return enchant ? `${tier}${enchant} ${capitalized}` : `${tier} ${capitalized}`;
  } else {
    name = clean.replace(/_/g, ' ');
  }

  return enchant ? `${name} ${enchant}` : name;
}

function updateTabCounts() {
  let allCount = 0;
  const hasSubSectors = Boolean(
    (state.opportunities.potions && state.opportunities.potions.length > 0) ||
    (state.opportunities.cooking && state.opportunities.cooking.length > 0) ||
    (state.opportunities.farming && state.opportunities.farming.length > 0) ||
    (state.opportunities.mounts && state.opportunities.mounts.length > 0)
  );

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

// Master Render with Virtual Pagination & High-Performance Single Pass
function updateKpisInPlace(filtered) {
  if (!filtered) filtered = getFilteredOpportunities();
  const totalEl = document.getElementById('stat-total-opps');
  if (totalEl) totalEl.textContent = filtered.length.toLocaleString();
  let pipelineProfit = 0;
  for (let i = 0; i < filtered.length; i++) {
    pipelineProfit += (filtered[i]._unitProfit !== undefined ? filtered[i]._unitProfit : Number(filtered[i].net_profit || filtered[i].profit || filtered[i].estimated_profit || 0));
  }
  const profitEl = document.getElementById('stat-pipeline-profit');
  if (profitEl) profitEl.textContent = (pipelineProfit >= 0 ? '+' : '') + fmtK(pipelineProfit) + ' s';
}

let renderRafId = null;

function renderViews() {
  if (renderRafId) cancelAnimationFrame(renderRafId);
  renderRafId = requestAnimationFrame(() => {
    const filtered = getFilteredOpportunities();
    updateKpisInPlace(filtered);
    updateActiveFilterChipsUI();

    // Compute pagination
    const totalPages = Math.max(1, Math.ceil(filtered.length / state.pageSize));
    if (state.currentPage > totalPages) state.currentPage = totalPages;
    if (state.currentPage < 1) state.currentPage = 1;

    const startIdx = (state.currentPage - 1) * state.pageSize;
    const pageSlice = filtered.slice(startIdx, startIdx + state.pageSize);

    renderPaginationControls(totalPages, filtered.length);

    const cv = document.getElementById('cards-view');
    const tv = document.getElementById('table-view');

    if (state.viewMode === 'cards') {
      if (cv) cv.style.display = 'grid';
      if (tv) tv.style.display = 'none';
      renderCardsView(pageSlice, startIdx);
    } else {
      if (cv) cv.style.display = 'none';
      if (tv) tv.style.display = 'block';
      renderTableView(pageSlice, startIdx);
    }
  });
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
    let currentTabTotal = 0;
    let globalTotalOpps = 0;
    for (const k in state.opportunities) {
      if (Array.isArray(state.opportunities[k])) globalTotalOpps += state.opportunities[k].length;
    }
    if (state.activeTab === 'all') {
      currentTabTotal = globalTotalOpps;
    } else {
      currentTabTotal = (state.opportunities[state.activeTab] || []).length;
    }

    const catMeta = getCategoryMeta(state.activeTab);
    const catLabel = state.activeTab === 'all' ? 'total' : catMeta.label;

    let icon = '🔍';
    let emptyTitle = 'No opportunities matched these filters';
    let emptySub = 'Adjust search filters or click "Scan Now".';
    let actionBtnHtml = '';

    if (globalTotalOpps === 0) {
      if (state.isScanning) {
        icon = '📡';
        emptyTitle = 'Market Scan in Progress...';
        emptySub = 'Evaluating orderbooks across Royal Cities, Caerleon, and Black Market.';
      } else {
        icon = '⚡';
        emptyTitle = 'Terminal Ready — Initiate Live Market Scan';
        emptySub = 'Connect to Albion Online live data or click "Scan Now" to calculate real-time trade corridors.';
        actionBtnHtml = `
          <button class="btn-scan-primary" style="margin-top: 1.25rem; padding: 0.55rem 1.6rem; font-size: 0.85rem;" onclick="triggerScan()">
            ⚡ Scan Now
          </button>
        `;
      }
    } else if (currentTabTotal === 0) {
      icon = '📦';
      emptyTitle = `No active opportunities in ${catLabel}`;
      emptySub = 'Run a fresh scan or check other market categories in the sidebar.';
      actionBtnHtml = `
        <button class="btn-scan-primary" style="margin-top: 1.25rem; padding: 0.55rem 1.6rem; font-size: 0.85rem;" onclick="triggerScan()">
          ⚡ Run Fresh Scan
        </button>
      `;
    } else if (activeFilters.length > 0) {
      icon = '🔍';
      emptyTitle = `${currentTabTotal} ${catLabel} opportunities exist, but are hidden by active filters`;
      emptySub = `Active Filters: <strong style="color: var(--accent-gold-bright);">${activeFilters.join(' • ')}</strong>`;
      actionBtnHtml = `
        <button class="btn-scan-primary" style="margin-top: 1.25rem; padding: 0.45rem 1.25rem; font-size: 0.8rem; background: var(--accent-gold); color: #000; font-weight: 700; border-radius: 6px; cursor: pointer; border: none;" onclick="resetAllFilters()">
          🧹 Clear Active Filters
        </button>
      `;
    }

    container.innerHTML = `
      <div style="grid-column: 1 / -1; text-align: center; padding: 4rem 1rem; color: var(--text-muted);">
        <div style="font-size: 2.5rem; margin-bottom: 0.5rem;">${icon}</div>
        <h3 style="color: #fff; font-size: 1.15rem; font-weight: 700;">${emptyTitle}</h3>
        <p style="font-size: 0.85rem; margin-top: 0.4rem; color: #a0aec0;">${emptySub}</p>
        ${actionBtnHtml}
      </div>
    `;
    return;
  }

  let html = '';
  for (let i = 0; i < pageSlice.length; i++) {
    try {
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

      const catStr = String(opp.category_key || state.activeTab || '').toLowerCase();
      const isBm = catStr.includes('bm') || catStr.includes('black_market') || (opp.destination_city && opp.destination_city.toLowerCase() === 'black market');
      const srcCity = opp.buy_city || opp.source_city || opp.craft_city || opp.refine_city || opp.base_city || 'Martlock';
      const dstCity = opp.sell_city || opp.destination_city || (isBm ? 'Black Market' : srcCity);
      const isDangerous = isLethalRoute(opp, srcCity, dstCity);
      const zoneMeta = getRouteZoneMeta(opp, srcCity, dstCity);
      const catMeta = getCategoryMeta(opp.category_key || state.activeTab, opp);

      const bmAge = Number(opp.data_age_bm || 0);
      const sellAge = Number(opp.data_age_sell || 0);
      const baseAge = Number(opp.data_age_base || opp.data_age_buy || 0);
      const effAge = getEffectiveDataAge(opp);

      const qualityNames = { 1: '', 2: 'Good', 3: 'Out', 4: 'Exc', 5: 'MP' };
      const stars = '★'.repeat(quality);
      const iconUrl = getItemIconUrl(itemId, quality, 64);

      const isFarming = (opp.subsector === 'crops' || opp.subsector === 'herbs' || opp.subsector === 'farming' || opp.category_key === 'farming');
      const isLivestock = (opp.subsector === 'livestock' || opp.category_key === 'livestock');
      const isIslandAgri = (isFarming || isLivestock) && opp.profit_per_plot_day > 0;
      const isCooking = (opp.category_key === 'cooking' || opp.subsector === 'cooking');
      const isPotion = (opp.category_key === 'potions' || opp.subsector === 'potions' || opp.subsector === 'alchemy');
      const isCrafting = (opp.type === 'crafting' || opp.category_key === 'crafting' || opp.category_key === 'bm_crafting');
      const isRefining = (opp.type === 'refining' || opp.category_key === 'refining' || opp.category_key === 'bm_refining');

      let srcRole = 'SOURCE / BUY';
      let dstRole = isBm ? 'DEST / BLACK MARKET' : 'DEST / SELL';
      if (isLivestock) {
        srcRole = 'SOURCE / BABY & FEED';
        dstRole = 'DEST / PRODUCE & MEAT';
      } else if (isFarming) {
        srcRole = 'SOURCE / SEEDS';
        dstRole = 'DEST / HARVEST CROP';
      } else if (isPotion) {
        srcRole = 'SOURCE / HERBS & FLUIDS';
        dstRole = `DEST / BATCH (${opp.output_qty || 5}x POTIONS)`;
      } else if (isCooking) {
        srcRole = 'SOURCE / INGREDIENTS';
        dstRole = `DEST / BATCH (${opp.output_qty || 10}x MEALS)`;
      } else if (isCrafting) {
        srcRole = `SOURCE / WORKSHOP (${srcCity})`;
        dstRole = isBm ? 'DEST / BLACK MARKET' : 'DEST / MARKET GEAR';
      } else if (isRefining) {
        srcRole = `SOURCE / REFINERY (${srcCity})`;
        dstRole = 'DEST / REFINED RESOURCES';
      }

      html += `
        <div class="opp-card tier-t${tierNum}" data-key="${oppKey}" data-item-id="${itemId.toUpperCase()}">
          
          <!-- Header: High-Res Albion Icon with Quality Overlay + Name + Tags -->
          <div class="card-top-row">
            <div class="item-icon-wrap tier-border-t${tierNum}">
              <img class="item-icon-img" src="${iconUrl}" alt="${opp.item_name || itemId}" width="60" height="60" loading="lazy" decoding="async" onerror="handleIconError(this, '${itemId}', ${quality})" />
              ${quality > 1 ? `<div class="item-quality-pill quality-q${quality}" title="Quality: ${qualityNames[quality]}">${qualityNames[quality]}</div>` : ''}
            </div>
            <div class="card-meta-block">
              <div class="card-item-title" title="${opp.item_name || itemId}">${opp.item_name || itemId}</div>
              <div class="card-tags-row">
                <span class="badge-tag badge-tier tier-color-t${tierNum}">${tier}${enchantLabel}</span>
                <span class="badge-tag badge-category" style="color: ${catMeta.color}; background: ${catMeta.bg}; border-color: ${catMeta.color}40;">${catMeta.label}</span>
                <span class="badge-tag ${zoneMeta.badgeClass}">${zoneMeta.label}</span>
                ${(opp.output_qty && opp.output_qty > 1) ? `<span class="badge-tag" style="background: rgba(234, 179, 8, 0.18); color: #facc15; border: 1px solid rgba(234, 179, 8, 0.35);">📦 ${opp.output_qty}x ${opp.subsector === 'livestock' ? 'Slaughter' : (opp.subsector === 'crops' || opp.subsector === 'herbs' ? 'Harvest' : (opp.category_key === 'potions' ? 'Potion' : (opp.category_key === 'cooking' ? 'Meal' : 'Batch')))} Yield</span>` : ''}
                ${(opp.has_lpb || (opp.category_key === 'potions' && srcCity === 'Brecilien') || (opp.category_key === 'cooking' && srcCity === 'Caerleon')) ? `<span class="badge-tag" style="background: rgba(56, 189, 248, 0.18); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.35);">✨ +15% LPB Specialty</span>` : ''}
                ${opp.biome_bonus_active ? `<span class="badge-tag" style="background: rgba(46, 160, 67, 0.2); color: #7ee787; border: 1px solid rgba(46, 160, 67, 0.4);">🌿 +10% Biome Specialty</span>` : ''}
                ${opp.manipulation_risk === 'high' ? `<span class="badge-tag" style="background: rgba(248, 81, 73, 0.2); color: #f85149; border: 1px solid rgba(248, 81, 73, 0.45); animation: pulse 2s infinite;">⚠️ High Manipulation Risk</span>` : opp.manipulation_risk === 'medium' ? `<span class="badge-tag" style="background: rgba(227, 179, 65, 0.2); color: #e3b341; border: 1px solid rgba(227, 179, 65, 0.4);">⚠️ Wide Spread — Verify</span>` : opp.manipulation_risk === 'low' ? `<span class="badge-tag" style="background: rgba(139, 148, 158, 0.15); color: #8b949e; border: 1px solid rgba(139, 148, 158, 0.3);">🔍 Low Liquidity</span>` : ''}
                ${opp.silver_per_focus > 0 ? `<span class="badge-tag" style="background: rgba(210, 168, 255, 0.15); color: #d2a8ff; border: 1px solid rgba(210, 168, 255, 0.3);">💎 ${opp.silver_per_focus} s/Focus</span>` : ''}
                <span id="fresh-badge-${oppKey}" class="badge-tag badge-freshness ${opp.freshness_tier === 'candidate' ? 'fresh-amber' : 'fresh-green'}" title="${opp.freshness_label || 'Data Freshness'} • Sourced: ${srcCity} (${fmtAge(baseAge || effAge)}) ➔ Dest: ${dstCity} (${fmtAge(bmAge || sellAge || effAge)})">
                  <span class="pulse-dot"></span>${opp.freshness_tier === 'candidate' ? '🟡 Candidate (Verify)' : '🟢 Verified (<45m)'}
                </span>
                ${opp.is_persisted_alert ? `<span class="badge-tag" style="background: rgba(163, 113, 247, 0.18); color: #d2a8ff; border: 1px solid rgba(163, 113, 247, 0.35);" title="Active unfulfilled order reconfirmed across scans">⚡ Active Order</span>` : ''}
              </div>
            </div>
          </div>

          <!-- Profit Hero: Batch Net Profit + ROI Margin -->
          <div class="card-profit-hero">
            <div class="profit-hero-left">
              <span class="profit-hero-label">Net Profit (${m.qty}x ${(opp.output_qty && opp.output_qty > 1) ? `Batch [${m.qty * opp.output_qty}x items]` : 'Batch'})</span>
              <span class="profit-hero-val font-mono" style="color: ${m.batchProfit >= 0 ? 'var(--accent-emerald)' : 'var(--accent-danger)'};" id="profit-${oppKey}">${fmtProfit(m.batchProfit)}</span>
              ${isIslandAgri ? `<div style="font-size: 0.72rem; color: var(--accent-gold-bright); font-family: 'JetBrains Mono', monospace; margin-top: 0.2rem;">🌾 Plot/Day: +${fmtK(opp.profit_per_plot_day)} s (9 spots)</div>` : ''}
            </div>
            <div class="profit-hero-right">
              <span class="roi-badge-pill font-mono" id="roi-${oppKey}">+${m.batchRoi}% ROI</span>
              <span class="profit-meta-sub font-mono">${fmtK(m.unitCost)} cost • ${fmtK(m.unitRevenue)} rev ${(opp.output_qty && opp.output_qty > 1) ? `(${opp.output_qty}x)` : ''} • ${m.batchWeight} kg</span>
              ${opp.cycle_hours ? `<div style="font-size: 0.68rem; color: var(--text-muted); text-align: right; margin-top: 0.15rem;">⏱️ ${opp.cycle_hours}h Cycle</div>` : ''}
            </div>
          </div>

          <!-- Route Visual Lane -->
          <div class="card-route-lane">
            <div class="route-lane-node">
              <span class="node-role-lbl">${srcRole}</span>
              <span class="node-city" style="color: ${CITY_COLORS[srcCity] || '#fff'};">${srcCity}</span>
              <span class="node-price font-mono">${fmtK(m.unitCost)} silver</span>
              ${baseAge > 0 ? `<span class="node-age-sub font-mono">Listed: ${fmtAge(baseAge)}</span>` : ''}
            </div>
            <div class="route-lane-arrow-wrap">
              <span class="route-lane-arrow">➔</span>
              <span class="route-lane-zone-tag">${zoneMeta.type}</span>
            </div>
            <div class="route-lane-node" style="text-align: right;">
              <span class="node-role-lbl">${dstRole}</span>
              <span class="node-city" style="color: ${CITY_COLORS[dstCity] || '#ffd700'};">${dstCity}</span>
              <span class="node-price font-mono" style="color: var(--accent-gold-bright);">${(opp.output_qty && opp.output_qty > 1) ? `${fmtK(opp._rawSellPrice || Math.round(m.unitRevenue / opp.output_qty))} s × ${opp.output_qty} = ${fmtK(m.unitRevenue)}` : `${fmtK(m.unitRevenue)} silver`}</span>
              ${bmAge > 0 ? `<span class="node-age-sub font-mono" style="color: var(--accent-emerald);">BM Order: ${fmtAge(bmAge)}</span>` : ''}
            </div>
          </div>

          <!-- Volume Stepper & Sizing Controls (Streamlined 4 Controls) -->
          <div class="card-volume-bar">
            <span class="volume-cap-lbl font-mono">Safe Depth: <strong>${m.safeLimit}x</strong></span>
            <div class="volume-stepper">
              <button class="vol-step-btn" onclick="stepVolume('${oppKey}', -1)" title="Decrease batch size">-</button>
              <input type="number" class="vol-input font-mono" id="vol-${oppKey}" value="${m.qty}" min="1" max="10000" onchange="setVolume('${oppKey}', this.value)" />
              <button class="vol-step-btn" onclick="stepVolume('${oppKey}', 1)" title="Increase batch size">+</button>
              <button class="vol-step-btn ${m.qty === m.safeLimit ? 'active' : ''}" onclick="setVolume('${oppKey}', ${m.safeLimit})" title="Size to top orderbook depth">Max</button>
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
            <div style="display: flex; gap: 0.4rem; align-items: center;">
              <button class="btn-verify-live" id="verify-btn-${oppKey}" onclick="verifyOpportunityLive('${oppKey}', '${itemId}', '${srcCity}', '${dstCity}', ${m.unitCost}, ${m.unitRevenue}, ${opp.quality || 1}, event)" title="1-Click Pre-Flight Live Price Check">⚡ Verify</button>
              <button class="btn-dismiss-sub" onclick="dismissOpportunity('${itemId}', '${opp.category_key || state.activeTab}', event, ${opp.data_age_bm || opp.data_age_sell || 0}, ${opp.bm_buy_price || opp.sell_price || 0}, ${opp.quality || 1})" title="Mark as filled or dismiss">✓ Filled</button>
              <button class="btn-blueprint-action" onclick="openDetailModal(${globalIdx}, '${opp.category_key || state.activeTab}')">🔍 Blueprint & Math</button>
            </div>
          </div>

        </div>
      `;
    } catch (err) {
      console.error('Error rendering card index', i, err);
    }
  }

  container.innerHTML = html;
}

// Render Dense Quant Data Table View
function renderTableView(pageSlice, offset) {
  const tbody = document.getElementById('dense-table-body');
  if (!tbody) return;

  if (pageSlice.length === 0) {
    let emptyMsg = 'No matching opportunities found for the selected filters.';
    let globalTotalOpps = 0;
    for (const k in state.opportunities) {
      if (Array.isArray(state.opportunities[k])) globalTotalOpps += state.opportunities[k].length;
    }
    if (globalTotalOpps === 0) {
      emptyMsg = 'Terminal Ready — Click "⚡ Scan Now" in the topbar to ingest markets and compute trade routes.';
    }
    tbody.innerHTML = `<tr><td colspan="10" style="text-align: center; padding: 4rem 1rem; color: var(--text-muted); font-size: 0.9rem;">${emptyMsg}</td></tr>`;
    return;
  }

  let html = '';
  for (let i = 0; i < pageSlice.length; i++) {
    try {
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

      const catStr = String(opp.category_key || state.activeTab || '').toLowerCase();
      const isBm = catStr.includes('bm') || catStr.includes('black_market') || (opp.destination_city && opp.destination_city.toLowerCase() === 'black market');
      const srcCity = opp.buy_city || opp.source_city || opp.craft_city || opp.refine_city || opp.base_city || 'Martlock';
      const dstCity = opp.sell_city || opp.destination_city || (isBm ? 'Black Market' : srcCity);
      const isDangerous = isLethalRoute(opp, srcCity, dstCity);
      const zoneMeta = getRouteZoneMeta(opp, srcCity, dstCity);
      const catMeta = getCategoryMeta(opp.category_key || state.activeTab, opp);

      html += `
        <tr data-key="${oppKey}" data-item-id="${itemId.toUpperCase()}">
          <td>
            <div style="display: flex; align-items: center; gap: 0.6rem;">
              <div class="item-icon-wrap" style="width: 38px; height: 38px; border-radius: 4px;">
                <img class="item-icon-img" src="${getItemIconUrl(itemId, quality, 64)}" width="38" height="38" loading="lazy" decoding="async" onerror="handleIconError(this, '${itemId}', ${quality})" />
              </div>
              <div>
                <div style="font-weight: 700; color: #fff; display: flex; align-items: center; gap: 0.35rem;">
                  <span class="badge-tag badge-tier" style="font-size: 0.62rem;">${tier}${enchantLabel}</span>
                  <span>${opp.item_name || itemId}</span>
                  ${opp.output_qty > 1 ? `<span class="badge-tag" style="font-size: 0.6rem; padding: 1px 4px; background: rgba(234, 179, 8, 0.2); color: #facc15;">${opp.output_qty}x/craft</span>` : ''}
                  ${(opp.has_lpb || (opp.category_key === 'potions' && srcCity === 'Brecilien') || (opp.category_key === 'cooking' && srcCity === 'Caerleon')) ? `<span class="badge-tag" style="font-size: 0.6rem; padding: 1px 4px; background: rgba(56, 189, 248, 0.2); color: #38bdf8;">+15% LPB</span>` : ''}
                </div>
                <div style="font-size: 0.68rem; color: var(--text-muted); display: flex; align-items: center; gap: 0.35rem; margin-top: 2px;">
                  <span>Q${quality}</span>
                  <span id="tbl-fresh-${oppKey}" class="badge-tag ${opp.freshness_tier === 'candidate' ? 'fresh-amber' : 'fresh-green'}" style="font-size: 0.6rem; padding: 1px 4px;">${opp.freshness_tier === 'candidate' ? '🟡 Candidate' : '🟢 Verified'}</span>
                  <span>• ${fmtAge(getEffectiveDataAge(opp))}</span>
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
            <button class="btn-verify-live" style="padding: 0.25rem 0.45rem; font-size: 0.7rem; margin-right: 0.3rem;" id="tbl-verify-btn-${oppKey}" onclick="verifyOpportunityLive('${oppKey}', '${itemId}', '${srcCity}', '${dstCity}', ${m.unitCost}, ${m.unitRevenue}, ${opp.quality || 1}, event)" title="Verify Live Price">⚡ Verify</button>
            <button class="btn-dismiss-sub" style="padding: 0.25rem 0.5rem; font-size: 0.7rem; margin-right: 0.3rem;" onclick="dismissOpportunity('${itemId}', '${opp.category_key || state.activeTab}', event, ${opp.data_age_bm || opp.data_age_sell || 0}, ${opp.bm_buy_price || opp.sell_price || 0}, ${opp.quality || 1})" title="Mark as filled">✓</button>
            <button class="btn-blueprint-action" style="padding: 0.25rem 0.5rem; font-size: 0.7rem;" onclick="openDetailModal(${globalIdx}, '${opp.category_key || state.activeTab}')">Blueprint</button>
          </td>
        </tr>
      `;
    } catch (err) {
      console.error('Error rendering table row index', i, err);
    }
  }

  tbody.innerHTML = html;
}

window.dismissOpportunity = async function(itemId, categoryKey, event, dataAgeBm = 0, bmPrice = 0, quality = 1) {
  if (!itemId || itemId === 'undefined' || itemId === 'null') return;
  const idUpper = itemId.trim().toUpperCase();
  if (!idUpper || idUpper === 'UNDEFINED' || idUpper === 'NULL') return;
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
  state.filterDirty = true;
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

window.verifyOpportunityLive = async function(oppKey, itemId, srcCity, dstCity, expBuy, expSell, quality, event) {
  if (event) event.stopPropagation();
  const btn = (event && event.currentTarget) ? event.currentTarget : document.getElementById(`verify-btn-${oppKey}`);
  const tblBtn = document.getElementById(`tbl-verify-btn-${oppKey}`);
  const originalText = btn ? btn.innerHTML : '⚡ Verify';

  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '⚡ Checking...';
    btn.classList.add('verifying');
  }
  if (tblBtn && tblBtn !== btn) {
    tblBtn.disabled = true;
    tblBtn.innerHTML = '⚡...';
    tblBtn.classList.add('verifying');
  }

  try {
    const params = new URLSearchParams({
      item_id: itemId,
      source_city: srcCity || '',
      destination_city: dstCity || '',
      expected_buy_price: Math.round(expBuy || 0),
      expected_sell_price: Math.round(expSell || 0),
      quality: quality || 1
    });

    const res = await fetch(`/api/v1/system/opportunities/verify?${params.toString()}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    const cardBadge = document.getElementById(`fresh-badge-${oppKey}`);
    const tblBadge = document.getElementById(`tbl-fresh-${oppKey}`);

    if (data.verified && data.status === 'CONFIRMED') {
      const confirmHtml = '✅ Confirmed!';
      if (btn) {
        btn.innerHTML = confirmHtml;
        btn.style.borderColor = 'var(--accent-emerald)';
        btn.style.color = '#86EFAC';
      }
      if (tblBtn) {
        tblBtn.innerHTML = '✅ OK';
        tblBtn.style.borderColor = 'var(--accent-emerald)';
        tblBtn.style.color = '#86EFAC';
      }
      if (cardBadge) {
        cardBadge.className = 'badge-tag badge-freshness fresh-green';
        cardBadge.innerHTML = '<span class="pulse-dot"></span>🟢 Verified Live Just Now';
        cardBadge.title = data.message;
      }
      if (tblBadge) {
        tblBadge.className = 'badge-tag fresh-green';
        tblBadge.textContent = '🟢 Verified Live';
      }
      showToast(data.message || 'Live orderbook verified!', 'success');
    } else if (data.status === 'SPREAD_CLOSED') {
      const closedHtml = '❌ Closed';
      if (btn) {
        btn.innerHTML = closedHtml;
        btn.style.borderColor = 'var(--accent-danger)';
        btn.style.color = '#F87171';
      }
      if (tblBtn) {
        tblBtn.innerHTML = '❌ Closed';
        tblBtn.style.borderColor = 'var(--accent-danger)';
        tblBtn.style.color = '#F87171';
      }
      if (cardBadge) {
        cardBadge.className = 'badge-tag badge-freshness fresh-amber';
        cardBadge.innerHTML = '⚠️ Margin Shifted';
        cardBadge.title = data.message;
      }
      if (tblBadge) {
        tblBadge.className = 'badge-tag fresh-amber';
        tblBadge.textContent = '⚠️ Closed';
      }
      showToast(data.message || 'Live spread has shifted below profitable threshold.', 'warning');
    } else {
      if (btn) btn.innerHTML = 'ℹ️ Checked';
      if (tblBtn) tblBtn.innerHTML = 'ℹ️ Done';
      showToast(data.message || 'Orderbook check finished.', 'info');
    }
  } catch (err) {
    console.error('[AQS] Verify live error:', err);
    if (btn) btn.innerHTML = '⚠️ Error';
    if (tblBtn) tblBtn.innerHTML = '⚠️ Err';
    showToast('Failed to connect to verification service.', 'warning');
  } finally {
    setTimeout(() => {
      if (btn) {
        btn.disabled = false;
        btn.classList.remove('verifying');
      }
      if (tblBtn) {
        tblBtn.disabled = false;
        tblBtn.classList.remove('verifying');
      }
    }, 3500);
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
  const list = (state.filteredList && state.filteredList.length > 0) ? state.filteredList : getFilteredOpportunities();
  const opp = list[globalIdx];
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
    roiEl.textContent = `+${m.batchRoi}% ROI`;
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

    const uProfit = opp._unitProfit !== undefined ? opp._unitProfit : Number(opp.net_profit || opp.profit || opp.estimated_profit || 0);
    if (uProfit <= 0) return false;
    if (minProfit > 0 && uProfit < minProfit) return false;

    const bRoi = opp._baseRoi !== undefined ? opp._baseRoi : 0;
    if (minRoi > 0 && bRoi < minRoi) return false;
    if (highRoiOnly && bRoi < 10.0) return false;

    const uCost = opp._unitCost !== undefined ? opp._unitCost : 0;
    if (maxInvestment > 0 && uCost > maxInvestment) return false;

    const dVol = opp._dailyVol !== undefined ? opp._dailyVol : Number(opp.daily_volume || 0);
    if (minVolume > 0 && dVol < minVolume) return false;
    if (highVolOnly && dVol < 50) return false;

    if (search) {
      const s = search.trim().toLowerCase();
      if (s) {
        const searchPool = opp._searchStr || `${String(opp.item_id || '').toLowerCase()} ${String(opp.item_name || '').toLowerCase()}`;
        if (!searchPool.includes(s)) return false;
      }
    }

    // Category Filter
    if (category && category !== 'all') {
      if (!matchesItemCategory(opp, category)) return false;
    }

    const tNum = opp._tierNum !== undefined ? opp._tierNum : (String(opp.item_id || '').startsWith('T') ? parseInt(String(opp.item_id)[1]) : 4);
    if (tier > 0 && tNum !== tier) return false;
    if (highTierOnly && tNum < 7) return false;

    const ench = opp._enchant !== undefined ? opp._enchant : (String(opp.item_id || '').includes('@') ? String(opp.item_id).split('@')[1] : '0');
    if (enchantment !== 'all' && ench !== enchantment) return false;

    const q = opp.quality || 1;
    if (quality > 0 && q !== parseInt(quality)) return false;

    if (sourceCity) {
      const src = opp._srcCityLower || String(opp.buy_city || opp.source_city || opp.craft_city || opp.refine_city || '').toLowerCase();
      if (!src.includes(sourceCity.toLowerCase())) return false;
    }
    if (destCity) {
      const dst = opp._dstCityLower || String(opp.sell_city || opp.destination_city || '').toLowerCase();
      if (!dst.includes(destCity.toLowerCase())) return false;
    }

    if (state.filters.islandCity) {
      const isl = String(opp._islandCity || opp.island_city || opp.craft_city || '').toLowerCase();
      if (!isl.includes(state.filters.islandCity.toLowerCase())) return false;
    }

    if (safeOnly) {
      const lethal = opp._isLethal !== undefined ? opp._isLethal : isLethalRoute(opp);
      if (lethal) return false;
    }

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
  if (!state.filterDirty && state.filteredList && state.filteredList.length >= 0) {
    return state.filteredList;
  }

  let pool = [];
  const hasSubSectors = Boolean(
    (state.opportunities.potions && state.opportunities.potions.length > 0) ||
    (state.opportunities.cooking && state.opportunities.cooking.length > 0) ||
    (state.opportunities.farming && state.opportunities.farming.length > 0) ||
    (state.opportunities.mounts && state.opportunities.mounts.length > 0)
  );

  if (state.activeTab === 'all') {
    for (const [catKey, list] of Object.entries(state.opportunities)) {
      if (hasSubSectors && catKey === 'island') continue;
      if (Array.isArray(list)) {
        for (let i = 0; i < list.length; i++) {
          pool.push(list[i]);
        }
      }
    }
  } else {
    pool = state.opportunities[state.activeTab] || [];
  }

  const filtered = pool.filter(opp => passesOpportunityFilter(opp));

  // Sorting
  const sortBy = (state.filters && state.filters.sortBy) ? state.filters.sortBy : 'score';
  filtered.sort((a, b) => {
    if (sortBy === 'profit') {
      const pA = a._unitProfit !== undefined ? a._unitProfit : Number(a.net_profit || a.profit || a.estimated_profit || 0);
      const pB = b._unitProfit !== undefined ? b._unitProfit : Number(b.net_profit || b.profit || b.estimated_profit || 0);
      return pB - pA;
    }
    if (sortBy === 'roi') {
      const rA = a._baseRoi !== undefined ? a._baseRoi : Number(a.roi || a.profit_pct || a.estimated_margin || 0);
      const rB = b._baseRoi !== undefined ? b._baseRoi : Number(b.roi || b.profit_pct || b.estimated_margin || 0);
      return rB - rA;
    }
    if (sortBy === 'cost_asc') {
      const cA = a._unitCost !== undefined ? a._unitCost : Number(a.total_cost || a.effective_cost || a.craft_cost || a.buy_price || 0);
      const cB = b._unitCost !== undefined ? b._unitCost : Number(b.total_cost || b.effective_cost || b.craft_cost || b.buy_price || 0);
      return cA - cB;
    }
    if (sortBy === 'cost_desc') {
      const cA = a._unitCost !== undefined ? a._unitCost : Number(a.total_cost || a.effective_cost || a.craft_cost || a.buy_price || 0);
      const cB = b._unitCost !== undefined ? b._unitCost : Number(b.total_cost || b.effective_cost || b.craft_cost || b.buy_price || 0);
      return cB - cA;
    }
    if (sortBy === 'volume') {
      return (Number(b._dailyVol || b.daily_volume || 0)) - (Number(a._dailyVol || a.daily_volume || 0));
    }
    if (sortBy === 'weight_eff') {
      return (Number(b.profit_per_kg) || 0) - (Number(a.profit_per_kg) || 0);
    }
    const sA = a._score !== undefined ? a._score : Number(a.score !== undefined ? a.score : (a.ev_score || 0));
    const sB = b._score !== undefined ? b._score : Number(b.score !== undefined ? b.score : (b.ev_score || 0));
    return sB - sA;
  });

  state.filteredList = filtered;
  state.filterDirty = false;
  return filtered;
}

// ═══════════════════════════════════════════════════════════════
// MODAL RECIPE INSPECTOR
// ═══════════════════════════════════════════════════════════════

window.openDetailModal = function(globalIdx, catKey) {
  const list = (state.filteredList && state.filteredList.length > 0) ? state.filteredList : getFilteredOpportunities();
  const opp = list[globalIdx];
  if (!opp) return;

  const oppKey = `${opp.item_id}_${globalIdx}`;
  const qty = state.volumeOverrides[oppKey] || (opp.safe_limit || 1);
  const m = calculateScaledMetrics(opp, qty);

  const modal = document.getElementById('detail-modal');
  const modalBody = document.getElementById('modal-body');

  const itemId = opp.item_id || opp.target_item_id || 'T4_BAG';
  const tier = itemId.startsWith('T') ? itemId.slice(0, 2) : 'T4';
  const tierNum = itemId.startsWith('T') ? itemId[1] : '4';
  const enchantMatch = itemId.match(/@(\d)/);
  const enchantNum = enchantMatch ? enchantMatch[1] : '0';
  const enchantLabel = enchantNum !== '0' ? `.${enchantNum}` : '';
  const quality = opp.quality || 1;
  const stars = '★'.repeat(quality);
  const qualityNames = ['', 'Normal', 'Good', 'Outstanding', 'Excellent', 'Masterpiece'];
  const iconUrl = getItemIconUrl(itemId, quality);
  const cat = String(opp.category_key || catKey || state.activeTab || '').toLowerCase();
  const catMeta = getCategoryMeta(cat, opp);
  const isBm = cat.includes('bm') || cat.includes('black_market') || (opp.destination_city && opp.destination_city.toLowerCase() === 'black market');
  const srcCity = opp.buy_city || opp.source_city || opp.craft_city || opp.refine_city || opp.base_city || 'Local';
  const dstCity = opp.sell_city || opp.destination_city || (isBm ? 'Black Market' : srcCity);
  const isDangerous = isLethalRoute(opp, srcCity, dstCity);
  const zoneMeta = getRouteZoneMeta(opp, srcCity, dstCity);

  const isFarming = (opp.subsector === 'crops' || opp.subsector === 'herbs' || opp.subsector === 'farming' || opp.category_key === 'farming');
  const isLivestock = (opp.subsector === 'livestock' || opp.category_key === 'livestock');
  const isIslandAgri = (isFarming || isLivestock) && opp.profit_per_plot_day > 0;
  const isCooking = (opp.category_key === 'cooking' || opp.subsector === 'cooking');
  const isPotion = (opp.category_key === 'potions' || opp.subsector === 'potions' || opp.subsector === 'alchemy');
  const isCrafting = (opp.type === 'crafting' || opp.category_key === 'crafting' || opp.category_key === 'bm_crafting');
  const isRefining = (opp.type === 'refining' || opp.category_key === 'refining' || opp.category_key === 'bm_refining');
  const outputQty = Number(opp.output_qty || 1);

  let modalSrcRole = 'ORIGIN / BUY';
  let modalDstRole = isBm ? 'DEST / BLACK MARKET' : 'DEST / SELL';
  if (isLivestock) {
    modalSrcRole = 'ORIGIN / BABY & FEED';
    modalDstRole = 'DEST / PRODUCE & MEAT';
  } else if (isIslandAgri) {
    modalSrcRole = 'ORIGIN / SEEDS & PLOT';
    modalDstRole = 'DEST / HARVESTED CROP';
  } else if (isPotion) {
    modalSrcRole = 'ORIGIN / HERBS & FLUIDS';
    modalDstRole = `DEST / BATCH (${outputQty}x POTIONS)`;
  } else if (isCooking) {
    modalSrcRole = 'ORIGIN / INGREDIENTS';
    modalDstRole = `DEST / BATCH (${outputQty}x MEALS)`;
  } else if (isCrafting) {
    modalSrcRole = `ORIGIN / WORKSHOP (${srcCity})`;
    modalDstRole = isBm ? 'DEST / BLACK MARKET' : 'DEST / MARKET GEAR';
  } else if (isRefining) {
    modalSrcRole = `ORIGIN / REFINERY (${srcCity})`;
    modalDstRole = 'DEST / REFINED RESOURCES';
  }

  // ─── Dynamic Recipe / Blueprint Breakdown for All Categories ───
  let blueprintHtml = '';

  // 1. Enchanting (BM & Royal Enchanting)
  if (cat.includes('enchant') || opp.material_id || opp.base_item_id) {
    const baseId = opp.base_item_id || itemId.split('@')[0];
    const basePrice = Number(opp.base_price || 0);
    const totalBaseCost = basePrice * qty;
    const baseAge = Number(opp.data_age_base || opp.data_age_buy || 0);
    const isBaseStale = baseAge > 1800; // > 30 minutes

    const baseTierMatch = baseId.match(/^T(\d+)/i);
    const baseTierNum = baseTierMatch ? baseTierMatch[1] : '4';
    const baseTier = `T${baseTierNum}`;
    const baseEnchantMatch = baseId.match(/@(\d+)/);
    const baseEnchant = baseEnchantMatch ? baseEnchantMatch[1] : '0';
    const baseEnchantLabel = baseEnchant !== '0' ? `.${baseEnchant}` : '.0';
    const targetTierLabel = `${tier}${enchantLabel}`;

    const materials = (opp.ingredients && opp.ingredients.length > 0) ? opp.ingredients : [{
      item_id: opp.material_id || (itemId.startsWith('T') ? `T${itemId[1]}_SOUL` : 'T4_SOUL'),
      name: opp.material_id ? formatItemName(opp.material_id) : (itemId.startsWith('T') ? `T${itemId[1]} Soul` : 'T4 Soul'),
      qty: Number(opp.material_qty || 96),
      quantity: Number(opp.material_qty || 96),
      unit_price: Number(opp.material_price || 0),
      buy_city: srcCity
    }];

    const materialsHtml = materials.map(mat => {
      const matQty = Number(mat.quantity || mat.qty || 1);
      const matPrice = Number(mat.unit_price || 0);
      const totalMatCost = matPrice * matQty * qty;
      const matId = mat.item_id;
      const matName = mat.name || mat.item_name || formatItemName(matId);
      const matCity = mat.buy_city || srcCity;
      
      return `
        <div style="display: flex; align-items: center; justify-content: space-between; background: var(--bg-surface-1); padding: 0.6rem 0.8rem; border-radius: 6px; border: 1px solid var(--border-subtle);">
          <div style="display: flex; align-items: center; gap: 0.6rem;">
            <img src="${getItemIconUrl(matId, 1, 64)}" style="width: 32px; height: 32px; border-radius: 4px;" loading="lazy" decoding="async" onerror="handleIconError(this, '${matId}', 1)" />
            <div>
              <div style="font-weight: 700; font-size: 0.84rem; color: #fff;">${matName} (Enchanting Material)</div>
              <div style="font-size: 0.7rem; color: var(--text-muted);">Sourced at: <strong>${matCity}</strong> @ ${fmtK(matPrice)} silver/ea (${matQty} per item)</div>
            </div>
          </div>
          <div style="text-align: right;">
            <div style="font-weight: 800; color: var(--accent-gold-bright); font-family: 'JetBrains Mono', monospace; font-size: 0.85rem;">${(matQty * qty).toLocaleString()}x</div>
            <div style="font-size: 0.7rem; color: var(--text-secondary);">${fmtK(totalMatCost)} silver</div>
          </div>
        </div>
      `;
    }).join('');

    const matSummaryText = materials.map(m => `${(Number(m.quantity || m.qty || 1) * qty).toLocaleString()}x ${m.name || formatItemName(m.item_id)}`).join(' + ');

    blueprintHtml = `
      <h4 style="margin-top: 1.25rem; font-size: 0.9rem; color: var(--accent-gold-bright); font-family: 'Outfit', sans-serif;">
        🔮 Artifact Foundry Enchanting: Upgrade ${baseTier}${baseEnchantLabel} ➔ ${targetTierLabel} (${qty}x Batch)
      </h4>

      <!-- Visual Step Pipeline -->
      <div style="margin-top: 0.4rem; margin-bottom: 0.5rem; display: flex; align-items: center; gap: 0.5rem; background: rgba(0, 0, 0, 0.25); padding: 0.45rem 0.75rem; border-radius: 6px; font-size: 0.73rem; border: 1px solid var(--border-subtle); flex-wrap: wrap;">
        <span style="font-weight: 700; color: #94A3B8;">Required Upgrade Flow:</span>
        <span class="badge-tag badge-tier tier-color-t${baseTierNum}">Buy ${baseTier}${baseEnchantLabel} Base Item</span>
        <span style="color: var(--accent-gold);">➔</span>
        <span style="color: var(--accent-cyan); font-weight: 600;">+ ${matSummaryText}</span>
        <span style="color: var(--accent-gold);">➔</span>
        <span class="badge-tag badge-tier tier-color-t${tierNum}">Produces ${targetTierLabel} (${qty}x)</span>
      </div>

      <div style="margin-top: 0.6rem; display: flex; flex-direction: column; gap: 0.4rem;">
        <!-- Base Item -->
        <div style="display: flex; align-items: center; justify-content: space-between; background: var(--bg-surface-1); padding: 0.6rem 0.8rem; border-radius: 6px; border: 1px solid ${isBaseStale ? 'rgba(234, 179, 8, 0.4)' : 'var(--border-subtle)'};">
          <div style="display: flex; align-items: center; gap: 0.6rem;">
            <img src="${getItemIconUrl(baseId, opp.base_quality || quality, 64)}" style="width: 32px; height: 32px; border-radius: 4px;" loading="lazy" decoding="async" onerror="handleIconError(this, '${baseId}', ${opp.base_quality || quality})" />
            <div>
              <div style="font-weight: 700; font-size: 0.84rem; color: #fff; display: flex; align-items: center; gap: 0.4rem; flex-wrap: wrap;">
                <span class="badge-tag badge-tier tier-color-t${baseTierNum}" style="font-size: 0.72rem; padding: 1px 6px;">${baseTier}${baseEnchantLabel}</span>
                <span>${formatItemName(baseId)}</span>
                <span style="font-size: 0.72rem; color: var(--accent-gold-bright); font-weight: 600;">(Base Item — Sourced as ${baseTier}${baseEnchantLabel})</span>
              </div>
              <div style="font-size: 0.7rem; color: var(--text-muted); margin-top: 2px;">
                Sourced at: <strong>${srcCity}</strong> @ ${fmtK(basePrice)} silver &bull; Scanned: <strong style="color: ${isBaseStale ? '#facc15' : '#7ee787'};">${fmtAge(baseAge)}</strong>
              </div>
              ${isBaseStale ? `
                <div style="margin-top: 3px; font-size: 0.68rem; color: #facc15;">
                  ⚠️ Scanned ${fmtAge(baseAge)} ago: Verify <strong>${srcCity}</strong> market stock in-game first to ensure ${baseTier}${baseEnchantLabel} is available at this price!
                </div>
              ` : ''}
            </div>
          </div>
          <div style="text-align: right;">
            <div style="font-weight: 800; color: var(--accent-gold-bright); font-family: 'JetBrains Mono', monospace; font-size: 0.85rem;">${qty.toLocaleString()}x</div>
            <div style="font-size: 0.7rem; color: var(--text-secondary);">${fmtK(totalBaseCost)} silver</div>
          </div>
        </div>

        <!-- Enchanting Materials -->
        ${materialsHtml}
      </div>

      <!-- Fail-Safe Execution Checklist -->
      <div style="margin-top: 0.65rem; background: rgba(234, 179, 8, 0.09); border: 1px solid rgba(234, 179, 8, 0.3); padding: 0.6rem 0.8rem; border-radius: 6px; font-size: 0.73rem; color: #fde047;">
        <div style="font-weight: 700; display: flex; align-items: center; gap: 0.35rem; margin-bottom: 0.3rem;">
          <span>⚡</span>
          <span>FAIL-SAFE EXECUTION CHECKLIST (Follow in this exact order):</span>
        </div>
        <ol style="margin: 0.2rem 0 0 1.2rem; padding: 0; line-height: 1.5; color: #E2E8F0;">
          <li><strong>Check ${isBm ? 'Black Market' : dstCity} Buy Order in-game first:</strong> Confirm target buy order for <strong>${fmtK(m.unitRevenue)} s</strong> (${targetTierLabel}) is active.</li>
          <li><strong>Check ${srcCity} Regular Market Stock:</strong> Verify that the <strong>${baseTier}${baseEnchantLabel}</strong> base item is in stock at <strong>${fmtK(basePrice)} s</strong> <em>BEFORE</em> purchasing any enchanting materials!</li>
          <li><strong>Buy Base Item + Materials:</strong> Once stock at both ends is verified, purchase the ${baseTier}${baseEnchantLabel} base item and ${qty > 1 ? `${qty}x batch of ` : ''}enchanting materials in <strong>${srcCity}</strong>.</li>
          <li><strong>Enchant & Sell:</strong> Walk to the Artifact Foundry in <strong>${srcCity}</strong> (0% loss risk, instant enchant ➔ ${targetTierLabel}), then sell to <strong>${dstCity}</strong> for <strong>+${fmtProfit(m.batchProfit)} s</strong> net profit.</li>
        </ol>
      </div>
    `;
  }
  // 2. Crafting, Refining & Island Farming
  else if (isIslandAgri || (opp.ingredients && opp.ingredients.length > 0)) {
    const isConsumable = !isIslandAgri && (cat.includes('potion') || cat.includes('cooking') || outputQty > 1);
    const hasLpb = opp.has_lpb || (cat.includes('potion') && srcCity === 'Brecilien') || (cat.includes('cooking') && srcCity === 'Caerleon');
    const rrrPct = (Number(opp.rrr_used || (hasLpb ? 0.248 : 0.152)) * 100).toFixed(1);

    blueprintHtml = `
      <h4 style="margin-top: 1.25rem; font-size: 0.9rem; color: var(--accent-gold-bright); font-family: 'Outfit', sans-serif;">
        ${isIslandAgri ? '🌾 Island Production Blueprint (9 Spots / Plot):' : isConsumable ? `🧪 Consumable Crafting Recipe (${qty}x Batch ➔ Produces ${qty * outputQty} Items):` : `⚒️ Required Ingredients & Resources (${qty}x Batch):`}
      </h4>
      ${isConsumable ? `
        <div style="margin-top: 0.4rem; margin-bottom: 0.6rem; display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 0.5rem; font-size: 0.75rem;">
          <div style="background: var(--bg-surface-1); padding: 0.5rem; border-radius: 6px; border: 1px solid var(--border-subtle);">
            <div style="color: var(--text-muted);">Batch Production Yield</div>
            <div style="font-weight: 800; color: #facc15; font-size: 0.9rem;">${outputQty}x per craft (${qty * outputQty}x total)</div>
          </div>
          <div style="background: var(--bg-surface-1); padding: 0.5rem; border-radius: 6px; border: 1px solid var(--border-subtle);">
            <div style="color: var(--text-muted);">Resource Return Rate</div>
            <div style="font-weight: 700; color: #38bdf8;">${rrrPct}% RRR</div>
          </div>
          <div style="background: var(--bg-surface-1); padding: 0.5rem; border-radius: 6px; border: 1px solid var(--border-subtle);">
            <div style="color: var(--text-muted);">City Production Bonus</div>
            <div style="font-weight: 700; color: ${hasLpb ? 'var(--accent-emerald)' : 'var(--text-muted)'};">
              ${hasLpb ? '✨ +15% LPB Active' : 'Base (15.2%)'}
            </div>
          </div>
          <div style="background: var(--bg-surface-1); padding: 0.5rem; border-radius: 6px; border: 1px solid var(--border-subtle);">
            <div style="color: var(--text-muted);">Unit Sell Price</div>
            <div style="font-weight: 800; color: var(--accent-gold-bright);">${fmtK(Math.round(m.unitRevenue / outputQty))} s / ea</div>
          </div>
          <div style="background: var(--bg-surface-1); padding: 0.5rem; border-radius: 6px; border: 1px solid ${opp.manipulation_risk === 'medium' ? 'rgba(227, 179, 65, 0.5)' : opp.manipulation_risk === 'low' ? 'rgba(139, 148, 158, 0.4)' : 'rgba(46, 160, 67, 0.35)'};">
            <div style="color: var(--text-muted);">Market Health</div>
            <div style="font-weight: 700; color: ${opp.manipulation_risk === 'medium' ? '#e3b341' : opp.manipulation_risk === 'low' ? '#8b949e' : '#7ee787'};">
              ${opp.manipulation_risk === 'medium' ? '⚠️ Wide Spread — Verify' : opp.manipulation_risk === 'low' ? '🔍 Low Liquidity' : '✅ Healthy'} (${opp.daily_volume || 0} vol/24h)
            </div>
          </div>
        </div>
      ` : ''}
      ${isIslandAgri ? `
        <div style="margin-top: 0.4rem; margin-bottom: 0.6rem; display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 0.5rem; font-size: 0.75rem;">
          <div style="background: var(--bg-surface-1); padding: 0.5rem; border-radius: 6px; border: 1px solid var(--border-subtle);">
            <div style="color: var(--text-muted);">Plot Profit/Day</div>
            <div style="font-weight: 800; color: var(--accent-emerald); font-size: 0.9rem;">+${fmtK(opp.profit_per_plot_day)} s</div>
          </div>
          <div style="background: var(--bg-surface-1); padding: 0.5rem; border-radius: 6px; border: 1px solid var(--border-subtle);">
            <div style="color: var(--text-muted);">Cycle Duration</div>
            <div style="font-weight: 700; color: #fff;">${opp.cycle_hours || 22} hours</div>
          </div>
          <div style="background: var(--bg-surface-1); padding: 0.5rem; border-radius: 6px; border: 1px solid var(--border-subtle);">
            <div style="color: var(--text-muted);">Biome Specialty</div>
            <div style="font-weight: 700; color: ${opp.biome_bonus_active ? 'var(--accent-emerald)' : 'var(--text-muted)'};">
              ${opp.biome_bonus_active ? '🌿 +10% Active' : 'None (Base)'}
            </div>
          </div>
          ${opp.silver_per_focus > 0 ? `
          <div style="background: var(--bg-surface-1); padding: 0.5rem; border-radius: 6px; border: 1px solid var(--border-subtle);">
            <div style="color: var(--text-muted);">Silver / Focus</div>
            <div style="font-weight: 800; color: #d2a8ff;">💎 ${opp.silver_per_focus} s/f</div>
          </div>` : ''}
        </div>
      ` : ''}
      <div style="margin-top: 0.6rem; display: flex; flex-direction: column; gap: 0.4rem;">
        ${(opp.ingredients || []).map(ing => {
          const ingQty = Number(ing.quantity || ing.qty || 1);
          const ingPrice = Number(ing.unit_price || 0);
          const ingName = ing.name || ing.item_name || formatItemName(ing.item_id);
          const extraInfo = ing.seed_return_pct !== undefined ? ` • Return: ${ing.seed_return_pct}% • Yield/Plot: ${ing.plot_yield || (ing.yield_per_spot ? (ing.yield_per_spot * 9).toFixed(1) : '81')}` : '';
          return `
          <div style="display: flex; align-items: center; justify-content: space-between; background: var(--bg-surface-1); padding: 0.55rem 0.75rem; border-radius: 6px; border: 1px solid var(--border-subtle);">
            <div style="display: flex; align-items: center; gap: 0.55rem;">
              <img src="${getItemIconUrl(ing.item_id, 1, 64)}" style="width: 28px; height: 28px; border-radius: 4px;" loading="lazy" decoding="async" onerror="handleIconError(this, '${ing.item_id}', 1)" />
              <div>
                <div style="font-weight: 700; font-size: 0.82rem; color: #fff;">${ingName}</div>
                <div style="font-size: 0.68rem; color: var(--text-muted);">Buy at: <strong>${ing.buy_city || srcCity}</strong> @ ${fmtK(ingPrice)} s${extraInfo}</div>
              </div>
            </div>
            <div style="text-align: right;">
              <div style="font-weight: 800; color: var(--accent-gold-bright); font-family: 'JetBrains Mono', monospace; font-size: 0.85rem;">${(ingQty * qty).toLocaleString()}x</div>
              <div style="font-size: 0.68rem; color: var(--text-secondary);">${fmtK(ingPrice * ingQty * qty)} silver</div>
            </div>
          </div>
        `;}).join('')}
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

  const modalHeadline = document.getElementById('modal-headline');
  if (modalHeadline) modalHeadline.textContent = `${opp.item_name || itemId} (${tier}${enchantLabel})`;

  const prevScroll = modalBody ? modalBody.scrollTop : 0;

  modalBody.innerHTML = `
    <div class="modal-dossier-grid">
      
      <!-- Full-Width Orderbook Execution Depth & Sizing Controller -->
      <div class="dossier-card" style="grid-column: 1 / -1; display: flex; align-items: center; justify-content: space-between; padding: 0.65rem 1rem; margin-bottom: 0.25rem; background: rgba(0, 0, 0, 0.45); border: 1px solid rgba(245, 158, 11, 0.25); flex-wrap: wrap; gap: 0.75rem;">
        <div style="display: flex; align-items: center; gap: 0.6rem; flex-wrap: wrap;">
          <span style="font-size: 0.72rem; font-weight: 800; color: var(--text-gold); text-transform: uppercase; letter-spacing: 0.05em;">TRADE EXECUTION DEPTH & SIZING:</span>
          <span class="volume-cap-lbl font-mono" style="font-size: 0.74rem;">Orderbook Safe Limit: <strong style="color: var(--accent-gold-bright); font-size: 0.85rem;">${m.safeLimit}x</strong></span>
          ${m.isOverSafeLimit ? `<span style="font-size: 0.7rem; color: #f87171; font-weight: 700; background: rgba(248, 113, 113, 0.15); padding: 1px 6px; border-radius: 4px; border: 1px solid rgba(248, 113, 113, 0.3);">⚠️ Over Depth (~${m.slippagePct}% slippage)</span>` : ''}
        </div>
        <div style="display: flex; align-items: center; gap: 0.45rem; flex-wrap: wrap;">
          <span style="font-size: 0.72rem; color: var(--text-muted);">Depth:</span>
          <div class="volume-stepper" style="border: 1px solid rgba(245, 158, 11, 0.35); background: rgba(0, 0, 0, 0.5);">
            <button class="vol-step-btn" onclick="modalStepVolume(${globalIdx}, '${catKey || ''}', -1)" title="Decrease depth by 1" style="padding: 0.25rem 0.65rem; font-size: 0.95rem; font-weight: 800; color: #fff;">−</button>
            <input type="number" class="vol-input font-mono" value="${qty}" min="1" max="10000" onchange="modalSetVolume(${globalIdx}, '${catKey || ''}', this.value)" style="width: 52px; font-size: 0.88rem; color: #facc15; font-weight: 800; text-align: center;" />
            <button class="vol-step-btn" onclick="modalStepVolume(${globalIdx}, '${catKey || ''}', 1)" title="Increase depth by 1" style="padding: 0.25rem 0.65rem; font-size: 0.95rem; font-weight: 800; color: #fff;">+</button>
          </div>
          <button class="vol-step-btn ${qty === 1 ? 'active' : ''}" style="border: 1px solid rgba(255,255,255,0.12); border-radius: 4px; padding: 0.28rem 0.65rem; font-size: 0.76rem;" onclick="modalSetVolume(${globalIdx}, '${catKey || ''}', 1)">1x</button>
          <button class="vol-step-btn ${qty === 5 ? 'active' : ''}" style="border: 1px solid rgba(255,255,255,0.12); border-radius: 4px; padding: 0.28rem 0.65rem; font-size: 0.76rem;" onclick="modalSetVolume(${globalIdx}, '${catKey || ''}', 5)">5x</button>
          <button class="vol-step-btn ${qty === 10 ? 'active' : ''}" style="border: 1px solid rgba(255,255,255,0.12); border-radius: 4px; padding: 0.28rem 0.65rem; font-size: 0.76rem;" onclick="modalSetVolume(${globalIdx}, '${catKey || ''}', 10)">10x</button>
          <button class="vol-step-btn ${qty === m.safeLimit ? 'active' : ''}" style="border: 1px solid rgba(245,158,11,0.3); border-radius: 4px; padding: 0.28rem 0.7rem; font-size: 0.76rem; color: var(--accent-gold-bright);" onclick="modalSetVolume(${globalIdx}, '${catKey || ''}', ${m.safeLimit})" title="Max safe orderbook depth">Max (${m.safeLimit}x)</button>
        </div>
      </div>

      <!-- Left Column: Trade Corridor & Financial Summary -->
      <div class="modal-col-summary">
        
        <!-- Item Overview Hero -->
        <div class="dossier-card" style="display: flex; align-items: center; gap: 0.9rem;">
          <div class="item-icon-wrap tier-border-t${tierNum}" style="width: 64px; height: 64px;">
            <img class="item-icon-img" src="${iconUrl}" alt="${opp.item_name || itemId}" loading="lazy" decoding="async" onerror="handleIconError(this, '${itemId}', ${quality})" />
            ${quality > 1 ? `<div class="item-quality-pill quality-q${quality}">${qualityNames[quality]}</div>` : ''}
          </div>
          <div>
            <div style="font-size: 1.05rem; font-weight: 800; color: #fff; font-family: 'Inter', sans-serif;">${opp.item_name || itemId}</div>
            <div style="display: flex; align-items: center; gap: 0.35rem; margin-top: 4px; flex-wrap: wrap;">
              <span class="badge-tag badge-tier tier-color-t${tierNum}">${tier}${enchantLabel}</span>
              <span class="badge-tag badge-category" style="color: ${catMeta.color}; background: ${catMeta.bg}; border-color: ${catMeta.color}40;">${catMeta.label}</span>
              <span class="badge-tag ${zoneMeta.badgeClass}">${zoneMeta.label}</span>
            </div>
          </div>
        </div>

        <!-- Trade Corridor Route Card -->
        <div class="dossier-card">
          <div class="dossier-card-title">TRADE ROUTE CORRIDOR</div>
          <div style="display: flex; align-items: center; justify-content: space-between; gap: 0.6rem; background: rgba(0,0,0,0.35); padding: 0.8rem; border-radius: 8px; border: 1px solid rgba(255,255,255,0.06);">
            <div>
              <span style="font-size: 0.62rem; color: var(--text-gold); font-weight: 700; text-transform: uppercase;">${modalSrcRole}</span>
              <div style="font-size: 0.96rem; font-weight: 800; color: ${CITY_COLORS[srcCity] || '#fff'};">${srcCity}</div>
              <div class="font-mono" style="font-size: 0.76rem; color: #94A3B8;">${fmtK(m.unitCost)} s</div>
            </div>
            <div style="text-align: center;">
              <span style="font-size: 1.2rem; color: var(--accent-gold);">➔</span>
              <div style="margin-top: 2px;"><span class="route-lane-zone-tag">${zoneMeta.type}</span></div>
            </div>
            <div style="text-align: right;">
              <span style="font-size: 0.62rem; color: var(--text-gold); font-weight: 700; text-transform: uppercase;">${modalDstRole}</span>
              <div style="font-size: 0.96rem; font-weight: 800; color: ${CITY_COLORS[dstCity] || '#ffd700'};">${dstCity}</div>
              <div class="font-mono" style="font-size: 0.76rem; color: var(--accent-gold-bright);">${fmtK(m.unitRevenue)} s</div>
            </div>
          </div>
          <div style="margin-top: 0.6rem; display: flex; align-items: center; justify-content: space-between; font-size: 0.72rem; color: var(--text-muted);">
            <span>Data Freshness: <strong>${fmtAge(getEffectiveDataAge(opp))}</strong></span>
            <span>24h Vol: <strong>${m.dailyVol} units</strong></span>
          </div>
        </div>

        <!-- Financial Summary Card (Financial Metrics & Math) -->
        <div class="dossier-card">
          <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.6rem; flex-wrap: wrap; gap: 0.4rem;">
            <div class="dossier-card-title" style="margin-bottom: 0;">FINANCIAL METRICS & YIELD</div>
            <div style="display: flex; align-items: center; gap: 0.35rem;">
              <span class="volume-cap-lbl font-mono" style="font-size: 0.68rem; color: var(--text-muted);">Depth:</span>
              <div class="volume-stepper" style="border: 1px solid rgba(245, 158, 11, 0.35); background: rgba(0, 0, 0, 0.4);">
                <button class="vol-step-btn" onclick="modalStepVolume(${globalIdx}, '${catKey || ''}', -1)" title="Decrease execution depth" style="font-weight: 800; padding: 0.2rem 0.55rem; font-size: 0.85rem; color: #fff;">−</button>
                <input type="number" class="vol-input font-mono" value="${qty}" min="1" max="10000" onchange="modalSetVolume(${globalIdx}, '${catKey || ''}', this.value)" style="width: 44px; color: #facc15; font-weight: 700; text-align: center;" />
                <button class="vol-step-btn" onclick="modalStepVolume(${globalIdx}, '${catKey || ''}', 1)" title="Increase execution depth" style="font-weight: 800; padding: 0.2rem 0.55rem; font-size: 0.85rem; color: #fff;">+</button>
                <button class="vol-step-btn ${qty === m.safeLimit ? 'active' : ''}" onclick="modalSetVolume(${globalIdx}, '${catKey || ''}', ${m.safeLimit})" title="Size to top safe depth" style="padding: 0.2rem 0.5rem; font-size: 0.72rem; color: var(--accent-gold-bright); border-left: 1px solid rgba(255,255,255,0.1);">Max</button>
              </div>
            </div>
          </div>
          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem;">
            <div>
              <div style="font-size: 0.64rem; color: var(--text-muted); text-transform: uppercase; font-weight: 700;">Batch Net Profit (${qty}x${(opp.output_qty && opp.output_qty > 1) ? ` Batch / ${qty * opp.output_qty}x Items` : ''})</div>
              <div class="font-mono" style="font-size: 1.25rem; font-weight: 800; color: ${m.batchProfit >= 0 ? 'var(--accent-emerald)' : 'var(--accent-danger)'};">${fmtProfit(m.batchProfit)} s</div>
            </div>
            <div>
              <div style="font-size: 0.64rem; color: var(--text-muted); text-transform: uppercase; font-weight: 700;">Batch ROI Margin</div>
              <div class="font-mono" style="font-size: 1.25rem; font-weight: 800; color: #fff;">+${m.batchRoi}%</div>
            </div>
            <div>
              <div style="font-size: 0.64rem; color: var(--text-muted); text-transform: uppercase; font-weight: 700;">Required Silver Cost</div>
              <div class="font-mono" style="font-size: 0.95rem; font-weight: 700; color: var(--accent-gold-bright);">${fmtK(m.batchCost)} s</div>
            </div>
            <div>
              <div style="font-size: 0.64rem; color: var(--text-muted); text-transform: uppercase; font-weight: 700;">Batch Revenue (After Tax)</div>
              <div class="font-mono" style="font-size: 0.95rem; font-weight: 700; color: var(--accent-emerald);">${fmtK(m.batchRevenueNet)} s</div>
            </div>
            <div>
              <div style="font-size: 0.64rem; color: var(--text-muted); text-transform: uppercase; font-weight: 700;">Batch Cargo Weight</div>
              <div class="font-mono" style="font-size: 0.95rem; font-weight: 700; color: #E2E8F0;">${m.batchWeight} kg</div>
            </div>
          </div>
          ${m.isOverSafeLimit ? `
            <div class="card-slippage-alert font-mono" style="margin-top: 0.65rem;">
              <span>⚠️</span>
              <span>Batch exceeds safe depth (${m.safeLimit}x). Estimated slippage: ~${m.slippagePct}%</span>
            </div>
          ` : ''}
        </div>

      </div>

      <!-- Right Column: Sourcing Recipe & Execution Math (Blueprint Section) -->
      <div class="modal-col-math">
        
        <div class="dossier-card">
          <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.6rem; flex-wrap: wrap; gap: 0.4rem;">
            <div class="dossier-card-title" style="margin-bottom: 0;">EXECUTION BLUEPRINT & SOURCING</div>
            <div style="display: flex; align-items: center; gap: 0.35rem;">
              <span class="volume-cap-lbl font-mono" style="font-size: 0.68rem; color: var(--text-muted);">Depth:</span>
              <div class="volume-stepper" style="border: 1px solid rgba(245, 158, 11, 0.35); background: rgba(0, 0, 0, 0.4);">
                <button class="vol-step-btn" onclick="modalStepVolume(${globalIdx}, '${catKey || ''}', -1)" title="Decrease blueprint batch depth" style="font-weight: 800; padding: 0.2rem 0.55rem; font-size: 0.85rem; color: #fff;">−</button>
                <input type="number" class="vol-input font-mono" value="${qty}" min="1" max="10000" onchange="modalSetVolume(${globalIdx}, '${catKey || ''}', this.value)" style="width: 44px; color: #facc15; font-weight: 700; text-align: center;" />
                <button class="vol-step-btn" onclick="modalStepVolume(${globalIdx}, '${catKey || ''}', 1)" title="Increase blueprint batch depth" style="font-weight: 800; padding: 0.2rem 0.55rem; font-size: 0.85rem; color: #fff;">+</button>
                <button class="vol-step-btn ${qty === m.safeLimit ? 'active' : ''}" onclick="modalSetVolume(${globalIdx}, '${catKey || ''}', ${m.safeLimit})" title="Size to top safe depth" style="padding: 0.2rem 0.5rem; font-size: 0.72rem; color: var(--accent-gold-bright); border-left: 1px solid rgba(255,255,255,0.1);">Max</button>
              </div>
            </div>
          </div>
          ${blueprintHtml}
        </div>

        <div style="display: flex; align-items: center; justify-content: space-between; gap: 0.75rem; margin-top: auto; padding-top: 0.5rem;">
          <a href="https://albiononline2d.com/en/item/id/${itemId}" target="_blank" class="tag-btn" style="text-decoration: none; padding: 0.45rem 0.9rem; font-size: 0.78rem;">🌐 View on Albion2D</a>
          <button class="btn-scan-primary" style="padding: 0.45rem 1.25rem; font-size: 0.78rem;" onclick="closeDetailModal()">Close Blueprint</button>
        </div>

      </div>

    </div>
  `;

  if (modalBody && prevScroll > 0) {
    modalBody.scrollTop = prevScroll;
  }

  modal.classList.add('open');
};

window.modalStepVolume = function(globalIdx, catKey, delta) {
  const list = (state.filteredList && state.filteredList.length > 0) ? state.filteredList : getFilteredOpportunities();
  const opp = list[globalIdx];
  if (!opp) return;
  const oppKey = `${opp.item_id}_${globalIdx}`;
  const current = state.volumeOverrides[oppKey] !== undefined ? state.volumeOverrides[oppKey] : (opp.safe_limit || 1);
  const next = Math.max(1, current + delta);
  state.volumeOverrides[oppKey] = next;
  updateCardMetricsInPlace(oppKey, next);
  openDetailModal(globalIdx, catKey);
};

window.modalSetVolume = function(globalIdx, catKey, val) {
  const list = (state.filteredList && state.filteredList.length > 0) ? state.filteredList : getFilteredOpportunities();
  const opp = list[globalIdx];
  if (!opp) return;
  const oppKey = `${opp.item_id}_${globalIdx}`;
  const next = Math.max(1, parseInt(val) || 1);
  state.volumeOverrides[oppKey] = next;
  updateCardMetricsInPlace(oppKey, next);
  openDetailModal(globalIdx, catKey);
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
      state.filterDirty = true;
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
      state.filterDirty = true;
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
        state.filterDirty = true;
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
      state.filterDirty = true;
      state.currentPage = 1;
      renderViews();
    }, 60);

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
      state.filterDirty = true;
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
      state.filterDirty = true;
      state.currentPage = 1;
      renderViews();
    });
  }

  const enchFilter = document.getElementById('enchant-filter');
  if (enchFilter) {
    enchFilter.addEventListener('change', (e) => {
      state.filters.enchantment = e.target.value;
      state.filterDirty = true;
      state.currentPage = 1;
      renderViews();
    });
  }

  const srcCityFilter = document.getElementById('source-city-filter');
  if (srcCityFilter) {
    srcCityFilter.addEventListener('change', (e) => {
      state.filters.sourceCity = e.target.value;
      state.filterDirty = true;
      state.currentPage = 1;
      renderViews();
    });
  }

  const dstCityFilter = document.getElementById('dest-city-filter');
  if (dstCityFilter) {
    dstCityFilter.addEventListener('change', (e) => {
      state.filters.destCity = e.target.value;
      state.filterDirty = true;
      state.currentPage = 1;
      renderViews();
    });
  }

  const islandCityFilter = document.getElementById('island-city-filter');
  if (islandCityFilter) {
    islandCityFilter.addEventListener('change', (e) => {
      state.filters.islandCity = e.target.value;
      state.filterDirty = true;
      state.currentPage = 1;
      renderViews();
    });
  }

  const maxCostFilter = document.getElementById('max-cost-filter');
  if (maxCostFilter) {
    maxCostFilter.addEventListener('change', (e) => {
      state.filters.maxInvestment = parseInt(e.target.value) || 0;
      state.filterDirty = true;
      state.currentPage = 1;
      renderViews();
    });
  }

  const minProfitFilter = document.getElementById('min-profit-filter');
  if (minProfitFilter) {
    minProfitFilter.addEventListener('change', (e) => {
      state.filters.minProfit = parseInt(e.target.value) || 0;
      state.filterDirty = true;
      state.currentPage = 1;
      renderViews();
    });
  }

  const minRoiFilter = document.getElementById('min-roi-filter');
  if (minRoiFilter) {
    minRoiFilter.addEventListener('change', (e) => {
      state.filters.minRoi = parseFloat(e.target.value) || 0;
      state.filterDirty = true;
      state.currentPage = 1;
      renderViews();
    });
  }

  const minVolFilter = document.getElementById('min-vol-filter');
  if (minVolFilter) {
    minVolFilter.addEventListener('change', (e) => {
      state.filters.minVolume = parseInt(e.target.value) || 0;
      state.filterDirty = true;
      state.currentPage = 1;
      renderViews();
    });
  }

  const sortSelect = document.getElementById('sort-by-select');
  if (sortSelect) {
    sortSelect.addEventListener('change', (e) => {
      state.filters.sortBy = e.target.value;
      state.filterDirty = true;
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

  // Privacy Mode Toggle Switch
  const privacyToggle = document.getElementById('privacy-mode-toggle');
  if (privacyToggle) {
    privacyToggle.addEventListener('change', (e) => {
      togglePrivacyMode(e.target.checked);
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

  // Initial Load (Parallel non-blocking fetch)
  Promise.allSettled([
    fetchSettings(),
    fetchStats(),
    fetchOpportunities(),
  ]);

  // Periodic Refresh (every 45s, silent non-destructive poll)
  setInterval(() => {
    fetchStats();
    fetchOpportunities(true);
  }, 45000);
});
