import os

# EasyStreet - Core Mod Scanner
# Version 0.1 - Written June 2026

server_path = "C:\\Program Files (x86)\\Steam\\steamapps\\common\\DayZServer"

# Find all mods
mods = [f for f in os.listdir(server_path) if f.startswith("@")]

# Build mod string
mod_string = ";".join(mods)

# Display result
print("Server: Easy Street")
print("Mods found: " + str(len(mods)))
print("Mod string: -mod=" + mod_string)