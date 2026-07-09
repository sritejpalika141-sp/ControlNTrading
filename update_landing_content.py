import re

new_css = """  <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg-base: #0a0b10;
      --bg-card: rgba(22, 26, 37, 0.4);
      --bg-pill: rgba(255, 255, 255, 0.03);
      --accent-cyan: #00E5FF;
      --accent-cyan-glow: rgba(0, 229, 255, 0.4);
      --accent-purple: #B829FF;
      --accent-purple-glow: rgba(184, 41, 255, 0.3);
      --border: rgba(255, 255, 255, 0.08);
      --text-main: #FFFFFF;
      --text-muted: #8B98AD;
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      font-family: 'Outfit', sans-serif;
      background-color: var(--bg-base);
      color: var(--text-main);
      overflow-x: hidden;
      line-height: 1.6;
      min-height: 100vh;
      background-image: 
        radial-gradient(circle at 10% 20%, rgba(0, 229, 255, 0.05) 0%, transparent 40%),
        radial-gradient(circle at 90% 80%, rgba(184, 41, 255, 0.05) 0%, transparent 40%);
    }

    /* ── SCROLLING TICKER ── */
    .ticker-wrap {
      width: 100%;
      background: rgba(0, 0, 0, 0.5);
      border-bottom: 1px solid var(--border);
      overflow: hidden;
      height: 40px;
      display: flex;
      align-items: center;
      box-sizing: content-box;
      position: fixed;
      top: 0;
      z-index: 1000;
      backdrop-filter: blur(10px);
    }
    .ticker {
      display: inline-block;
      white-space: nowrap;
      padding-right: 100%;
      animation-iteration-count: infinite;
      animation-timing-function: linear;
      animation-name: ticker;
      animation-duration: 30s;
    }
    .ticker__item {
      display: inline-block;
      padding: 0 2rem;
      font-size: 0.85rem;
      font-family: 'JetBrains Mono', monospace;
      color: var(--text-main);
      font-weight: 500;
    }
    .ticker__item.up { color: var(--accent-cyan); }
    .ticker__item.down { color: #FF2A5F; }
    
    @keyframes ticker {
      0% { transform: translate3d(0, 0, 0); }
      100% { transform: translate3d(-100%, 0, 0); }
    }

    /* ── MOCKUP CONTAINER ── */
    .mockup-wrapper {
      max-width: 1280px;
      margin: 80px auto 40px; /* added top margin for ticker */
      background: rgba(13, 15, 22, 0.7);
      border: 1px solid rgba(255, 255, 255, 0.05);
      border-radius: 24px;
      padding: 40px;
      backdrop-filter: blur(20px);
      box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
    }

    /* ── HEADER (PILL MENUBAR) ── */
    header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 80px;
    }
    
    .logo {
      display: flex;
      align-items: center;
      gap: 12px;
      font-size: 1.4rem;
      font-weight: 700;
      letter-spacing: 1px;
    }
    .logo img {
      height: 32px;
      width: auto;
    }
    .logo span { color: #fff; }
    .logo span.ai { color: var(--accent-cyan); }

    .nav-pill {
      display: flex;
      background: var(--bg-pill);
      border: 1px solid var(--border);
      border-radius: 40px;
      padding: 8px 16px;
      align-items: center;
      gap: 32px;
    }
    
    .nav-links {
      display: flex;
      gap: 32px;
      list-style: none;
      margin-right: 16px;
    }
    .nav-links a {
      color: var(--text-muted);
      text-decoration: none;
      font-size: 0.95rem;
      font-weight: 500;
      transition: color 0.3s;
    }
    .nav-links a:hover { color: #fff; }

    .header-actions {
      display: flex;
      align-items: center;
      gap: 16px;
    }
    .btn-cyan {
      background: var(--accent-cyan);
      color: #000;
      border: none;
      padding: 10px 24px;
      border-radius: 30px;
      font-weight: 700;
      font-family: 'Outfit', sans-serif;
      font-size: 0.95rem;
      cursor: pointer;
      box-shadow: 0 0 20px var(--accent-cyan-glow);
      transition: all 0.3s;
      text-decoration: none;
      display: inline-block;
    }
    .btn-cyan:hover {
      box-shadow: 0 0 30px var(--accent-cyan-glow);
      transform: translateY(-2px);
    }

    /* ── HERO SECTION ── */
    .hero-section {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 40px;
      align-items: center;
      margin-bottom: 80px;
    }
    
    .hero-content h1 {
      font-size: 4.5rem;
      font-weight: 800;
      line-height: 1.1;
      margin-bottom: 24px;
      letter-spacing: -1px;
    }
    .hero-content p {
      font-size: 1.15rem;
      color: var(--text-muted);
      margin-bottom: 40px;
      max-width: 90%;
      line-height: 1.7;
    }
    
    .hero-actions {
      display: flex;
      gap: 20px;
    }
    .btn-outline {
      background: transparent;
      color: var(--text-main);
      border: 1px solid var(--border);
      padding: 12px 32px;
      border-radius: 30px;
      font-weight: 600;
      font-family: 'Outfit', sans-serif;
      font-size: 1.05rem;
      cursor: pointer;
      transition: all 0.3s;
      text-decoration: none;
      display: inline-block;
    }
    .btn-outline:hover {
      background: rgba(255,255,255,0.05);
      border-color: rgba(255,255,255,0.2);
    }

    .hero-image {
      position: relative;
    }
    .hero-image img {
      width: 100%;
      height: auto;
      border-radius: 20px;
      box-shadow: 0 20px 50px rgba(0,0,0,0.5);
      position: relative;
      z-index: 2;
    }
    .hero-image::before {
      content: '';
      position: absolute;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%);
      width: 120%;
      height: 120%;
      background: radial-gradient(circle, rgba(0, 229, 255, 0.15) 0%, transparent 60%);
      z-index: 1;
      pointer-events: none;
    }

    /* ── STATS ROW ── */
    .stats-row {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 24px;
      margin-bottom: 100px;
    }
    .stat-box {
      background: linear-gradient(180deg, rgba(255,255,255,0.05) 0%, rgba(255,255,255,0.01) 100%);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 24px;
      text-align: center;
      transition: transform 0.3s;
    }
    .stat-box:hover {
      transform: translateY(-5px);
      border-color: rgba(255,255,255,0.15);
    }
    .stat-value {
      font-size: 2.2rem;
      font-weight: 800;
      margin-bottom: 8px;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 12px;
    }
    .stat-icon {
      color: var(--accent-cyan);
      font-size: 1.5rem;
    }
    .stat-label {
      color: var(--text-muted);
      font-size: 0.9rem;
      font-weight: 500;
    }

    /* ── BOTTOM CARDS ── */
    .section-heading {
      text-align: center;
      font-size: 2.2rem;
      font-weight: 700;
      margin-bottom: 40px;
    }

    .features-row {
      display: grid;
      grid-template-columns: repeat(4, 1fr); /* 4 Columns */
      gap: 24px;
    }
    .feature-card {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 20px;
      padding: 30px 24px;
      position: relative;
      transition: transform 0.3s;
    }
    .feature-card:hover {
      transform: translateY(-5px);
    }
    
    .card-cyan { border: 1px solid var(--accent-cyan); box-shadow: 0 0 20px rgba(0, 229, 255, 0.1) inset; }
    .card-purple { border: 1px solid var(--accent-purple); box-shadow: 0 0 20px rgba(184, 41, 255, 0.1) inset; }
    .card-pink { border: 1px solid #FF2A5F; box-shadow: 0 0 20px rgba(255, 42, 95, 0.1) inset; }
    .card-gold { border: 1px solid #FFC107; box-shadow: 0 0 20px rgba(255, 193, 7, 0.1) inset; }

    .feature-icon {
      width: 48px;
      height: 48px;
      border-radius: 12px;
      display: flex;
      align-items: center;
      justify-content: center;
      margin-bottom: 20px;
      font-size: 1.5rem;
    }
    .icon-cyan { background: rgba(0, 229, 255, 0.1); color: var(--accent-cyan); border: 1px solid rgba(0, 229, 255, 0.2); }
    .icon-purple { background: rgba(184, 41, 255, 0.1); color: var(--accent-purple); border: 1px solid rgba(184, 41, 255, 0.2); }
    .icon-pink { background: rgba(255, 42, 95, 0.1); color: #FF2A5F; border: 1px solid rgba(255, 42, 95, 0.2); }
    .icon-gold { background: rgba(255, 193, 7, 0.1); color: #FFC107; border: 1px solid rgba(255, 193, 7, 0.2); }

    .feature-title {
      font-size: 1.25rem;
      font-weight: 700;
      margin-bottom: 10px;
      line-height: 1.3;
    }
    .feature-desc {
      color: var(--text-muted);
      font-size: 0.9rem;
      line-height: 1.5;
    }

    /* ── RESPONSIVE ── */
    @media (max-width: 1024px) {
      .hero-section { grid-template-columns: 1fr; text-align: center; }
      .hero-content p { margin: 0 auto 40px; }
      .hero-actions { justify-content: center; }
      .nav-pill { display: none; }
      .stats-row { grid-template-columns: repeat(2, 1fr); }
      .features-row { grid-template-columns: repeat(2, 1fr); }
    }
    @media (max-width: 600px) {
      .features-row { grid-template-columns: 1fr; }
    }
  </style>
"""

