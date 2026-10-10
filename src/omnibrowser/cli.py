#!/usr/bin/env python3
"""
OmniBrowser CLI

Commands:
    omnibrowser                    Start interactive mode
    omnibrowser install-host       Install native messaging host
    omnibrowser profiles           List Chrome profiles
    omnibrowser instances          List running Chrome instances with debug ports
    omnibrowser tabs               List tabs via Chrome extension
    omnibrowser screenshot         Take screenshot via Chrome extension
"""

import argparse
import asyncio
import json
import socket
import struct
import sys
from pathlib import Path

SOCKET_PATH = Path("/tmp/omnibrowser.sock")


def send_to_extension(action, params=None, timeout=30):
    """Send a command to the extension via the native host socket."""
    if not SOCKET_PATH.exists():
        print("Error: OmniBrowser native host is not running.")
        print("Make sure the Chrome extension is loaded and connected.")
        sys.exit(1)

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)

    try:
        sock.connect(str(SOCKET_PATH))

        # Send command
        message = {"action": action, "params": params or {}}
        data = json.dumps(message).encode("utf-8")
        sock.send(struct.pack("!I", len(data)))
        sock.send(data)

        # Read response
        length_data = sock.recv(4)
        if not length_data:
            return None
        msg_length = struct.unpack("!I", length_data)[0]
        response_data = sock.recv(msg_length).decode("utf-8")
        return json.loads(response_data)

    except socket.timeout:
        print("Error: Timeout waiting for extension response")
        sys.exit(1)
    except ConnectionRefusedError:
        print("Error: Could not connect to native host socket")
        sys.exit(1)
    finally:
        sock.close()


def cmd_install_host(args):
    """Install the native messaging host for the Chrome extension."""
    from omnibrowser.native_host import install_native_host

    if not args.extension_id:
        print("Error: --extension-id is required")
        print("\nTo find your extension ID:")
        print("1. Load the extension in Chrome (chrome://extensions)")
        print("2. Enable 'Developer mode'")
        print("3. Copy the ID shown under the extension")
        print("\nThen run:")
        print("    omnibrowser install-host --extension-id <YOUR_ID>")
        sys.exit(1)

    install_native_host(args.extension_id)


def cmd_profiles(args):
    """List Chrome profiles."""
    from omnibrowser.adapters.chrome import ChromeProfileManager

    manager = ChromeProfileManager()
    profiles = manager.discover_profiles()

    if not profiles:
        print("No Chrome profiles found")
        return

    print(f"Found {len(profiles)} Chrome profiles:\n")
    for p in profiles:
        print(f"  {p.name}")
        print(f"    ID: {p.id}")
        print(f"    Path: {p.path}")
        print()


def cmd_instances(args):
    """List running Chrome instances with debug ports."""
    from omnibrowser.adapters.chrome import ChromeInstanceManager

    async def discover():
        manager = ChromeInstanceManager()
        instances = await manager.discover_instances()

        if not instances:
            print("No Chrome instances found with debug ports.")
            print("\nTo enable, restart Chrome with:")
            print("    /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome --remote-debugging-port=9222")
            print("\nOr install the OmniBrowser extension for automatic support.")
            return

        print(f"Found {len(instances)} Chrome instance(s):\n")
        for inst in instances:
            print(f"  Port {inst.port}: {inst.browser_version}")
            if inst.profile_name:
                print(f"    Profile: {inst.profile_name}")
            print(f"    Pages: {len(inst.pages)}")
            for page in inst.pages[:3]:
                title = page.get("title", "Untitled")[:40]
                print(f"      - {title}")
            if len(inst.pages) > 3:
                print(f"      ... and {len(inst.pages) - 3} more")
            print()

    asyncio.run(discover())


