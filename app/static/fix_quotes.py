#!/usr/bin/env python3
"""Fix malformed backslash-apostrophe sequences in app.js"""

# Read as binary to handle escapes properly
with open('app.js', 'rb') as f:
    content = f.read()

# Replace alert("You\'ve (backslash + apostrophe) with alert("You've (just apostrophe)
content = content.replace(b'alert("You\\\'ve', b"alert(\"You've")

with open('app.js', 'wb') as f:
    f.write(content)

print("Fixed: replaced alert(\"You\\'ve with alert(\"You've")
