// ══════════════════════════════════════════════════════════════════════════════
// i18n - Internationalization system
// ══════════════════════════════════════════════════════════════════════════════

const TRANSLATIONS = {
  en: {
    // Header
    title: "Options Monitor Agent",
    subtitle: "Real-time Options Analytics | Powered by Claude AI",
    refresh: "Refresh",
    runCycle: "Run Cycle",
    running: "Running...",
    last: "Last:",
    
    // Stats cards
    sentiment: "SENTIMENT",
    pcRatio: "P/C RATIO",
    tickers: "TICKERS",
    snapshots: "SNAPSHOTS",
    alerts: "ALERTS",
    btAccuracy: "BT ACCURACY",
    
    // Sentiment values
    bullish: "BULLISH",
    bearish: "BEARISH",
    neutral: "NEUTRAL",
    
    // Sections
    watchlist: "Watchlist",
    impliedVolatility: "Implied Volatility",
    putCallRatio: "Put/Call Ratio",
    alertsSection: "Alerts",
    unusualActivity: "Unusual Activity",
    history: "History",
    askAgent: "Ask the Agent",
    backtestResults: "Backtest Results",
    spikeAlerts: "Premium Spike Alerts",
    askAgentPlaceholder: "Ask about options...",
    spikeAlertsDesc: ">25% vs previous cycle. Sent to iPhone + Email.",
    
    // Table headers
    ticker: "TICKER",
    price: "PRICE",
    callIV: "CALL IV%",
    putIV: "PUT IV%",
    ivSkew: "IV SKEW",
    updated: "UPDATED",
    time: "TIME",
    type: "TYPE",
    strike: "STRIKE",
    expiry: "EXPIRY",
    prev: "PREV",
    curr: "CURR",
    change: "CHANGE",
    message: "MESSAGE",
    severity: "SEVERITY",
    volume: "VOLUME",
    oi: "OI",
    ratio: "RATIO",
    iv: "IV",
    
    // Messages
    loading: "Loading...",
    noData: "No data available",
    selectTicker: "Select...",
    askPlaceholder: "Ask about options...",
    send: "Send",
    thinking: "Thinking...",
    error: "Error",
    cycleStarted: "Cycle started!",
    cycleDone: "Cycle done!",
    cycleError: "Error starting cycle",
    noAlerts: "No alerts yet",
    noUnusual: "No unusual activity",
    noSpikes: "No spike alerts yet. Run a cycle to detect.",
    
    // Footer
    footerText: "Options Monitor Agent v2.0 | Claude AI | Yahoo Finance",
    spikeDesc: "Options where premium jumped >25% vs previous cycle. Sent to iPhone + Email.",
  },
  
  es: {
    // Header
    title: "Agente Monitor de Opciones",
    subtitle: "Análisis de Opciones en Tiempo Real | Potenciado por Claude AI",
    refresh: "Actualizar",
    runCycle: "Ejecutar Ciclo",
    running: "Ejecutando...",
    last: "Última:",
    
    // Stats cards
    sentiment: "SENTIMIENTO",
    pcRatio: "RATIO P/C",
    tickers: "TICKERS",
    snapshots: "CAPTURAS",
    alerts: "ALERTAS",
    btAccuracy: "PRECISIÓN BT",
    
    // Sentiment values
    bullish: "ALCISTA",
    bearish: "BAJISTA",
    neutral: "NEUTRAL",
    
    // Sections
    watchlist: "Lista de Seguimiento",
    impliedVolatility: "Volatilidad Implícita",
    putCallRatio: "Ratio Put/Call",
    alertsSection: "Alertas",
    unusualActivity: "Actividad Inusual",
    history: "Historial",
    askAgent: "Preguntar al Agente",
    backtestResults: "Resultados Backtest",
    spikeAlerts: "Alertas de Picos de Primas",
    askAgentPlaceholder: "Pregunta sobre opciones...",
    spikeAlertsDesc: ">25% vs ciclo anterior. Enviado al iPhone + Email.",
    
    // Table headers
    ticker: "TICKER",
    price: "PRECIO",
    callIV: "IV CALL%",
    putIV: "IV PUT%",
    ivSkew: "SESGO IV",
    updated: "ACTUALIZADO",
    time: "HORA",
    type: "TIPO",
    strike: "STRIKE",
    expiry: "VENC.",
    prev: "PREV",
    curr: "ACTUAL",
    change: "CAMBIO",
    message: "MENSAJE",
    severity: "SEVERIDAD",
    volume: "VOLUMEN",
    oi: "OI",
    ratio: "RATIO",
    iv: "IV",
    
    // Messages
    loading: "Cargando...",
    noData: "No hay datos disponibles",
    selectTicker: "Seleccionar...",
    askPlaceholder: "Pregunta sobre opciones...",
    send: "Enviar",
    thinking: "Pensando...",
    error: "Error",
    cycleStarted: "¡Ciclo iniciado!",
    cycleDone: "¡Ciclo completado!",
    cycleError: "Error al iniciar ciclo",
    noAlerts: "Sin alertas aún",
    noUnusual: "Sin actividad inusual",
    noSpikes: "Sin alertas de picos aún. Ejecuta un ciclo para detectar.",
    
    // Footer
    footerText: "Agente Monitor de Opciones v2.0 | Claude AI | Yahoo Finance",
    spikeDesc: "Opciones donde la prima saltó >25% vs ciclo previo. Enviado a iPhone + Email.",
  }
};

// Get current language from localStorage or browser default
function getCurrentLang() {
  const saved = localStorage.getItem('lang');
  if (saved && (saved === 'en' || saved === 'es')) return saved;
  
  // Auto-detect from browser
  const browserLang = (navigator.language || navigator.userLanguage || '').toLowerCase();
  return browserLang.startsWith('es') ? 'es' : 'en';
}

// Set and save language
function setLanguage(lang) {
  if (lang !== 'en' && lang !== 'es') lang = 'en';
  localStorage.setItem('lang', lang);
  window.currentLang = lang;
  
  // Update flag buttons
  document.querySelectorAll('.lang-flag').forEach(f => {
    f.classList.toggle('active', f.dataset.lang === lang);
  });
  
  // Apply translations
  applyTranslations();
}

// Get translated text
function t(key) {
  const lang = window.currentLang || 'en';
  return TRANSLATIONS[lang][key] || TRANSLATIONS.en[key] || key;
}

// Apply all translations to DOM
function applyTranslations() {
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.dataset.i18n;
    if (el.tagName === 'INPUT' && el.placeholder !== undefined) {
      el.placeholder = t(key);
    } else {
      el.textContent = t(key);
    }
  });
}

// Initialize i18n on page load
document.addEventListener('DOMContentLoaded', () => {
  window.currentLang = getCurrentLang();
  setLanguage(window.currentLang);
  
  // Add click listeners to flag buttons
  document.querySelectorAll('.lang-flag').forEach(flag => {
    flag.addEventListener('click', () => {
      setLanguage(flag.dataset.lang);
    });
  });
});
