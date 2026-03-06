/**
 * Options Monitor Agent - Dashboard Application
 * Main JavaScript file handling UI interactions, data fetching, and chart rendering
 */

// =============================================================================
// CONSTANTS
// =============================================================================

const CONFIG = {
    API_ENDPOINTS: {
        LATEST: '/api/latest',
        HISTORY: '/api/history',
        ALERTS: '/api/alerts',
        UNUSUAL: '/api/unusual',
        STATS: '/api/stats',
        BACKTEST: '/api/backtest',
        SPIKE_ALERTS: '/api/spike-alerts',
        ASK: '/api/ask',
        CYCLE_STATUS: '/api/cycle-status',
        RUN_CYCLE: '/api/run-cycle',
        CYCLE_LOG: '/api/cycle-log'
    },
    REFRESH_INTERVAL: 60000, // 60 seconds
    POLL_INTERVAL: 3000,     // 3 seconds for cycle status
    POLL_TIMEOUT: 300000     // 5 minutes max poll duration
};

// =============================================================================
// STATE
// =============================================================================

const STATE = {
    charts: {
        iv: null,
        pcr: null,
        history: null
    },
    pollInterval: null,
    cycleStartTime: null
};

// =============================================================================
// UTILITY FUNCTIONS
// =============================================================================

/**
 * Fetch JSON from API endpoint with error handling
 * @param {string} url - API endpoint URL
 * @returns {Promise<Object>} Parsed JSON response
 */
async function fetchJSON(url) {
    try {
        const response = await fetch(url);
        return await response.json();
    } catch (error) {
        console.error(`Error fetching ${url}:`, error);
        return { status: 'error', message: error.message };
    }
}

/**
 * Show notification to user
 * @param {string} message - Notification message
 * @param {string} type - Notification type ('info', 'success', 'error')
 */
