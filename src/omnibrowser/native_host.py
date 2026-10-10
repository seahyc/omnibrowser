#!/usr/bin/env python3
"""
OmniBrowser Native Messaging Host

Standalone script - no external dependencies required.
Communicates with Chrome extension via Native Messaging protocol.
Also listens on a Unix socket for commands from CLI/MCP server.
"""

import json
import struct
import sys
import os
import socket
import threading
import select
import uuid
from pathlib import Path

# Socket path for CLI communication
SOCKET_PATH = Path("/tmp/omnibrowser.sock")

# Pending requests waiting for extension response
pending_requests = {}  # id -> {'event': threading.Event, 'response': None}


def read_message():
    """Read a message from stdin (Chrome extension)."""
    # Read message length (4 bytes, native byte order)
    raw_length = sys.stdin.buffer.read(4)
    if not raw_length or len(raw_length) < 4:
        return None

    message_length = struct.unpack("@I", raw_length)[0]

    # Read message content
    message_data = sys.stdin.buffer.read(message_length).decode("utf-8")
    return json.loads(message_data)


def send_message(message):
    """Send a message to the Chrome extension via stdout."""
    encoded = json.dumps(message).encode("utf-8")

    # Write message length (4 bytes, native byte order)
    sys.stdout.buffer.write(struct.pack("@I", len(encoded)))

    # Write message content
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


def handle_extension_message(message):
    """Process a message from the extension."""
    msg_type = message.get("type")
    msg_id = message.get("id")

    # Handshake from extension
    if msg_type == "handshake":
        return {
            "type": "handshake_ack",
            "version": "0.1.0",
            "extensionId": message.get("extensionId"),
            "status": "connected",
        }

    # Response to a command we sent
    if msg_id and msg_id in pending_requests:
        pending_requests[msg_id]["response"] = message
        pending_requests[msg_id]["event"].set()
        return None  # No response needed

    # Unknown message, echo back
    return {
        "id": msg_id,
        "success": True,
        "result": {"echo": message},
    }


def send_to_extension(action, params=None, timeout=30):
    """Send a command to the extension and wait for response."""
    request_id = str(uuid.uuid4())

    # Set up pending request
    event = threading.Event()
    pending_requests[request_id] = {"event": event, "response": None}

    # Send command to extension
    command = {
        "id": request_id,
        "action": action,
        "params": params or {},
    }
    send_message(command)

    # Wait for response
    if event.wait(timeout=timeout):
        response = pending_requests[request_id]["response"]
        del pending_requests[request_id]
        return response
    else:
        del pending_requests[request_id]
        return {"id": request_id, "success": False, "error": "Timeout waiting for extension response"}


def handle_socket_client(client_socket, addr):
    """Handle a connection from CLI/MCP server."""
    sys.stderr.write(f"[OmniBrowser] Socket client connected\n")
    sys.stderr.flush()

    try:
        while True:
            # Read length-prefixed JSON message
            length_data = client_socket.recv(4)
            if not length_data:
                break

            msg_length = struct.unpack("!I", length_data)[0]
            msg_data = client_socket.recv(msg_length).decode("utf-8")
            message = json.loads(msg_data)

            sys.stderr.write(f"[OmniBrowser] Socket received: {message.get('action')}\n")
            sys.stderr.flush()

            # Forward to extension and get response
            action = message.get("action")
            params = message.get("params", {})

            response = send_to_extension(action, params)

            # Send response back to CLI
            response_data = json.dumps(response).encode("utf-8")
            client_socket.send(struct.pack("!I", len(response_data)))
            client_socket.send(response_data)

    except Exception as e:
        sys.stderr.write(f"[OmniBrowser] Socket client error: {e}\n")
        sys.stderr.flush()
    finally:
        client_socket.close()
        sys.stderr.write(f"[OmniBrowser] Socket client disconnected\n")
        sys.stderr.flush()


def socket_server_thread():
    """Run the socket server in a background thread."""
    # Remove existing socket file
    if SOCKET_PATH.exists():
        SOCKET_PATH.unlink()

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(str(SOCKET_PATH))
    server.listen(5)

    sys.stderr.write(f"[OmniBrowser] Socket server listening on {SOCKET_PATH}\n")
    sys.stderr.flush()

    # Make socket world-accessible
    os.chmod(SOCKET_PATH, 0o777)

    while True:
        try:
            client, addr = server.accept()
            # Handle each client in a new thread
            thread = threading.Thread(target=handle_socket_client, args=(client, addr))
            thread.daemon = True
            thread.start()
        except Exception as e:
            sys.stderr.write(f"[OmniBrowser] Socket server error: {e}\n")
            sys.stderr.flush()
            break


def main():
    """Main loop - read messages from extension and respond."""
    sys.stderr.write("[OmniBrowser Native Host] Started\n")
    sys.stderr.flush()

    # Start socket server in background thread
    socket_thread = threading.Thread(target=socket_server_thread)
    socket_thread.daemon = True
    socket_thread.start()

    while True:
        try:
            message = read_message()
            if message is None:
                # stdin closed, exit
                break

            response = handle_extension_message(message)
            if response:
                send_message(response)

        except Exception as e:
            # Send error response
            send_message({
                "type": "error",
                "error": str(e),
            })
            sys.stderr.write(f"[OmniBrowser Native Host] Error: {e}\n")
            sys.stderr.flush()


if __name__ == "__main__":
    main()
