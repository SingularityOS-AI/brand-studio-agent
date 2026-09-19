#!/usr/bin/env python3
"""Debug the replacement - try direct byte sequence"""

with open('app.js', 'rb') as f:
    content = f.read()

# Show what we find
idx = content.find(b'alert("You')
if idx > 0:
    # The bytes around it
    print(f'Bytes around alert("You:')
    for i in range(idx, idx+22):
        b = content[i]
        c = chr(b) if 32 <= b < 127 else '.'
        print(f'  offset {i-idx}: 0x{b:02X} = "{c}"')

    # Now build pattern exactly as those bytes
    # alert("You  = 0x61 0x6C 0x65 0x72 0x74 0x28 0x22 0x59 0x6F 0x75
    # \  = 0x5C
    # ' = 0x27
    # ve = 0x76 0x65
    pattern_bytes = bytes([0x61,0x6C,0x65,0x72,0x74,0x28,0x22,0x59,0x6F,0x75]) + bytes([0x5C,0x27]) + bytes([0x76,0x65])
    print(f'\nBuilt pattern: {pattern_bytes}')
    print(f'In file:      {content[idx:idx+14]}')
    print(f'Match:        {pattern_bytes == content[idx:idx+14]}')
