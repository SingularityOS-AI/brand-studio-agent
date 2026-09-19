#!/usr/bin/env python3
"""Check bytes in app.js around You pattern"""

with open('app.js', 'rb') as f:
    content = f.read()

# Search for pattern
idx = content.find(b'alert("You')
if idx > 0:
    snippet = content[idx:idx+60]
    print('Raw bytes:', snippet)
    print('Decoded:', snippet.decode('utf-8'))
else:
    print('Pattern not found')
