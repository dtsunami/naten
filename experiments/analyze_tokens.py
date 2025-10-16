"""Analyze token breakdown for system message."""
import sys
import tiktoken

# Set stdout encoding to UTF-8
sys.stdout.reconfigure(encoding='utf-8')

enc = tiktoken.encoding_for_model('gpt-4')

# Read todo.md
with open('todo.md', 'r', encoding='utf-8') as f:
    todo_content = f.read()

print('='*80)
print('TOKEN BREAKDOWN ANALYSIS')
print('='*80)
print()

# System message components
system_prefix = """🤖 You are da_code, an AI coding assistant with access to tools for command execution and file operations.

📋 PROJECT CONTEXT:

  + Name: naten
  + Description:

⚡ SYSTEM MESSAGE:

You are a semi-autonomous coding agent that helps users create coding projects, debug issues and edit files.
Always use available tools and if you encounter an error show the input you supplied to the tool and the output you got.
Don't prompt the user before running tools, tools will ask user for confirmation themselves if it is needed.

📂 Working Directory: F:\\naten
"""

wrapper = "\n📌 TODO.md:\n"

# Instructions (sent separately from system message in Agno)
instructions = [
    "🔧 Use available tools to help with coding tasks - ALWAYS properly **invoke** tools, never give tool inputs back to user",
    "💻 For command execution, use execute_command tool - user confirmation is handled automatically",
    "🚀 Invoke tools as needed WITHOUT reprompting user",
    "✅ Always track and update todos to ensure you don't lose track of planned items",
    "📝 Always use proper tool arguments as specified in tool descriptions",
    "✍️ Always use the replace_text tool to update/edit files and re-read the file back after edit to ensure it worked properly!",
]

print("SYSTEM MESSAGE BREAKDOWN:")
print(f"  System prefix:        {len(enc.encode(system_prefix)):>4} tokens")
print(f"  Todo.md wrapper:      {len(enc.encode(wrapper)):>4} tokens")
print(f"  Todo.md content:      {len(enc.encode(todo_content)):>4} tokens")
total_system = len(enc.encode(system_prefix + wrapper + todo_content))
print(f"  {'─'*40}")
print(f"  TOTAL SYSTEM MESSAGE: {total_system:>4} tokens")
print()

print("INSTRUCTIONS BREAKDOWN (sent separately by Agno):")
instructions_total = 0
for i, instr in enumerate(instructions, 1):
    tokens = len(enc.encode(instr))
    instructions_total += tokens
    print(f"  {i}. {tokens:>3} tokens: {instr[:55]}...")
print(f"  {'─'*40}")
print(f"  TOTAL INSTRUCTIONS:   {instructions_total:>4} tokens")
print()

print("COMBINED:")
print(f"  System message:       {total_system:>4} tokens")
print(f"  Instructions:         {instructions_total:>4} tokens")
print(f"  {'─'*40}")
print(f"  TOTAL:                {total_system + instructions_total:>4} tokens")
print()

# User message
user_msg = "nice, what do you think?"
user_tokens = len(enc.encode(user_msg))
print(f"USER MESSAGE:")
print(f"  '{user_msg}'")
print(f"  Tokens: {user_tokens}")
print()

print("="*80)
print("EXPECTED BREAKDOWN FOR FIRST CALL:")
print("="*80)
print(f"  System + Instructions: {total_system + instructions_total:>4} tokens")
print(f"  User message:          {user_tokens:>4} tokens")
print(f"  Tool schemas:          ~1,217 tokens (from actual interceptor)")
print(f"  {'─'*40}")
print(f"  EXPECTED TOTAL:        ~{total_system + instructions_total + user_tokens + 1217:>4} tokens")
print()
print("ACTUAL FROM INTERCEPTOR: 2,761 tokens")
print(f"Difference: {2761 - (total_system + instructions_total + user_tokens + 1217)} tokens")
print()
