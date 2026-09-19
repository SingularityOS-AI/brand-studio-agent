# -*- coding: utf-8 -*-

with open("app.js", "rb") as f:
    lines = f.readlines()

line2022 = lines[2021]
line2023 = lines[2022]

print("Line 2022 (raw bytes):")
print(line2022)
print()

print("Line 2023 (raw bytes):")
print(line2023)

if len(line2022) > 90:
    print(f"Line 2022 bytes 85-95: {line2022[85:95].hex()}")
    print(f"Characters: {repr(line2022[85:95].decode('utf-8', errors='replace'))}")

print("")

if len(line2023) > 90:
    print(f"Line 2023 bytes 84-94: {line2023[84:94].hex()}")
    print(f"Characters: {repr(line2023[84:94].decode('utf-8', errors='replace'))}")
