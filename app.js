/* ===== NIFTY Trading Dashboard — Frontend Logic ===== */

// Global Safe Polling Helper for EDGE/Slow Networks
function startSafePolling(fn, intervalMs) {
  async function loop() {
    try { await fn(); } catch (e) { console.warn("SafePolling error:", e); }
    setTimeout(loop, intervalMs);
  }
  setTimeout(loop, intervalMs);
}

// Global fetch override with 15s timeout for slow networks
const originalFetch = window.fetch;
window.fetch = function() {
    let args = Array.prototype.slice.call(arguments);
    return new Promise((resolve, reject) => {
        const abortController = new AbortController();
        const id = setTimeout(() => abortController.abort(), 15000);
        
        if (args[1]) {
            args[1].signal = abortController.signal;
        } else {
            args[1] = { signal: abortController.signal };
        }
        
        originalFetch.apply(window, args)
            .then(res => { clearTimeout(id); resolve(res); })
            .catch(err => { clearTimeout(id); reject(err); });
    });
};


// IST offset: +5:30 = 19800 seconds
const IST_OFFSET = 19800;

// State
let chart5m = null;
let series5m = null;
let analysisData = null;
let refreshInterval = null;
let markers1h = [], markers5m = [];
let obZoneSeries = [];  // OB rectangle zone series
let fvgZoneSeries = []; // FVG rectangle zone series
let lastCandleTime5m = 0; // Track latest 5m candle time for zone extension

// Live spot price lines
let liveSpotLine1h = null;
let liveSpotLine5m = null;

// Active trade lines
let activeEntryLine = null;
let activeSLLine = null;
let activeTargetLine = null;
let lastKnownActiveTrades = [];

// ===== INITIALIZATION =====
let wsConnection = null;
let analysisInterval = null;

// Theme state
let isLightMode = localStorage.getItem('theme') === 'light';

function toggleTheme() {
  isLightMode = !isLightMode;
  localStorage.setItem('theme', isLightMode ? 'light' : 'dark');
  applyTheme();
}

function applyTheme() {
  const btn = document.getElementById('themeToggleBtn');
  if (isLightMode) {
    document.body.classList.add('light-theme');
    if (btn) btn.textContent = '🌙';
  } else {
    document.body.classList.remove('light-theme');
    if (btn) btn.textContent = '☀️';
  }

  // Update chart theme if it exists
  if (chart5m) {
    chart5m.applyOptions({
      layout: {
        background: { type: 'solid', color: isLightMode ? '#ffffff' : '#0a0e1a' },
        textColor: isLightMode ? '#0f172a' : '#e2e8f0',
      },
      grid: {
        vertLines: { color: isLightMode ? '#f1f5f9' : '#141b2d' },
        horzLines: { color: isLightMode ? '#f1f5f9' : '#141b2d' },
      },
      rightPriceScale: { borderColor: isLightMode ? '#cbd5e1' : '#2a3144' },
      timeScale: { borderColor: isLightMode ? '#cbd5e1' : '#2a3144' },
    });
  }
}
let activeSymbol = "NSE:NIFTY50-INDEX";

// Dynamic state for Risk Sizer & Lockout
let dailyCapReached = false;
let isRegimeLockout = false;
let selectedStrikeSymbol = null;
let selectedStrikePremium = 0;
let currentAvailableMargin = 0;
let activeScripts = [];
let lastMarketData = {};
let currentUserIsAdmin = false;
let currentUsername = "Guest";

async function selectScript(symbol) {
  activeSymbol = symbol;
  showToast(`Switching chart to ${symbol.replace('NSE:','')}`, 'info');
  
  // Highlight the row in UI
  renderScriptsList();
  
  // Update header immediately
  const spotData = lastMarketData[symbol];
  if (spotData) {
      updateSpotLive({
          symbol: symbol,
          spot: spotData.lp,
          change: spotData.change,
          change_pct: spotData.change_pct,
          vix: lastMarketData.vix?.lp || 0,
          vix_change: lastMarketData.vix?.change || 0
      });
  }

  // Refresh data
  await fetchAnalysis();
  await fetchCandles();
  updateActiveTradeLines();
}

async function fetchScripts() {
  try {
    const res = await fetch('/api/scripts');
    const data = await res.json();
    activeScripts = data.scripts || [];
    enabledScripts = data.enabled || [];
    renderScriptsList();
  } catch (e) {
    console.error("Failed to fetch scripts:", e);
  }
}

function renderScriptsList(liveData = null) {
  const container = document.getElementById('scriptList');
  if (!container) return;
  
  if (liveData) lastMarketData = liveData;
  const dataMap = lastMarketData || {};
  
  if (!activeScripts || activeScripts.length === 0) {
    container.innerHTML = '<tr><td colspan="4" style="padding:20px; text-align:center; color:var(--text-muted);">No active scripts.</td></tr>';
    return;
  }
  
  container.innerHTML = activeScripts.map(s => {
    const d = dataMap[s] || {};
    const lp = d.lp || 0;
    const ch = d.change || 0;
    const chp = d.change_pct || 0;
    const isUp = chp >= 0;
    const color = isUp ? 'var(--green)' : 'var(--red)';
    const sign = isUp ? '+' : '';
    const isSelected = s === activeSymbol;
    const displayName = s.replace('NSE:', '').replace('-INDEX', '').replace('-EQ', '');
    const isEnabled = enabledScripts.includes(s);
    
    return `
      <tr style="cursor:pointer; ${isSelected ? 'background:rgba(255,255,255,0.04)' : ''}" onclick="selectScript('${s}')">
        <td onclick="event.stopPropagation()">
          <input type="checkbox" ${isEnabled ? 'checked' : ''} onchange="toggleScriptAutoTrade('${s}', this.checked)" title="Enable Auto-Trade">
        </td>
        <td style="color:${isSelected ? 'var(--cyan)' : 'inherit'}">${displayName}</td>
        <td style="color:${color}">${lp > 0 ? lp.toFixed(2) : '--'}</td>
        <td style="color:${color}">${lp > 0 ? sign + ch.toFixed(2) : '--'}</td>
        <td style="color:${color}">${lp > 0 ? sign + chp.toFixed(2) + '%' : '--'}</td>
        <td style="text-align:right" onclick="event.stopPropagation()"><span onclick="removeScript('${s}')" style="cursor:pointer; opacity:0.5">×</span></td>
      </tr>
    `;
  }).join('');
  
  // Also update symbol tabs
  renderSymbolTabs();
}

async function addScript() {
  const input = document.getElementById('newScript');
  const symbol = input.value.trim().toUpperCase();
  if (!symbol) return;
  
  showToast(`Adding ${symbol}...`, 'info');
  try {
    const res = await fetch('/api/scripts/add', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol })
    });
    const data = await res.json();
    if (data.success) {
      activeScripts = data.scripts || [];
      renderScriptsList();
      input.value = '';
      showToast('Scrip added', 'success');
    } else {
      showToast('Failed to add: ' + data.message, 'error');
    }
  } catch (e) {
    showToast('Error adding scrip', 'error');
    renderScriptsList();
    renderSymbolTabs();
  }
}

async function toggleScriptAutoTrade(symbol, enabled) {
  try {
    const res = await fetch('/api/scripts/toggle-auto-trade', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol, enabled })
    });
    const data = await res.json();
    if (data.success) {
      enabledScripts = data.enabled || [];
      showToast(`${enabled ? 'Enabled' : 'Disabled'} auto-trade for ${symbol}`, 'success');
    }
  } catch (e) {
    console.error("Failed to toggle script:", e);
    showToast("Failed to toggle auto-trade", "error");
  }
}

async function removeScript(symbol) {
  if (!confirm(`Remove ${symbol}?`)) return;
  
  showToast(`Removing ${symbol}...`, 'info');
  try {
    const res = await fetch('/api/scripts/remove', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol })
    });
    const data = await res.json();
    if (data.success) {
      activeScripts = data.scripts || [];
      renderScriptsList();
      showToast('Scrip removed', 'success');
    }
  } catch (e) {
    showToast('Error removing scrip', 'error');
  }
}

// Initialization
document.addEventListener('DOMContentLoaded', async () => {
  // 1. Immediate WebSocket connect
  connectWebSocket();

  // 2. Load UI and Data
  try { applyTheme(); } catch(e) { console.error('Error applying theme:', e); }
  try { loadVisibilityPrefs(); } catch(e) { console.error('Error loading visibility preferences:', e); }
  try { fetchScripts(); } catch(e) { console.error('Error fetching scripts:', e); }
  try { fetchSignalHistory(); } catch(e) { console.error('Error fetching signal history:', e); }
  try { initCharts(); } catch(e) { console.error('Error initializing charts:', e); }
  try { loadJournalEntries(); } catch(e) { console.error('Error loading journal entries:', e); }
  
  try {
    const res = await fetch('/api/user-config');
    if (res.ok) {
        const config = await res.json();
        if (config.theme) document.body.setAttribute('data-theme', config.theme);
    }
  } catch(e) {}

  try {
    await fetchAnalysis();
  } catch (e) {
    console.error('Initial data fetch failed:', e);
    showToast('Dashboard starting with partial data...', 'info');
  }

  // 3. Poll Fyers Status
  startSafePolling(async () => {
    try {
      const res = await fetch('/api/fyers/status');
      if (res.ok) {
        const data = await res.json();
        const footerConn = document.getElementById('footerConn');
        if (footerConn) {
          if (data.connected && data.ws_connected) {
            footerConn.textContent = 'Fyers: Connected';
            footerConn.style.color = 'var(--green)';
          } else if (data.connected && !data.ws_connected) {
            footerConn.textContent = 'Fyers: WS Down';
            footerConn.style.color = 'var(--yellow)';
          } else {
            footerConn.textContent = 'Fyers: Auth Expired';
            footerConn.style.color = 'var(--red)';
          }
        }
      }
    } catch (e) {}
  }, 5000);

  // Always fetch candles separately to guarantee chart data even if analysis fails (e.g. 429)
  try {
    await fetchCandles();
  } catch (e) {
    console.error('Initial candle fetch failed:', e);
  }
  
  // Refresh analysis every 45 seconds (includes candle data)
  startSafePolling(async () => {
    try {
      await fetchAnalysis();
    } catch (e) {
      console.error('Interval refresh failed:', e);
    }
    // Always refresh candles independently of analysis
    try {
      await fetchCandles();
    } catch (e) {}
  }, 45000);

  // Start core loops
  checkAuthStatus(); // Immediate badge render on page load
  await fetchAutomationStatus(); // Must complete BEFORE fetchFunds so trade count is in DOM
  startSafePolling(fetchAutomationStatus, 15000); // Fast update for automation stats

  fetchSignalHistory();
  startSafePolling(fetchSignalHistory, 20000);

  fetchFunds();
  startSafePolling(fetchFunds, 60000);

  fetchMarketSummary();
  startSafePolling(fetchMarketSummary, 300000); // 5 mins

  fetchMarketNews();
  startSafePolling(fetchMarketNews, 300000); // 5 mins — refresh headlines

  // Fetch version info
  fetchVersion();
  
  // Initial onboarding check
  if (typeof updateOnboardingWizard === 'function') {
    updateOnboardingWizard();
  }

  // --- IDLE TIMER AUTO-LOCK (15 Minutes) ---
  let idleTime = 0;
  const idleTimeout = 15 * 60; // 15 minutes in seconds

  function resetIdleTime() {
    idleTime = 0;
  }

  const idleInterval = setInterval(() => {
    idleTime++;
    if (idleTime >= idleTimeout) {
      clearInterval(idleInterval);
      window.location.href = '/logout?reason=idle';
    }
  }, 1000);

  const activityEvents = ['mousemove', 'mousedown', 'keypress', 'scroll', 'touchstart'];
  activityEvents.forEach(evt => {
    document.addEventListener(evt, resetIdleTime, { passive: true });
  });
});

async function fetchAutomationStatus() {
  try {
    const resp = await fetch('/api/automation');
    const data = await resp.json();
    
    document.getElementById('autoToggle').checked = data.enabled;
    const autoTrades = document.getElementById('autoTrades');
    if (autoTrades) autoTrades.textContent = `${data.trades_today}/${data.max_trades} Trades`;
    window._automationStatsLoaded = true; // Mark that we have real automation data
    
    const isCapReached = data.trades_today >= data.max_trades;
    window.dailyCapReached = isCapReached;
    const tradeStats = document.querySelector('.trade-stats');
    if (tradeStats) {
      if (isCapReached) {
        tradeStats.classList.add('cooldown-active');
      } else {
        tradeStats.classList.remove('cooldown-active');
      }
    }
    
    // PnL is updated ONLY via WebSocket (positions → total_pnl) to prevent flickering.
    // Do NOT update autoPnl here — the REST endpoint may return stale state.pnl_today.
    
    // Update auto status text
    const statusText = document.getElementById('autoStatusText');
    if (statusText) {
      statusText.style.color = data.enabled ? 'var(--accent-blue)' : 'var(--text-muted)';
      statusText.textContent = data.enabled ? 'AUTO ACTIVE' : 'AUTO OFF';
    }

    // Update Regime Badge
    const regimeBadge = document.getElementById('aiRegimeBadge');
    if (regimeBadge && data.market_regime) {
      regimeBadge.style.display = 'inline-block';
      regimeBadge.textContent = '🧠 Regime: ' + data.market_regime;
      regimeBadge.title = data.regime_reason || '';
      if (data.market_regime.includes('TREND')) {
        regimeBadge.style.color = 'var(--success)';
      } else if (data.market_regime.includes('CHOPPY')) {
        regimeBadge.style.color = 'var(--warning)';
      } else {
        regimeBadge.style.color = 'var(--text-primary)';
      }
    }
  } catch (e) {}
}

async function toggleAutomation() {
  const enabled = document.getElementById('autoToggle').checked;
  try {
    const resp = await fetch('/api/automation/toggle', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled })
    });
    const data = await resp.json();
    if (data.success) {
      showToast(`Automation ${enabled ? 'ENABLED' : 'DISABLED'}`, enabled ? 'success' : 'info');
      const statusText = document.getElementById('autoStatusText');
      if (statusText) {
        statusText.style.color = enabled ? 'var(--accent-blue)' : 'var(--text-muted)';
        statusText.textContent = enabled ? 'AUTO ACTIVE' : 'AUTO OFF';
      }
      if (typeof updateOnboardingWizard === 'function') {
        updateOnboardingWizard();
      }
    } else {
      showToast(data.message || 'Failed to toggle automation', 'error');
      document.getElementById('autoToggle').checked = !enabled; // Revert
      
      if (enabled && data.message && data.message.toLowerCase().includes("not active")) {
        if (confirm("Your Fyers account is not active. Would you like to log in to Fyers now to activate auto-trading?")) {
          // Open settings drawer if not already open
          const drawer = document.getElementById('sidebarNav') || document.getElementById('drawer');
          if (drawer && !drawer.classList.contains('open')) {
            toggleDrawer();
          }
          // Click Connect Fyers button if it exists, otherwise fall back to triggerLogin
          setTimeout(() => {
            const connectBtn = document.getElementById('fyersConnectBtn');
            if (connectBtn && connectBtn.style.display !== 'none') {
              connectBtn.click();
            } else {
              triggerLogin();
            }
          }, 300);
        }
      }
    }
  } catch (e) {
    console.error('Error toggling automation:', e);
    showToast('Network error toggling automation', 'error');
    document.getElementById('autoToggle').checked = !enabled; // Revert
  }
}