function showNotif(message, type = 'info') {
    const colors = {
        info: '#3b82f6',
        success: '#10b981', 
        error: '#ef4444'
    };
    
    const notification = document.createElement('div');
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        padding: 14px 24px;
        background: ${colors[type]};
        color: white;
        border-radius: 10px;
        font-weight: 600;
        z-index: 10000;
        box-shadow: 0 4px 12px rgba(0,0,0,0.3);
    `;
    notification.textContent = message;
    document.body.appendChild(notification);
    
    setTimeout(() => {
        notification.style.opacity = '0';
        notification.style.transition = 'opacity 0.3s';
        setTimeout(() => notification.remove(), 300);
    }, 3000);
}

// =============================================================================
// DATA REFRESH FUNCTIONS  
// =============================================================================

/**
 * Refresh all dashboard data
 */
async function refreshData() {
    document.getElementById('last-update').textContent = new Date().toLocaleTimeString();
    
    const [latest, unusual, stats, backtest, spikeAlerts] = await Promise.all([
        fetchJSON(`${CONFIG.API_ENDPOINTS.LATEST}?hours=24`),
        fetchJSON(`${CONFIG.API_ENDPOINTS.UNUSUAL}?days=7`),
        fetchJSON(CONFIG.API_ENDPOINTS.STATS),
        fetchJSON(CONFIG.API_ENDPOINTS.BACKTEST),
        fetchJSON(CONFIG.API_ENDPOINTS.SPIKE_ALERTS)
    ]);
    
    if (latest.status === 'ok') updateTable(latest.data);
    if (stats.status === 'ok') updateStats(stats.data);
    if (unusual.status === 'ok') updateUnusual(unusual.data);
    if (backtest.status === 'ok') updateBacktest(backtest.data);
    if (spikeAlerts.status === 'ok') updateSpikeAlerts(spikeAlerts.data);
}

/**
 * Update the main tickers table
 * @param {Array} data - Array of ticker data objects
 */
function updateTable(data) {
    const tbody = document.getElementById('tickers-body');
    if (!data || !data.length) {
        tbody.innerHTML = '<tr><td colspan="8" class="loading">No data. Run a cycle.</td></tr>';
        return;
    }
    
    document.getElementById('tickers-count').textContent = data.length;
    tbody.innerHTML = data.map(d => {
        const p = d.pcr_volume || 0;
        const pc = p > 1.2 ? 'badge-bearish' : p < 0.8 ? 'badge-bullish' : 'badge-neutral';
        const sentiment = d.sentiment?.includes('BEAR') ? 'badge-bearish' : 
                         d.sentiment?.includes('BULL') ? 'badge-bullish' : 'badge-neutral';
        
        return `<tr onclick="selectTicker('${d.ticker}')" style="cursor:pointer">
            <td><b>${d.ticker}</b></td>
            <td>${d.last_price?.toFixed(2) || '-'}</td>
            <td class="${pc}">${p.toFixed(2)} ${d.minimumFractionDigits ? '🐻' : '🐂'}</td>
            <td>${(d.call_iv || 0).toFixed(1)}%</td>
            <td>${(d.put_iv || 0).toFixed(1)}%</td>
            <td>${(d.iv_skew || 0).toFixed(1)}%</td>
            <td><span class="badge ${sentiment}">${d.sentiment || '-'}</span></td>
            <td class="alert-time">${new Date(d.timestamp).toLocaleString()}</td>
        </tr>`;
    }).join('');
}

// =============================================================================
// CYCLE MANAGEMENT
// =============================================================================

/**
 * Start a new analysis cycle
 */
async function runCycle() {
    const button = document.getElementById('btn-run-cycle');
    button.disabled = true;
    button.textContent = 'Starting...';
    
    try {
        const response = await fetch(CONFIG.API_ENDPOINTS.RUN_CYCLE, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        
        const result = await response.json();
        
        if (result.status === 'ok') {
            showNotif('Cycle started!', 'info');
            STATE.cycleStartTime = Date.now();
            startCyclePolling();
        } else {
            showNotif(`Error: ${result.message}`, 'error');
            button.disabled = false;
            button.textContent = 'Run Cycle';
        }
    } catch (error) {
        showNotif('Error starting cycle', 'error');
        button.disabled = false;
        button.textContent = 'Run Cycle';
    }
}

/**
 * Poll cycle status and update UI
 */
function startCyclePolling() {
    if (STATE.pollInterval) return; // Already polling
    
    STATE.pollInterval = setInterval(async () => {
        try {
            const status = await fetchJSON(CONFIG.API_ENDPOINTS.CYCLE_STATUS);
            const button = document.getElementById('btn-run-cycle');
            
            if (status.status === 'ok' && status.cycle) {
                if (status.cycle.running) {
                    button.textContent = 'Running...';
                    
                    // Stop polling after timeout
                    if (Date.now() - STATE.cycleStartTime > CONFIG.POLL_TIMEOUT) {
                        stopCyclePolling();
                        button.disabled = false;
                        button.textContent = 'Run Cycle';
                    }
                } else if (status.cycle.completed_at) {
                    stopCyclePolling();
                    button.disabled = false;
                    button.textContent = 'Run Cycle';
                    
                    if (status.cycle.error) {
                        showNotif(`Cycle error: ${status.cycle.error}`, 'error');
                    } else {
                        showNotif('Cycle done!', 'success');
                        refreshData();
                    }
                }
            }
        } catch (error) {
            console.error('Poll error:', error);
        }
    }, CONFIG.POLL_INTERVAL);
    
    // Safety timeout
    setTimeout(() => {
        if (STATE.pollInterval) {
            stopCyclePolling();
            const button = document.getElementById('btn-run-cycle');
            button.disabled = false;
            button.textContent = 'Run Cycle';
        }
    }, CONFIG.POLL_TIMEOUT);
}

/**
 * Stop polling cycle status
 */
function stopCyclePolling() {
    if (STATE.pollInterval) {
        clearInterval(STATE.pollInterval);
        STATE.pollInterval = null;
    }
}

// =============================================================================
// INITIALIZATION
// =============================================================================

// Initialize on DOM load
document.addEventListener('DOMContentLoaded', () => {
    refreshData();
    setInterval(refreshData, CONFIG.REFRESH_INTERVAL);
});

