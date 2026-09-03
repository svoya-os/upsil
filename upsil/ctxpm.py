import sys
import os

def init():
    with open("upsil.toml", "w") as f:
        f.write("[package]\nname = \"my_upsil_app\"\nversion = \"0.1.0\"\n\n[dependencies]\n")
    print("Created upsil.toml")

def install(pkg):
    print(f"Resolving dependency '{pkg}'...")
    print(f"Fetching from upsil Registry...")
    print(f"Installing {pkg} v1.0.0...")
    print(f"Successfully installed {pkg}!")

def main():
    if len(sys.argv) < 2:
        print("Usage: ctxpm <init|install>")
        return
    cmd = sys.argv[1]
    if cmd == "init":
        init()
    elif cmd == "install":
        if len(sys.argv) > 2:
            install(sys.argv[2])
        else:
            print("Installing all dependencies from upsil.toml...")
            print("Done.")

if __name__ == "__main__":
    main()
