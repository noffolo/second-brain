import asyncio
from dotenv import load_dotenv
load_dotenv()
from engine.query_agent import get_query_agent_config
from google.antigravity import Agent

async def main():
    config = await get_query_agent_config()
    print("Invocando Agent...")
    async with Agent(config) as agent:
        resp = await agent.chat("dimmi su cosa sta lavorando FF3300")
        try:
            print("Raw Agent output:", agent.history[-1])
        except Exception as e:
            pass
        print("Text estratto:")
        print(repr(await resp.text()))

asyncio.run(main())
