"""Serve synthetic UI-contract evidence without contacting Blue or Green."""

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from scripts.normalize_ui_contract_reference import normalized_reference_html


ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "docs" / "evidence" / "ui-contract-transversal" / "local-pages"
STATIC = ROOT / "app" / "static"
PROTOTYPE = Path(
    r"C:\Users\andre\.codex\visualizations\2026\08\26\01a03beb-dd9d-7cd1-8993-e17cb0a048f1\carfast-ui-contract-prototype.html"
)


class EvidenceHandler(SimpleHTTPRequestHandler):
    def do_GET(self) -> None:
        if urlsplit(self.path).path == "/reference":
            payload = normalized_reference_html().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        super().do_GET()

    def translate_path(self, path: str) -> str:
        clean = urlsplit(path).path
        if clean.startswith("/static/"):
            return str(STATIC / clean.removeprefix("/static/"))
        if clean.startswith("/v2-clean/email/") and clean.endswith("/preview"):
            return str(PAGES / "email-preview.html")
        if clean.startswith("/v2-clean/email/messages/") and clean.endswith("/body"):
            return str(PAGES / "email-body.html")
        if clean.startswith("/v2-clean/documents/") and clean.endswith("/file"):
            return str(PAGES / "document-preview.pdf")
        page = clean.strip("/") or "dashboard"
        if page.endswith(".html"):
            page = page[:-5]
        return str(PAGES / f"{page}.html")

    def log_message(self, format: str, *args: object) -> None:
        return


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8765), EvidenceHandler).serve_forever()
