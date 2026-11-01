#!/usr/bin/env python3
"""
Figma MCP OAuth & Dynamic Client Registration (DCR) Authenticator
================================================================
A zero-dependency CLI tool to authenticate with Figma's official Remote MCP
server (https://mcp.figma.com/mcp) using OAuth 2.0 PKCE and Dynamic Client
Registration (RFC 7591).

Solves the common issues where:
1. Figma's MCP DCR endpoint restricts registrations to allowlisted client profiles.
2. In-app browser handlers fail to launch the system browser on Windows/macOS/Linux.
3. Code-exchange fails with invalid_grant due to redirect URI or PKCE mismatches.
4. Remote MCP requires valid Bearer authorization in headers for tools/call.

Works with: Claude Code, Antigravity, Cursor, Claude Desktop, VS Code, and custom MCP clients.
"""

import argparse
import base64
import hashlib
import json
import os
import platform
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Dict, Optional, Tuple

# Endpoints
DCR_URL = "https://api.figma.com/v1/oauth/mcp/register"
AUTH_ENDPOINT = "https://www.figma.com/oauth/mcp"
TOKEN_ENDPOINT = "https://api.figma.com/v1/oauth/token"
REMOTE_MCP_URL = "https://mcp.figma.com/mcp"

# Default redirect configuration
DEFAULT_PORT = 3344
DEFAULT_CLIENT_NAME = "Claude Code"
DEFAULT_SCOPES = "mcp:connect openid email"


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """Local HTTP server handler to capture OAuth redirect code and state."""

    auth_code: Optional[str] = None
    auth_state: Optional[str] = None
    error: Optional[str] = None

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/callback":
            params = urllib.parse.parse_qs(parsed.query)
            if "code" in params:
                OAuthCallbackHandler.auth_code = params["code"][0]
                OAuthCallbackHandler.auth_state = params.get("state", [""])[0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                html = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Figma MCP Authentication Successful</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: #0f172a;
            color: #f8fafc;
            display: flex;
            align-items: center;
            justify-content: center;
            height: 100vh;
            margin: 0;
        }
        .card {
            background: #1e293b;
            padding: 40px;
            border-radius: 12px;
            text-align: center;
            max-width: 480px;
            box-shadow: 0 10px 25px rgba(0,0,0,0.5);
            border: 1px solid #334155;
        }
        h2 { color: #38bdf8; margin-top: 0; }
        p { color: #94a3b8; font-size: 15px; line-height: 1.5; }
        .badge {
            display: inline-block;
            background: rgba(34, 197, 94, 0.15);
            color: #22c55e;
            padding: 4px 12px;
            border-radius: 9999px;
            font-size: 13px;
            font-weight: 600;
            margin-top: 10px;
        }
    </style>
</head>
<body>
    <div class="card">
        <h2>Authentication Successful!</h2>
        <p>Your authorization code was received by the local listener.</p>
        <span class="badge">&#10003; Token Exchange in Progress</span>
        <p style="margin-top: 20px;">You may safely close this browser tab and return to your terminal.</p>
    </div>
</body>
</html>"""
                self.wfile.write(html.encode("utf-8"))
            else:
                OAuthCallbackHandler.error = params.get("error", ["Unknown error"])[0]
                self.send_response(400)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(f"<h3>Authentication failed: {OAuthCallbackHandler.error}</h3>".encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Suppress standard HTTP server request logs in terminal
        pass


def generate_pkce() -> Tuple[str, str]:
    """Generates RFC 7636 PKCE code_verifier and S256 code_challenge."""
    verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode("ascii")
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    return verifier, challenge


def register_dcr_client(client_name: str, redirect_uri: str) -> Dict[str, str]:
    """Performs Dynamic Client Registration (RFC 7591) with Figma's MCP gate."""
    payload = {
        "client_name": client_name,
        "redirect_uris": [redirect_uri],
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "scope": DEFAULT_SCOPES,
    }
    req = urllib.request.Request(
        DCR_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "vscode/1.95.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="ignore")
        if e.code == 403:
            raise RuntimeError(
                f"Figma DCR registration rejected (HTTP 403). Client name '{client_name}' "
                f"might not be accepted by Figma. Response: {error_body}"
            )
        raise RuntimeError(f"Figma DCR registration failed (HTTP {e.code}): {error_body}")


def exchange_code_for_tokens(
    client_id: str,
    client_secret: str,
    code: str,
    verifier: str,
    redirect_uri: str,
) -> Dict[str, str]:
    """Exchanges an authorization code and PKCE verifier for OAuth tokens."""
    payload = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code": code,
        "code_verifier": verifier,
    }
    if client_secret:
        payload["client_secret"] = client_secret

    encoded_payload = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(
        TOKEN_ENDPOINT,
        data=encoded_payload,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Token exchange failed (HTTP {e.code}): {error_body}")


def refresh_access_token(
    client_id: str,
    refresh_token: str,
    client_secret: str = "",
) -> Dict[str, str]:
    """Refreshes an expired OAuth access token using a refresh token."""
    payload = {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "refresh_token": refresh_token,
    }
    if client_secret:
        payload["client_secret"] = client_secret

    encoded_payload = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(
        TOKEN_ENDPOINT,
        data=encoded_payload,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Token refresh failed (HTTP {e.code}): {error_body}")


def verify_remote_mcp(access_token: str) -> bool:
    """Verifies that the access token can initialize the remote Figma MCP server."""
    init_payload = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "figma-mcp-auth", "version": "1.0.0"},
        },
    }).encode("utf-8")

    req = urllib.request.Request(
        REMOTE_MCP_URL,
        data=init_payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {access_token}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            body = resp.read().decode("utf-8")
            if resp.status == 200:
                print("   [+] Handshake Succeeded! Remote MCP is responsive.")
                # Show serverInfo if present in response
                try:
                    res_json = json.loads(body)
                    s_info = res_json.get("result", {}).get("serverInfo", {})
                    if s_info:
                        print(f"       Server: {s_info.get('name')} (v{s_info.get('version')})")
                except Exception:
                    pass
                return True
            return False
    except urllib.error.HTTPError as e:
        print(f"   [-] MCP Verification failed (HTTP {e.code}): {e.read().decode('utf-8', errors='ignore')}")
        return False
    except Exception as e:
        print(f"   [-] MCP Verification network error: {e}")
        return False


def open_browser(url: str):
    """Attempts to launch the browser across platforms with intelligent fallbacks."""
    # First try Python's standard webbrowser
    try:
        if webbrowser.open(url):
            return True
    except Exception:
        pass

    # Platform specific fallbacks
    os_name = platform.system()
    try:
        if os_name == "Windows":
            # Check popular browser executables
            candidates = [
                os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
                os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
                os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
                os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
            ]
            for exe in candidates:
                if os.path.exists(exe):
                    subprocess.Popen([exe, url])
                    return True
            subprocess.Popen(["cmd.exe", "/c", "start", "", url], shell=True)
            return True
        elif os_name == "Darwin":
            subprocess.Popen(["open", url])
            return True
        elif os_name == "Linux":
            subprocess.Popen(["xdg-open", url])
            return True
    except Exception:
        pass

    return False


def discover_mcp_config_paths() -> Dict[str, Path]:
    """Discovers standard MCP config file paths across platforms."""
    home = Path.home()
    configs = {}

    # Antigravity paths
    ag_user = home / ".gemini" / "config" / "mcp_config.json"
    ag_ide = home / ".gemini" / "antigravity-ide" / "mcp_config.json"
    if ag_user.parent.exists():
        configs["antigravity-user"] = ag_user
    if ag_ide.parent.exists():
        configs["antigravity-ide"] = ag_ide

    # Claude Desktop paths
    if platform.system() == "Darwin":
        claude_cfg = home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    elif platform.system() == "Windows":
        appdata = os.environ.get("APPDATA")
        claude_cfg = Path(appdata) / "Claude" / "claude_desktop_config.json" if appdata else None
    else:
        claude_cfg = home / ".config" / "Claude" / "claude_desktop_config.json"

    if claude_cfg and claude_cfg.parent.exists():
        configs["claude-desktop"] = claude_cfg

    # Cursor paths
    cursor_cfg = home / ".cursor" / "mcp.json"
    if cursor_cfg.parent.exists():
        configs["cursor"] = cursor_cfg

    return configs


def update_mcp_config(config_path: Path, server_name: str, access_token: str) -> bool:
    """Injects or updates the remote Figma MCP server in the specified config file."""
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}

        if "mcpServers" not in data:
            data["mcpServers"] = {}

        data["mcpServers"][server_name] = {
            "url": REMOTE_MCP_URL,
            "headers": {
                "Authorization": f"Bearer {access_token}"
            }
        }

        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        print(f"      [!] Failed to update {config_path}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Figma Remote MCP OAuth 2.0 Authenticator & Dynamic Client Registration"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Local port for OAuth redirect callback listener (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--client-name",
        type=str,
        default=DEFAULT_CLIENT_NAME,
        help=f"Allowlisted DCR client name (default: '{DEFAULT_CLIENT_NAME}')",
    )
    parser.add_argument(
        "--server-name",
        type=str,
        default="figma-remote",
        help="Name of the MCP server entry in configs (default: 'figma-remote')",
    )
    parser.add_argument(
        "--config",
        type=str,
        help="Custom path to an MCP config JSON file to update",
    )
    parser.add_argument(
        "--token-file",
        type=str,
        default=str(Path.home() / ".figma_mcp_tokens.json"),
        help="Destination path to persist the acquired OAuth tokens",
    )
    parser.add_argument(
        "--manual",
        action="store_true",
        help="Manual/headless mode (do not spawn local callback server, prompts for manual code input)",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Verify existing token from token-file against the remote MCP server",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Refresh access token using the stored refresh_token",
    )

    args = parser.parse_args()

    token_path = Path(args.token_file)

    print("=" * 66)
    print("  Figma Remote MCP OAuth 2.0 Dynamic Authenticator")
    print("=" * 66)

    # 1. Verify Only Mode
    if args.verify_only:
        if not token_path.exists():
            print(f"[!] No token file found at {token_path}")
            sys.exit(1)
        with open(token_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        tok = data.get("access_token")
        if not tok:
            print("[!] Token file does not contain 'access_token'")
            sys.exit(1)
        print(f"[*] Verifying token from {token_path}...")
        ok = verify_remote_mcp(tok)
        sys.exit(0 if ok else 1)

    # 2. Token Refresh Mode
    if args.refresh:
        if not token_path.exists():
            print(f"[!] No token file found at {token_path}")
            sys.exit(1)
        with open(token_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        ref_tok = data.get("refresh_token")
        c_id = data.get("client_id")
        c_sec = data.get("client_secret", "")
        if not ref_tok or not c_id:
            print("[!] Token file missing required 'refresh_token' or 'client_id'")
            sys.exit(1)
        print("[*] Refreshing access token...")
        try:
            new_tokens = refresh_access_token(c_id, ref_tok, c_sec)
            data.update(new_tokens)
            with open(token_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            print("[+] Token refreshed successfully!")
            verify_remote_mcp(data["access_token"])
            sys.exit(0)
        except Exception as e:
            print(f"[!] Refresh failed: {e}")
            sys.exit(1)

    # 3. Dynamic Registration (RFC 7591)
    redirect_uri = f"http://127.0.0.1:{args.port}/callback"
    print(f"\n[1/5] Registering dynamic OAuth client with Figma (name: '{args.client_name}')...")
    try:
        reg = register_dcr_client(args.client_name, redirect_uri)
    except Exception as e:
        print(f"[!] Registration failed: {e}")
        sys.exit(1)

    client_id = reg.get("client_id")
    client_secret = reg.get("client_secret", "")
    print(f"      Client registered successfully! Client ID: {client_id}")

    # 4. Generate PKCE & Authorization URL
    verifier, challenge = generate_pkce()
    state = base64.urlsafe_b64encode(os.urandom(16)).rstrip(b"=").decode("ascii")

    auth_url = (
        f"{AUTH_ENDPOINT}"
        f"?client_id={urllib.parse.quote(client_id)}"
        f"&redirect_uri={urllib.parse.quote(redirect_uri)}"
        f"&response_type=code"
        f"&scope=mcp%3Aconnect"
        f"&state={urllib.parse.quote(state)}"
        f"&code_challenge={urllib.parse.quote(challenge)}"
        f"&code_challenge_method=S256"
    )

    auth_code = None

    if args.manual:
        # Headless manual mode
        print("\n[2/5] Running in MANUAL / HEADLESS mode.")
        print(f"      Open this URL in any browser:\n\n{auth_url}\n")
        auth_code = input("Paste the authorization code (or full redirect URL): ").strip()
        if "code=" in auth_code:
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(auth_code).query)
            auth_code = qs.get("code", [auth_code])[0]
    else:
        # Automated local server mode
        print(f"\n[2/5] Starting local callback server on port {args.port}...")
        try:
            server = HTTPServer(("127.0.0.1", args.port), OAuthCallbackHandler)
        except OSError as e:
            print(f"[!] Could not bind to port {args.port}: {e}")
            print("    Try passing --port <another_port> or --manual")
            sys.exit(1)

        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()

        print("[3/5] Opening browser to complete authorization...")
        opened = open_browser(auth_url)
        if not opened:
            print("   [!] Could not auto-launch browser. Please open this link manually:")
        print(f"\n   -> {auth_url}\n")

        print("Waiting for you to click 'Allow access' in your browser (timeout: 180s)...")
        start_time = time.time()
        while time.time() - start_time < 180:
            if OAuthCallbackHandler.auth_code:
                auth_code = OAuthCallbackHandler.auth_code
                break
            if OAuthCallbackHandler.error:
                print(f"[!] Authorization error: {OAuthCallbackHandler.error}")
                server.shutdown()
                sys.exit(1)
            time.sleep(1)

        server.shutdown()

    if not auth_code:
        print("[!] Timed out waiting for authorization code.")
        sys.exit(1)

    print(f"\n[+] Authorization code captured successfully!")

    # 5. Token Exchange
    print("\n[4/5] Exchanging authorization code for OAuth tokens...")
    try:
        tokens = exchange_code_for_tokens(
            client_id=client_id,
            client_secret=client_secret,
            code=auth_code,
            verifier=verifier,
            redirect_uri=redirect_uri,
        )
    except Exception as e:
        print(f"[!] Token exchange failed: {e}")
        sys.exit(1)

    access_token = tokens.get("access_token")
    if not access_token:
        print(f"[!] Token response did not contain access_token: {tokens}")
        sys.exit(1)

    # Attach registration client details for future refresh
    tokens["client_id"] = client_id
    if client_secret:
        tokens["client_secret"] = client_secret
    tokens["saved_at"] = int(time.time())

    # Save to disk
    token_path.parent.mkdir(parents=True, exist_ok=True)
    with open(token_path, "w", encoding="utf-8") as f:
        json.dump(tokens, f, indent=2)
    print(f"      Tokens successfully saved to: {token_path}")
    print(f"      Token Type: {tokens.get('token_type', 'Bearer')}")
    print(f"      Expires In: {tokens.get('expires_in', 7776000)}s (~90 days)")

    # 6. Verify Remote MCP
    print("\n[5/5] Verifying remote MCP connection...")
    verify_remote_mcp(access_token)

    # 7. Update MCP Configs
    print("\n[*] Updating MCP client configuration files...")
    target_configs = {}
    if args.config:
        target_configs["custom"] = Path(args.config)
    else:
        target_configs = discover_mcp_config_paths()

    if not target_configs:
        print("    No existing MCP config files were automatically found.")
        print(f"    You can manually configure your MCP client with:")
        print(f"    URL: {REMOTE_MCP_URL}")
        print(f"    Header: Authorization: Bearer {access_token[:12]}...")
    else:
        for name, cfg_path in target_configs.items():
            if update_mcp_config(cfg_path, args.server_name, access_token):
                print(f"    [+] Updated '{args.server_name}' in: {cfg_path}")

    print("\n" + "=" * 66)
    print("  ALL SET! Your Figma Remote MCP server is ready for production.")
    print("=" * 66)


if __name__ == "__main__":
    main()
