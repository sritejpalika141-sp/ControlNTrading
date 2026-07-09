import re
import os

with open("old_landing.html", "r", encoding="utf-8") as f:
    old_html = f.read()

with open("trading-app/static/landing.html", "r", encoding="utf-8") as f:
    new_html = f.read()

# 1. Extract CSS
# I will extract from ".feature-card {" (wait, new_html already has .feature-card, I need to be careful not to conflict)
# Let's extract from "    .features-grid {" down to "  </style>" from old_landing.html
css_match = re.search(r"(\s*\.features-grid \{.*?)(\s*</style>)", old_html, re.DOTALL)
if css_match:
    old_css = css_match.group(1)
    
    # In old_css, rename .feature-card to .old-feature-card to avoid conflict with the new mockup cards
    old_css = old_css.replace('.feature-card', '.old-feature-card')
    old_css = old_css.replace('.feature-title', '.old-feature-title')
    old_css = old_css.replace('.feature-desc', '.old-feature-desc')
    old_css = old_css.replace('.feature-icon', '.old-feature-icon')
    
    # Inject into new_html
    new_html = new_html.replace("</style>", old_css + "\n  </style>")

# 2. Extract HTML sections
html_match = re.search(r"(<!-- ═══ STRATEGIES ═══ -->.*?)(<script>)", old_html, re.DOTALL)
if html_match:
    old_sections = html_match.group(1)
    
    # Rename classes in old_sections to match the renamed CSS
    old_sections = old_sections.replace('class="feature-card"', 'class="old-feature-card"')
    old_sections = old_sections.replace('class="feature-title"', 'class="old-feature-title"')
    old_sections = old_sections.replace('class="feature-desc"', 'class="old-feature-desc"')
    old_sections = old_sections.replace('class="feature-icon"', 'class="old-feature-icon"')
    
    # Rename IDs so they match the nav links in the new mockup
    old_sections = old_sections.replace('id="features"', 'id="strategies"')
    # old_sections already has id="security", id="compliance", id="news" (we should rename "news" to "marketnews" to match nav link)
    old_sections = old_sections.replace('id="news"', 'id="marketnews"')
    
    # Find where to inject in new_html. After the modal overlay, before <script>
    new_html = new_html.replace("<!-- MODAL -->", old_sections + "\n  <!-- MODAL -->")

# 3. Extract JS
js_match = re.search(r"(// ═══════════════════════════════════════════════════\n\s*// MARKET PRICES.*?)(</script>)", old_html, re.DOTALL)
if js_match:
    old_js = js_match.group(1)
    new_html = new_html.replace("</script>\n</body>", old_js + "\n</script>\n</body>")

# 4. Remove 'Get Started' or 'Login' if requested? User said: "remove login in menu." 
# But keep "ControlN trading Logo".
# In current nav-pill, there's `<a href="/login" class="btn-cyan">Get Started</a>`
# User: "remove login in menu."
# We'll leave Get Started button, maybe they meant removing it from the ul list if it was there? No, the old one had it.
# Actually I'll remove the Get Started button in the navbar just to be safe, or rename it. They said "remove login in menu". 
# The new menu has "Get Started" which acts as login. I'll remove the `<a href="/login" class="btn-cyan">Get Started</a>` from the nav-pill.
new_html = re.sub(r'<div class="header-actions">.*?</div>', '', new_html, flags=re.DOTALL)

with open("trading-app/static/landing.html", "w", encoding="utf-8") as f:
    f.write(new_html)

print("Merged successfully!")
