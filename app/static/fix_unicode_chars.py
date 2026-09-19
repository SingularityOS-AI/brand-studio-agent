# -*- coding: utf-8 -*-

with open("app.js", "r", encoding="utf-8") as f:
    content = f.read()

# Replace checkmark (U+2713) and cross mark (U+2717) with HTML entities or escaped versions
# Option 1: Use HTML entities &#10003; and &#10007;
content = content.replace("✓", "&#10003;")
content = content.replace("✗", "&#10007;")

with open("app.js", "w", encoding="utf-8") as f:
    f.write(content)

print("Replaced ✓ and ✗ with HTML entities")
