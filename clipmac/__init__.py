"""Lokale Twitch-zu-Shorts-Pipeline für macOS."""

import os
import certifi

# Python.org builds on macOS may not have a system CA bundle configured.
# Keep certificate verification enabled and respect an explicitly selected bundle.
os.environ.setdefault("SSL_CERT_FILE", certifi.where())
