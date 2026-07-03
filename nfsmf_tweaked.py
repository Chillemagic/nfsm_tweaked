#!/usr/bin/env python3
# Adapted from Andrew Song's impl: https://github.com/YaLTeR/niri/issues/426#issuecomment-3367714198
import json
import os
import socket
# Run niri commands via python
import subprocess
import sys
# Create concurrent threads 
import threading

# tracks current position (column/row) of all windows { window_id -> (col, row) }
window_positions = {}
# dict that tracks fullscreen windows and their restore positions { window_id -> { position: (col, row), expanded: Bool, window_width } }
fullscreen_windows = {}

def main():
    # Start threads
    t1 = threading.Thread(target=nfsm_stream)
    t2 = threading.Thread(target=nfsm_socket)
    t1.start()
    t2.start()
    # Wait for threads to finish
    try:
        t1.join()
        t2.join()
    except KeyboardInterrupt:
        sys.exit()

    def run_fullscreen_cmd(window_id, ):
        subprocess.run(
            # niri msg action command --id window_id
            ["niri", "msg", "action", "fullscreen-window", "--id", str(window_id)]
        )

def run_full_width_cmd(window_id):
 
    column = fullscreen_windows[window_id]["position"][0]
    workspace_id = fullscreen_windows[window_id]["workspace_id"]
    stacked = fullscreen_windows[window_id]["stacked"]

    for other_id, data in window_positions.items():

        if other_id == window_id:
            continue

        if (
            data["position"][0] == column 
            and data["workspace_id"] == workspace_id
        ):

            stacked = True
            break

    if stacked: 
        subprocess.run(
            ["niri", "msg", "action", "consume-or-expel-window-right", "--id", str(window_id)]
        )
    

    subprocess.run(
        ["niri", "msg", "action", "set-window-width", "100%"]
    )
    
def restore_window_cmd(window_id):

    # window = fullscreen_windows[window_id]
    # width = window["width"]
    # stacked = window["stacked"]

    subprocess.run(
        ["niri", "msg", "action", "set-window-width", str(width)]
    )
    

def handle_fullscreen_request():

    props = subprocess.run(
        ["niri", "msg", "--json", "focused-window"],
        capture_output=True,
        text=True,
    )
    # Fetches window id and sends to run_fullscreen_cmd method
    window_id = json.loads(props.stdout)["id"]

    # the window is exiting fullscreen
    # Checks if window exists in fullscreen_windows list defined at the top
    if window_id in fullscreen_windows:
        fullscreen_windows[window_id]["expanded"] = True
        # trigger a niri window layouts changed event
        restore_window_cmd(window_id)
        return

    # the window is entering fullscreen

    if window_id in window_positions:

        window_width = json.loads(props.stdout)["layout"]["window_size"][0]

        
        col, row = window_positions[window_id]["position"]
        workspace_id = window_positions[window_id]["workspace_id"]
        fullscreen_windows[window_id] = {
            "position": (col, row),
            "restore_row": (row),
            "width": window_width,
            "expanded": False,
            "stacked": False,
            "workspace_id": workspace_id
        }
        run_full_width_cmd(window_id)

def nfsm_socket():
    server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    socket_path = os.getenv("NFSM_SOCKET", "/run/user/1000/nfsm.sock")

    # remove the socket file if it already exists
    try:
        os.unlink(socket_path)
    except OSError:
        if os.path.exists(socket_path):
            raise

    try:
        server_socket.bind(socket_path)
    except socket.error as message:
        print(f"Failed to bind socket: {message}")
        sys.exit()

    # allow five connections to have some buffer for concurrent clients, but a single connection should be enough
    server_socket.listen(5)
    print(f"Socket server listening on: {socket_path}")

    while True:
        # client connection
        client_socket = server_socket.accept()[0]

        try:
            data = client_socket.recv(1024)
            if data:
                cmd = data.decode('utf-8').strip()
                if cmd == "FullscreenRequest":
                    handle_fullscreen_request()
        except socket.error as e:
            print(f"Socket error: {e}")
        finally:
            client_socket.close()

def handle_window_closed(window_id):
    if window_id in window_positions:
        col, row = window_positions[window_id]["position"]
        del window_positions[window_id]
    if window_id in fullscreen_windows:
        del fullscreen_windows[window_id]

def niri_cmd(command):
    subprocess.run(["niri", "msg", "action", command])

def nfsm_stream():
    proc = subprocess.Popen(
        ["stdbuf", "-oL", "niri", "msg", "--json", "event-stream"],
        stdout=subprocess.PIPE,
        text=True,
    )

    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue

        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            print("Failed to parse JSON")
            continue

        # initial window positions
        if "WindowsChanged" in event and not window_positions:
            windows = event["WindowsChanged"]["windows"]

            for window in windows:
                window_id = window["id"]
                workspace_id = window["workspace_id"]
                layout = window.get("layout", {})
                pos = layout.get("pos_in_scrolling_layout")
                if pos is None:
                    continue  # skip floating windows
                window_positions[window_id] = {
                    "workspace_id": workspace_id,
                    "position": tuple(pos)
                }

        # it occurs when a window is closed; only the id is available
        if "WindowClosed" in event:
            window_id = event["WindowClosed"]["id"]
            handle_window_closed(window_id)

        # it occurs when a window is opened or moved to a new workspace
        if "WindowOpenedOrChanged" in event:
            window = event["WindowOpenedOrChanged"]["window"]
            window_id = window["id"]
            # Add workspace id to check if window is stacked
            workspace_id = window["workspace_id"]
            layout = window.get("layout", {})
            pos = layout.get("pos_in_scrolling_layout")
            if pos is not None:
                window_positions[window_id] = {
                    "workspace_id": workspace_id,
                    "position": tuple(pos)
                }

        if "WindowLayoutsChanged" not in event:
            continue

        changes = event["WindowLayoutsChanged"]["changes"]

        for change in changes:
            window_id = change[0]
            window_data = change[1]

            # 3,{"pos_in_scrolling_layout":[2,1],"tile_size":[672.0,868.0],
            # "window_size":[672,868],
            # "tile_pos_in_workspace_view":null,"window_offset_in_tile":[0.0,0.0]}

            try:
                col, row = window_data["pos_in_scrolling_layout"]
            except TypeError:
                # ignore floating windows that are made fullscreen and then go back to floating
                continue

            # move the window to the last recorded position when necessary
            if window_id in fullscreen_windows and fullscreen_windows[window_id]["expanded"]:
                dest_col, dest_row = fullscreen_windows[window_id]["position"]
                # move window to the right column if necessary
                if dest_col < col:
                    niri_cmd("consume-or-expel-window-left")
                    continue
                # the window is already in the right column, zwe now need to move it to the correct row
                if dest_row != row:
                    for _ in range(row - dest_row):
                        niri_cmd("move-window-up")
                # window is already back at its last recorded position
                del fullscreen_windows[window_id]

            window_positions[window_id]["position"] = (col, row)

            sys.stdout.flush()

if __name__ == "__main__":
    main()
