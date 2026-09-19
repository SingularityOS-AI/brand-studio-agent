# -*- coding: utf-8 -*-

with open("app.js", "r", encoding="utf-8") as f:
    lines = f.readlines()

stack = []
for i, line in enumerate(lines, 1):
    for j, char in enumerate(line):
        if char in "({[":
            stack.append((i+1, j+1, char))
        elif char in ")}]":
            if not stack:
                print(f"Unmatched closing '{char}' at line {i+1}, col {j+1}")
                continue
            opener_i, opener_j, opener = stack.pop()
            opening = {"(": ")", "{": "}", "[": "]"}
            if opening[opener] != char:
                print(f"Mismatched: '{opener}' at ({opener_i},{opener_j}) closed by '{char}' at ({i+1},{j+1})")

if stack:
    print("Unclosed parentheses/braces:")
    for i, j, char in stack:
        print(f"  Line {i+1}, col {j+1}: '{char}' not closed")
else:
    print("All parentheses/braces balanced")

# Check lines around 2000-2040 specifically
print("\n=== Lines 2000-2040 ===")
for i, line in enumerate(lines[1999:2040], start=2000):
    print(f"{i}: {repr(line[:100])}")
