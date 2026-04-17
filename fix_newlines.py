import re

for filename in ["app.py", "ai_analyzer.py"]:
    with open(filename, "r", encoding="utf-8") as f:
        content = f.read()
    
    # Replace the pattern where } is followed by a newline and then a quote and a newline
    # This specifically target f-strings like yield f"data: ...}\n\n" that got mangled.
    # Looking at the read_file output: yield f"...}" \n \n "
    # Wait, let's see exactly what's there.
    # yield f"data: {json.dumps({'status': ...})} \n \n "
    
    # Actually, let's just use a more general regex for any f-string that was split
    fixed_content = re.sub(r'yield f"(data: .*?)\n\n"', r'yield f"\1\\n\\n"', content)
    
    # Also fix other instances like summarize_history
    fixed_content = re.sub(r'text_to_summarize \+= f"(.*?)\n"', r'text_to_summarize += f"\1\\n"', fixed_content)
    fixed_content = re.sub(r'prompt = f"(.*?)\n\n(.*?)"', r'prompt = f"\1\\n\\n\2"', fixed_content)

    with open(filename, "w", encoding="utf-8") as f:
        f.write(fixed_content)
