import re

with open("trading-app/static/landing.html", "r", encoding="utf-8") as f:
    html = f.read()

# Exact Match Mockup HTML & CSS
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

    /* ── MOCKUP CONTAINER ── */
    .mockup-wrapper {
      max-width: 1280px;
      margin: 40px auto;
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
    .btn-login {
      color: var(--text-main);
      text-decoration: none;
      font-weight: 500;
      font-size: 0.95rem;
      margin-right: 8px;
    }
    .btn-login:hover {
      color: var(--accent-cyan);
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
      grid-template-columns: repeat(3, 1fr);
      gap: 32px;
    }
    .feature-card {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 20px;
      padding: 40px 32px;
      position: relative;
      transition: transform 0.3s;
    }
    .feature-card:hover {
      transform: translateY(-5px);
    }
    
    /* Gradients matching the mockup cards */
    .card-cyan { border: 1px solid var(--accent-cyan); box-shadow: 0 0 20px rgba(0, 229, 255, 0.1) inset; }
    .card-purple { border: 1px solid var(--accent-purple); box-shadow: 0 0 20px rgba(184, 41, 255, 0.1) inset; }
    .card-pink { border: 1px solid #FF2A5F; box-shadow: 0 0 20px rgba(255, 42, 95, 0.1) inset; }

    .feature-icon {
      width: 56px;
      height: 56px;
      border-radius: 12px;
      display: flex;
      align-items: center;
      justify-content: center;
      margin-bottom: 24px;
      font-size: 1.8rem;
    }
    .icon-cyan { background: rgba(0, 229, 255, 0.1); color: var(--accent-cyan); border: 1px solid rgba(0, 229, 255, 0.2); }
    .icon-purple { background: rgba(184, 41, 255, 0.1); color: var(--accent-purple); border: 1px solid rgba(184, 41, 255, 0.2); }
    .icon-pink { background: rgba(255, 42, 95, 0.1); color: #FF2A5F; border: 1px solid rgba(255, 42, 95, 0.2); }

    .feature-title {
      font-size: 1.4rem;
      font-weight: 700;
      margin-bottom: 12px;
      line-height: 1.3;
    }
    .feature-desc {
      color: var(--text-muted);
      font-size: 0.95rem;
      line-height: 1.6;
    }

    /* ── RESPONSIVE ── */
    @media (max-width: 1024px) {
      .hero-section { grid-template-columns: 1fr; text-align: center; }
      .hero-content p { margin: 0 auto 40px; }
      .hero-actions { justify-content: center; }
      .nav-pill { display: none; }
      .stats-row { grid-template-columns: repeat(2, 1fr); }
      .features-row { grid-template-columns: 1fr; }
    }
  </style>
"""

new_body = """
<body>
  <div class="mockup-wrapper">
    
    <!-- HEADER -->
    <header>
      <div class="logo">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="var(--accent-cyan)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polygon points="12 2 2 7 12 12 22 7 12 2"></polygon>
          <polyline points="2 17 12 22 22 17"></polyline>
          <polyline points="2 12 12 17 22 12"></polyline>
        </svg>
        <span>SWARM <span class="ai">AI</span></span>
      </div>
      
      <div class="nav-pill">
        <ul class="nav-links">
          <li><a href="#features">Features</a></li>
          <li><a href="#strategies">Strategies</a></li>
          <li><a href="#pricing">Pricing</a></li>
          <li><a href="#docs">Docs</a></li>
        </ul>
        <div class="header-actions">
          <a href="/login" class="btn-cyan">Get Started</a>
          <a href="/login" class="btn-login">Login</a>
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
        <div class="stat-label">Autonomous Strategies</div>
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
      
      <div class="feature-card card-cyan">
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
        <h3 class="feature-title">9 Autonomous<br>Strategies</h3>
        <p class="feature-desc">Diverse strategies, rapid execution, Adaptive models built specifically for Indian Markets.</p>
      </div>

      <div class="feature-card card-purple">
        <div class="feature-icon icon-purple">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline>
          </svg>
        </div>
        <h3 class="feature-title">Real-time PnL &<br>Analytics</h3>
        <p class="feature-desc">Live portfolio tracking, instant performance metrics, and advanced risk analysis.</p>
      </div>

      <div class="feature-card card-pink">
        <div class="feature-icon icon-pink">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21.21 15.89A10 10 0 1 1 8 2.83"></path>
            <path d="M22 12A10 10 0 0 0 12 2v10z"></path>
          </svg>
        </div>
        <h3 class="feature-title">Secure Cloud<br>Infrastructure</h3>
        <p class="feature-desc">Enterprise-grade security, lightning-fast execution, reliable 99.99% uptime.</p>
      </div>

    </section>

  </div>
</body>
"""

html_replaced = re.sub(
    r'<style>.*?</style>',
    new_css,
    html,
    flags=re.DOTALL
)

# If it didn't find the style tag, let's just create a new HTML from scratch
new_full_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>SWARM AI - Trading Platform</title>
{new_css}
</head>
{new_body}
</html>"""

with open("trading-app/static/landing.html", "w", encoding="utf-8") as f:
    f.write(new_full_html)

print("Successfully replaced landing.html with exact mockup layout")
