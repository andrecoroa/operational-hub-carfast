"""Export the approved prototype without its presentation-only chrome.

The source stays outside the application repository and is never replaced by a
capture of the implementation.  This exporter only resolves explicit contract
tokens, repairs known mojibake and selects a deterministic page/viewport.
"""

from __future__ import annotations

from pathlib import Path


SOURCE = Path(
    r"C:\Users\andre\.codex\visualizations\2026\08\26\01a03beb-dd9d-7cd1-8993-e17cb0a048f1"
    r"\carfast-ui-contract-prototype.html"
)

TOKEN_STYLE = """
<style id="canonical-export-tokens">
:root{--background:#fff;--foreground:#16181d;--muted:#f5f6f8;
--muted-foreground:#667085;--border:#dfe3e8;--input:#cfd5dc;
--primary:#fff;--primary-foreground:#16181d;--accent:#eef4ff;
--accent-foreground:#163f8c;--blue:#315fce;--green:#16805c;
--orange:#b86814;--red:#bd3131}
html,body{margin:0;background:#fff}.cf-devicebar,.cf-caption{display:none!important}
.cf-stage{border:0!important;border-radius:0!important}.cf-stage.desktop,
.cf-stage.tablet,.cf-stage.mobile{width:100%!important;margin:0!important}
</style>
"""

MOJIBAKE = {
    "Ã§": "ç", "Ã£": "ã", "Ãµ": "õ", "Ã¡": "á", "Ã©": "é",
    "Ã­": "í", "Ã³": "ó", "Ãº": "ú", "Ã‡": "Ç", "Ãƒ": "Ã",
    "Â·": "·", "Â»:": "»:", "Â": "",
}


def normalized_reference_html() -> str:
    html = SOURCE.read_text(encoding="utf-8")
    for broken, fixed in MOJIBAKE.items():
        html = html.replace(broken, fixed)
    html = TOKEN_STYLE + html
    html += """
<script>
(() => {
  const query = new URLSearchParams(location.search);
  const page = query.get('page') || 'dashboard';
  const size = query.get('size') || 'desktop';
  document.querySelector(`[data-page="${page}"]`)?.click();
  document.querySelector(`[data-size="${size}"]`)?.click();
})();
</script>
"""
    return html


if __name__ == "__main__":
    print(normalized_reference_html())