def cmd_connect(args):
    """Connect to a Chrome instance and run interactive commands."""
    from omnibrowser.adapters.chrome import ChromeAdapter

    async def interactive():
        adapter = ChromeAdapter()

        # Try to connect
        try:
            if args.port:
                client = await adapter.connect(port=args.port)
            else:
                client = await adapter.connect()
        except RuntimeError as e:
            print(f"Error: {e}")
            print("\nRun 'omnibrowser instances' to see available Chrome instances.")
            return

        print(f"Connected to Chrome on port {client.port}")
        version = await client.get_version()
        print(f"Browser: {version.get('Browser', 'Unknown')}")

        pages = await client.list_pages()
        print(f"\nFound {len(pages)} pages:")
        for i, page in enumerate(pages):
            print(f"  [{i}] {page.get('title', 'Untitled')[:50]}")

        print("\nEntering interactive mode. Commands:")
        print("  pages              - List pages")
        print("  select <n>         - Select page by index")
        print("  goto <url>         - Navigate to URL")
        print("  screenshot         - Take screenshot")
        print("  quit               - Exit")

        current_page = None

        while True:
            try:
                cmd = input("\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                break

            if not cmd:
                continue

            parts = cmd.split(maxsplit=1)
            action = parts[0].lower()
            arg = parts[1] if len(parts) > 1 else ""

            try:
                if action == "quit" or action == "exit":
                    break

                elif action == "pages":
                    pages = await client.list_pages()
                    for i, page in enumerate(pages):
                        marker = "*" if page.get("id") == (current_page or {}).get("id") else " "
                        print(f"  {marker}[{i}] {page.get('title', 'Untitled')[:50]}")

                elif action == "select":
                    idx = int(arg)
                    pages = await client.list_pages()
                    if 0 <= idx < len(pages):
                        current_page = pages[idx]
                        await client.connect_to_page(current_page)
                        print(f"Selected: {current_page.get('title', 'Untitled')}")
                    else:
                        print(f"Invalid index. Use 0-{len(pages)-1}")

                elif action == "goto":
                    if not current_page:
                        print("Select a page first with 'select <n>'")
                        continue
                    await client.navigate(arg)
                    print(f"Navigated to {arg}")

                elif action == "screenshot":
                    if not current_page:
                        print("Select a page first with 'select <n>'")
                        continue
                    data = await client.screenshot()
                    path = Path(f"screenshot_{current_page.get('id', 'unknown')[:8]}.png")
                    with open(path, "wb") as f:
                        f.write(data)
                    print(f"Saved: {path}")

                else:
                    print(f"Unknown command: {action}")

            except Exception as e:
                print(f"Error: {e}")

        await adapter.close_all()
        print("Disconnected.")

    asyncio.run(interactive())


# ============================================================================
# Extension Commands (via Native Messaging)
# ============================================================================

def cmd_tabs(args):
    """List tabs via the Chrome extension."""
    response = send_to_extension("getTabs")

    if not response:
        print("No response from extension")
        return

    if not response.get("success"):
        print(f"Error: {response.get('error')}")
        return

    tabs = response.get("result", [])
    if not tabs:
        print("No tabs found")
        return

    print(f"Found {len(tabs)} tabs:\n")
    for tab in tabs:
        active = "*" if tab.get("active") else " "
        title = tab.get("title", "Untitled")[:50]
        url = tab.get("url", "")[:60]
        print(f"  {active}[{tab['id']}] {title}")
        print(f"         {url}")


def cmd_screenshot_ext(args):
    """Take a screenshot via the Chrome extension."""
    import base64

    tab_id = args.tab_id

    # If no tab ID, get active tab
    if not tab_id:
        response = send_to_extension("getActiveTab")
        if response.get("success") and response.get("result"):
            tab_id = response["result"]["id"]
        else:
            print("Error: Could not get active tab. Specify --tab-id")
            return

    response = send_to_extension("screenshot", {"tabId": tab_id})

    if not response.get("success"):
        print(f"Error: {response.get('error')}")
        return

    result = response.get("result", {})
    screenshot_data = result.get("screenshot")

    if not screenshot_data:
        print("No screenshot data received")
        return

    # Save to file
    output = args.output or f"screenshot_{tab_id}.png"
    with open(output, "wb") as f:
        f.write(base64.b64decode(screenshot_data))

    print(f"Screenshot saved to: {output}")


def cmd_navigate(args):
    """Navigate a tab to a URL."""
    tab_id = args.tab_id
    url = args.url

    # If no tab ID, get active tab
    if not tab_id:
        response = send_to_extension("getActiveTab")
        if response.get("success") and response.get("result"):
            tab_id = response["result"]["id"]
        else:
            print("Error: Could not get active tab. Specify --tab-id")
            return

    response = send_to_extension("navigate", {"tabId": tab_id, "url": url})

    if not response.get("success"):
        print(f"Error: {response.get('error')}")
        return

    print(f"Navigated tab {tab_id} to {url}")


def cmd_ping(args):
    """Ping the extension to test connectivity."""
    response = send_to_extension("ping")

    if not response:
        print("No response from extension")
        return

    if response.get("success"):
        result = response.get("result", {})
        print(f"Pong! Extension responded.")
        if "timestamp" in result:
            print(f"  Timestamp: {result['timestamp']}")
    else:
        print(f"Error: {response.get('error')}")


def main():
    parser = argparse.ArgumentParser(
        description="OmniBrowser - Multi-profile browser automation for AI agents"
    )
    subparsers = parser.add_subparsers(dest="command")

    # install-host command
    install_parser = subparsers.add_parser(
        "install-host",
        help="Install native messaging host for Chrome extension"
    )
    install_parser.add_argument(
        "--extension-id",
        help="Chrome extension ID"
    )
    install_parser.set_defaults(func=cmd_install_host)

    # profiles command
    profiles_parser = subparsers.add_parser(
        "profiles",
        help="List Chrome profiles"
    )
    profiles_parser.set_defaults(func=cmd_profiles)

    # instances command
    instances_parser = subparsers.add_parser(
        "instances",
        help="List running Chrome instances with debug ports"
    )
    instances_parser.set_defaults(func=cmd_instances)

    # connect command
    connect_parser = subparsers.add_parser(
        "connect",
        help="Connect to Chrome and run interactive commands"
    )
    connect_parser.add_argument(
        "--port", "-p",
        type=int,
        help="Chrome debug port to connect to"
    )
    connect_parser.set_defaults(func=cmd_connect)

    # Extension commands (via Native Messaging)

    # tabs command
    tabs_parser = subparsers.add_parser(
        "tabs",
        help="List tabs via Chrome extension"
    )
    tabs_parser.set_defaults(func=cmd_tabs)

    # screenshot command
    screenshot_parser = subparsers.add_parser(
        "screenshot",
        help="Take screenshot via Chrome extension"
    )
    screenshot_parser.add_argument(
        "--tab-id", "-t",
        type=int,
        help="Tab ID to screenshot (default: active tab)"
    )
    screenshot_parser.add_argument(
        "--output", "-o",
        help="Output file path"
    )
    screenshot_parser.set_defaults(func=cmd_screenshot_ext)

    # navigate command
    navigate_parser = subparsers.add_parser(
        "navigate",
        help="Navigate a tab to a URL"
    )
    navigate_parser.add_argument(
        "url",
        help="URL to navigate to"
    )
    navigate_parser.add_argument(
        "--tab-id", "-t",
        type=int,
        help="Tab ID to navigate (default: active tab)"
    )
    navigate_parser.set_defaults(func=cmd_navigate)

    # ping command
    ping_parser = subparsers.add_parser(
        "ping",
        help="Test connection to Chrome extension"
    )
    ping_parser.set_defaults(func=cmd_ping)

    args = parser.parse_args()

    if args.command is None:
        # Default: show help
        parser.print_help()
    else:
        args.func(args)


if __name__ == "__main__":
    main()