async function resetTradeCount() {
  if (!confirm('Reset daily trade count and P&L to 0? This will allow new trades.')) return;
  try {
    const resp = await fetch('/api/automation/reset', { method: 'POST' });
    const data = await resp.json();
    if (data.success) {
      showToast('✅ Trade counters reset to 0. Ready to trade!', 'success');
      // Immediately refresh the automation status
      fetchAutomationStatus();
    } else {
      showToast('Reset failed: ' + (data.message || 'Unknown error'), 'error');
    }
  } catch (e) {
    showToast('Reset failed: ' + e.message, 'error');
  }
}

async function restartServer() {
  if (!confirm('⚠️ Are you sure you want to restart the server? All active connections will be temporarily disconnected.')) return;
  try {
    const res = await fetch('/api/admin/restart-server', { method: 'POST' });
    const data = await res.json();
    if (data.success) {
      showToast('🔄 Server restarting... Page will reload in 10 seconds.', 'info');
      setTimeout(() => location.reload(), 10000);
    } else {
      showToast('❌ ' + (data.message || 'Restart failed'), 'error');
    }
  } catch(e) {
    showToast('❌ Failed to connect: ' + e.message, 'error');
  }
}

async function fetchTradingConfig() {
  try {
    const resp = await fetch('/api/trading-config');
    const data = await resp.json();
    const fields = {
      cfgMaxTrades: data.max_trades_per_day,
      cfgMaxLossTrades: data.max_loss_trades_per_day,
      cfgMaxLoss: data.max_daily_loss,
      cfgProfitTarget: data.daily_profit_target,
      cfgLots: data.trade_lots,
      cfgStockLots: data.stock_lots,
      cfgWebhookUrl: data.webhook_url
    };
    for (const [id, val] of Object.entries(fields)) {
      const el = document.getElementById(id);
      if (el && val !== undefined) el.value = val;
    }
    const ptEl = document.getElementById('cfgPaperTrading');
    if (ptEl && data.paper_trading !== undefined) ptEl.checked = data.paper_trading;
    
    const oracleEl = document.getElementById('cfgUseAIOracle');
    if (oracleEl && data.use_ai_oracle !== undefined) oracleEl.checked = data.use_ai_oracle;

    const biasBadge = document.getElementById('aiDailyBiasBadge');
    if (biasBadge) {
      if (data.use_ai_oracle && data.ai_daily_bias) {
        biasBadge.style.display = 'inline-block';
        biasBadge.textContent = '🔮 Bias: ' + data.ai_daily_bias;
        if (data.ai_daily_bias === 'BULLISH') biasBadge.style.color = 'var(--success)';
        else if (data.ai_daily_bias === 'BEARISH') biasBadge.style.color = 'var(--danger)';
        else biasBadge.style.color = 'var(--text-primary)';
      } else {
        biasBadge.style.display = 'none';
      }
    }
    
    // Set strategy checkboxes (v5.2)
    const activeStrats = data.active_strategies || [];
    const checkboxes = document.querySelectorAll('input[name="active_strategies"]');
    checkboxes.forEach(cb => {
      cb.checked = activeStrats.includes(cb.value);
    });
    
    // Update Select All state
    const allChecked = Array.from(checkboxes).every(cb => cb.checked);
    document.getElementById('selectAllStrategies').checked = allChecked;
  } catch (e) {
    console.error('Failed to fetch trading config:', e);
  }
}

async function saveTradingConfig() {
  const btn = document.getElementById('btnSaveConfig');
  const config = {
    max_trades_per_day: parseInt(document.getElementById('cfgMaxTrades').value) || 10,
    max_loss_trades_per_day: parseInt(document.getElementById('cfgMaxLossTrades').value) || 2,
    max_daily_loss: parseFloat(document.getElementById('cfgMaxLoss').value) || 2500,
    daily_profit_target: parseFloat(document.getElementById('cfgProfitTarget').value) || 2500,
    trade_lots: parseInt(document.getElementById('cfgLots').value, 10) || 1,
    stock_lots: parseInt(document.getElementById('cfgStockLots').value, 10) || 1,
    webhook_url: document.getElementById('cfgWebhookUrl') ? document.getElementById('cfgWebhookUrl').value.trim() : "",
    paper_trading: document.getElementById('cfgPaperTrading').checked,
    use_ai_oracle: document.getElementById('cfgUseAIOracle') ? document.getElementById('cfgUseAIOracle').checked : false,
    active_strategies: Array.from(document.querySelectorAll('input[name="active_strategies"]:checked')).map(cb => cb.value)
  };

  btn.disabled = true;
  btn.textContent = 'Saving...';

  try {
    const resp = await fetch('/api/trading-config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config)
    });
    const data = await resp.json();
    if (data.success) {
      btn.textContent = '✅ Saved!';
      btn.classList.add('saved');
      showToast('⚙️ Risk settings updated on server', 'success');
      // Refresh automation display to reflect new max_trades
      fetchAutomationStatus();
      setTimeout(() => {
        btn.textContent = '💾 Save Settings';
        btn.classList.remove('saved');
        btn.disabled = false;
      }, 2000);
    } else {
      showToast('Failed to save settings: ' + (data.message || 'Error'), 'error');
      btn.disabled = false;
      btn.textContent = '💾 Save Settings';
    }
  } catch (e) {
    console.error('Save error:', e);
    btn.disabled = false;
    btn.textContent = '💾 Save Settings';
    showToast('Save failed: ' + e.message, 'error');
  }
}

function toggleAllStrategies(source) {
  const checkboxes = document.querySelectorAll('input[name="active_strategies"]');
  checkboxes.forEach(cb => {
    cb.checked = source.checked;
  });
}
window.holidayModalShown = false;

function showHolidayModal(reason) {
  if (window.holidayModalShown) return;
  window.holidayModalShown = true;
  
  const modal = document.getElementById('holidayModal');
  const reasonEl = document.getElementById('holidayReason');
  if (modal && reasonEl) {
    reasonEl.textContent = `Reason: ${reason || 'Weekend'}`;
    modal.classList.remove('hidden');
  }
}

function closeHolidayModal() {
  const modal = document.getElementById('holidayModal');
  if (modal) {
    modal.classList.add('hidden');
  }
}

function openUpdatesModal() {
  const modal = document.getElementById('updatesModal');
  const contentEl = document.getElementById('updatesContent');
  if (modal) {
    modal.classList.remove('hidden');
  }
  if (contentEl) {
    contentEl.innerHTML = '<div style="text-align: center; padding: 20px; color: var(--text-muted);">📡 Loading updates...</div>';
    fetch('/api/updates')
      .then(resp => resp.json())
      .then(data => {
        if (data.status === 'ok' && data.content) {
          contentEl.innerHTML = parseMarkdownToHtml(data.content);
        } else {
          contentEl.innerHTML = `<div style="text-align: center; padding: 20px; color: var(--red);">⚠️ Failed to load updates: ${data.message || 'Unknown error'}</div>`;
        }
      })
      .catch(err => {
        contentEl.innerHTML = `<div style="text-align: center; padding: 20px; color: var(--red);">⚠️ Error fetching updates: ${err}</div>`;
      });
  }
}

function closeUpdatesModal() {
  const modal = document.getElementById('updatesModal');
  if (modal) {
    modal.classList.add('hidden');
  }
}

function parseMarkdownToHtml(md) {
  if (!md) return '';
  const lines = md.split('\n');
  let html = '';
  let inList = false;

  for (let line of lines) {
    let trimmed = line.trim();

    // List item parsing
    if (trimmed.startsWith('- ')) {
      if (!inList) {
        html += '<ul style="margin-left: 18px; margin-bottom: 12px; list-style-type: disc; color: var(--text-muted);">';
        inList = true;
      }
      let content = trimmed.substring(2);
      content = content.replace(/\*\*(.*?)\*\*/g, '<strong style="color: var(--cyan);">$1</strong>');
      content = content.replace(/`(.*?)`/g, '<code style="background:rgba(255,255,255,0.06); color:var(--yellow); padding:1px 4px; border-radius:3px; font-family:monospace; font-size:11px;">$1</code>');
      html += `<li style="margin-bottom: 6px; line-height: 1.5;">${content}</li>`;
      continue;
    } else {
      if (inList) {
        html += '</ul>';
        inList = false;
      }
    }

    if (!trimmed) {
      continue;
    }

    // Title headers (# text)
    if (trimmed.startsWith('# ')) {
      let title = trimmed.substring(2);
      html += `<h2 style="color: var(--cyan); border-bottom: 1px solid var(--border); padding-bottom: 8px; margin-top: 10px; margin-bottom: 16px; font-size: 20px; font-weight: 800;">📢 ${title}</h2>`;
    }
    // Date headers (## text)
    else if (trimmed.startsWith('## ')) {
      let date = trimmed.substring(3);
      html += `<h3 style="color: var(--yellow); margin-top: 24px; margin-bottom: 12px; font-size: 15px; font-weight: 700; border-left: 3px solid var(--yellow); padding-left: 8px; letter-spacing: 0.5px;">📅 ${date}</h3>`;
    }
    // Time/Action subheaders (### text)
    else if (trimmed.startsWith('### ')) {
      let time = trimmed.substring(4);
      html += `<h4 style="color: var(--cyan); margin-top: 14px; margin-bottom: 6px; font-size: 13px; font-weight: 600; display: flex; align-items: center; gap: 6px;">⏱️ ${time}</h4>`;
    }
    // Standard paragraph
    else {
      let paragraph = trimmed;
      paragraph = paragraph.replace(/\*\*(.*?)\*\*/g, '<strong style="color: var(--cyan);">$1</strong>');
      paragraph = paragraph.replace(/`(.*?)`/g, '<code style="background:rgba(255,255,255,0.06); color:var(--yellow); padding:1px 4px; border-radius:3px; font-family:monospace; font-size:11px;">$1</code>');
      html += `<p style="margin-bottom: 8px; color: var(--text); line-height: 1.5;">${paragraph}</p>`;
    }
  }

  if (inList) {
    html += '</ul>';
  }

  return html;
}

async function checkAuthStatus() {
  try {
    const resp = await fetch('/api/auth-status');
    const data = await resp.json();
    updateAuthUI(data.authenticated, data.is_admin, data.username, data.feed_connected);
    if (data.is_admin) {
      document.getElementById('adminBtn').style.display = 'block';
      const navAdmin = document.getElementById('navAdminPanel');
      if (navAdmin) navAdmin.style.display = 'flex';
      const rsBtn = document.getElementById('restartServerBtn');
      if (rsBtn) rsBtn.style.display = 'block';
      const rsBtnSidebar = document.getElementById('restartServerBtnSidebar');
      if (rsBtnSidebar) rsBtnSidebar.style.display = 'block';
    } else {
      document.getElementById('adminBtn').style.display = 'none';
      const navAdmin = document.getElementById('navAdminPanel');
      if (navAdmin) navAdmin.style.display = 'none';
      const rsBtn = document.getElementById('restartServerBtn');
      if (rsBtn) rsBtn.style.display = 'none';
      const rsBtnSidebar = document.getElementById('restartServerBtnSidebar');
      if (rsBtnSidebar) rsBtnSidebar.style.display = 'none';
    }
    if (data.market_holiday) {
      showHolidayModal(data.holiday_reason);
    }
  } catch (e) {}
}

function updateAuthUI(authState, isAdmin, username, feedConnected = false) {
  if (isAdmin !== undefined) currentUserIsAdmin = isAdmin;
  if (username !== undefined) currentUsername = username;

  const connDot = document.getElementById('connDot');
  const connText = document.getElementById('connText');
  const footerConn = document.getElementById('footerConn');
  
  window.wsConnectedState = (authState === true);
  
  if (authState === 'connecting') {
    if (connDot) { connDot.className = 'status-dot degraded'; }
    if (connText) { connText.textContent = 'CONNECTING...'; connText.style.color = 'var(--yellow)'; }
    if (footerConn) { footerConn.textContent = 'Fyers: Connecting'; footerConn.style.color = 'var(--yellow)'; }
  } else if (authState === 'reconnecting') {
    if (connDot) { connDot.className = 'status-dot degraded'; }
    if (connText) { connText.textContent = 'RECONNECTING...'; connText.style.color = 'var(--yellow)'; }
    if (footerConn) { footerConn.textContent = 'Fyers: Reconnecting'; footerConn.style.color = 'var(--yellow)'; }
  } else if (authState === false) {
    if (connDot) { connDot.className = 'status-dot disconnected'; }
    if (connText) { connText.textContent = 'DISCONNECTED'; connText.style.color = 'var(--red)'; }
    if (footerConn) { footerConn.textContent = 'Fyers: Disconnected'; footerConn.style.color = 'var(--red)'; }
  } else if (authState === true) {
    if (connDot) { connDot.className = 'status-dot connected'; }
    if (feedConnected) {
      if (connText) { connText.textContent = 'LIVE'; connText.style.color = 'var(--cyan)'; }
      if (footerConn) { footerConn.textContent = 'Fyers: Live'; footerConn.style.color = 'var(--cyan)'; }
    } else {
      if (connText) { connText.textContent = 'CONNECTED'; connText.style.color = 'var(--green)'; }
      if (footerConn) { footerConn.textContent = 'Fyers: Connected'; footerConn.style.color = 'var(--green)'; }
    }
  }

  // Render Welcome Badge dynamically inside div#welcomeUser
  const welcomeUser = document.getElementById('welcomeUser');
  if (welcomeUser) {
    if (authState === true) {
      const displayUsername = currentUsername.charAt(0).toUpperCase() + currentUsername.slice(1);
      if (currentUserIsAdmin) {
        welcomeUser.innerHTML = `<span class="admin-badge"><span style="margin-right:4px">👑</span> Welcome, ${displayUsername}</span>`;
      } else {
        welcomeUser.innerHTML = `<span class="user-badge"><span style="margin-right:4px">👤</span> Welcome, ${displayUsername}</span>`;
      }
      welcomeUser.style.display = '';
    } else {
      welcomeUser.innerHTML = '';
      welcomeUser.style.display = 'none';
    }
  }
  
  // Update onboarding card dynamically
  if (typeof updateOnboardingWizard === 'function') {
    updateOnboardingWizard();
  }
}

function closeAuthModal() {
  document.getElementById('authModal').classList.add('hidden');
}

async function triggerLogin() {
  showToast('Generating Fyers Login URL...', 'info');
  const loginWin = window.open('', '_blank');
  if (!loginWin) {
    showToast('Popup window was blocked! Please allow popups for this site.', 'error');
    return;
  }
  try {
    const resp = await fetch('/api/login');
    const data = await resp.json();
    if (data.url) {
      loginWin.location.href = data.url;
      // Show the modal
      document.getElementById('authModal').classList.remove('hidden');
      document.getElementById('authUrlInput').value = '';
      document.getElementById('authUrlInput').focus();
      showToast('Login window opened. Please complete login and paste the redirect URL.', 'info');
    } else {
      loginWin.close();
      showToast('Failed to generate login URL: ' + (data.message || 'Unknown error'), 'error');
    }
  } catch (e) {
    if (loginWin) loginWin.close();
    console.error('Login error:', e);
    showToast('Failed to initiate login flow', 'error');
  }
}

