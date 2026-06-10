import asyncio
from google.antigravity import Agent, LocalAgentConfig, CapabilitiesConfig

async def main():
    config = LocalAgentConfig(
        system_instructions="Sei Pippo.",
        api_key="dummy",
        capabilities=CapabilitiesConfig(enabled_tools=["finish"])
    )
    agent = Agent(config)
    print("AGENT TOOLS:")
    print([t.name for t in agent._tools])

asyncio.run(main())