new_body = """
<body>
  <!-- TICKER TAPE -->
  <div class="ticker-wrap">
    <div class="ticker">
      <div class="ticker__item up">NIFTY 50: 24,500.25 (+0.45%)</div>
      <div class="ticker__item down">BANKNIFTY: 52,100.10 (-0.12%)</div>
      <div class="ticker__item up">SENSEX: 80,450.00 (+0.50%)</div>
      <div class="ticker__item up">FINNIFTY: 23,400.15 (+0.60%)</div>
      <div class="ticker__item down">MIDCPNIFTY: 12,345.50 (-0.25%)</div>
      
      <!-- Duplicate for seamless looping -->
      <div class="ticker__item up">NIFTY 50: 24,500.25 (+0.45%)</div>
      <div class="ticker__item down">BANKNIFTY: 52,100.10 (-0.12%)</div>
      <div class="ticker__item up">SENSEX: 80,450.00 (+0.50%)</div>
      <div class="ticker__item up">FINNIFTY: 23,400.15 (+0.60%)</div>
      <div class="ticker__item down">MIDCPNIFTY: 12,345.50 (-0.25%)</div>
    </div>
  </div>

  <div class="mockup-wrapper">
    
    <!-- HEADER -->
    <header>
      <div class="logo">
        <img src="/static/logo.png" alt="ControlN" onerror="this.src='data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCIgZmlsbD0ibm9uZSIgc3Ryb2tlPSIjMDBFNUZGIiBzdHJva2Utd2lkdGg9IjIiPjxwb2x5Z29uIHBvaW50cz0iMTIgMiAyIDcgMTIgMTIgMjIgNyAxMiAyIj48L3BvbHlnb24+PHBvbHlsaW5lIHBvaW50cz0iMiAxNyAxMiAyMiAyMiAxNyI+PC9wb2x5bGluZT48cG9seWxpbmUgcG9pbnRzPSIyIDEyIDEyIDE3IDIyIDEyIj48L3BvbHlsaW5lPjwvc3ZnPg=='">
        <span>ControlN <span class="ai">Trading</span></span>
      </div>
      
      <div class="nav-pill">
        <ul class="nav-links">
          <li><a href="#strategies">Strategies</a></li>
          <li><a href="#security">Security</a></li>
          <li><a href="#compliance">Compliance</a></li>
          <li><a href="#marketnews">Market News</a></li>
        </ul>
        <div class="header-actions">
          <a href="/login" class="btn-cyan">Get Started</a>
        </div>
      </div>
    </header>

    <!-- HERO -->
    <section class="hero-section">
      <div class="hero-content">
        <h1>AUTOMATED AI<br>TRADING SWARM</h1>
        <p>Maximize Profits with 9 Autonomous, High-Performance Algorithmic Strategies for Indian Index Options. Powered by advanced Machine Learning.</p>
        <div class="hero-actions">
          <a href="/login" class="btn-cyan" style="padding: 16px 32px; font-size: 1.05rem;">Start Trading Now</a>
          <a href="#features" class="btn-outline">Learn More</a>
        </div>
      </div>
      <div class="hero-image">
        <img src="/static/ai_trading_chip.jpg" alt="AI Trading Chip">
      </div>
    </section>

    <!-- STATS -->
    <section class="stats-row">
      <div class="stat-box">
        <div class="stat-value">$20M+</div>
        <div class="stat-label">Traded Volume</div>
      </div>
      <div class="stat-box">
        <div class="stat-value"><span class="stat-icon">🤖</span> 9</div>
        <div class="stat-label">Automated Modules</div>
      </div>
      <div class="stat-box">
        <div class="stat-value"><span class="stat-icon">📈</span> 150%</div>
        <div class="stat-label">Avg. Annual Return</div>
      </div>
      <div class="stat-box">
        <div class="stat-value"><span class="stat-icon">⏱️</span> 24/7</div>
        <div class="stat-label">Market Monitoring</div>
      </div>
    </section>

    <!-- FEATURES -->
    <h2 class="section-heading">Master the Markets with Precision AI</h2>
    
    <section class="features-row" id="features">
      
      <!-- Card 1 -->
      <div class="feature-card card-cyan" id="strategies">
        <div class="feature-icon icon-cyan">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="4" y="4" width="16" height="16" rx="2" ry="2"></rect>
            <rect x="9" y="9" width="6" height="6"></rect>
            <line x1="9" y1="1" x2="9" y2="4"></line>
            <line x1="15" y1="1" x2="15" y2="4"></line>
            <line x1="9" y1="20" x2="9" y2="23"></line>
            <line x1="15" y1="20" x2="15" y2="23"></line>
            <line x1="20" y1="9" x2="23" y2="9"></line>
            <line x1="20" y1="14" x2="23" y2="14"></line>
            <line x1="1" y1="9" x2="4" y2="9"></line>
            <line x1="1" y1="14" x2="4" y2="14"></line>
          </svg>
        </div>
        <h3 class="feature-title">Automated Trading Modules</h3>
        <p class="feature-desc">Diverse algorithms, rapid execution, Adaptive models built for Indian Markets.</p>
      </div>

      <!-- Card 2 -->
      <div class="feature-card card-purple" id="security">
        <div class="feature-icon icon-purple">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21.21 15.89A10 10 0 1 1 8 2.83"></path>
            <path d="M22 12A10 10 0 0 0 12 2v10z"></path>
          </svg>
        </div>
        <h3 class="feature-title">Enterprise-Grade Security</h3>
        <p class="feature-desc">Top-tier encryption, lightning-fast execution, and reliable 99.99% uptime.</p>
      </div>

      <!-- Card 3 -->
      <div class="feature-card card-pink" id="compliance">
        <div class="feature-icon icon-pink">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
            <polyline points="22 4 12 14.01 9 11.01"></polyline>
          </svg>
        </div>
        <h3 class="feature-title">Regulatory Compliance</h3>
        <p class="feature-desc">Fully compliant with standard regulations to ensure a safe, legal trading environment.</p>
      </div>

      <!-- Card 4 -->
      <div class="feature-card card-gold" id="marketnews">
        <div class="feature-icon icon-gold">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline>
          </svg>
        </div>
        <h3 class="feature-title">Market Pulse</h3>
        <p class="feature-desc">📊 Live Market Prices and Market Daily News right at your fingertips.</p>
      </div>

    </section>

  </div>
</body>
"""

new_full_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>ControlN Trading - AI Swarm Platform</title>
{new_css}
</head>
{new_body}
</html>"""

with open("trading-app/static/landing.html", "w", encoding="utf-8") as f:
    f.write(new_full_html)

print("Successfully replaced landing.html with ControlN logo, updated menu, ticker, and updated cards.")
