# -*- coding: utf-8 -*-

with open("app.js", "r", encoding="utf-8") as f:
    lines = f.readlines()

# Find and fix line 88 (index 87)
for i, line in enumerate(lines, 1):
    if "Turn detection baseline" in line and i == 88:
        print(f"Found line {i}: {repr(line[:80])}")
        # Replace the problematic line - remove the backtick from the quoted string
        if chr(96) in line:
            new_line = line.replace(chr(96), '')  # Simply remove the backtick
            print(f"Fixed line -> {repr(new_line[:80])}")
            lines[i-1] = new_line
        break

with open("app.js", "w", encoding="utf-8") as f:
    f.writelines(lines)

print("Done!")
