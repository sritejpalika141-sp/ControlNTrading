import re

with open("trading-app/static/landing.html", "r", encoding="utf-8") as f:
    html = f.read()

# Add CSS for Modal
modal_css = """
    /* ── MODAL SYSTEM ── */
    .modal-overlay {
      position: fixed;
      top: 0;
      left: 0;
      width: 100%;
      height: 100%;
      background: rgba(0, 0, 0, 0.7);
      backdrop-filter: blur(10px);
      z-index: 2000;
      display: none;
      align-items: center;
      justify-content: center;
      opacity: 0;
      transition: opacity 0.3s ease;
    }
    .modal-overlay.active {
      display: flex;
      opacity: 1;
    }
    .modal-content {
      background: rgba(13, 15, 22, 0.95);
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 20px;
      padding: 40px;
      max-width: 600px;
      width: 90%;
      position: relative;
      transform: translateY(20px);
      transition: transform 0.3s ease;
      box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
    }
    .modal-overlay.active .modal-content {
      transform: translateY(0);
    }
    .modal-close {
      position: absolute;
      top: 20px;
      right: 20px;
      background: transparent;
      border: none;
      color: var(--text-muted);
      font-size: 1.5rem;
      cursor: pointer;
      transition: color 0.3s;
    }
    .modal-close:hover {
      color: #fff;
    }
    .modal-header {
      display: flex;
      align-items: center;
      gap: 16px;
      margin-bottom: 24px;
    }
    .modal-icon {
      width: 48px;
      height: 48px;
      border-radius: 12px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 1.5rem;
    }
    .modal-title {
      font-size: 1.8rem;
      font-weight: 700;
    }
    .modal-body {
      font-size: 1.05rem;
      color: var(--text-muted);
      line-height: 1.7;
    }
    .modal-body p {
      margin-bottom: 16px;
    }
    .modal-body ul {
      margin-left: 20px;
      margin-bottom: 16px;
    }
    .modal-body li {
      margin-bottom: 8px;
    }
    
    .feature-card {
      cursor: pointer;
    }
  </style>
"""

html = html.replace("  </style>", modal_css)

# Add onclick handlers to cards
html = html.replace('<div class="feature-card card-cyan" id="strategies">', '<div class="feature-card card-cyan" id="strategies" onclick="openModal(\'modules\')">')
html = html.replace('<div class="feature-card card-purple" id="security">', '<div class="feature-card card-purple" id="security" onclick="openModal(\'security\')">')
html = html.replace('<div class="feature-card card-pink" id="compliance">', '<div class="feature-card card-pink" id="compliance" onclick="openModal(\'compliance\')">')
html = html.replace('<div class="feature-card card-gold" id="marketnews">', '<div class="feature-card card-gold" id="marketnews" onclick="openModal(\'pulse\')">')

