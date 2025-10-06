import asyncio

from agno.agent import Agent
from agno.models.azure import AzureOpenAI
from agno.tools.mcp import MCPTools, StreamableHTTPClientParams

server_params = StreamableHTTPClientParams(
    url="https://docs.agno.com/mcp",
    #url="https://gofastmcp.com/mcp",
    #headers=...,
    timeout=30,
    terminate_on_close=True,
)

async def run_agent(message: str) -> None:
    async with MCPTools(
        server_params=server_params,
        transport="streamable-http"
    ) as agno_mcp_server:
        agent = Agent(
            model=AzureOpenAI(),
            tools=[agno_mcp_server],
            markdown=True,
        )
        await agent.aprint_response(input=message, stream=True)


async def run_agent2(message: str) -> None:
    mcp_tool = MCPTools(
        server_params=server_params,
        transport="streamable-http"
    )
    await mcp_tool.connect()

    agent = Agent(
        model=AzureOpenAI(),
        tools=[mcp_tool],
        markdown=True,
    )
    await agent.aprint_response(input=message, stream=True)
    
    await mcp_tool.close()


if __name__ == "__main__":
    asyncio.run(run_agent2("What is Agno?"))