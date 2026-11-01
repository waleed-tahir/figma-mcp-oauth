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

## 🔍 Deep Dive: The "Antigravity Problem" Explained

If you are using **Google Antigravity IDE**, you have likely encountered this exact failure mode when trying to connect Figma:

```
┌────────────────────────────────────────────────────────────┐
│ figma  OAUTH                                               │
│ Used for: figma (MCP)                                      │
│ Domains: mcp.figma.com                                     │
│ Scopes: mcp:connect                                        │
│                                                            │
│ Paste the code shown after you sign in. Restart sign-in    │
│ [ Paste code                     ] [ Submit ]              │
└────────────────────────────────────────────────────────────┘
```

### Why Antigravity Gets Stuck:

#### 1. The Electron `window.open` Sandbox Block
When you click **"Sign in"** or **"Restart sign-in"** in Antigravity's **Plugins > Accounts** tab, the frontend UI (`workbench.desktop.main.js`) executes:
```javascript
AB(window, ke.authUrl, "_blank", "noopener,noreferrer"); // calls window.open(...)
```
In Antigravity's Electron architecture, calls to `window.open` inside the plugin accounts webview are not routed to Electron's `shell.openExternal()`. Consequently, **no browser window opens**, and nothing happens on screen. The UI switches to `lat.PASTE` mode, leaving you staring at an empty `[Paste code]` box with no URL to visit.

#### 2. The Ephemeral PKCE Mismatch (`invalid_grant`)
When users try to work around this by manually creating an OAuth app in Figma, authorizing in their own browser, and pasting the resulting code into Antigravity's `[Paste code]` box, Antigravity's Language Server (`CompleteMcpOAuth`) immediately rejects it:

```log
interceptor.go:70] /exa.language_server_pb.LanguageServerService/CompleteMcpOAuth: 
failed to exchange code for token: oauth2: "invalid_grant" "An error occurred processing your request"
```

**Why this happens:**
During the initial handshake, Antigravity's internal language server registered a dynamic client with an ephemeral PKCE `code_verifier` and set `redirect_uri=https://antigravity.google/oauth-callback`. If you paste a code obtained through a different client, different verifier, or different redirect URI, RFC 6749 requires Figma's token endpoint to reject the exchange with `invalid_grant`.

#### 3. How `figma-mcp-oauth` Solves It
`figma-mcp-oauth` completely bypasses the broken in-IDE webview flow:
1. Performs Dynamic Client Registration (RFC 7591) independently with an allowlisted client profile.
2. Generates a fresh, matched PKCE pair (`code_verifier` + `S256 code_challenge`).
3. Launches your real OS browser directly using system process calls (bypassing Electron's webview sandbox).
4. Catches the callback on `http://127.0.0.1:3344/callback`.
5. Exchanges the token successfully without `invalid_grant`.
6. Auto-injects the resulting Bearer token into Antigravity's configuration files:
   * `~/.gemini/config/mcp_config.json`
   * `~/.gemini/antigravity-ide/mcp_config.json`

Once injected, Antigravity instantly establishes a connection to `https://mcp.figma.com/mcp` as `figma-remote`, granting full access to all 42 Figma MCP tools (canvas writes via `use_figma`, Dev Mode code inspection, token extraction, etc.) without touching the broken accounts UI.

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

