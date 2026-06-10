from google.antigravity import LocalAgentConfig
from google.antigravity.types import CustomSystemInstructions

config = LocalAgentConfig(
    system_instructions=CustomSystemInstructions(text="Sei Pippo.")
)
print("SYS PROMPT:")
print(config.system_instructions)
print("\nTOOLS:")
print(config.tools)
