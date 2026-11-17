"""Bench test for the SmartGuard ESP32 (no camera, no app needed).

    python tools/hw_test.py              finds the ESP32 by itself
    python tools/hw_test.py --port COM5  uses that port

Close the SmartGuard app and the Arduino Serial Monitor first: only one program can use the port.
"""
import argparse
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import serial  # noqa: E402

from hardware.serial_handler import find_candidate_ports  # noqa: E402

MENU = {
    "1": ("TEST", "self-test: green, red, beep, gate open, gate close"),
    "2": ("PASS", "green LED + open gate (closes after 5 s)"),
    "3": ("WARN", "red LED + warning beeps (3 s)"),
    "4": ("GATE_OPEN", "open the gate"),
    "5": ("GATE_CLOSE", "close the gate"),
    "6": ("BUZZ", "one beep"),
    "7": ("STATUS", "print the board's state"),
    "8": ("SAFE", "everything off, gate closed"),
}


def open_board(port):
    conn = serial.Serial()
    conn.port, conn.baudrate, conn.timeout = port, 115200, 0.2
    conn.dtr = conn.rts = False                    # do not reset the board on open
    conn.open()
    deadline = time.time() + 3
    buf = b""
    while time.time() < deadline:
        conn.write(b"PING\n")
        time.sleep(0.3)
        buf += conn.read(conn.in_waiting or 1)
        if b"PONG" in buf or b"READY" in buf:
            return conn
    conn.close()
    return None


def find_board(port):
    ports = [port] if port else find_candidate_ports()
    if not ports:
        sys.exit("No USB serial port found. Check the USB cable (charge-only cables do not work) "
                 "and the driver (Device Manager > Ports).")
    for p in ports:
        try:
            conn = open_board(p)
        except serial.SerialException as exc:
            print(f"  {p}: {exc}")
            continue
        if conn:
            return conn
        print(f"  {p}: opened, but no SmartGuard firmware answered")
    sys.exit("ESP32 not found. Is the firmware flashed? Is the app or Serial Monitor holding the port?")


def reader(conn, stop):
    while not stop.is_set():
        try:
            line = conn.readline().decode("ascii", "ignore").strip()
        except serial.SerialException:
            print("\n!! Board disconnected.")
            stop.set()
            return
        if line and line != "PONG":
            print(f"   <- {line}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="")
    a = ap.parse_args()
    conn = find_board(a.port)
    print(f"Connected on {conn.port}.")
    conn.write(b"STATUS\n")
    stop = threading.Event()
    threading.Thread(target=reader, args=(conn, stop), daemon=True).start()
    try:
        while not stop.is_set():
            time.sleep(0.3)
            print("\n" + "\n".join(f"  {k}  {cmd:<10} {txt}" for k, (cmd, txt) in MENU.items()) + "\n  q  quit")
            choice = input("> ").strip().lower()
            if choice == "q":
                break
            if choice in MENU:
                conn.write((MENU[choice][0] + "\n").encode())
            elif choice:
                conn.write((choice.upper() + "\n").encode())    # any raw command, e.g. LED_GREEN
    finally:
        stop.set()
        try:
            conn.write(b"SAFE\n")
            conn.close()
        except serial.SerialException:
            pass


if __name__ == "__main__":
    main()