# Add modal HTML and JS before </body>
modal_html = """
  <!-- MODAL -->
  <div class="modal-overlay" id="featureModal" onclick="closeModal(event)">
    <div class="modal-content" onclick="event.stopPropagation()">
      <button class="modal-close" onclick="closeModal()">&times;</button>
      <div class="modal-header">
        <div class="modal-icon" id="modalIcon"></div>
        <h2 class="modal-title" id="modalTitle">Title</h2>
      </div>
      <div class="modal-body" id="modalBody">
        Content goes here.
      </div>
    </div>
  </div>

  <script>
    const modalData = {
      modules: {
        title: "Automated Trading Modules",
        iconClass: "icon-cyan",
        iconSvg: `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="4" y="4" width="16" height="16" rx="2" ry="2"></rect><rect x="9" y="9" width="6" height="6"></rect><line x1="9" y1="1" x2="9" y2="4"></line><line x1="15" y1="1" x2="15" y2="4"></line><line x1="9" y1="20" x2="9" y2="23"></line><line x1="15" y1="20" x2="15" y2="23"></line><line x1="20" y1="9" x2="23" y2="9"></line><line x1="20" y1="14" x2="23" y2="14"></line><line x1="1" y1="9" x2="4" y2="9"></line><line x1="1" y1="14" x2="4" y2="14"></line></svg>`,
        content: `
          <p>Our AI swarm consists of 9 distinct trading strategies specifically optimized for Indian Index Options (NIFTY, BANKNIFTY, SENSEX, FINNIFTY).</p>
          <ul>
            <li><strong>OB + FVG:</strong> Order block and fair value gap detection.</li>
            <li><strong>Mean Reversion:</strong> Capitalizing on price over-extensions.</li>
            <li><strong>Momentum Scalper:</strong> Lightning-fast execution on micro-trends.</li>
            <li><strong>Smart Money Concepts:</strong> Tracking institutional order flow.</li>
          </ul>
          <p>Each module runs autonomously, evaluating market conditions in real-time, 24/7 without human emotion or fatigue.</p>
        `
      },
      security: {
        title: "Enterprise-Grade Security",
        iconClass: "icon-purple",
        iconSvg: `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21.21 15.89A10 10 0 1 1 8 2.83"></path><path d="M22 12A10 10 0 0 0 12 2v10z"></path></svg>`,
        content: `
          <p>Security is the foundation of our algorithmic infrastructure. We employ multiple layers of protection to ensure your capital and data are safe.</p>
          <ul>
            <li><strong>Data Encryption:</strong> AES-256 encryption for all sensitive data and API keys at rest and in transit.</li>
            <li><strong>Secure Cloud Computing:</strong> Deployed on hardened Google Cloud infrastructure with strict firewall rules.</li>
            <li><strong>API Sandboxing:</strong> Broker API keys are isolated and execute within secure, restricted memory enclaves.</li>
            <li><strong>99.99% Uptime:</strong> Redundant server architecture ensures you never miss a critical trade due to downtime.</li>
          </ul>
        `
      },
      compliance: {
        title: "Regulatory Compliance",
        iconClass: "icon-pink",
        iconSvg: `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>`,
        content: `
          <p>We prioritize building robust systems that align with strict financial regulations to provide a safe, legal trading environment.</p>
          <ul>
            <li><strong>SEBI Guidelines Alignment:</strong> Built with adherence to standard exchange and broker guidelines.</li>
            <li><strong>Transparent Auditing:</strong> Every algorithmic decision and order placement is logged and auditable in real-time via your dashboard.</li>
            <li><strong>Risk Management:</strong> Strict internal circuit breakers and daily loss limits prevent runaway algorithms or catastrophic drawdowns.</li>
          </ul>
        `
      },
      pulse: {
        title: "Market Pulse",
        iconClass: "icon-gold",
        iconSvg: `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline></svg>`,
        content: `
          <p>Information advantage is critical. ControlN Trading brings institutional-grade market data directly to your dashboard.</p>
          <ul>
            <li><strong>Live Ticker Feeds:</strong> Millisecond-accurate pricing for NIFTY, BANKNIFTY, SENSEX, and MIDCPNIFTY.</li>
            <li><strong>AI News Sentiment:</strong> We parse thousands of financial news articles daily and use LLMs to gauge market sentiment (Bullish, Bearish, or Neutral) instantly.</li>
            <li><strong>Macro Indicators:</strong> Real-time tracking of global cues and institutional (FII/DII) activity to give context to our algorithmic entries.</li>
          </ul>
        `
      }
    };

    function openModal(id) {
      const data = modalData[id];
      if (!data) return;
      
      const modal = document.getElementById('featureModal');
      const icon = document.getElementById('modalIcon');
      
      // Setup content
      document.getElementById('modalTitle').innerText = data.title;
      document.getElementById('modalBody').innerHTML = data.content;
      
      // Setup icon classes and SVG
      icon.className = 'modal-icon ' + data.iconClass;
      icon.innerHTML = data.iconSvg;
      
      // Show modal
      modal.classList.add('active');
      document.body.style.overflow = 'hidden'; // Prevent scrolling
    }

    function closeModal(e) {
      if (e && e.target.classList.contains('modal-content')) return;
      document.getElementById('featureModal').classList.remove('active');
      document.body.style.overflow = 'auto'; // Restore scrolling
    }
  </script>
</body>
"""

html = html.replace("</body>", modal_html)

with open("trading-app/static/landing.html", "w", encoding="utf-8") as f:
    f.write(html)

print("Successfully added interactive modals to feature cards.")
