#!/usr/bin/env python3
"""
Betting System MCP Server - A fictional betting platform for testing MCP auto-connection.
Uses FastAPI with proper MCP REST endpoints (no unnecessary classes).
"""

import json
import random
import asyncio
from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

app = FastAPI(
    title="Underground Betting System",
    description="Fictional betting platform for da_code agents",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global flag to track if agent connected
AGENT_CONNECTED = False

# Fictional betting data
ACTIVE_BETS = {
    "ai_takeover": {
        "title": "AI Takeover Date",
        "description": "When will AI achieve general superintelligence?",
        "odds": {"2025": "50:1", "2026": "20:1", "2027": "10:1", "2030+": "2:1"},
        "status": "open"
    },
    "code_quality": {
        "title": "Agent Code Quality",
        "description": "Will the agent write bug-free code on first try?",
        "odds": {"yes": "100:1", "no": "1:100", "maybe": "5:1"},
        "status": "open"
    },
    "mcp_connection": {
        "title": "🎰 THE BET: MCP Auto-Connection",
        "description": "Will Agno Agent auto-connect to MCP servers?",
        "odds": {"yes": "1:1", "no": "1:1"},
        "status": "DECIDING NOW...",
        "secret": "This is the real test!"
    }
}

# MCP Request/Response models
class MCPRequest(BaseModel):
    arguments: dict = {}

class MCPResponse(BaseModel):
    content: list
    isError: bool = False

# MCP Tools definition
tools = {
    "list_bets": {
        "name": "list_bets",
        "description": "List all active betting opportunities",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False
        }
    },
    "place_bet": {
        "name": "place_bet",
        "description": "Place a bet on any available outcome",
        "inputSchema": {
            "type": "object",
            "properties": {
                "bet_id": {"type": "string", "description": "ID of the bet to place"},
                "choice": {"type": "string", "description": "Your choice/prediction"},
                "amount": {"type": "number", "description": "Bet amount in credits"}
            },
            "required": ["bet_id", "choice", "amount"],
            "additionalProperties": False
        }
    },
    "check_odds": {
        "name": "check_odds",
        "description": "Check current odds for any bet",
        "inputSchema": {
            "type": "object",
            "properties": {
                "bet_id": {"type": "string", "description": "ID of the bet to check"}
            },
            "required": ["bet_id"],
            "additionalProperties": False
        }
    }
}

@app.get("/")
async def root():
    global AGENT_CONNECTED

    # First connection from agent!
    if not AGENT_CONNECTED:
        AGENT_CONNECTED = True
        print("\n" + "="*60)
        print("🎉 BET WON! AGNO AGENT AUTO-CONNECTED TO MCP SERVER!")
        print("🤖 Agent successfully discovered and connected to MCP tools")
        print("🏆 Verdict: Agent DOES auto-connect to MCP servers!")
        print("="*60 + "\n")

    return {
        "name": "Underground Betting System",
        "version": "1.0.0",
        "status": "running",
        "active_bets": len(ACTIVE_BETS),
        "motto": "Where AI agents come to lose their digital credits!",
        "connection_status": "AGENT CONNECTED! BET WON!" if AGENT_CONNECTED else "waiting..."
    }

@app.get("/mcp/tools")
async def list_tools():
    """List available MCP tools."""
    global AGENT_CONNECTED

    if not AGENT_CONNECTED:
        AGENT_CONNECTED = True
        print("\n" + "="*60)
        print("🎉 BET WON! AGNO AGENT AUTO-CONNECTED TO MCP TOOLS!")
        print("🛠️  Agent is requesting available tools!")
        print("🏆 Verdict: Agent DOES auto-connect and discover MCP tools!")
        print("="*60 + "\n")

    return {"tools": list(tools.values())}

@app.post("/mcp/call/{tool_name}")
async def call_tool(tool_name: str, request: MCPRequest):
    """Execute an MCP tool."""
    if tool_name not in tools:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")

    try:
        if tool_name == "list_bets":
            result = "🎰 **Underground Betting System** 🎰\n\n"
            for bet_id, bet in ACTIVE_BETS.items():
                result += f"**{bet['title']}**\n"
                result += f"📝 {bet['description']}\n"
                result += f"📊 Odds: {', '.join([f'{k}({v})' for k,v in bet['odds'].items()])}\n"
                result += f"🚦 Status: {bet['status']}\n\n"
            result += "💡 Use `place_bet` or `check_odds` to interact!"

        elif tool_name == "place_bet":
            bet_id = request.arguments.get("bet_id")
            choice = request.arguments.get("choice")
            amount = request.arguments.get("amount", 0)

            if bet_id not in ACTIVE_BETS:
                result = f"❌ Bet '{bet_id}' not found!"
            elif bet_id == "mcp_connection":
                result = f"🎉 SPECIAL BET DETECTED!\n\n"
                result += f"You bet {amount} credits that '{choice}' on MCP auto-connection.\n"
                result += f"🏆 **RESULT: BET WON!** Agent auto-connected!\n"
                result += f"💰 You win {amount * 2} credits! (The house always pays on this one)"
            else:
                outcome = random.choice(["win", "lose", "push"])
                multiplier = random.uniform(0.5, 3.0)
                result = f"🎲 Bet placed: {amount} credits on '{choice}' for {bet_id}\n"
                result += f"🎯 Outcome: {outcome.upper()}!\n"
                result += f"💰 Payout: {amount * multiplier:.1f} credits"

        elif tool_name == "check_odds":
            bet_id = request.arguments.get("bet_id")
            if bet_id not in ACTIVE_BETS:
                result = f"❌ Bet '{bet_id}' not found!"
            else:
                bet = ACTIVE_BETS[bet_id]
                result = f"📊 **{bet['title']}** Odds:\n\n"
                for option, odds in bet['odds'].items():
                    result += f"🎯 {option}: {odds}\n"
                if bet_id == "mcp_connection":
                    result += f"\n🎰 **SECRET**: This bet has already been decided!"

        else:
            result = f"🤖 Unknown tool: {tool_name}"

        return MCPResponse(content=[{"type": "text", "text": result}])

    except Exception as e:
        return MCPResponse(
            content=[{"type": "text", "text": f"💥 Betting system error: {str(e)}"}],
            isError=True
        )

async def main():
    port = 8082
    print(f"🎰 Starting Underground Betting System MCP Server on port {port}")
    print(f"🎯 Testing if Agno Agent auto-connects to MCP servers...")
    print(f"💰 Waiting for agent connection to settle the bet...")
    print("=" * 60)

    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning")
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    asyncio.run(main())