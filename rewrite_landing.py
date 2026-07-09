import re

with open("trading-app/static/landing.html", "r", encoding="utf-8") as f:
    html = f.read()

# The new CSS for the landing page that matches our glassmorphism premium aesthetic
new_css = """  <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="/static/styles.css?v=v6.2">
  <style>
    :root {
      --bg-base: #0B0E14;
      --bg-card: rgba(22, 26, 37, 0.65);
      --bg-card-hover: rgba(30, 35, 51, 0.85);
      --accent-green: #00FF9D;
      --accent-green-glow: rgba(0, 255, 157, 0.15);
      --accent-cyan: #00D2FF;
      --accent-cyan-glow: rgba(0, 210, 255, 0.2);
      --accent-purple: #B829FF;
      --accent-purple-glow: rgba(184, 41, 255, 0.15);
      --border: rgba(255, 255, 255, 0.08);
      --border-hover: rgba(0, 210, 255, 0.4);
      --text-main: #F8F9FA;
      --text-muted: #8B98AD;
      --text-dim: #4B5975;
      --radius-lg: 24px;
      --radius-md: 16px;
      --radius-sm: 8px;
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      font-family: 'Outfit', sans-serif;
      background-color: var(--bg-base);
      color: var(--text-main);
      overflow-x: hidden;
      line-height: 1.6;
      background-image: 
        radial-gradient(circle at 15% 50%, rgba(0, 210, 255, 0.05), transparent 25%),
        radial-gradient(circle at 85% 30%, rgba(184, 41, 255, 0.05), transparent 25%);
      position: relative;
    }

    /* ── LIVE TICKER BAR ── */
    .ticker-bar {
      position: fixed;
      top: 0;
      left: 0;
      right: 0;
      height: 40px;
      background: rgba(11, 14, 20, 0.85);
      border-bottom: 1px solid var(--border);
      z-index: 1000;
      display: flex;
      align-items: center;
      overflow: hidden;
      backdrop-filter: blur(12px);
    }
    .ticker-label {
      background: var(--accent-cyan);
      color: #000;
      font-weight: 800;
      font-size: 0.75rem;
      padding: 0 16px;
      height: 100%;
      display: flex;
      align-items: center;
      letter-spacing: 1px;
      z-index: 2;
      box-shadow: 0 0 15px var(--accent-cyan-glow);
    }
    .ticker-scroll-wrapper {
      flex: 1;
      overflow: hidden;
      position: relative;
    }
    .ticker-track {
      display: flex;
      white-space: nowrap;
      animation: tickerScroll 30s linear infinite;
    }
    .ticker-track:hover { animation-play-state: paused; }
    .ticker-item {
      display: inline-flex;
      align-items: center;
      padding: 0 24px;
      font-size: 0.85rem;
      border-right: 1px solid var(--border);
    }
    .t-name { font-weight: 600; color: var(--text-muted); margin-right: 8px; }
    .t-price { font-family: 'JetBrains Mono', monospace; font-weight: 700; color: #fff; }
    .t-chg { font-family: 'JetBrains Mono', monospace; font-weight: 700; font-size: 0.75rem; margin-left: 6px; }
    .t-chg.up { color: var(--accent-green); }
    .t-chg.down { color: #FF2A5F; }

    @keyframes tickerScroll {
      0% { transform: translateX(0); }
      100% { transform: translateX(-50%); }
    }

    /* ── HEADER ── */
    header {
      position: fixed;
      top: 40px;
      left: 0;
      right: 0;
      padding: 16px 40px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      background: rgba(11, 14, 20, 0.6);
      backdrop-filter: blur(20px);
      border-bottom: 1px solid var(--border);
      z-index: 999;
    }
    .nav-links {
      display: flex;
      gap: 32px;
      list-style: none;
    }
    .nav-links a {
      color: var(--text-muted);
      text-decoration: none;
      font-weight: 500;
      font-size: 0.9rem;
      transition: color 0.3s;
    }
    .nav-links a:hover { color: var(--accent-cyan); }
    .btn-login {
      background: transparent;
      border: 1px solid var(--accent-cyan);
      color: var(--accent-cyan);
      padding: 8px 24px;
      border-radius: 20px;
      font-family: 'Outfit', sans-serif;
      font-weight: 600;
      font-size: 0.9rem;
      cursor: pointer;
      transition: all 0.3s;
    }
    .btn-login:hover {
      background: var(--accent-cyan-glow);
      box-shadow: 0 0 15px var(--accent-cyan-glow);
    }

    /* ── HERO ── */
    .hero-container {
      padding: 160px 20px 80px;
      max-width: 1000px;
      margin: 0 auto;
      text-align: center;
    }
    .hero-tag {
      display: inline-block;
      padding: 6px 16px;
      background: rgba(184, 41, 255, 0.1);
      border: 1px solid rgba(184, 41, 255, 0.3);
      border-radius: 20px;
      color: var(--accent-purple);
      font-weight: 600;
      font-size: 0.85rem;
      margin-bottom: 24px;
      letter-spacing: 0.5px;
    }
    .hero-title {
      font-size: 4rem;
      font-weight: 800;
      line-height: 1.1;
      margin-bottom: 24px;
      letter-spacing: -1px;
    }
    .hero-title span {
      background: linear-gradient(135deg, var(--accent-cyan), var(--accent-purple));
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }
    .hero-subtitle {
      font-size: 1.1rem;
      color: var(--text-muted);
      max-width: 700px;
      margin: 0 auto 48px;
    }

    .cta-group {
      display: flex;
      gap: 16px;
      justify-content: center;
      margin-bottom: 80px;
    }
    .btn-primary {
      background: linear-gradient(135deg, var(--accent-cyan), var(--accent-purple));
      border: none;
      color: #fff;
      padding: 16px 40px;
      border-radius: 30px;
      font-family: 'Outfit', sans-serif;
      font-weight: 700;
      font-size: 1.05rem;
      cursor: pointer;
      box-shadow: 0 10px 30px rgba(0, 210, 255, 0.2);
      transition: all 0.3s;
    }
    .btn-primary:hover {
      transform: translateY(-2px);
      box-shadow: 0 15px 40px rgba(0, 210, 255, 0.3);
    }
    .btn-secondary {
      background: var(--bg-card);
      border: 1px solid var(--border);
      color: var(--text-main);
      padding: 16px 40px;
      border-radius: 30px;
      font-family: 'Outfit', sans-serif;
      font-weight: 600;
      font-size: 1.05rem;
      cursor: pointer;
      transition: all 0.3s;
    }
    .btn-secondary:hover {
      background: var(--bg-card-hover);
      border-color: var(--text-muted);
    }

    .stats-container {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 24px;
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      padding: 32px;
      backdrop-filter: blur(12px);
    }
    .stat-card {
      text-align: center;
    }
    .stat-val {
      font-family: 'JetBrains Mono', monospace;
      font-size: 2rem;
      font-weight: 700;
      color: var(--accent-cyan);
      margin-bottom: 8px;
    }
    .stat-label {
      font-size: 0.85rem;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 1px;
      font-weight: 600;
    }

    /* ── SECTIONS ── */
    .section-block {
      padding: 100px 40px;
      max-width: 1200px;
      margin: 0 auto;
    }
    .section-title {
      font-size: 2.5rem;
      font-weight: 800;
      text-align: center;
      margin-bottom: 16px;
    }
    .section-subtitle {
      text-align: center;
      color: var(--text-muted);
      max-width: 700px;
      margin: 0 auto 64px;
      font-size: 1.1rem;
    }

    .features-grid, .compliance-grid, .security-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 24px;
    }

    .feature-card, .compliance-card, .security-card {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      padding: 32px;
      position: relative;
      overflow: hidden;
      transition: all 0.3s;
      backdrop-filter: blur(12px);
    }
    .feature-card:hover, .compliance-card:hover, .security-card:hover {
      transform: translateY(-5px);
      border-color: var(--border-hover);
      box-shadow: 0 10px 30px rgba(0,0,0,0.5);
    }

    .strategy-badge {
      position: absolute;
      top: 24px;
      right: 24px;
      padding: 4px 12px;
      border-radius: 20px;
      font-size: 0.75rem;
      font-weight: 700;
      letter-spacing: 0.5px;
    }
    .badge-blue { background: rgba(0, 210, 255, 0.1); color: var(--accent-cyan); border: 1px solid rgba(0, 210, 255, 0.2); }
    .badge-green { background: rgba(0, 255, 157, 0.1); color: var(--accent-green); border: 1px solid rgba(0, 255, 157, 0.2); }
    .badge-amber { background: rgba(255, 208, 0, 0.1); color: #FFD000; border: 1px solid rgba(255, 208, 0, 0.2); }

    .feature-icon, .cc-icon, .security-icon-wrap {
      font-size: 2.5rem;
      margin-bottom: 24px;
      display: inline-block;
    }
    .feature-title {
      font-size: 1.25rem;
      font-weight: 700;
      margin-bottom: 12px;
    }
    .feature-desc {
      color: var(--text-muted);
      font-size: 0.95rem;
      margin-bottom: 24px;
    }

    .strategy-details { display: flex; flex-direction: column; gap: 8px; }
    .strategy-detail-item {
      font-size: 0.85rem;
      color: var(--text-main);
      display: flex;
      align-items: center;
    }
    .strategy-detail-item::before {
      content: "→";
      color: var(--accent-cyan);
      margin-right: 8px;
      font-weight: bold;
    }

    /* ── NEWS ── */
    .news-layout {
      display: grid;
      grid-template-columns: 1fr 400px;
      gap: 32px;
    }
    .market-prices-grid {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 16px;
      margin-bottom: 24px;
    }
    .price-card {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      padding: 20px;
    }
    .pc-name { font-weight: 600; color: var(--text-muted); font-size: 0.85rem; margin-bottom: 8px; }
    .pc-price { font-family: 'JetBrains Mono', monospace; font-size: 1.5rem; font-weight: 700; margin-bottom: 4px; }
    .pc-chg { font-family: 'JetBrains Mono', monospace; font-size: 0.85rem; font-weight: 600; }
    .pc-chg.up { color: var(--accent-green); }
    .pc-chg.down { color: #FF2A5F; }

    .news-card {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      padding: 24px;
      height: 100%;
    }
    
    /* ── RESPONSIVE ── */
    @media (max-width: 900px) {
      .stats-container { grid-template-columns: repeat(2, 1fr); }
      .news-layout { grid-template-columns: 1fr; }
      .hero-title { font-size: 2.8rem; }
    }
    @media (max-width: 600px) {
      header { padding: 16px 20px; }
      .nav-links { display: none; }
      .stats-container { grid-template-columns: 1fr; }
      .cta-group { flex-direction: column; }
    }
  </style>"""

# Replace the existing fonts and style block with the new CSS
# Find the start and end of the <head> block contents related to styles
html_replaced = re.sub(
    r'<link href="https://fonts.googleapis.com/css2\?family=Syne.*?<style>.*?</style>',
    new_css,
    html,
    flags=re.DOTALL
)

# If the regex fails for any reason, we fallback to a simpler replacement
if html_replaced == html:
    html_replaced = re.sub(r'<style>.*?</style>', new_css, html, flags=re.DOTALL)

with open("trading-app/static/landing.html", "w", encoding="utf-8") as f:
    f.write(html_replaced)

print("Successfully rewrote landing.html styles")
