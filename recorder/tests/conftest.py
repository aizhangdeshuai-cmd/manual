"""Shared pytest fixtures for recorder tests."""
import http.server
import socketserver
import threading
from pathlib import Path
import pytest

STATIC_SITE_DIR = Path(__file__).parent / "fixtures" / "static_site"


class _Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_SITE_DIR), **kwargs)

    def log_message(self, *args, **kwargs):
        pass  # silence fixture HTTP logs


@pytest.fixture(scope="session")
def fixture_url():
    """Start a local HTTP server hosting the static fixture, return base URL."""
    with socketserver.TCPServer(("127.0.0.1", 0), _Handler) as httpd:
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        yield f"http://127.0.0.1:{port}"
        httpd.shutdown()


@pytest.fixture(scope="session")
def auth_secret():
    """Test TOTP secret (Base32, no padding)."""
    return "JBSWY3DPEHPK3PXP"
