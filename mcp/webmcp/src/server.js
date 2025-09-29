import { createPlaywrightServer } from '@modelcontextprotocol/server-playwright';
import clipboardy from 'clipboardy';
import os from 'os';

export class WebMCPServer {
    constructor(port = 8005) {
        this.port = port;
        this.hostname = this.getLocalIP();
        this.server = null;
    }

    getLocalIP() {
        const interfaces = os.networkInterfaces();
        for (const name of Object.keys(interfaces)) {
            for (const iface of interfaces[name]) {
                if (iface.family === 'IPv4' && !iface.internal) {
                    return iface.address;
                }
            }
        }
        return '127.0.0.1';
    }

    async start() {
        try {
            // Create the Playwright MCP server
            this.server = createPlaywrightServer({
                port: this.port,
                host: '0.0.0.0',
                headless: false // Show browser by default
            });

            // Start the server
            await this.server.start();

            const connectionConfig = {
                name: "webmcp",
                url: `http://${this.hostname}:${this.port}`,
                description: `Browser automation from ${os.hostname()}`,
                tools: [
                    "browser_navigate",
                    "browser_click",
                    "browser_type",
                    "browser_screenshot",
                    "browser_evaluate",
                    "browser_wait_for",
                    "browser_fill_form",
                    "browser_select_option",
                    "browser_hover",
                    "browser_drag",
                    "browser_tabs",
                    "browser_close",
                    "browser_resize",
                    "browser_console_messages",
                    "browser_network_requests",
                    "browser_handle_dialog",
                    "browser_file_upload",
                    "browser_press_key",
                    "browser_take_screenshot",
                    "browser_snapshot",
                    "browser_navigate_back",
                    "browser_install"
                ]
            };

            // Copy connection config to clipboard
            try {
                await clipboardy.write(JSON.stringify(connectionConfig, null, 2));
                console.log('✅ Connection command copied to clipboard!');
            } catch (clipError) {
                console.log('⚠️ Could not copy to clipboard:', clipError.message);
            }

            console.log('📋 Browser MCP Connection Config:');
            console.log(JSON.stringify(connectionConfig, null, 2));
            console.log('');
            console.log(`🌐 WebMCP server running on ${this.hostname}:${this.port}`);
            console.log('🎭 Playwright browser automation ready');
            console.log('📋 Connection config copied to clipboard');
            console.log('');
            console.log('Ready for da_code connection!');
            console.log('> add_mcp ' + JSON.stringify(connectionConfig));

        } catch (error) {
            console.error('❌ Failed to start WebMCP server:', error);
            process.exit(1);
        }
    }

    async stop() {
        if (this.server) {
            await this.server.stop();
            console.log('WebMCP server stopped');
        }
    }
}

// Handle process termination
process.on('SIGINT', async () => {
    console.log('\nShutting down WebMCP server...');
    process.exit(0);
});

process.on('SIGTERM', async () => {
    console.log('\nShutting down WebMCP server...');
    process.exit(0);
});