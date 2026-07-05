"""Chrome session bridge — import the user's real logged-in Chrome session
into Fagun's browser so any authenticated website can be tested without
providing credentials to the AI.

Three methods, tried in order:
  A. CDP (localhost:9222) — best; also pulls localStorage
  B. Chrome profile SQLite — reads & decrypts the Cookies DB directly
  C. File import — accepts a cookies.json dropped by the user

The result is injected into Fagun's browser context via context.add_cookies().
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .browser import manager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _domain_from_url(url: str) -> str:
    return urlparse(url).netloc.lstrip("www.")


def _cookie_matches(cookie_host: str, domain: str) -> bool:
    """Return True when a cookie's host_key covers the target domain."""
    h = cookie_host.lstrip(".")
    return h == domain or domain.endswith("." + h) or h.endswith("." + domain)


def _chrome_profile_paths() -> list[Path]:
    """Return candidate Chrome Default profile directories for this OS."""
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "Google" / "Chrome"
        edge = Path.home() / "Library" / "Application Support" / "Microsoft Edge"
        chromium = Path.home() / "Library" / "Application Support" / "Chromium"
    elif sys.platform.startswith("win"):
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        base = local / "Google" / "Chrome" / "User Data"
        edge = local / "Microsoft" / "Edge" / "User Data"
        chromium = local / "Chromium" / "User Data"
    else:
        cfg = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        base = cfg / "google-chrome"
        edge = cfg / "microsoft-edge"
        chromium = cfg / "chromium"

    paths = []
    for b in (base, edge, chromium):
        for profile in ("Default", "Profile 1", "Profile 2"):
            p = b / profile
            if p.exists():
                paths.append(p)
    return paths


def _decrypt_mac(encrypted_value: bytes) -> str:
    """Decrypt a macOS Chrome AES-CBC cookie value."""
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        from cryptography.hazmat.primitives import hashes, padding as sym_padding
        from cryptography.hazmat.backends import default_backend

        pw_result = subprocess.run(
            ["security", "find-generic-password", "-w", "-s", "Chrome Safe Storage"],
            capture_output=True, text=True, timeout=5,
        )
        pw = pw_result.stdout.strip().encode()
        if not pw:
            pw = b"peanuts"  # Chromium default

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA1(),
            length=16,
            salt=b"saltysalt",
            iterations=1003,
            backend=default_backend(),
        )
        key = kdf.derive(pw)

        # Strip the 3-byte 'v10' prefix
        iv = b" " * 16
        payload = encrypted_value[3:]
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
        dec = cipher.decryptor()
        raw = dec.update(payload) + dec.finalize()
        # Remove PKCS7 padding
        pad_len = raw[-1]
        return raw[:-pad_len].decode("utf-8", errors="replace")
    except Exception:
        return ""


def _decrypt_linux(encrypted_value: bytes, local_state_path: Path) -> str:
    """Decrypt a Linux Chrome AES-CBC cookie value."""
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.backends import default_backend

        ls = json.loads(local_state_path.read_text(encoding="utf-8"))
        enc_key_b64 = ls["os_crypt"]["encrypted_key"]
        enc_key = base64.b64decode(enc_key_b64)[5:]  # strip 'DPAPI' prefix
        pw = enc_key  # on Linux, the key itself is the password (no OS decryption)
        # Simplified: use default Chromium password
        pw = b"peanuts"

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA1(),
            length=16,
            salt=b"saltysalt",
            iterations=1,
            backend=default_backend(),
        )
        key = kdf.derive(pw)

        iv = b" " * 16
        version = encrypted_value[:3]
        payload = encrypted_value[3:] if version in (b"v10", b"v11") else encrypted_value
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
        dec = cipher.decryptor()
        raw = dec.update(payload) + dec.finalize()
        pad_len = raw[-1]
        return raw[:-pad_len].decode("utf-8", errors="replace")
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Method A — CDP
# ---------------------------------------------------------------------------

