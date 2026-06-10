import asyncio
from google.antigravity import Agent, LocalAgentConfig
from google.antigravity.types import CustomSystemInstructions

async def main():
    config = LocalAgentConfig(
        system_instructions=CustomSystemInstructions(text="Sei Pippo."),
        api_key="dummy"
    )
    agent = Agent(config)
    print("AGENT SYS PROMPT:\n" + agent.system_instruction)
    print("AGENT TOOLS:")
    print([t.name for t in agent.tools])

asyncio.run(main())