async function submitAuthCode() {
  const input = document.getElementById('authUrlInput').value.trim();
  if (!input) {
    showToast('Please paste the redirect URL or auth code', 'warning');
    return;
  }

  showToast('Exchanging token... Please wait', 'info');
  try {
    const resp = await fetch('/api/submit-auth-code', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code: input })
    });
    const data = await resp.json();
    if (data.success) {
      showToast('Fyers Account Connected!', 'success');
      closeAuthModal();
      // Status will be updated via WebSocket broadcast
    } else {
      showToast('Connection failed: ' + (data.message || 'Check your code'), 'error');
    }
  } catch (e) {
    console.error('Submission error:', e);
    showToast('Failed to connect. Try again.', 'error');
  }
}

function initCharts() {
  const chartOptions = {
    layout: {
      background: { type: 'solid', color: isLightMode ? '#ffffff' : '#1a1f2e' },
      textColor: isLightMode ? '#475569' : '#94a3b8',
      fontFamily: 'Inter, sans-serif',
      fontSize: 11,
    },
    grid: {
      vertLines: { visible: false },
      horzLines: { visible: false },
    },
    crosshair: {
      mode: LightweightCharts.CrosshairMode.Normal,
      vertLine: { color: '#3b82f640', width: 1, style: 2 },
      horzLine: { color: '#3b82f640', width: 1, style: 2 },
    },
    rightPriceScale: {
      borderColor: isLightMode ? '#cbd5e1' : '#2a3144',
      scaleMargins: { top: 0.1, bottom: 0.1 },
    },
    timeScale: {
      borderColor: isLightMode ? '#cbd5e1' : '#2a3144',
      timeVisible: true,
      secondsVisible: false,
      rightOffset: 5,
      barSpacing: 8,
    },
    localization: {
      priceFormatter: price => price.toFixed(2),
      timeFormatter: (time) => {
        // Since we add IST_OFFSET to the timestamp, we treat it as UTC to avoid double-shift
        const date = new Date(time * 1000);
        return date.getUTCHours().toString().padStart(2, '0') + ':' + 
               date.getUTCMinutes().toString().padStart(2, '0');
      },
    },
    handleScroll: { vertTouchDrag: false },
  };

  // 5M Master Chart
  const el5m = document.getElementById('chart5m');
  chart5m = LightweightCharts.createChart(el5m, { ...chartOptions, width: el5m.clientWidth, height: el5m.clientHeight });
  series5m = chart5m.addCandlestickSeries({
    upColor: '#10b981', downColor: '#ef4444',
    borderUpColor: '#10b981', borderDownColor: '#ef4444',
    wickUpColor: '#10b98188', wickDownColor: '#ef444488',
  });

  // Resize handler
  const resizeObserver = new ResizeObserver(entries => {
    for (const entry of entries) {
      const { width, height } = entry.contentRect;
      if (entry.target.id === 'chart5m') chart5m.resize(width, height);
    }
  });
  resizeObserver.observe(el5m);

  // === CROSSHAIR HOVER OHLC LEGEND ===
  function makeLegendHandler(chart, series, legendId) {
    const legendEl = document.getElementById(legendId);
    chart.subscribeCrosshairMove((param) => {
      if (!param || !param.time || !param.seriesData) {
        legendEl.innerHTML = 'O: -- H: -- L: -- C: --';
        return;
      }
      const d = param.seriesData.get(series);
      if (!d) return;
      const o = d.open?.toFixed(2) || '--';
      const h = d.high?.toFixed(2) || '--';
      const l = d.low?.toFixed(2) || '--';
      const c = d.close?.toFixed(2) || '--';
      const color = d.close >= d.open ? 'lg-up' : 'lg-down';
      legendEl.innerHTML = `O: <span class="${color}">${o}</span>  H: <span class="${color}">${h}</span>  L: <span class="${color}">${l}</span>  C: <span class="${color}">${c}</span>`;
    });
  }
  makeLegendHandler(chart5m, series5m, 'legend5m');
}


// ===== WEBSOCKET STREAMING =====
// Mobile-resilient reconnect: exponential backoff (so we don't hammer a dead link) plus
// instant reconnect when the device comes back online or the app returns to the foreground.
let _wsReconnectDelay = 1000;
let _wsReconnectTimer = null;
const _WS_MAX_DELAY = 20000;
function scheduleWsReconnect() {
  if (_wsReconnectTimer) return; // one pending reconnect at a time — avoid duplicate sockets
  console.log(`📡 Reconnecting in ${_wsReconnectDelay}ms...`);
  _wsReconnectTimer = setTimeout(() => {
    _wsReconnectTimer = null;
    connectWebSocket();
  }, _wsReconnectDelay);
  _wsReconnectDelay = Math.min(_wsReconnectDelay * 2, _WS_MAX_DELAY);
}
function reconnectWsNow() {
  // Network restored or app refocused — cancel any pending backoff and reconnect immediately.
  if (_wsReconnectTimer) { clearTimeout(_wsReconnectTimer); _wsReconnectTimer = null; }
  _wsReconnectDelay = 1000;
  if (!wsConnection || wsConnection.readyState === WebSocket.CLOSED || wsConnection.readyState === WebSocket.CLOSING) {
    connectWebSocket();
  }
}
window.addEventListener('online', reconnectWsNow);
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') reconnectWsNow();
});

function connectWebSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/ws/live`;
  console.log('📡 Connecting WebSocket:', wsUrl);
  
  updateAuthUI('connecting'); // Show connecting state immediately

  wsConnection = new WebSocket(wsUrl);

  wsConnection.onopen = () => {
    console.log('📡 WebSocket connected');
    _wsReconnectDelay = 1000; // reset backoff on a healthy connection
    // We wait for auth_status message before setting Live status
  };

  wsConnection.onmessage = (event) => {
    const data = JSON.parse(event.data);

    switch (data.type) {
      case 'auth_status':
        updateAuthUI(data.authenticated, data.is_admin, data.username, data.feed_connected);
        if (data.market_holiday) {
          showHolidayModal(data.holiday_reason);
        }
        break;
      case 'spot':
        updateSpotLive(data);
        break;
      case 'positions':
        renderPositions(data.positions);
        // Update P&L in account section
        updatePnlDisplays(data.total_pnl || 0);
        updateActiveTradeLines(data.active_trades);
        
        if (data.automation_stats) {
          const tradesToday = data.automation_stats.trades_today || 0;
          const autoTradesEl = document.getElementById('autoTrades');
          if (autoTradesEl) {
            autoTradesEl.textContent = `${tradesToday}/${data.automation_stats.max_trades || 2} Trades`;
          }
          window._automationStatsLoaded = true; // Mark that we have real automation data
          const autoPnlEl = document.getElementById('autoPnl');
          if (autoPnlEl) {
            const autoPnl = data.total_pnl || 0;
            const sign = autoPnl > 0 ? '+' : (autoPnl < 0 ? '-' : '');
            autoPnlEl.textContent = `${sign}₹${Math.abs(autoPnl).toLocaleString('en-IN', {minimumFractionDigits: 2})}`;
            autoPnlEl.className = autoPnl > 0 ? 'pnl-positive' : (autoPnl < 0 ? 'pnl-negative' : '');
          }

          // Cooldown cap validation
          const maxTrades = data.automation_stats.max_trades || 2;
          const isCapReached = tradesToday >= maxTrades;
          window.dailyCapReached = isCapReached;
          const tradeStats = document.querySelector('.trade-stats');
          if (tradeStats) {
            if (isCapReached) {
              tradeStats.classList.add('cooldown-active');
            } else {
              tradeStats.classList.remove('cooldown-active');
            }
          }
        }
        break;
      case 'orders':
        renderOrders(data.orders);
        break;
      case 'funds':
        updateFundsLive(data.funds);
        break;
      case 'log':
        appendActivityLog(data.msg, data.level, data.time);
        break;
      case 'strike_update':
        // Lightweight strike LTP update
        if (!analysisData) analysisData = { signals: [], strike_recommendations: [] };
        
        // Update the recommendations
        const currentTopSignal = analysisData.signals?.[0];
        if (currentTopSignal) {
          // If we have a signal, show the relevant strike (CALL or PUT)
          analysisData.strike_recommendations = currentTopSignal.type === 'CALL' ? data.ce_strikes : data.pe_strikes;
        } else {
          // If no signal, show both ATM CALL and Premium Matched PUT for monitoring
          analysisData.strike_recommendations = [...(data.ce_strikes || []), ...(data.pe_strikes || [])];
        }
        
        analysisData.expiry = data.expiry;
        
        // Re-render
        renderSignals(analysisData.signals);
        renderStrikes(analysisData.strike_recommendations);
        break;
      case 'market_update':
        // Update header with the activeSymbol
        let displayData = data.spots[activeSymbol];
        
        if (!displayData && activeSymbol === "NSE:NIFTY50-INDEX") {
            // Fallback if Nifty is missing but active
            const firstSym = Object.keys(data.spots)[0];
            if (firstSym) displayData = data.spots[firstSym];
        }

        if (displayData) {
            updateSpotLive({
                symbol: activeSymbol,
                spot: displayData.lp,
                change: displayData.change,
                change_pct: displayData.change_pct,
                vix: data.vix.lp,
                vix_change: data.vix.change
            });
        }
        
        // Refresh the Market Watch table
        renderScriptsList(data.spots);
        break;
      case 'scripts_update':
        activeScripts = data.scripts || [];
        if (data.enabled) enabledScripts = data.enabled || [];
        renderScriptsList();
        break;
    }
  };

  wsConnection.onclose = () => {
    console.log('📡 WebSocket disconnected. Scheduling reconnect...');
    updateAuthUI('reconnecting');
    scheduleWsReconnect();
  };

  wsConnection.onerror = (error) => {
    console.error('📡 WebSocket error:', error);
    // Don't close here, onclose will handle it
  };
}

function updateSpotLive(data) {
  if (!data) return;
  const spot = data.spot || data.lp || 0;
  const change = data.change || 0;
  const change_pct = data.change_pct || data.chp || 0;
  const vix = data.vix || 0;
  const vix_change = data.vix_change || 0;
  const symbol = data.symbol?.replace('NSE:', '').replace('-INDEX', '').replace('-EQ', '') || 'NIFTY';

  const spotLabel = document.getElementById('spotLabel');
  if (spotLabel) {
      spotLabel.textContent = symbol;
  }

  document.getElementById('spotPrice').textContent = '₹' + Number(spot).toLocaleString('en-IN', { minimumFractionDigits: 2 });

  const changeEl = document.getElementById('spotChange');
  const sign = change >= 0 ? '+' : '';
  changeEl.textContent = `${sign}${change.toFixed(2)} (${sign}${change_pct.toFixed(2)}%)`;
  changeEl.className = 'spot-change ' + (change >= 0 ? 'positive' : 'negative');

  document.getElementById('vixValue').textContent = Number(vix).toFixed(2);
  const vixChEl = document.getElementById('vixChange');
  if (vixChEl) {
    const vSign = vix_change >= 0 ? '+' : '';
    vixChEl.textContent = `${vSign}${Number(vix_change).toFixed(2)}%`;
    vixChEl.className = 'spot-change ' + (vix_change >= 0 ? 'negative' : 'positive');
  }

  // Update live spot lines on chart
  const spotPrice = Number(spot);

  if (series5m && spotPrice > 0) {
    if (!liveSpotLine5m) {
      liveSpotLine5m = series5m.createPriceLine({
        price: spotPrice,
        color: '#3b82f6',
        lineWidth: 1,
        lineStyle: 2,
        axisLabelVisible: true,
        title: 'LIVE',
      });
    } else {
      liveSpotLine5m.applyOptions({ price: spotPrice });
    }
  }
}

function updateFundsLive(funds, pnl) {
  if (funds) {
    const available = funds.equityAmount !== undefined ? funds.equityAmount : (funds.availableBalance !== undefined ? funds.availableBalance : 0);
    const used = funds.utilisedAmount !== undefined ? funds.utilisedAmount : (funds.usedAmount || 0);
    
    document.getElementById('fundAvailable').textContent = '₹' + Number(available || 0).toLocaleString('en-IN', { maximumFractionDigits: 0 });
    document.getElementById('fundUsed').textContent = '₹' + Number(used || 0).toLocaleString('en-IN', { maximumFractionDigits: 0 });

    currentAvailableMargin = available;  // update local var (read by updateRiskCalc)
    window.currentAvailableMargin = available;
    updateRiskCalc();
  }
  if (pnl !== undefined) {
    updatePnlDisplays(pnl);
  }
}

function updateActiveTradeLines(activeTrades) {
  if (activeTrades !== undefined) {
    lastKnownActiveTrades = activeTrades;
  }
  if (!series5m) return;

  const trade = (lastKnownActiveTrades || []).find(t => t.symbol === activeSymbol);

  if (trade) {
    const entry = trade.entry_price;
    const sl = trade.sl_price;
    const target = trade.target_price;

    if (!activeEntryLine) {
      activeEntryLine = series5m.createPriceLine({
        price: entry,
        color: '#10b981',
        lineWidth: 2,
        lineStyle: 0,
        axisLabelVisible: true,
        title: 'ENTRY @ ₹' + entry.toFixed(1),
      });
    } else {
      activeEntryLine.applyOptions({
        price: entry,
        title: 'ENTRY @ ₹' + entry.toFixed(1)
      });
    }

    if (!activeSLLine) {
      activeSLLine = series5m.createPriceLine({
        price: sl,
        color: '#ef4444',
        lineWidth: 2,
        lineStyle: 2,
        axisLabelVisible: true,
        title: 'SL @ ₹' + sl.toFixed(1),
      });
    } else {
      activeSLLine.applyOptions({
        price: sl,
        title: 'SL @ ₹' + sl.toFixed(1)
      });
    }

    if (target && target > 0) {
      if (!activeTargetLine) {
        activeTargetLine = series5m.createPriceLine({
          price: target,
          color: '#3b82f6',
          lineWidth: 2,
          lineStyle: 1,
          axisLabelVisible: true,
          title: 'TGT @ ₹' + target.toFixed(1),
        });
      } else {
        activeTargetLine.applyOptions({
          price: target,
          title: 'TGT @ ₹' + target.toFixed(1)
        });
      }
    } else {
      if (activeTargetLine) {
        series5m.removePriceLine(activeTargetLine);
        activeTargetLine = null;
      }
    }
  } else {
    if (activeEntryLine) {
      series5m.removePriceLine(activeEntryLine);
      activeEntryLine = null;
    }
    if (activeSLLine) {
      series5m.removePriceLine(activeSLLine);
      activeSLLine = null;
    }
    if (activeTargetLine) {
      series5m.removePriceLine(activeTargetLine);
      activeTargetLine = null;
    }
  }
}

function getLoggedInUser() {
  const cookies = document.cookie.split(';');
  const uc = cookies.find(c => c.trim().startsWith('username='));
  if (uc) {
    return decodeURIComponent(uc.split('=')[1]);
  }
  return 'default';
}

function updatePnlDisplays(pnl) {
  const pnlEl = document.getElementById('totalPnl');
  const headerPnlEl = document.getElementById('headerPnl');
  
  const today = new Date().toDateString();
  const username = getLoggedInUser();
  const cacheKey = `dailyPnl_${username}`;
  const cachedData = JSON.parse(localStorage.getItem(cacheKey) || '{}');
  
  const tradesEl = document.getElementById('autoTrades');
  let tradesToday = 0;
  if (tradesEl) {
    const text = tradesEl.textContent || '0/2';
    tradesToday = parseInt(text.split('/')[0]) || 0;
  }
  
  let persistentPnl = pnl;
  
  // Prevent ghost PnL early morning (handled by backend or acceptable during market hours)
  if (pnl === 0 && cachedData.date === today && cachedData.pnl !== 0) {
    persistentPnl = cachedData.pnl;
  } else if (pnl !== 0) {
    // Update cache with fresh non-zero PnL
    try {
      localStorage.setItem(cacheKey, JSON.stringify({ date: today, pnl: pnl }));
    } catch(e){}
  }
  
  const sign = persistentPnl > 0 ? '+' : (persistentPnl < 0 ? '-' : '');
  const formatted = sign + '₹' + Math.abs(persistentPnl).toFixed(2);
  const colorClass = persistentPnl > 0 ? 'pnl-positive' : (persistentPnl < 0 ? 'pnl-negative' : '');
  
  if (pnlEl) {
    pnlEl.textContent = formatted;
    pnlEl.className = 'fund-value ' + colorClass;
    pnlEl.style.color = ''; 
  }
  if (headerPnlEl) {
    headerPnlEl.textContent = `P&L: ${formatted}`;
    headerPnlEl.className = colorClass;
    headerPnlEl.style.color = '';
  }
}


// ===== DATA FETCHING (for heavy/initial loads) =====
async function refreshAll() {
  const btn = document.getElementById('refreshBtn');
  if (btn) { btn.disabled = true; btn.textContent = '⟳ Loading...'; }

  try {
    await fetchAnalysis();
    showToast('Data refreshed', 'success');
  } catch (e) {
    showToast('Refresh failed: ' + e.message, 'error');
  }

  if (btn) { btn.disabled = false; btn.textContent = '⟳ Refresh'; }
}

async function fetchSpot() {
  // Kept for manual refresh fallback
  const resp = await fetch('/api/spot');
  const data = await resp.json();
  updateSpotLive(data);
}

async function fetchCandles() {
  const btn = document.getElementById('refreshBtn');
  if (btn) { btn.disabled = true; btn.textContent = '...'; }

  try {
    const resp5m = await fetch(`/api/candles?symbol=${activeSymbol}&resolution=5&days=3`);
    const data5m = await resp5m.json();

    // Convert to Lightweight Charts format (add IST offset)
    const format = (candles) => candles.map(c => ({
      time: c.timestamp + IST_OFFSET,
      open: c.open, high: c.high, low: c.low, close: c.close,
    }));

    const formatted5m = format(data5m.candles || []);
    
    // Only update chart if we received valid candle data (prevents wipe on API glitch)
    if (formatted5m.length > 0) {
      series5m.setData(formatted5m);

      // Track last 5m candle time for extending OB/FVG zones
      lastCandleTime5m = formatted5m[formatted5m.length - 1].time;
    }

    chart5m.timeScale().fitContent();
  } catch (e) {
    showToast('Refresh failed: ' + e.message, 'error');
  }

  if (btn) { btn.disabled = false; btn.textContent = '⟳ Refresh'; }
}

function handleVisibilityChange() {
  if (!analysisData || !chart5m || !series5m) return;
  
  try {
    renderKeyLevels(analysisData.key_levels);
    renderBOSOnChart(analysisData.bos_events);
    renderOrderBlocksOnChart(analysisData.order_blocks);
    renderFVGsOnChart(analysisData.fvgs);
    updateAllMarkers();

    // Save preferences
    localStorage.setItem('vis_OB', document.getElementById('toggleOB').checked);
    localStorage.setItem('vis_FVG', document.getElementById('toggleFVG').checked);
    localStorage.setItem('vis_KEY', document.getElementById('toggleKEY').checked);
  } catch (err) {
    console.error("Chart Visibility Update Error:", err);
  }
}

// Add to DOMContentLoaded to load preferences
function loadVisibilityPrefs() {
  const ob = localStorage.getItem('vis_OB');
  const fvg = localStorage.getItem('vis_FVG');
  const key = localStorage.getItem('vis_KEY');
  
  if (ob !== null) document.getElementById('toggleOB').checked = ob === 'true';
  if (fvg !== null) document.getElementById('toggleFVG').checked = fvg === 'true';
  // Default KEY to checked if no preference saved (key levels should always be visible)
  if (key !== null) {
    document.getElementById('toggleKEY').checked = key === 'true';
  } else {
    document.getElementById('toggleKEY').checked = true;
  }
}

async function fetchAnalysis() {
  try {
    const resp = await fetch(`/api/analysis?symbol=${activeSymbol}`);
    if (!resp.ok) {
        const errorData = await resp.json().catch(() => ({}));
        console.warn('Analysis fetch partially failed:', errorData.detail || 'Rate Limited');
        return;
    }
    
    analysisData = await resp.json();
    if (!analysisData) return;

    // Update candles from analysis data if available
    if (analysisData.candles_5m && analysisData.candles_5m.length > 0) {
      const formatted = analysisData.candles_5m.map(c => ({
        time: c.timestamp + IST_OFFSET,
        open: c.open, high: c.high, low: c.low, close: c.close,
      }));
      series5m.setData(formatted);
      lastCandleTime5m = formatted[formatted.length - 1].time;
      chart5m.timeScale().fitContent();
    }

    if (analysisData.trend) renderTrend(analysisData.trend);
    
    // Render everything - each function now respects its own toggle
    renderKeyLevels(analysisData.key_levels || []);
    renderBOSOnChart(analysisData.bos_events || []);
    renderOrderBlocksOnChart(analysisData.order_blocks || []);
    renderFVGsOnChart(analysisData.fvgs || []);
    updateAllMarkers();

    renderSignals(analysisData.signals || []);
    renderStrikes(analysisData.strike_recommendations || []);

    const obCount = (analysisData.active_order_blocks || []).length;
    document.getElementById('obCount').textContent = `${obCount} OB`;
  } catch (e) {
    console.error('fetchAnalysis failed:', e);
  }
}

async function fetchPositions() {
  try {
    const [posResp, ordResp] = await Promise.all([
      fetch('/api/positions'), fetch('/api/orders'),
    ]);
    const posData = await posResp.json();
    const ordData = await ordResp.json();

    // Fyers returns netPositions list
    const positions = posData.netPositions || [];
    renderPositions(positions);
    
    // Also update PnL from overall summary if available
    if (posData.overallPnl !== undefined) {
       updatePnlDisplays(posData.overallPnl);
    }
    
    renderOrders(ordData.orders || []);
  } catch (e) {
    console.error('Position fetch error:', e);
  }
}

async function fetchFunds() {
  try {
    const [fundResp, posResp] = await Promise.all([
      fetch('/api/funds'),
      fetch('/api/positions')
    ]);
    const fundData = await fundResp.json();
    const posData = await posResp.json();
    
    // overallPnl is the correct field from Fyers API
    const totalPnl = posData.overallPnl !== undefined ? posData.overallPnl : 0;
    updateFundsLive(fundData.funds || {}, totalPnl);
  } catch (e) {
    console.error('Funds/P&L fetch error:', e);
  }
}


// ===== RENDERING =====
function renderTrend(trend) {
  const badge = document.getElementById('trendBadge');
  const indicator = document.getElementById('regimeIndicator');
  const lockoutText = document.getElementById('regimeLockoutText');
  
  // Per-TF bias elements
  const tf1h = document.getElementById('tf1hBias');
  const tf15m = document.getElementById('tf15mBias');
  const tf5m = document.getElementById('tf5mBias');
  const tfAi = document.getElementById('tfAiBias');
  const tf1hCell = document.getElementById('tf1hCell');
  const tf15mCell = document.getElementById('tf15mCell');
  const tf5mCell = document.getElementById('tf5mCell');
  const tfAiCell = document.getElementById('tfAiCell');
  
  // Helper: get color and symbol for a bias
  function biasStyle(bias) {
    const b = (bias || 'NEUTRAL').toUpperCase();
    if (b === 'BULLISH') return { text: '↑ Bull', color: 'var(--green)', border: 'rgba(46, 196, 182, 0.25)' };
    if (b === 'BEARISH') return { text: '↓ Bear', color: 'var(--red)', border: 'rgba(244, 63, 94, 0.25)' };
    return { text: '— Flat', color: 'var(--yellow)', border: 'rgba(250, 204, 21, 0.2)' };
  }
  
  // Update per-TF cells
  function updateTFCell(el, cellEl, bias) {
    if (!el || !cellEl) return;
    const s = biasStyle(bias);
    el.textContent = s.text;
    el.style.color = s.color;
    cellEl.style.borderColor = s.border;
  }
  
  if (!trend || !trend.trend) {
    if (badge) {
      badge.textContent = 'NEUTRAL';
      badge.className = 'trend-pill ms-2 badge-neutral';
    }
    if (indicator) {
      indicator.textContent = 'NEUTRAL';
      indicator.className = 'regime-indicator rangebound';
    }
    if (lockoutText) {
      lockoutText.textContent = '🔒 Capital Protection Active: Flat/Choppy market detected. Zero-trading lockout is active.';
      lockoutText.style.color = 'var(--yellow)';
    }
    updateTFCell(tf1h, tf1hCell, 'NEUTRAL');
    updateTFCell(tf15m, tf15mCell, 'NEUTRAL');
    updateTFCell(tf5m, tf5mCell, 'NEUTRAL');
    updateTFCell(tfAi, tfAiCell, 'NEUTRAL');
    window.isRegimeLockout = true;
    return;
  }
  
  const currentTrend = trend.trend.toUpperCase();
  const strength = trend.strength || 0;
  
  // Update per-TF bias cells from the new multi-TF data
  const tfData1h = trend.tf_1h || {};
  const tfData15m = trend.tf_15m || {};
  const tfData5m = trend.tf_5m || {};
  const aiTrend = trend.ai_trend || 'NEUTRAL';
  
  updateTFCell(tf1h, tf1hCell, tfData1h.bias || 'NEUTRAL');
  updateTFCell(tf15m, tf15mCell, tfData15m.bias || 'NEUTRAL');
  updateTFCell(tf5m, tf5mCell, tfData5m.bias || 'NEUTRAL');
  updateTFCell(tfAi, tfAiCell, aiTrend);
  
  if (badge) {
    badge.textContent = `${currentTrend} (${strength}%)`;
    badge.title = trend.rationale || "No rationale provided.";
    badge.className = 'trend-pill ms-2 ' + (
      currentTrend === 'BULLISH' ? 'badge-bullish' :
      currentTrend === 'BEARISH' ? 'badge-bearish' : 'badge-neutral'
    );
  }
  
  if (indicator) {
    indicator.textContent = `${currentTrend} (${strength}%)`;
    indicator.className = 'regime-indicator ' + (
      currentTrend === 'BULLISH' ? 'bullish' :
      currentTrend === 'BEARISH' ? 'bearish' : 'rangebound'
    );
  }
  
  if (lockoutText) {
    if (anyNeutralOrRange(currentTrend)) {
      lockoutText.textContent = '🔒 Capital Protection Active: Timeframes disagree. Zero-trading lockout is active.';
      lockoutText.style.color = 'var(--yellow)';
      window.isRegimeLockout = true;
    } else if (currentTrend === 'BULLISH') {
      lockoutText.textContent = '⚡ All TFs + AI aligned BULLISH: Only CALL (CE) buys are allowed.';
      lockoutText.style.color = 'var(--green)';
      window.isRegimeLockout = false;
    } else if (currentTrend === 'BEARISH') {
      lockoutText.textContent = '⚡ All TFs + AI aligned BEARISH: Only PUT (PE) buys are allowed.';
      lockoutText.style.color = 'var(--red)';
      window.isRegimeLockout = false;
    } else {
      lockoutText.textContent = '🔒 Capital Protection Active: Timeframes disagree. Zero-trading lockout is active.';
      lockoutText.style.color = 'var(--yellow)';
      window.isRegimeLockout = true;
    }
  }
}

function anyNeutralOrRange(trendStr) {
  const t = trendStr.toUpperCase();
  return t.includes("NEUTRAL") || t.includes("RANGE") || t.includes("SIDEWAYS") || t.includes("CHOPPY") || t.includes("CHOOPY");
}

function renderKeyLevels(levels) {
  clearKeyLevelLines();
  const container = document.getElementById('keyLevelsContainer');
  const showOnChart = document.getElementById('toggleKEY').checked;

  if (!levels || !levels.length) {
    container.innerHTML = '<div class="no-data">No key levels detected</div>';
    document.getElementById('levelCount').textContent = '0';
    return;
  }

  document.getElementById('levelCount').textContent = levels.length;

  // Always render the panel list (key levels data is always useful)
  container.innerHTML = levels.map(l => {
    const color = l.type === 'resistance' ? 'var(--bearish)' :
                  l.type === 'support' ? 'var(--bullish)' :
                  l.type === 'pivot' ? 'var(--accent-purple)' : 'var(--accent-yellow)';

    // Only add price lines to chart if KEY toggle is checked
    if (showOnChart) {
      try {
        const line = series5m.createPriceLine({
          price: l.price,
          color: l.type === 'resistance' ? '#ef4444' : l.type === 'support' ? '#10b981' : '#8b5cf6',
          lineWidth: 2,
          lineStyle: 1, // Solid line for better visibility
          axisLabelVisible: true,
          title: l.label || l.type,
        });
        markers1h.push(line);
      } catch (e) {
        console.error('Key level price line error:', e);
      }
    }

    return `<div class="level-item">
      <div>
        <span class="level-type ${l.type}">${l.type}</span>
        <span style="margin-left:6px;font-size:10px;color:var(--text-muted)">${l.label || ''}</span>
      </div>
      <div style="display:flex;align-items:center;gap:8px">
        <span class="level-price">${l.price.toLocaleString('en-IN')}</span>
        <div class="strength-bar">
          <div class="strength-fill" style="width:${l.strength*10}%;background:${color}"></div>
        </div>
      </div>
    </div>`;
  }).join('');
}

let bosSeriesList = []; // BOS Ray series

function clearKeyLevelLines() {
  markers1h.forEach(m => { try { series5m.removePriceLine(m); } catch(e) {} });
  markers1h = [];
}

function clearBOS() {
  bosSeriesList.forEach(s => { try { chart5m.removeSeries(s); } catch(e) {} });
  bosSeriesList = [];
  window.bosMarkers = [];
}

function renderBOSOnChart(bosEvents) {
  clearBOS();
  if (!document.getElementById('toggleKEY').checked) return;
  window.bosMarkers = [];
  if (!bosEvents || !bosEvents.length) return;

  const endTime = lastCandleTime5m || Math.floor(Date.now() / 1000) + IST_OFFSET;

  bosEvents.forEach(bos => {
    const isBull = bos.type === 'BULLISH_BOS';
    const color = isBull ? '#3b82f6' : '#ef4444';

    const raySeries = chart5m.addLineSeries({
      color: color,
      lineWidth: 2,
      lineStyle: 2, // Dashed
      lastValueVisible: false,
      priceLineVisible: false,
      crosshairMarkerVisible: false,
    });

    raySeries.setData([
      { time: bos.timestamp + IST_OFFSET, value: bos.price },
      { time: endTime, value: bos.price }
    ]);
    bosSeriesList.push(raySeries);
    
    // Add text marker
    window.bosMarkers = window.bosMarkers || [];
    window.bosMarkers.push({
      time: bos.timestamp + IST_OFFSET,
      position: isBull ? 'belowBar' : 'aboveBar',
      color: color,
      shape: 'circle',
      text: 'BOS',
    });
  });
}

function clearOBZones() {
  obZoneSeries.forEach(s => { try { chart5m.removeSeries(s); } catch(e) {} });
  obZoneSeries = [];
  window.obMarkers = [];
}

function clearFVGZones() {
  fvgZoneSeries.forEach(s => { try { chart5m.removeSeries(s); } catch(e) {} });
  fvgZoneSeries = [];
  window.fvgMarkers = [];
}

function renderOrderBlocksOnChart(obs) {
  clearOBZones();
  if (!document.getElementById('toggleOB').checked) return;
  if (!obs || !obs.length) return;

  // Show only active OBs by default to reduce clutter
  const displayOBs = obs.filter(ob => ob.active);
  const endTime = lastCandleTime5m || Math.floor(Date.now() / 1000) + IST_OFFSET;

  displayOBs.forEach(ob => {
    const startTime = ob.timestamp + IST_OFFSET;
    const isBull = ob.direction === 'BULLISH';
    const topPrice = ob.top;
    const bottomPrice = ob.bottom;
    
    // Green for Bullish, Red for Bearish
    const color = isBull ? 'rgba(34, 197, 94, ' : 'rgba(239, 68, 68, ';
    const fillAlpha = '0.15';
    const lineAlpha = '0.4';
    const obFill = color + fillAlpha + ')';
    const obLine = color + lineAlpha + ')';

    try {
      // Create baseline series for the bounded zone rectangle
      const zoneSeries = chart5m.addBaselineSeries({
        baseValue: { type: 'price', price: bottomPrice },
        topFillColor1: obFill,
        topFillColor2: obFill,
        topLineColor: obLine,
        bottomFillColor1: 'transparent',
        bottomFillColor2: 'transparent',
        bottomLineColor: 'transparent',
        lineWidth: 1,
        lastValueVisible: false,
        priceLineVisible: false,
        crosshairMarkerVisible: false,
      });

      // Fill from startTime to endTime at top price
      const numPoints = 6;
      const step = Math.max(1, Math.floor((endTime - startTime) / numPoints));
      const data = [];
      for (let t = startTime; t <= endTime; t += step) {
        data.push({ time: t, value: topPrice });
      }
      // Ensure end point
      if (data.length === 0 || data[data.length - 1].time < endTime) {
        data.push({ time: endTime, value: topPrice });
      }

      zoneSeries.setData(data);
      obZoneSeries.push(zoneSeries);

      // Also add a bottom border line series
      const borderSeries = chart5m.addLineSeries({
        color: obLine,
        lineWidth: 1,
        lineStyle: 2,
        lastValueVisible: false,
        priceLineVisible: false,
        crosshairMarkerVisible: false,
      });
      borderSeries.setData([
        { time: startTime, value: bottomPrice },
        { time: endTime, value: bottomPrice },
      ]);
      obZoneSeries.push(borderSeries);
    } catch (e) {
      console.error('OB zone error:', e);
    }
  });

  // Add text markers on the candle series for OB
  const chartMarkers = displayOBs.map(ob => ({
    time: ob.timestamp + IST_OFFSET,
    position: ob.direction === 'BULLISH' ? 'belowBar' : 'aboveBar',
    color: ob.direction === 'BULLISH' ? '#22c55e' : '#ef4444',
    shape: ob.direction === 'BULLISH' ? 'arrowUp' : 'arrowDown',
    text: 'OB',
  }));
  chartMarkers.sort((a, b) => a.time - b.time);
  
  // Note: Since we also want FVG markers, we should combine them or set them together.
  // We'll manage all markers in a separate pass or just update the OB ones here for now.
  // Wait, if we call series5m.setMarkers() twice, the second overwrites the first.
  // We need to store global markers and set them once, or retrieve existing.
  window.obMarkers = chartMarkers;
}

function renderFVGsOnChart(fvgs) {
  clearFVGZones();
  if (!document.getElementById('toggleFVG').checked) return;
  if (!fvgs || !fvgs.length) return;

  const endTime = lastCandleTime5m || Math.floor(Date.now() / 1000) + IST_OFFSET;

  fvgs.filter(fvg => fvg.active).forEach(fvg => {
    const startTime = fvg.timestamp + IST_OFFSET;
    const isBull = fvg.direction === 'BULLISH';
    const topPrice = fvg.top;
    const bottomPrice = fvg.bottom;

    try {
      const zoneSeries = chart5m.addBaselineSeries({
        baseValue: { type: 'price', price: bottomPrice },
        topFillColor1: isBull ? 'rgba(245, 158, 11, 0.15)' : 'rgba(139, 92, 246, 0.15)',
        topFillColor2: isBull ? 'rgba(245, 158, 11, 0.15)' : 'rgba(139, 92, 246, 0.15)',
        topLineColor: isBull ? 'rgba(245, 158, 11, 0.5)' : 'rgba(139, 92, 246, 0.5)',
        bottomFillColor1: 'transparent',
        bottomFillColor2: 'transparent',
        bottomLineColor: 'transparent',
        lineWidth: 1,
        lineStyle: 2,
        lastValueVisible: false,
        priceLineVisible: false,
        crosshairMarkerVisible: false,
      });

      const numPoints = 6;
      const step = Math.max(1, Math.floor((endTime - startTime) / numPoints));
      const data = [];
      for (let t = startTime; t <= endTime; t += step) {
        data.push({ time: t, value: topPrice });
      }
      if (data.length === 0 || data[data.length - 1].time < endTime) {
        data.push({ time: endTime, value: topPrice });
      }

      zoneSeries.setData(data);
      fvgZoneSeries.push(zoneSeries);

      // Bottom border
      const borderSeries = chart5m.addLineSeries({
        color: isBull ? 'rgba(245, 158, 11, 0.4)' : 'rgba(139, 92, 246, 0.4)',
        lineWidth: 1,
        lineStyle: 3,
        lastValueVisible: false,
        priceLineVisible: false,
        crosshairMarkerVisible: false,
      });
      borderSeries.setData([
        { time: startTime, value: bottomPrice },
        { time: endTime, value: bottomPrice },
      ]);
      fvgZoneSeries.push(borderSeries);
    } catch (e) {
      console.error('FVG zone error:', e);
    }
  });

  // Create markers for FVGs
  window.fvgMarkers = fvgs.filter(fvg => fvg.active).map(fvg => ({
    time: fvg.timestamp + IST_OFFSET,
    position: fvg.direction === 'BULLISH' ? 'belowBar' : 'aboveBar',
    color: fvg.direction === 'BULLISH' ? '#f59e0b' : '#8b5cf6',
    shape: 'circle',
    text: 'FVG',
  }));
}

function updateAllMarkers() {
  const showOB = document.getElementById('toggleOB')?.checked;
  const showFVG = document.getElementById('toggleFVG')?.checked;
  const showKEY = document.getElementById('toggleKEY')?.checked;
  
  console.log(`📊 Updating Markers: OB=${showOB}, FVG=${showFVG}, KEY=${showKEY}`);
  
  const markerMap = new Map(); // Map time -> markers
  
  const process = (markers, type) => {
    if (!markers) return;
    markers.forEach(m => {
      if (!markerMap.has(m.time)) markerMap.set(m.time, []);
      markerMap.get(m.time).push({ ...m, type });
    });
  };
  
  if (showOB) process(window.obMarkers, 'OB');
  if (showFVG) process(window.fvgMarkers, 'FVG');
  
  const finalMarkers = [];
  markerMap.forEach((list, time) => {
    if (list.length === 1) {
      finalMarkers.push(list[0]);
    } else {
      // Merge overlapping markers
      const types = [...new Set(list.map(l => l.type))].sort();
      const merged = { ...list[0] };
      merged.text = types.join('+');
      finalMarkers.push(merged);
    }
  });
  
  // Add BOS and others that shouldn't be merged
  if (window.bosMarkers) finalMarkers.push(...window.bosMarkers);
  
  if (series5m) {
    series5m.setMarkers(finalMarkers.sort((a, b) => a.time - b.time));
  }
}

function renderSignals(signals) {
  const container = document.getElementById('signalsContainer');
  
  // Filter out advisory / waiting / placeholder signals
  const activeSignals = (signals || [])
    .map((sig, origIdx) => ({ sig, origIdx }))
    .filter(item => !item.sig.advisory_only && item.sig.type !== 'WAITING' && item.sig.type !== 'WATCH');

  document.getElementById('signalCount').textContent = activeSignals.length;

  if (!activeSignals.length) {
    container.innerHTML = '<div class="empty-state"><div class="empty-icon">📡</div><div class="empty-text">No active signals</div></div>';
    container.classList.remove('has-multiple-signals');
    return;
  }

  if (activeSignals.length > 1) {
    container.classList.add('has-multiple-signals');
  } else {
    container.classList.remove('has-multiple-signals');
  }

  const strikes = analysisData?.strike_recommendations || [];
  const bestStrike = strikes[0];

  container.innerHTML = activeSignals.map(({ sig, origIdx }, i) => {
    const isCall = sig.type === 'CALL';
    const isAdvisory = sig.advisory_only === true;
    const confClass = sig.confidence >= 70 ? 'high' : sig.confidence >= 50 ? 'medium' : 'low';
    const strategyName = sig.strategy || 'Strategy 1: OB + FVG';

    // Build AI rationale & strike info
    let aiInfo = '';
    if (sig.rationale) {
      aiInfo = `<div class="signal-reason" style="color:var(--text-muted); font-style:italic; border-left:2px solid var(--cyan); padding-left:6px; margin: 6px 0;">AI: ${sig.rationale}</div>`;
    }

    let strikeInfo = '';
    const expiry = analysisData?.expiry;
    const expiryStr = expiry ? `${expiry.date} (${expiry.day})` : '';
    if (bestStrike && !isAdvisory) {
      strikeInfo = `<div style="display:flex; justify-content:space-between; align-items:center; background:rgba(255,255,255,0.02); padding:6px; border-radius:4px; margin-bottom:8px;">
        <span style="font-weight:700; color:var(--cyan); font-family:'JetBrains Mono',monospace;">${bestStrike.strike} ${isCall ? 'CE' : 'PE'}</span>
        <span style="font-size:11px; color:var(--text-muted);">LTP: <span style="color:var(--text); font-family:'JetBrains Mono',monospace; font-weight:600;">₹${bestStrike.ltp?.toFixed(2) || '--'}</span></span>
      </div>`;
    }

    // Prices
    let priceInfo = '';
    if (!isAdvisory) {
      const isSpotFallback = !bestStrike;
      const optionBuy = bestStrike ? (bestStrike.locked_price || bestStrike.ltp || 0) : (sig.entry_price || 0);
      const optionSl = bestStrike ? (bestStrike.sl || optionBuy - 12.0) : (sig.sl || 0);
      const optionTgt = bestStrike ? (bestStrike.target || optionBuy + 24.0) : (sig.target || 0);
      const labelPrefix = isSpotFallback ? 'SPOT ' : '';

      priceInfo = `
        <div class="signal-price-grid">
          <div class="signal-price-item">
            <div class="signal-price-label">${labelPrefix}ENTRY</div>
            <div class="signal-price-value" style="color:var(--cyan)">₹${optionBuy.toFixed(1)}</div>
          </div>
          <div class="signal-price-item">
            <div class="signal-price-label">${labelPrefix}SL</div>
            <div class="signal-price-value" style="color:var(--text)">₹${optionSl.toFixed(1)}</div>
          </div>
          <div class="signal-price-item">
            <div class="signal-price-label">${labelPrefix}TARGET</div>
            <div class="signal-price-value" style="color:var(--text)">₹${optionTgt.toFixed(1)}</div>
          </div>
        </div>
      `;
    }

    if (isAdvisory) {
      return `<div class="signal-card" style="opacity:0.7">
        <div class="signal-header">
          <span class="signal-type ${isCall ? 'call' : 'put'}">${sig.type} WATCH</span>
          <span class="strategy-label" style="font-size:9px; color:var(--text-dim); text-transform:uppercase; font-weight:600; background:rgba(255,255,255,0.05); padding:2px 6px; border-radius:4px; margin-left:8px;">${strategyName}</span>
          <span class="confidence-badge" style="background:rgba(100,116,139,0.2);color:var(--text-muted)">WATCHING</span>
        </div>
        <div class="signal-reason">${sig.reason}</div>
        <div class="signal-zone" style="margin-top:8px">Spot: ${document.getElementById('spotPrice')?.textContent || '--'}</div>
      </div>`;
    }

    return `<div class="signal-card ${sig.confidence >= 80 ? 'high-conf' : ''}">
      <div class="signal-header">
        <span class="signal-type ${isCall ? 'call' : 'put'}">${sig.type} BUY</span>
        <span class="strategy-label" style="font-size:9px; color:var(--text-dim); text-transform:uppercase; font-weight:600; background:rgba(255,255,255,0.05); padding:2px 6px; border-radius:4px; margin-left:8px;">${strategyName}</span>
        <span class="confidence-badge confidence-${confClass}">TECH: ${Number(sig.tech_confidence || sig.confidence).toFixed(1)}% | AI: ${Number(sig.ai_confidence || sig.confidence).toFixed(1)}%</span>
      </div>
      <div class="signal-reason">${sig.reason}</div>
      ${aiInfo}
      ${strikeInfo}
      ${priceInfo}
      <div class="confidence-meter"><div class="confidence-fill ${confClass}" style="width:${sig.confidence}%"></div></div>
      <div class="signal-actions">
        <button class="btn-buy" onclick="openOrderFromSignal(${origIdx})">BUY</button>
        <button class="btn-skip" onclick="skipSignal(${origIdx}, ${i})">SKIP</button>
      </div>
    </div>`;
  }).join('');
}

function renderStrikes(strikes) {
  const container = document.getElementById('strikesContainer');
  if (!strikes || !strikes.length) {
    container.innerHTML = '<div class="empty-state"><div class="empty-text">Waiting for signal...</div></div>';
    return;
  }
  
  if (!selectedStrikeSymbol && strikes.length > 0) {
    selectedStrikeSymbol = strikes[0].symbol;
    selectedStrikePremium = strikes[0].ltp || 0;
  }
  
  container.innerHTML = strikes.map((s, i) => {
    const isSelected = selectedStrikeSymbol === s.symbol;
    return `
      <div class="strike-item ${isSelected?'selected':''}" onclick="selectStrikeForCalc('${s.symbol}', ${s.ltp || 0})">
        <div class="strike-info">
          <span class="strike-value">${s.strike} ${s.symbol.includes('CE')?'CE':'PE'}</span>
          <span class="strike-label">OI: ${(s.oi/100000).toFixed(1)}L | Vol: ${(s.volume/100000).toFixed(1)}L</span>
        </div>
        <div class="strike-premium">₹${s.ltp?.toFixed(2)}</div>
      </div>
    `;
  }).join('');
  
  updateRiskCalc();
}

let lastPositionsJSON = "";
function renderPositions(positions) {
  const currentJSON = JSON.stringify(positions);
  if (currentJSON === lastPositionsJSON) return;
  lastPositionsJSON = currentJSON;

  const container = document.getElementById('positionsContainer');
  const activePositions = positions ? positions.filter(p => p.qty !== 0) : [];
  
  // Calculate total PnL
  let totalPnl = 0;
  if (positions) {
    positions.forEach(p => { totalPnl += (p.pl || 0); });
  }

  // Render in drawer
  if (!activePositions.length) {
    container.innerHTML = '<div class="empty-state"><div class="empty-text">No open positions</div></div>';
  } else {
    container.innerHTML = activePositions.map(p => {
      const pnl = p.pl || 0;
      const side = p.side > 0 ? 'LONG' : 'SHORT';
      return `<div class="position-item">
        <div>
          <div style="font-weight:600;font-size:12px">${p.symbol}</div>
          <div style="font-size:10px;color:var(--text-muted)">${side} · Qty: ${Math.abs(p.qty)} · Avg: ₹${p.buyAvg?.toFixed(2) || p.sellAvg?.toFixed(2) || p.entryPrice?.toFixed(2) || '0.00'}</div>
        </div>
        <div style="text-align:right">
          <div class="${pnl >= 0 ? 'pnl-positive' : 'pnl-negative'}" style="font-family:'JetBrains Mono';font-weight:600">
            ${pnl > 0 ? '+' : (pnl < 0 ? '-' : '')}₹${Math.abs(pnl).toFixed(2)}
          </div>
          <div style="font-size:10px;color:var(--text-muted)">LTP: ₹${p.ltp?.toFixed(2)}</div>
        </div>
      </div>`;
    }).join('');
  }

  // Update Active Trade Strip
  const strip = document.getElementById('activeTradeStrip');
  const stripContent = document.getElementById('activeTradeContent');
  if (activePositions.length > 0) {
    // Show only the first active position
    const p = activePositions[0];
    const pnl = p.pl || 0;
    const sign = pnl > 0 ? '+' : '';
    const color = pnl >= 0 ? 'var(--green)' : 'var(--red)';
    const strikeMatch = p.symbol.match(/\d{5}(CE|PE)/);
    const shortSymbol = strikeMatch ? strikeMatch[0] : p.symbol;
    const avg = p.buyAvg || p.sellAvg || p.entryPrice || 0;
    
    let slStr = "--";
    let tgStr = "--";
    if (typeof lastKnownActiveTrades !== 'undefined' && lastKnownActiveTrades) {
      const at = lastKnownActiveTrades.find(t => t.symbol === p.symbol);
      if (at) {
        slStr = at.sl_price ? `₹${at.sl_price.toFixed(1)}` : "--";
        tgStr = (at.target_price && at.target_price !== at.entry_price) ? `₹${at.target_price.toFixed(1)}` : "None (Trailing)";
      }
    }
    
    stripContent.innerHTML = `ACTIVE: NIFTY ${shortSymbol} <span style="color:var(--text-dim);margin:0 8px">|</span> Entry: ₹${avg.toFixed(1)} <span style="color:var(--text-dim);margin:0 8px">|</span> SL: ${slStr} <span style="color:var(--text-dim);margin:0 8px">|</span> TG: ${tgStr} <span style="color:var(--text-dim);margin:0 8px">|</span> LTP: ₹${p.ltp?.toFixed(1) || '--'} <span style="color:var(--text-dim);margin:0 8px">|</span> PnL: <span style="color:${color}">${sign}₹${Math.abs(pnl).toFixed(0)}</span>`;
    strip.classList.remove('hidden');
    // Change strip border/bg based on profit
    if (pnl >= 0) {
      strip.style.background = 'linear-gradient(90deg,rgba(34,197,94,0.08),rgba(6,182,212,0.08))';
      strip.style.borderTopColor = 'rgba(34,197,94,0.2)';
    } else {
      strip.style.background = 'linear-gradient(90deg,rgba(239,68,68,0.08),rgba(6,182,212,0.08))';
      strip.style.borderTopColor = 'rgba(239,68,68,0.2)';
    }
  } else {
    strip.classList.add('hidden');
  }

  updatePnlDisplays(totalPnl);
}

let lastOrdersJSON = "";
function renderOrders(orders) {
  const currentJSON = JSON.stringify(orders);
  if (currentJSON === lastOrdersJSON) return;
  lastOrdersJSON = currentJSON;

  const container = document.getElementById('ordersContainer');
  if (!orders || !orders.length) {
    container.innerHTML = '<div class="no-signal"><div class="no-signal-text">No orders today</div></div>';
    return;
  }

  container.innerHTML = orders.slice(-5).reverse().map(o => {
    const side = o.side > 0 ? 'BUY' : 'SELL';
    const statusColor = o.status === 2 ? 'var(--bullish)' : o.status === 1 ? 'var(--accent-yellow)' : 'var(--text-muted)';
    return `<div class="position-item">
      <div>
        <div style="font-weight:600;font-size:12px">${o.symbol}</div>
        <div style="font-size:10px;color:var(--text-muted)">${side} · Qty: ${o.qty}</div>
      </div>
      <div style="color:${statusColor};font-size:11px;font-weight:600">
        ${o.status === 2 ? 'FILLED' : o.status === 1 ? 'PENDING' : 'CANCELLED'}
      </div>
    </div>`;
  }).join('');
}


// ===== RISK CALCULATOR & TRADING JOURNAL =====
function getLotSize(symbol) {
  const sym = symbol.toUpperCase();
  if (sym.includes("BANKNIFTY")) return 30;
  if (sym.includes("FINNIFTY")) return 60;
  if (sym.includes("MIDCPNIFTY") || sym.includes("MIDCAP")) return 120;
  if (sym.includes("NIFTY")) return 65;
  return 65;
}

function updateRiskCalc() {
  const slider = document.getElementById('riskSlider');
  if (!slider) return;
  const riskPct = parseFloat(slider.value) || 2;
  
  const riskPercentageEl = document.getElementById('calcRiskPercentage');
  if (riskPercentageEl) {
    riskPercentageEl.textContent = riskPct + '%';
  }
  
  const marginEl = document.getElementById('calcMargin');
  if (marginEl) {
    marginEl.textContent = '₹' + Math.round(currentAvailableMargin).toLocaleString('en-IN');
  }
  
  const premiumEl = document.getElementById('calcPremium');
  if (premiumEl) {
    premiumEl.textContent = selectedStrikePremium > 0 ? '₹' + selectedStrikePremium.toFixed(2) : '₹--';
  }
  
  const qtyEl = document.getElementById('calcSuggestedQty');
  if (qtyEl) {
    if (selectedStrikePremium > 0 && currentAvailableMargin > 0) {
      const riskAmt = currentAvailableMargin * (riskPct / 100);
      const suggestedQty = riskAmt / selectedStrikePremium;
      const lotSize = getLotSize(activeSymbol);
      const numLots = Math.floor(suggestedQty / lotSize);
      const roundedQty = numLots * lotSize;
      
      qtyEl.textContent = `${roundedQty} (${numLots} Lots)`;
      
      // Auto-fill manual order quantity if modal is active or if input exists
      const modalQtyInput = document.getElementById('modalQty');
      if (modalQtyInput) {
        modalQtyInput.value = roundedQty > 0 ? roundedQty : lotSize;
      }
    } else {
      qtyEl.textContent = '-- (0)';
    }
  }
}

function selectStrikeForCalc(symbol, ltp) {
  selectedStrikeSymbol = symbol;
  selectedStrikePremium = ltp;
  
  // Update modal input symbol as well
  const modalSymInput = document.getElementById('modalSymbol');
  if (modalSymInput) {
    modalSymInput.value = symbol;
  }
  
  // Re-render strikes to update visual selected state
  if (analysisData && analysisData.strike_recommendations) {
    renderStrikes(analysisData.strike_recommendations);
  } else {
    updateRiskCalc();
  }
}

function loadJournalEntries() {
  const container = document.getElementById('journalHistoryList');
  if (!container) return;
  
  let entries = [];
  try {
    entries = JSON.parse(localStorage.getItem('trading_journal_entries')) || [];
  } catch (e) {
    entries = [];
  }
  
  if (!entries.length) {
    container.innerHTML = '<div style="color:var(--text-muted); font-size:11px; text-align:center; padding:10px;">No entries logged yet.</div>';
    return;
  }
  
  container.innerHTML = entries.map(e => `
    <div class="journal-entry-item">
      <div class="journal-entry-time">${e.time}</div>
      <div class="journal-entry-text" style="color:var(--text); word-break:break-word;">${e.text}</div>
    </div>
  `).join('');
}

function saveJournalEntry() {
  const input = document.getElementById('journalInput');
  if (!input) return;
  const text = input.value.trim();
  if (!text) {
    showToast('Please type a journal entry before submitting.', 'warning');
    return;
  }
  
  let entries = [];
  try {
    entries = JSON.parse(localStorage.getItem('trading_journal_entries')) || [];
  } catch (e) {
    entries = [];
  }
  
  const now = new Date();
  const timeStr = now.toLocaleDateString('en-IN') + ' ' + now.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  
  entries.unshift({ time: timeStr, text: text });
  
  if (entries.length > 50) {
    entries = entries.slice(0, 50);
  }
  
  localStorage.setItem('trading_journal_entries', JSON.stringify(entries));
  input.value = '';
  showToast('Journal entry submitted successfully.', 'success');
  loadJournalEntries();
}


// ===== ORDER MANAGEMENT =====
function openOrderFromSignal(idx) {
  if (!analysisData || !analysisData.signals[idx]) return;
  
  if (window.dailyCapReached) {
    showToast('⛔ Trade Cap Reached! Manual orders are locked under the 2-trade limit.', 'error');
    return;
  }
  if (window.isRegimeLockout) {
    showToast('⛔ Regime Lockout Active! Trades are blocked during flat/choppy markets.', 'error');
    return;
  }

  const sig = analysisData.signals[idx];
  const strikes = analysisData.strike_recommendations || [];
  const bestStrike = strikes[0];

  if (!bestStrike) {
    showToast('No strike available for this signal', 'error');
    return;
  }

  document.getElementById('modalTitle').textContent = `${sig.type} BUY — ${bestStrike.strike} ${sig.type === 'CALL' ? 'CE' : 'PE'}`;
  document.getElementById('modalSymbol').value = bestStrike.symbol;
  
  selectStrikeForCalc(bestStrike.symbol, bestStrike.ltp);

  // Auto-fill quantity using risk calculator suggestions
  let qtyVal = getLotSize(activeSymbol);
  const riskSlider = document.getElementById('riskSlider');
  const riskPct = riskSlider ? parseFloat(riskSlider.value) : 2;
  if (selectedStrikePremium > 0 && currentAvailableMargin > 0) {
    const riskAmt = currentAvailableMargin * (riskPct / 100);
    const suggestedQty = riskAmt / selectedStrikePremium;
    const lotSize = getLotSize(selectedStrikeSymbol || activeSymbol);
    const numLots = Math.floor(suggestedQty / lotSize);
    const roundedQty = numLots * lotSize;
    if (roundedQty > 0) {
      qtyVal = roundedQty;
    }
  }
  
  document.getElementById('modalQty').value = qtyVal;
  document.getElementById('modalSide').value = 'BUY';

  document.getElementById('orderModal').classList.remove('hidden');
}

function closeModal() {
  document.getElementById('orderModal').classList.add('hidden');
}

async function runSystemCheck() {
  showToast('Running System Integrity Check...', 'info');
  try {
    const resp = await fetch('/api/test-signal');
    const result = await resp.json();
    if (result.success) {
      showToast('✅ Signal Logic Verified. Refreshing history...', 'success');
      setTimeout(() => {
        fetchSignalHistory();
        refreshAll();
      }, 1000);
    } else {
      showToast('❌ System Check Failed: ' + result.message, 'error');
    }
  } catch (err) {
    showToast('❌ Connection Error during check', 'error');
  }
}

let isPlacingOrder = false;

async function confirmOrder() {
  if (isPlacingOrder) {
    showToast('⏳ Order is already being placed. Please wait...', 'info');
    return;
  }
  
  if (window.dailyCapReached) {

    showToast('⛔ Trade Cap Reached! Manual orders are locked under the 2-trade limit.', 'error');
    return;
  }
  if (window.isRegimeLockout) {
    showToast('⛔ Regime Lockout Active! Trades are blocked during flat/choppy markets.', 'error');
    return;
  }

  const symbol = document.getElementById('modalSymbol').value;
  const qty = parseInt(document.getElementById('modalQty').value);
  const side = document.getElementById('modalSide').value;
  const orderType = document.getElementById('modalOrderType').value;
  const product = document.getElementById('modalProduct').value;
  const slPoints = parseFloat(document.getElementById('modalSLPoints').value) || 0;
  const targetPoints = parseFloat(document.getElementById('modalTargetPoints').value) || 0;

  // Direction alignment check
  if (analysisData && analysisData.trend) {
    const currentTrend = (analysisData.trend.trend || "").toUpperCase();
    if (currentTrend === 'BULLISH' && symbol.toUpperCase().includes('PE')) {
      showToast('⛔ Manual trade blocked: Trend is bullish (only CALL CE trades allowed).', 'error');
      return;
    }
    if (currentTrend === 'BEARISH' && symbol.toUpperCase().includes('CE')) {
      showToast('⛔ Manual trade blocked: Trend is bearish (only PUT PE trades allowed).', 'error');
      return;
    }
  }

  closeModal();
  showToast(`Placing ${side} order for ${symbol}...`, 'info');

  try {
    const resp = await fetch('/api/order', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ 
        symbol, qty, side, order_type: orderType, product,
        sl_points: slPoints, target_points: targetPoints
      }),
    });
    const result = await resp.json();

    if (result.success) {
      showToast(`✅ Order placed! ID: ${result.order_id}`, 'success');
      setTimeout(() => { fetchPositions(); fetchFunds(); }, 2000);
    } else {
      showToast(`❌ Order failed: ${result.message}`, 'error');
    }
  } catch (e) {
    showToast('❌ Order error: ' + e.message, 'error');
  } finally {
    isPlacingOrder = false;
  }
}

async function skipSignal(idx, uiIdx) {
  if (uiIdx === undefined) uiIdx = idx;
  const cards = document.querySelectorAll('.signal-card');
  const skipBtn = cards[uiIdx] ? cards[uiIdx].querySelector('.btn-skip') : null;
  const buyBtn = cards[uiIdx] ? cards[uiIdx].querySelector('.btn-buy') : null;

  if (cards[uiIdx]) {
    cards[uiIdx].style.opacity = '0.5';
    cards[uiIdx].style.filter = 'grayscale(1)';
    cards[uiIdx].style.pointerEvents = 'none';
  }
  if (skipBtn) skipBtn.disabled = true;
  if (buyBtn) buyBtn.disabled = true;

  showToast('Skipping signal...', 'info');
  
  try {
    const resp = await fetch('/api/skip-signal', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ index: idx })
    });
    const result = await resp.json();
    if (result.success) {
      showToast('Signal skipped', 'success');
      
      // Immediately remove from local memory to prevent re-renders before next WS update
      if (analysisData && analysisData.signals && analysisData.signals[idx]) {
         analysisData.signals.splice(idx, 1);
         renderSignals(analysisData.signals);
         
         // Clear recommendations if no more signals
         if (analysisData.signals.length === 0) {
            analysisData.strike_recommendations = [];
            renderStrikes([]);
         }
      }
      
      // Refresh history panel
      fetchSignalHistory();
    } else {
      showToast('Failed to skip: ' + result.message, 'error');
      // Re-enable if failed
      if (cards[idx]) {
        cards[idx].style.opacity = '1';
        cards[idx].style.filter = 'none';
        cards[idx].style.pointerEvents = 'auto';
      }
      if (skipBtn) skipBtn.disabled = false;
      if (buyBtn) buyBtn.disabled = false;
    }
  } catch (e) {
    showToast('❌ Skip error: ' + e.message, 'error');
    if (cards[idx]) {
        cards[idx].style.opacity = '1';
        cards[idx].style.pointerEvents = 'auto';
    }
  }
}


// ===== TOAST =====
function showToast(message, type = 'info') {
  const container = document.getElementById('toastContainer');
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 4000);
}

// ===== SIGNAL HISTORY =====
let historyMinimized = false;
function toggleCard(cardId, expandedMaxHeight) {
  // v5.1 compatibility — drawer panels handle their own toggling now
  const card = document.getElementById(cardId);
  if (!card) return;
  const body = card.querySelector('.card-body, .card-content, .drawer-section-body');
  if (!body) return;
  const isHidden = body.style.display === 'none';
  body.style.display = isHidden ? '' : 'none';
}
function toggleHistory() { toggleCard('historyCard'); }
function toggleKeyLevels() { toggleCard('keyLevelsCard'); }

async function fetchSignalHistory() {
  if (historyMinimized) return;
  try {
    const resp = await fetch('/api/signal-history');
    const data = await resp.json();
    if (data.success && data.history) {
      renderSignalHistory(data.history);
    }
  } catch (err) {
    console.error("Failed to fetch signal history", err);
  }
}

function renderSignalHistory(history) {
  const container = document.getElementById('historyContainer');
  if (!history || history.length === 0) {
    container.innerHTML = '<div class="no-signal"><div class="no-signal-text">No recent history...</div></div>';
    return;
  }
  
  let html = '';
  history.forEach(item => {
    let actionClass = 'badge-advisory';
    if (item.action.includes('TRADED')) actionClass = 'badge-traded';
    else if (item.action.includes('FAILED') || item.action.includes('ERROR')) actionClass = 'badge-failed';
    else if (item.action.includes('SKIPPED')) {
      if (item.action.includes('Auto Off') || item.action.includes('No Strikes')) actionClass = 'badge-skipped';
      else actionClass = 'badge-advisory';
    }
    
    // Extract HH:MM:SS from timestamp if possible
    let timeStr = item.time;
    if (timeStr.includes(' ')) {
      timeStr = timeStr.split(' ')[1];
    }
    
    let tradeHtml = '';
    if (item.trade) {
      const t = item.trade;
      tradeHtml = `
        <div class="history-trade">
          ${t.strike} @ ${t.entry?.toFixed(1) || '--'} | SL: ${t.sl?.toFixed(1) || '--'} | TGT: ${t.target?.toFixed(1) || '--'}
        </div>
      `;
    }
    
    html += `
      <div class="history-item">
        <div class="history-time">${timeStr}</div>
        <div class="history-main">
          <span class="history-type" style="color: ${item.type==='CALL' ? 'var(--bullish)' : 'var(--bearish)'}">${item.type} NIFTY</span>
          <span class="history-badge ${actionClass}">${item.action}</span>
        </div>
        ${tradeHtml}
      </div>
    `;
  });
  
  container.innerHTML = html;
}

/**
 * Play a notification sound when an order is placed.
 * Uses Web Audio API — no external files needed.
 */
function playOrderSound(type = 'success') {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const now = ctx.currentTime;

    if (type === 'success') {
      // Rising two-tone chime for successful trade
      [440, 660, 880].forEach((freq, i) => {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = 'sine';
        osc.frequency.value = freq;
        gain.gain.setValueAtTime(0.3, now + i * 0.12);
        gain.gain.exponentialRampToValueAtTime(0.01, now + i * 0.12 + 0.3);
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start(now + i * 0.12);
        osc.stop(now + i * 0.12 + 0.35);
      });
    } else if (type === 'error') {
      // Low buzz for failed trade
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'square';
      osc.frequency.value = 200;
      gain.gain.setValueAtTime(0.2, now);
      gain.gain.exponentialRampToValueAtTime(0.01, now + 0.4);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(now);
      osc.stop(now + 0.45);
    }
  } catch (e) {
    console.log('Sound not available:', e);
  }
}

/**
 * Appends a new message to the Activity Log section
 */
function appendActivityLog(msg, level = 'info', time = null) {
  const container = document.getElementById('activityLog');
  const statusEl = document.getElementById('logStatus');
  if (!container) return;

  const timestamp = time || new Date().toLocaleTimeString([], { hour12: false });
  
  const entry = document.createElement('div');
  entry.className = `log-entry log-${level}`;
  
  entry.innerHTML = `
    <span class="log-time">[${timestamp}]</span>
    <span class="log-msg">${msg}</span>
  `;
  
  container.appendChild(entry);
  
  // Auto-scroll to bottom
  container.scrollTop = container.scrollHeight;
  
  // Limit to 100 entries to prevent memory issues
  while (container.childNodes.length > 100) {
    container.removeChild(container.firstChild);
  }
  
  // 🔊 Play sound on order events
  const msgLower = msg.toLowerCase();
  if (msgLower.includes('order placed') || msgLower.includes('auto-trade:') || msgLower.includes('auto-executing') || msgLower.includes('ai approved')) {
    playOrderSound('success');
  } else if (msgLower.includes('auto-trade failed') || msgLower.includes('order failed')) {
    playOrderSound('error');
  }
  
  // Update status text if it's a heartbeat/success
  if (statusEl && (level === 'success' || msg.includes('refreshed'))) {
    statusEl.textContent = 'ONLINE';
    statusEl.style.color = 'var(--bullish)';
  } else if (statusEl && level === 'error') {
    statusEl.textContent = 'ERROR DETECTED';
    statusEl.style.color = 'var(--bearish)';
  }
}

// ===== BETA v3 ADDITIONS =====

function renderSymbolTabs() {
  const container = document.getElementById('symbolTabs');
  if (!container || !activeScripts || activeScripts.length === 0) return;
  
  container.innerHTML = activeScripts.map(s => {
    const label = s.replace('NSE:', '').replace('-INDEX', '').replace('-EQ', '');
    const isActive = s === activeSymbol;
    return `<div class="symbol-tab ${isActive ? 'active' : ''}" onclick="selectScript('${s}')">${label}</div>`;
  }).join('');
}

// Price flash animation on spot price change
let lastSpotPrice = 0;
const originalUpdateSpotLive = updateSpotLive;
updateSpotLive = function(data) {
  const spot = data.spot || data.lp || 0;
  const spotEl = document.getElementById('spotPrice');
  
  if (spotEl && lastSpotPrice > 0 && spot !== lastSpotPrice) {
    spotEl.classList.remove('price-flash-up', 'price-flash-down');
    void spotEl.offsetWidth; // Force reflow
    spotEl.classList.add(spot > lastSpotPrice ? 'price-flash-up' : 'price-flash-down');
  }
  lastSpotPrice = spot;
  
  originalUpdateSpotLive(data);
  
  // Update footer timestamp
  const footerUpdate = document.getElementById('footerLastUpdate');
  if (footerUpdate) {
    footerUpdate.textContent = 'Last: ' + new Date().toLocaleTimeString([], { hour12: false });
  }
};

async function fetchVersion() {
  try {
    const resp = await fetch('/api/version');
    const data = await resp.json();
    const badge = document.getElementById('versionBadge');
    const footer = document.getElementById('footerVersion');
    if (badge) badge.textContent = data.version || 'v3.0';
    if (footer) footer.textContent = `${data.name || 'ControlN Trading'} ${data.version || ''}`;
    
    const footerSymbols = document.getElementById('footerSymbols');
    if (footerSymbols) footerSymbols.textContent = `${data.active_symbols || 1} symbol${data.active_symbols !== 1 ? 's' : ''}`;
    
    const footerAI = document.getElementById('footerAI');
    if (footerAI) {
      footerAI.textContent = data.ai_active ? `AI ${data.ai_provider}: Active` : 'AI: Offline';
      footerAI.style.color = data.ai_active ? 'var(--green)' : 'var(--red)';
    }
    
    // Server Uptime
    const footerUptime = document.getElementById('footerUptime');
    if (footerUptime && data.uptime) {
      footerUptime.textContent = `${data.uptime} (since ${data.started_at})`;
    }
  } catch (e) {
    console.log('Version fetch failed:', e);
  }
}
// Refresh uptime every 30s
startSafePolling(fetchVersion, 30000);
// ===== ACCOUNT SETTINGS =====
async function openAccountModal() {
  const modal = document.getElementById('accountModal');
  modal.style.display = 'flex';
  
  try {
    const res = await fetch('/api/user/settings');
    const data = await res.json();
    if(data.client_id) {
      document.getElementById('accClientId').value = data.client_id;
      document.getElementById('fyersConnectBtn').style.display = 'block';
    } else if(data.has_master_app) {
      document.getElementById('accClientId').placeholder = 'Using platform credentials (optional)';
      document.getElementById('accSecretId').placeholder = 'Using platform credentials (optional)';
      document.getElementById('accFyersPin').placeholder = 'Using platform PIN (optional)';
      document.getElementById('fyersConnectBtn').style.display = 'block';
    }
    if(data.secret_id) document.getElementById('accSecretId').value = data.secret_id;
    if(data.fyers_pin) document.getElementById('accFyersPin').value = data.fyers_pin;
  } catch (e) {
    console.error("Failed to load account settings");
  }
}

async function saveAccountSettings() {
  const client_id = document.getElementById('accClientId').value;
  const secret_id = document.getElementById('accSecretId').value;
  const fyers_pin = document.getElementById('accFyersPin').value;
  
  if(!client_id || !secret_id) return alert("Please enter both IDs");
  
  try {
    const res = await fetch('/api/user/settings', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({client_id, secret_id, fyers_pin})
    });
    const data = await res.json();
    if(data.success) {
      alert("Settings saved! Now click 'Connect Fyers' to complete the connection.");
      document.getElementById('fyersConnectBtn').style.display = 'block';
    }
  } catch (e) {
    alert("Failed to save settings");
  }
}

function toggleActivityConsole() {
  const consoleEl = document.getElementById('activityConsole');
  if (consoleEl) {
    consoleEl.classList.toggle('minimized');
  }
}

// Drag to resize activity console
(function() {
  setTimeout(() => {
    const resizer = document.getElementById('consoleResizer');
    const consoleBody = document.querySelector('.console-body');
    const activityConsole = document.getElementById('activityConsole');
    
    if (!resizer || !consoleBody || !activityConsole) return;
    
    let isResizing = false;
    let startY;
    let startHeight;
    
    resizer.addEventListener('mousedown', function(e) {
      isResizing = true;
      startY = e.clientY;
      startHeight = consoleBody.offsetHeight;
      document.body.style.cursor = 'ns-resize';
      document.body.style.userSelect = 'none';
    });
    
    document.addEventListener('mousemove', function(e) {
      if (!isResizing) return;
      
      const diff = startY - e.clientY;
      const newHeight = startHeight + diff;
      
      if (newHeight >= 50 && newHeight <= window.innerHeight * 0.6) {
        consoleBody.style.height = newHeight + 'px';
        activityConsole.classList.remove('minimized');
      }
    });
    
    document.addEventListener('mouseup', function() {
      if (isResizing) {
        isResizing = false;
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
      }
    });
  }, 1000); // Wait for DOM to be fully ready
})();

// ===== PNL HISTORY =====
let globalPnLHistory = []; // currently viewed history cache for exporting CSV
let globalPnLLiveHistory = [];
let globalPnLPaperHistory = [];
let currentPnLMode = 'live';

async function openPnLHistoryModal() {
  const modal = document.getElementById('pnlHistoryModal');
  modal.style.display = 'flex';
  
  // Clear previous data
  document.getElementById('pnlHistoryTableBody').innerHTML = '<tr><td colspan="3" class="mw-loading">Loading PnL history...</td></tr>';
  
  try {
    const res = await fetch('/api/pnl-history');
    const data = await res.json();
    if (!data.success) {
      document.getElementById('pnlHistoryTableBody').innerHTML = `<tr><td colspan="3" class="mw-loading text-danger">⚠️ ${data.message}</td></tr>`;
      return;
    }
    
    globalPnLLiveHistory = data.history || [];
    globalPnLPaperHistory = data.paper_history || [];
    
    currentPnLMode = data.is_paper_mode ? 'paper' : 'live';
    updatePnLModeButtons();
    
    globalPnLHistory = currentPnLMode === 'paper' ? globalPnLPaperHistory : globalPnLLiveHistory;
    renderPnLHistory(globalPnLHistory);
  } catch (e) {
    console.error("Failed to load PnL history:", e);
    document.getElementById('pnlHistoryTableBody').innerHTML = '<tr><td colspan="3" class="mw-loading text-danger">⚠️ Connection failed</td></tr>';
  }
}

function switchPnLMode(mode) {
  currentPnLMode = mode;
  updatePnLModeButtons();
  globalPnLHistory = mode === 'paper' ? globalPnLPaperHistory : globalPnLLiveHistory;
  renderPnLHistory(globalPnLHistory);
}

function updatePnLModeButtons() {
  const btnLive = document.getElementById('pnlBtnLive');
  const btnPaper = document.getElementById('pnlBtnPaper');
  if (!btnLive || !btnPaper) return;
  
  if (currentPnLMode === 'live') {
    btnLive.style.background = 'var(--cyan)';
    btnLive.style.color = '#000';
    btnPaper.style.background = 'transparent';
    btnPaper.style.color = 'var(--text-muted)';
  } else {
    btnPaper.style.background = 'var(--cyan)';
    btnPaper.style.color = '#000';
    btnLive.style.background = 'transparent';
    btnLive.style.color = 'var(--text-muted)';
  }
}

function renderPnLHistory(history) {
  const tbody = document.getElementById('pnlHistoryTableBody');
  tbody.innerHTML = '';
  
  if (history.length === 0) {
    tbody.innerHTML = '<tr><td colspan="3" class="mw-loading">No history found. Start trading to log performance!</td></tr>';
    document.getElementById('pnlStatNet').textContent = '₹0.00';
    document.getElementById('pnlStatWinRate').textContent = '0.0%';
    document.getElementById('pnlStatBest').textContent = '₹0.00';
    document.getElementById('pnlStatWorst').textContent = '₹0.00';
    // Clear paths
    document.getElementById('chartLinePath').setAttribute('d', '');
    document.getElementById('chartAreaPath').setAttribute('d', '');
    document.getElementById('pnlHeatmap').innerHTML = '';
    return;
  }
  
  // 1. Calculate KPI Statistics
  let netPnL = 0;
  let profitableDays = 0;
  let totalDays = 0;
  let bestDayVal = -Infinity;
  let worstDayVal = Infinity;
  let bestDayDate = "-";
  let worstDayDate = "-";
  
  // Sort ascending for cumulative curve calculations
  const chronologicalHistory = [...history].reverse();
  let cumulativePnL = 0;
  const equityPoints = chronologicalHistory.map(day => {
    cumulativePnL += day.pnl;
    return cumulativePnL;
  });
  
  history.forEach(day => {
    netPnL += day.pnl;
    totalDays++;
    if (day.pnl > 0) profitableDays++;
    if (day.pnl > bestDayVal) {
      bestDayVal = day.pnl;
      bestDayDate = day.date;
    }
    if (day.pnl < worstDayVal) {
      worstDayVal = day.pnl;
      worstDayDate = day.date;
    }
  });
  
  if (bestDayVal === -Infinity) bestDayVal = 0;
  if (worstDayVal === Infinity) worstDayVal = 0;
  
  const winRate = totalDays > 0 ? (profitableDays / totalDays) * 100 : 0;
  
  // Render KPI Stats
  const netEl = document.getElementById('pnlStatNet');
  netEl.textContent = `${netPnL >= 0 ? '+' : ''}₹${netPnL.toLocaleString('en-IN', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
  netEl.className = `pnl-stat-val ${netPnL > 0 ? 'pnl-positive' : (netPnL < 0 ? 'pnl-negative' : '')}`;
  
  document.getElementById('pnlStatWinRate').textContent = `${winRate.toFixed(1)}%`;
  
  document.getElementById('pnlStatBest').textContent = `₹${bestDayVal.toLocaleString('en-IN', {maximumFractionDigits: 0})} (${bestDayDate.slice(5)})`;
  document.getElementById('pnlStatWorst').textContent = `₹${worstDayVal.toLocaleString('en-IN', {maximumFractionDigits: 0})} (${worstDayDate.slice(5)})`;
  
  // 2. Render Equity Curve SVG
  renderEquityChart(equityPoints);
  
  // 3. Render Heatmap (last 180 days / ~26 weeks)
  renderHeatmapGrid(history);
  
  // 4. Populate Breakdown Table
  history.forEach(day => {
    const tr = document.createElement('tr');
    if (day.active) {
      tr.style.background = 'rgba(6,182,212,0.08)';
      tr.style.fontWeight = 'bold';
    }
    
    const pnlSign = day.pnl > 0 ? '+' : '';
    const pnlClass = day.pnl > 0 ? 'pnl-badge profit' : (day.pnl < 0 ? 'pnl-badge loss' : 'pnl-badge zero');
    
    tr.innerHTML = `
      <td>${day.date} ${day.active ? ' <span style="font-size:8px; background:var(--cyan); color:var(--bg); padding:1px 4px; border-radius:3px;">TODAY</span>' : ''}</td>
      <td>${day.trades}</td>
      <td><span class="${pnlClass}">${pnlSign}₹${day.pnl.toLocaleString('en-IN', {minimumFractionDigits: 2, maximumFractionDigits: 2})}</span></td>
    `;
    tbody.appendChild(tr);
  });
}

function renderEquityChart(points) {
  const chartLine = document.getElementById('chartLinePath');
  const chartArea = document.getElementById('chartAreaPath');
  
  if (points.length === 0) return;
  
  // Add a starting point of 0 if we only have 1 data point to show a line
  const displayPoints = points.length === 1 ? [0, ...points] : points;
  
  const width = 600;
  const height = 150;
  const padding = 15;
  
  const minVal = Math.min(...displayPoints, 0);
  const maxVal = Math.max(...displayPoints, 0);
  const range = maxVal - minVal === 0 ? 1000 : maxVal - minVal;
  
  const pointsX = displayPoints.map((_, i) => padding + (i / (displayPoints.length - 1)) * (width - 2 * padding));
  const pointsY = displayPoints.map(val => height - padding - ((val - minVal) / range) * (height - 2 * padding));
  
  // Build SVG Path
  let pathD = `M ${pointsX[0]} ${pointsY[0]}`;
  for (let i = 1; i < displayPoints.length; i++) {
    pathD += ` L ${pointsX[i]} ${pointsY[i]}`;
  }
  
  chartLine.setAttribute('d', pathD);
  
  // Build Area Path (close the shape to the bottom of the SVG)
  const areaD = `${pathD} L ${pointsX[pointsX.length - 1]} ${height} L ${pointsX[0]} ${height} Z`;
  chartArea.setAttribute('d', areaD);
}

function renderHeatmapGrid(history) {
  const heatmapEl = document.getElementById('pnlHeatmap');
  heatmapEl.innerHTML = '';
  
  // We want to render a 26-column by 7-row grid (182 days / ~6 months of data)
  const dateMap = {};
  history.forEach(day => {
    dateMap[day.date] = day.pnl;
  });
  
  const daysToShow = 182; // 26 weeks
  const today = new Date();
  const dateList = [];
  
  // Start from 181 days ago up to today
  for (let i = daysToShow - 1; i >= 0; i--) {
    const d = new Date(today);
    d.setDate(today.getDate() - i);
    const dateStr = d.toISOString().split('T')[0];
    dateList.push(dateStr);
  }
  
  // Populate the grid
  dateList.forEach(dateStr => {
    const cell = document.createElement('div');
    const pnl = dateMap[dateStr];
    
    let colorClass = 'neutral';
    let tooltipVal = `${dateStr}: No Trades`;
    
    if (pnl !== undefined) {
      tooltipVal = `${dateStr}: ${pnl >= 0 ? '+' : ''}₹${pnl.toLocaleString('en-IN', {maximumFractionDigits: 0})}`;
      if (pnl > 1000) colorClass = 'profit-high';
      else if (pnl > 0) colorClass = 'profit-low';
      else if (pnl < -1000) colorClass = 'loss-high';
      else if (pnl < 0) colorClass = 'loss-low';
    }
    
    cell.className = `heatmap-day ${colorClass}`;
    cell.setAttribute('data-tooltip', tooltipVal);
    heatmapEl.appendChild(cell);
  });
}

function exportPnLHistoryToCSV() {
  if (!globalPnLHistory || globalPnLHistory.length === 0) return alert("No history to export.");
  
  let csvContent = "Date,Trades,PnL\n";
  globalPnLHistory.forEach(day => {
    csvContent += `${day.date},${day.trades},${day.pnl}\n`;
  });
  
  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.setAttribute("href", url);
  link.setAttribute("download", `ControlN_Trading_PnL_History_${new Date().toISOString().split('T')[0]}.csv`);
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

// ═══ ONBOARDING WIZARD ═══
let onboardingDismissed = false;

function closeOnboardingWizard() {
  onboardingDismissed = true;
  const wizard = document.getElementById('onboardingWizard');
  if (wizard) wizard.classList.add('hidden');
}

async function updateOnboardingWizard() {
  if (onboardingDismissed) return;
  const wizard = document.getElementById('onboardingWizard');
  if (!wizard) return;

  let client_id = "";
  let secret_id = "";
  try {
    const res = await fetch('/api/user/settings');
    const data = await res.json();
    client_id = data.client_id || "";
    secret_id = data.secret_id || "";
  } catch (e) {
    console.error("Onboarding settings fetch failed", e);
  }

  const hasKeys = !!(client_id && secret_id) || data.has_master_app;
  const isConnected = !!(window.wsConnectedState);
  const isAutoEnabled = document.getElementById('autoToggle')?.checked || false;

  const step1 = document.getElementById('step1');
  const step2 = document.getElementById('step2');
  const step3 = document.getElementById('step3');
  const onboardingDesc = document.getElementById('onboardingDesc');
  const onboardingBtn = document.getElementById('onboardingBtn');

  // Reset classes
  [step1, step2, step3].forEach(s => {
    if (s) s.className = 'onboarding-step';
  });

  if (!hasKeys) {
    wizard.classList.remove('hidden');
    if (step1) step1.classList.add('active');
    if (onboardingDesc) onboardingDesc.textContent = "Please connect your Fyers API account first to start auto-trading.";
    if (onboardingBtn) {
      onboardingBtn.textContent = "Setup API Keys";
      onboardingBtn.onclick = () => openAccountModal();
    }
  } else if (!isConnected) {
    wizard.classList.remove('hidden');
    if (step1) step1.classList.add('completed');
    if (step2) step2.classList.add('active');
    if (onboardingDesc) onboardingDesc.textContent = "Your API Keys are saved. Now link your active Fyers trading session for today.";
    if (onboardingBtn) {
      onboardingBtn.textContent = "Login to Fyers";
      onboardingBtn.onclick = () => openAccountModal();
    }
  } else if (!isAutoEnabled) {
    wizard.classList.remove('hidden');
    if (step1) step1.classList.add('completed');
    if (step2) step2.classList.add('completed');
    if (step3) step3.classList.add('active');
    if (onboardingDesc) onboardingDesc.textContent = "Almost there! Toggle 'Auto Trade' ON in the header to activate automated strategy execution.";
    if (onboardingBtn) {
      onboardingBtn.textContent = "Enable Auto-Trade";
      onboardingBtn.onclick = async () => {
        const toggle = document.getElementById('autoToggle');
        if (toggle) {
          toggle.checked = true;
          await toggleAutomation();
        }
      };
    }
  } else {
    wizard.classList.add('hidden');
  }
}

async function fetchMarketSummary() {
  try {
    const res = await fetch('/api/market-summary');
    if (res.ok) {
      const data = await res.json();
      const elSentiment = document.getElementById('aiNewsSentiment');
      const elSummary = document.getElementById('aiNewsSummary');
      
      if (elSentiment) {
        elSentiment.innerText = data.trend || 'NEUTRAL';
        if (data.trend === 'BULLISH') elSentiment.style.color = '#00ff88';
        else if (data.trend === 'BEARISH') elSentiment.style.color = '#ff3366';
        else elSentiment.style.color = '#ffa500';
      }
      if (elSummary) {
        elSummary.innerText = data.summary || 'No summary available.';
      }
    }
  } catch (e) {
    console.error('Failed to fetch market summary', e);
  }
}

// ─── Live Market News Headlines ───────────────────────────────────────────────
async function fetchMarketNews() {
  const container = document.getElementById('marketNewsList');
  const timeEl = document.getElementById('newsRefreshTime');
  if (!container) return;

  try {
    const res = await fetch('/api/market-news');
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    const items = (data.news || []).sort((a, b) => {
      const da = a.pubDate ? new Date(a.pubDate).getTime() : 0;
      const db = b.pubDate ? new Date(b.pubDate).getTime() : 0;
      return db - da; // newest first
    });

    if (timeEl && data.fetched_at) {
      timeEl.innerText = 'Updated: ' + data.fetched_at;
    }

    if (!items.length) {
      container.innerHTML = '<div style="color:var(--text-muted);font-size:12px;text-align:center;padding:12px;">No headlines available right now.</div>';
      return;
    }

    // Helper: format pubDate to relative time
    function relativeTime(pub) {
      if (!pub) return '';
      try {
        const d = new Date(pub);
        const diff = (Date.now() - d.getTime()) / 1000; // seconds
        if (diff < 60) return 'just now';
        if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
        if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
        return Math.floor(diff / 86400) + 'd ago';
      } catch { return ''; }
    }

    // Source badge colors
    const srcColors = {
      'NDTV Profit':    '#e64040',
      'Times of India': '#1a73e8',
      'Livemint':       '#00b5ad',
    };

    function buildCard(item) {
      const srcColor = srcColors[item.source] || '#888';
      const rel = relativeTime(item.pubDate);
      const link = item.link ? `href="${item.link}" target="_blank" rel="noopener"` : '';
      return `
        <a ${link} style="display:block; text-decoration:none; color:inherit;">
          <div style="
            padding: 7px 8px;
            border-radius: 6px;
            background: rgba(255,255,255,0.03);
            border: 1px solid rgba(255,255,255,0.05);
            transition: background 0.15s;
            cursor: pointer;
          " onmouseover="this.style.background='rgba(99,179,255,0.07)'" onmouseout="this.style.background='rgba(255,255,255,0.03)'">
            <div style="font-size:11px; font-weight:600; color:var(--text); line-height:1.35; margin-bottom:4px;">${item.title}</div>
            <div style="display:flex; align-items:center; gap:6px;">
              <span style="font-size:9px; font-weight:700; padding:1px 5px; border-radius:3px; background:${srcColor}22; color:${srcColor}; border:1px solid ${srcColor}44; letter-spacing:0.3px;">${item.source}</span>
              ${rel ? `<span style="font-size:9px; color:var(--text-dim);">${rel}</span>` : ''}
            </div>
          </div>
        </a>`;
    }

    const INITIAL = 4;
    const total = items.length;
    let expanded = false;

    function renderNews() {
      const visible = expanded ? items : items.slice(0, INITIAL);
      const cards = visible.map(buildCard).join('');
      const remaining = total - INITIAL;

      const toggleBtn = total > INITIAL ? `
        <button onclick="window._newsToggle()" style="
          width: 100%;
          margin-top: 4px;
          padding: 6px 0;
          background: rgba(99,179,255,0.06);
          border: 1px solid rgba(99,179,255,0.18);
          border-radius: 6px;
          color: #63b3ff;
          font-size: 11px;
          font-weight: 600;
          cursor: pointer;
          transition: background 0.15s;
          letter-spacing: 0.3px;
        " onmouseover="this.style.background='rgba(99,179,255,0.14)'" onmouseout="this.style.background='rgba(99,179,255,0.06)'">
          ${expanded ? '↑ Show less' : `↓ Show ${remaining} more`}
        </button>` : '';

      container.innerHTML = cards + toggleBtn;
    }

    window._newsToggle = () => {
      expanded = !expanded;
      renderNews();
    };

    renderNews();

  } catch (e) {
    console.error('Failed to fetch market news:', e);
    if (container.innerHTML.includes('Fetching')) {
      container.innerHTML = '<div style="color:var(--text-muted);font-size:11px;text-align:center;padding:8px;">⚠️ Could not load headlines. Retrying soon.</div>';
    }
  }
}