async def import_from_cdp(target_url: str, port: int = 9222) -> dict[str, Any]:
    """Import cookies (and localStorage when possible) from a Chrome instance
    with remote debugging enabled on localhost:port."""
    domain = _domain_from_url(target_url)
    cdp_url = f"http://127.0.0.1:{port}"

    # Check if debug port is open via a plain HTTP request (no aiohttp needed)
    import urllib.request
    try:
        with urllib.request.urlopen(f"{cdp_url}/json/version", timeout=3) as r:
            if r.status != 200:
                return {"imported": 0, "method": "cdp", "error": f"CDP port {port} returned {r.status}"}
    except Exception as e:
        return {"imported": 0, "method": "cdp", "error": f"CDP not available on port {port}: {e}"}

    # Use Playwright CDP session to read all cookies
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            browser = await pw.chromium.connect_over_cdp(cdp_url)
            contexts = browser.contexts
            if not contexts:
                await browser.close()
                return {"imported": 0, "method": "cdp", "error": "No browser contexts found"}

            ctx = contexts[0]
            # Get all cookies from the existing context
            all_cookies = await ctx.cookies()
            matching = [c for c in all_cookies if _cookie_matches(c.get("domain", ""), domain)]

            # Try to get localStorage via a page
            ls_data: dict[str, str] = {}
            pages = ctx.pages
            target_page = None
            for p in pages:
                if domain in p.url:
                    target_page = p
                    break
            if target_page:
                try:
                    ls_data = await target_page.evaluate(
                        "() => Object.fromEntries(Object.entries(localStorage))"
                    )
                except Exception:
                    pass

            await browser.close()

        if not matching:
            return {"imported": 0, "method": "cdp", "domain": domain,
                    "error": f"No cookies found for {domain} in Chrome. Are you logged in?"}

        # Inject into Fagun's context
        context = manager._context
        if context is None:
            await manager.start()
            context = manager._context

        await context.add_cookies(matching)

        # Inject localStorage if found
        if ls_data and target_page:
            page = await manager.page()
            try:
                await page.goto(target_url, wait_until="domcontentloaded", timeout=15000)
                for k, v in ls_data.items():
                    await page.evaluate(f"localStorage.setItem({json.dumps(k)}, {json.dumps(v)})")
            except Exception:
                pass

        return {
            "imported": len(matching),
            "method": "cdp",
            "domain": domain,
            "localStorage_keys": list(ls_data.keys()),
            "cookies": [c["name"] for c in matching],
        }
    except Exception as e:
        return {"imported": 0, "method": "cdp", "error": str(e)}


# ---------------------------------------------------------------------------
# Method B — Chrome profile SQLite
# ---------------------------------------------------------------------------

async def import_from_chrome_profile(target_url: str) -> dict[str, Any]:
    """Read and decrypt cookies from Chrome's local SQLite Cookies database."""
    domain = _domain_from_url(target_url)
    profile_paths = _chrome_profile_paths()

    if not profile_paths:
        return {"imported": 0, "method": "profile",
                "error": "No Chrome profile directory found"}

    # Try to import cryptography — needed for decryption
    try:
        import cryptography  # noqa: F401
    except ImportError:
        return {"imported": 0, "method": "profile",
                "error": "cryptography package not installed. Run: pip install cryptography"}

    imported_cookies = []
    errors = []

    for profile_dir in profile_paths:
        cookies_db = profile_dir / "Cookies"
        if not cookies_db.exists():
            # Chromium 96+ moved to Network/Cookies
            cookies_db = profile_dir / "Network" / "Cookies"
        if not cookies_db.exists():
            continue

        # Copy DB to temp (Chrome may have it locked)
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        try:
            shutil.copy2(str(cookies_db), tmp.name)
            conn = sqlite3.connect(tmp.name)
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT host_key, name, encrypted_value, value, path, "
                "expires_utc, is_secure, is_httponly, samesite "
                "FROM cookies"
            )
            rows = cursor.fetchall()
            conn.close()
        except Exception as e:
            errors.append(str(e))
            continue
        finally:
            try:
                os.unlink(tmp.name)
            except Exception:
                pass

        local_state = profile_dir.parent / "Local State"

        for row in rows:
            host_key = row["host_key"]
            if not _cookie_matches(host_key, domain):
                continue

            enc = row["encrypted_value"]
            value = row["value"] or ""
            if enc:
                if sys.platform == "darwin":
                    value = _decrypt_mac(enc) or value
                elif sys.platform.startswith("linux"):
                    value = _decrypt_linux(enc, local_state) if local_state.exists() else value
                # Windows DPAPI not implemented — use plaintext fallback

            if not value:
                continue

            # Convert Chrome epoch (microseconds since 1601) to Unix timestamp
            expires = 0
            if row["expires_utc"]:
                chrome_epoch = row["expires_utc"]
                unix_epoch = (chrome_epoch / 1_000_000) - 11644473600
                expires = max(0, int(unix_epoch))

            imported_cookies.append({
                "name": row["name"],
                "value": value,
                "domain": host_key,
                "path": row["path"] or "/",
                "expires": expires,
                "httpOnly": bool(row["is_httponly"]),
                "secure": bool(row["is_secure"]),
                "sameSite": {0: "Lax", 1: "Strict", 2: "None"}.get(row["samesite"], "Lax"),
            })

        if imported_cookies:
            break  # Found cookies in first matching profile

    if not imported_cookies:
        return {
            "imported": 0,
            "method": "profile",
            "domain": domain,
            "error": f"No decryptable cookies for {domain} in Chrome profile. "
                     f"Errors: {errors[:2]}",
        }

    # Inject into Fagun context
    context = manager._context
    if context is None:
        await manager.start()
        context = manager._context

    # Filter to valid cookies (remove expired, fix domain format)
    valid = []
    for c in imported_cookies:
        try:
            if c["expires"] and c["expires"] < 1000:
                continue  # already expired
            valid.append(c)
        except Exception:
            pass

    if valid:
        try:
            await context.add_cookies(valid)
        except Exception as e:
            return {"imported": 0, "method": "profile", "error": f"add_cookies failed: {e}"}

    return {
        "imported": len(valid),
        "method": "profile",
        "domain": domain,
        "cookies": [c["name"] for c in valid],
    }


