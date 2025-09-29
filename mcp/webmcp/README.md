# 🌐 webmcp - Browser Automation MCP Server

[![Python](https://img.shields.io/badge/python-3.8+-blue.svg)](https://python.org)
[![Playwright](https://img.shields.io/badge/playwright-automation-green.svg)](https://playwright.dev)
[![MCP](https://img.shields.io/badge/MCP-protocol-orange.svg)](https://github.com/anthropics/mcp)

> **Revolutionary browser automation MCP server that inherits your local browser credentials and sessions**

## 🚀 The Magic

**webmcp** follows our **revolutionary local MCP pattern**:

1. **Start locally**: `webmcp` (auto-detects your browser profile)
2. **Auto-copies connection**: JSON config copied to clipboard
3. **Remote connection**: Paste in da_code cloud → instant browser automation with YOUR credentials
4. **Full power**: Remote AI agent controls your local browser with all your logged-in sessions

## ⚡ Key Features

### 🔑 **Local Credential Inheritance**
- **Auto-detects** your browser profile directory
- **Inherits** all your logged-in sessions (Gmail, GitHub, etc.)
- **Reuses** saved passwords and authentication cookies
- **Zero setup** - works with your existing browser state

### 🌐 **Full Browser Automation**
- **Navigate** to any URL with wait conditions
- **Click** elements using CSS selectors or accessibility names
- **Fill forms** with automatic field clearing
- **Take screenshots** (full page or viewport)
- **Execute JavaScript** with return values
- **Wait** for elements or text content
- **Multi-tab** management

### 🔄 **da_code Integration**
- **Automatic clipboard copy** of connection JSON
- **Session-scoped** connections (clean disconnection)
- **Real-time** browser control from remote agents
- **Error handling** with detailed feedback

## 🎯 Installation & Usage

### **Local Setup** (Your machine with browser)
```bash
# Install webmcp
cd /path/to/mcp/webmcp
pip install -e .

# Start server (auto-detects browser profile)
webmcp

# Output:
# ✅ Connection command copied to clipboard!
# 📋 Browser MCP Connection Config:
# {
#   "name": "webmcp",
#   "url": "http://192.168.1.77:8005",
#   "description": "Browser automation from YourMachine",
#   "tools": ["browser_navigate", "browser_click", ...]
# }
```

### **Remote Connection** (da_code instance)
```bash
# In your da_code session (Linux/cloud)
> add_mcp {"name": "webmcp", "url": "http://192.168.1.77:8005", ...}
✅ MCP server 'webmcp' added successfully

# Instantly available tools:
> browser_navigate {"url": "https://github.com"}
🤖 Navigated to GitHub using your local browser with your login!
```

## 🛠️ Tool Reference

### **Navigation**
```bash
# Navigate to URL
browser_navigate {"url": "https://example.com", "wait_until": "networkidle"}

# Navigate with custom timeout
browser_navigate {"url": "https://slow-site.com", "timeout": 60000}
```

### **Element Interaction**
```bash
# Click elements
browser_click {"selector": "#login-button"}
browser_click {"selector": "text=Sign In", "button": "left"}

# Fill forms
browser_fill {"selector": "#username", "value": "myuser"}
browser_fill {"selector": "input[type=password]", "value": "secret", "clear": true}
```

### **Content & Screenshots**
```bash
# Take screenshots
browser_screenshot {"full_page": true, "format": "png"}
browser_screenshot {"path": "/tmp/page.jpg", "format": "jpeg", "quality": 80}

# Get page content
browser_get_content  # Returns HTML, text, title, URL
```

### **JavaScript Execution**
```bash
# Execute JavaScript
browser_evaluate {"script": "return document.title"}
browser_evaluate {"script": "window.scrollTo(0, document.body.scrollHeight)"}

# With arguments
browser_evaluate {
  "script": "return arguments[0] + arguments[1]",
  "args": [5, 10]
}
```

### **Waiting & Timing**
```bash
# Wait for elements
browser_wait {"selector": "#dynamic-content", "state": "visible", "timeout": 30000}

# Wait for text
browser_wait {"text": "Loading complete", "timeout": 15000}
```

### **Tab Management**
```bash
# Create new tab
browser_new_tab {"url": "https://example.com"}

# Close specific tab
browser_close_tab {"page_id": "tab_1"}

# Close current tab
browser_close_tab
```

## 🎪 Revolutionary Use Cases

### **Authenticated Workflows**
```bash
# Your browser is already logged into GitHub
> "navigate to my GitHub repositories and create a new repo called 'ai-experiment'"

🤖 1. Navigating to github.com...
   ✅ Already logged in (using your credentials)

   2. Clicking "New repository"...
   ✅ Repository creation form opened

   3. Filling repository name...
   ✅ Entered "ai-experiment"

   4. Clicking "Create repository"...
   ✅ Repository created successfully!
```

### **Cross-Platform Development**
```bash
# Local browser on Windows, da_code on Linux
> "open the staging environment and run the test suite in the browser console"

🤖 Using your local browser with saved staging credentials...
   ✅ Navigated to staging.example.com
   ✅ Executed test suite: 15 tests passed
   📸 Screenshot saved for verification
```

### **Automated Testing**
```bash
# Test with real browser state
> "test the login flow on our app using my existing session"

🤖 1. Opening app.example.com...
   ✅ Page loaded (already authenticated)

   2. Testing logout/login flow...
   ✅ Logout successful
   ✅ Login form appeared
   ✅ Re-authentication successful

   All tests passed! 🎉
```

## ⚙️ Configuration Options

### **Browser Selection**
```bash
# Use different browsers
webmcp --browser chromium    # Default
webmcp --browser firefox     # Firefox
webmcp --browser webkit      # Safari engine
```

### **Custom Profile Directory**
```bash
# Specify custom browser profile
webmcp --user-data-dir "/path/to/browser/profile"

# Headless mode (for cloud deployment)
webmcp --headless
```

### **Network Configuration**
```bash
# Bind to specific interface
webmcp --host 0.0.0.0 --port 8005

# Custom port
webmcp --port 9000
```

## 🏗️ Architecture

### **Local Browser Integration**
```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  Your Browser   │◄──►│    webmcp       │◄──►│ Remote da_code  │
│                 │    │                 │    │                 │
│ 🔑 Your Logins  │    │ 🎭 Playwright   │    │ 🤖 AI Agent     │
│ 🍪 Your Cookies │    │ 🌐 HTTP Server  │    │ 🧠 Commands     │
│ 📁 Your Profile │    │ 📋 Auto-copy    │    │ 🔗 MCP Client   │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

### **Security Model**
- **Local execution**: Browser runs on your machine with your permissions
- **Network isolation**: Only HTTP API exposed, no direct browser access
- **Session inheritance**: Uses your existing authentication safely
- **Timeout protection**: All operations have configurable timeouts

## 🚨 Security Considerations

### **Safe Defaults**
- **Non-headless by default**: See what the browser is doing
- **Local binding**: Only localhost access unless explicitly configured
- **Timeout limits**: Prevents runaway operations
- **Error boundaries**: Graceful failure handling

### **Authentication**
- **No credential storage**: Uses your existing browser sessions
- **No credential transmission**: Credentials never leave your machine
- **Session reuse**: Leverages existing authenticated state
- **Clean disconnection**: No persistent connections

## 🎯 Perfect for da_code

**webmcp** integrates seamlessly with the da_code ecosystem:

1. **Follows MCP patterns**: Standard tool naming and error handling
2. **Auto-discovery**: Clipboard copy for instant connection
3. **Session management**: Clean connection lifecycle
4. **Rich responses**: Detailed success/error feedback
5. **Async architecture**: Non-blocking operations

## 🔮 Future Enhancements

- **Mobile browsers**: iOS Safari and Android Chrome support
- **Browser extensions**: Direct extension communication
- **Video recording**: Capture browser interactions
- **Performance metrics**: Page load timing and analysis
- **Advanced selectors**: XPath and custom selector engines

---

**webmcp: Where local browser power meets remote AI intelligence.**

**Your browser. Your credentials. Unlimited automation possibilities.**