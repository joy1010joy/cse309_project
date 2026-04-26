import re
import os

file_path = "/Users/rasheduzzamanrochi/Projects/Web Project/cse309_project_joy/unicafe-project/static/index.html"
if not os.path.exists(file_path):
    print(f"File not found: {file_path}")
    exit(1)

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Find all script blocks
matches = list(re.finditer(r'<script>(.*?)</script>', content, re.DOTALL))
if not matches:
    print("No <script>...</script> blocks found.")
    exit(0)

# Get the last script block
last_match = matches[-1]
script_content = last_match.group(1)

# 1) Print character length
print(f"Character length: {len(script_content)}")

# 2) Count occurrences of '</script>' case-insensitive inside the extracted script text
search_term = '</script>'
# Note: In HTML, a script content shouldn't normally contain </script> unless escaped or as a string.
# We search case-insensitively.
occurrences = [m.start() for m in re.finditer(re.escape(search_term), script_content, re.IGNORECASE)]
count = len(occurrences)
print(f"Occurrences of '{search_term}': {count}")

# 3) If count > 0, print surrounding 80 chars (40 before, 40 after) around each occurrence
if count > 0:
    for idx, pos in enumerate(occurrences):
        start = max(0, pos - 40)
        end = min(len(script_content), pos + len(search_term) + 40)
        context = script_content[start:end]
        print(f"\nOccurrence {idx + 1} at index {pos}:")
        print("-" * 10)
        print(context)
        print("-" * 10)