# ---------------------------------------------------------------------------
# Method C — File import
# ---------------------------------------------------------------------------

async def import_from_file(path: str, target_url: str) -> dict[str, Any]:
    """Import cookies from a JSON file (array of {name, value, domain, path} objects
    or Netscape cookie format). The user exports this from a browser extension."""
    domain = _domain_from_url(target_url)
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as e:
        return {"imported": 0, "method": "file", "error": f"Cannot read {path}: {e}"}

    # Handle array of cookie objects
    if isinstance(data, list):
        cookies = data
    elif isinstance(data, dict) and "cookies" in data:
        cookies = data["cookies"]
    else:
        return {"imported": 0, "method": "file", "error": "Unrecognised format. Expected JSON array of cookie objects."}

    matching = [c for c in cookies if _cookie_matches(c.get("domain", ""), domain)]
    if not matching:
        return {"imported": 0, "method": "file", "domain": domain,
                "error": f"No cookies for {domain} in file"}

    context = manager._context
    if context is None:
        await manager.start()
        context = manager._context

    # Normalise fields to what Playwright expects
    norm = []
    for c in matching:
        try:
            norm.append({
                "name": c["name"],
                "value": c.get("value", ""),
                "domain": c.get("domain", f".{domain}"),
                "path": c.get("path", "/"),
                "expires": int(c["expirationDate"]) if "expirationDate" in c else -1,
                "httpOnly": bool(c.get("httpOnly", False)),
                "secure": bool(c.get("secure", False)),
                "sameSite": c.get("sameSite", "Lax"),
            })
        except Exception:
            continue

    await context.add_cookies(norm)
    return {
        "imported": len(norm),
        "method": "file",
        "domain": domain,
        "cookies": [c["name"] for c in norm],
    }


# ---------------------------------------------------------------------------
# Auto-import: try all methods
# ---------------------------------------------------------------------------

async def auto_import(target_url: str, cdp_port: int = 9222) -> dict[str, Any]:
    """Try CDP → Chrome profile → give up. Returns result from the first
    method that successfully imports at least one cookie."""

    # Method A: CDP
    result = await import_from_cdp(target_url, port=cdp_port)
    if result.get("imported", 0) > 0:
        result["auto_method"] = "cdp"
        return result

    # Method B: Chrome profile SQLite
    result = await import_from_chrome_profile(target_url)
    if result.get("imported", 0) > 0:
        result["auto_method"] = "profile"
        return result

    # Nothing worked
    domain = _domain_from_url(target_url)
    return {
        "imported": 0,
        "auto_method": "none",
        "domain": domain,
        "error": (
            "Could not import Chrome session automatically. "
            "Options: (1) Enable Chrome remote debugging — launch Chrome with "
            "--remote-debugging-port=9222, or run fagun connect_chrome first. "
            "(2) Export cookies from Chrome with a browser extension (e.g. Cookie-Editor) "
            "and use import_chrome_session(url, cookie_file='path/to/cookies.json'). "
            "(3) Use login_with_credentials() to log in directly."
        ),
    }
