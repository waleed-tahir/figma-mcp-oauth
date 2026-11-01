# Figma Remote MCP OAuth Authenticator (`figma-mcp-oauth`)

> **Automated OAuth 2.0 PKCE & Dynamic Client Registration (RFC 7591) for Figma's official Remote Model Context Protocol (MCP) server.**

Zero dependencies. Works with **Claude Code**, **Antigravity**, **Cursor**, **Claude Desktop**, **VS Code (Cline / Roo)**, and custom MCP clients.

---

## 💡 The Problem

Figma's official remote MCP server at `https://mcp.figma.com/mcp` provides 40+ deep tools for inspecting designs, reading dev mode code, generating vector layouts (`use_figma`), and extracting design tokens. However, connecting to it from developer tools and AI IDEs frequently fails due to three obstacles:

1. **Strict Dynamic Client Registration (DCR) Filter**: Figma's RFC 7591 endpoint (`https://api.figma.com/v1/oauth/mcp/register`) returns `403 Forbidden` if an unrecognized `client_name` is submitted.
2. **Blocked In-App Browser Launches**: Many AI IDEs and editors run in Electron sandboxes where internal webview calls to `window.open()` fail to open the OS default browser, leaving users stuck at a blank "Paste authorization code" prompt.
3. **`invalid_grant` Token Exchange Failures**: Manually copy-pasting codes or using generic OAuth tools fails because Figma strictly validates the cryptographically paired `code_verifier` (PKCE) and exact `redirect_uri` registered during the initial dynamic registration handshake.

---

## ⚡ The Solution

`figma-mcp-oauth` automates the entire RFC 7591 DCR and RFC 7636 PKCE handshake in a single command using **pure Python standard library** (no `pip install` required):

```
┌─────────────────┐       RFC 7591 DCR       ┌──────────────────────┐
│ figma_mcp_auth  │ ───────────────────────> │  api.figma.com/mcp   │
│                 │ <─────────────────────── │                      │
└────────┬────────┘       Client ID          └──────────────────────┘
         │
         │  1. Spawns 127.0.0.1:3344 callback listener
         │  2. Launches OS Browser with PKCE S256 challenge
         ▼
┌─────────────────┐      User Approves       ┌──────────────────────┐
│ Default Browser │ ───────────────────────> │ www.figma.com/oauth  │
└────────┬────────┘                          └──────────┬───────────┘
         │                                              │
         │ Redirects to http://127.0.0.1:3344/callback  │
         └──────────────────────────────────────────────┘
         │
         ▼ (Authorization Code captured automatically)
┌─────────────────┐     Token Exchange       ┌──────────────────────┐
│ figma_mcp_auth  │ ───────────────────────> │ api.figma.com/oauth  │
│                 │ <─────────────────────── │      /token          │
└────────┬────────┘    Bearer Access Token   └──────────────────────┘
         │
         ├─► Validates live with JSON-RPC initialize against https://mcp.figma.com/mcp
         └─► Auto-injects Authorization header into your editor's MCP config file!
```

---

## 🚀 Quickstart

Run with Python 3.8+ (no installation or external packages needed):

```bash
# Clone the repository
git clone https://github.com/waleed-tahir/figma-mcp-oauth.git
cd figma-mcp-oauth

# Run the authenticator
python figma_mcp_auth.py
```

### What Happens Automatically:
1. Registers a dynamic client with Figma's MCP server.
2. Starts a local redirect listener on `http://127.0.0.1:3344/callback`.
3. Opens your default browser (Chrome, Edge, Safari, Brave, Firefox) to Figma's authorization screen.
4. Once you click **"Allow access"**, the code is captured automatically.
5. Exchanges the code for an OAuth access token (valid for ~90 days) and a refresh token.
6. Verifies the connection to `https://mcp.figma.com/mcp`.
7. Auto-detects and updates your MCP configuration file(s).

---

## ⚙️ Command-Line Options

```
usage: figma_mcp_auth.py [-h] [--port PORT] [--client-name CLIENT_NAME]
                         [--server-name SERVER_NAME] [--config CONFIG]
                         [--token-file TOKEN_FILE] [--manual] [--verify-only]
                         [--refresh]

options:
  -h, --help            Show this help message and exit
  --port PORT           Local port for OAuth redirect callback listener (default: 3344)
  --client-name NAME    Allowlisted DCR client profile (default: 'Claude Code')
  --server-name NAME    Name of the MCP server key in configs (default: 'figma-remote')
  --config PATH         Custom path to an MCP config JSON file to update
  --token-file PATH     Destination path to persist tokens (default: ~/.figma_mcp_tokens.json)
  --manual              Headless mode: prints auth URL and prompts for code (useful over SSH)
  --verify-only         Verifies an existing token against the remote MCP server
  --refresh             Refreshes an existing access token using stored refresh_token
```

---

## 🛠️ Editor Configurations

If you prefer to configure your editor manually, add the following entry to your MCP configuration file using the generated access token:

### 1. Claude Desktop
**Path:**
* **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
* **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "figma-remote": {
      "url": "https://mcp.figma.com/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_ACCESS_TOKEN"
      }
    }
  }
}
```

### 2. Cursor
**Path:** `~/.cursor/mcp.json`

```json
{
  "mcpServers": {
    "figma-remote": {
      "url": "https://mcp.figma.com/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_ACCESS_TOKEN"
      }
    }
  }
}
```

### 3. Google Antigravity / Gemini CLI
**Path:** `~/.gemini/config/mcp_config.json`

```json
{
  "mcpServers": {
    "figma-remote": {
      "url": "https://mcp.figma.com/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_ACCESS_TOKEN"
      }
    }
  }
}
```

### 4. VS Code (Cline / Roo Code)
Add to your extension's MCP Settings JSON:

```json
{
  "mcpServers": {
    "figma-remote": {
      "url": "https://mcp.figma.com/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_ACCESS_TOKEN"
      }
    }
  }
}
```

---

## 🖥️ Headless / SSH / Remote Containers Mode

If you are running on a remote server or container without a local graphical browser:

```bash
python figma_mcp_auth.py --manual
```

1. The script will output the full Figma OAuth URL.
2. Open that URL on your local machine browser.
3. After approving, copy the redirected URL or authorization code from the browser address bar.
4. Paste it back into the terminal prompt.

---

## 🔄 Refreshing Expired Tokens

Figma access tokens typically remain valid for **90 days**. When your token nears expiration, refresh it seamlessly without re-authenticating in the browser:

```bash
python figma_mcp_auth.py --refresh
```

---

## 🔒 Security & Privacy

* **Zero telemetry**: This script contains no tracking, telemetry, or third-party SDKs.
* **Direct communication**: Requests only ever communicate with `api.figma.com` and `mcp.figma.com`.
* **Local credential storage**: Tokens are saved locally to your machine (defaulting to `~/.figma_mcp_tokens.json`) with standard user permissions.
* **Open Source**: Complete code is in a single, auditable Python script under the permissive MIT license.

---

## 📄 License

MIT License. See [LICENSE](LICENSE) for details.
