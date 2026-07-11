#!/usr/bin/env python3
"""
Pico 2W Audio Streamer — Sender
=================================
Reads a WAV file and streams it over UDP to the Pico.
Also sends metadata (song name, device name).

Usage:
  python stream_sender.py <wav_file> [pico_ip] [song_name]

Requirements:
  pip install sounddevice  (optional, for mic input)
  or use a WAV file

Packet format:
  [4-byte type][4-byte seq][data]
  type 0 = audio data (16-bit PCM, 44100 Hz, mono)
  type 1 = metadata ("song_name||device_name")
"""

import socket
import struct
import sys
import time
import os

PICO_PORT = 8888
BUF_SAMPLES = 2048  # must match receiver
SAMPLE_RATE = 44100

def load_wav(filepath):
    """Load a WAV file and return 16-bit mono samples at 44100 Hz."""
    import wave
    import array
    with wave.open(filepath, 'rb') as wf:
        frames = wf.readframes(wf.getnframes())
        params = wf.getparams()
        nchannels = params.nchannels
        sampwidth = params.sampwidth
        framerate = params.framerate
        nframes = params.nframes

    # Convert to 16-bit mono array
    raw = array.array('h')
    raw.frombytes(frames)

    if nchannels == 2:
        # Downmix stereo to mono
        mono = array.array('h', [0]) * (len(raw) // 2)
        for i in range(len(mono)):
            mono[i] = (raw[i * 2] + raw[i * 2 + 1]) // 2
        raw = mono

    if sampwidth != 2:
        print(f"Warning: {sampwidth}-byte samples, expected 2. May sound wrong.")

    # Resample if needed
    if framerate != SAMPLE_RATE:
        print(f"Warning: {framerate} Hz file, receiver expects {SAMPLE_RATE} Hz.")
        print("Consider converting to 44100 Hz first.")

    return raw

def send_metadata(sock, addr, song_name="Unknown", device_name="Python Sender"):
    """Send metadata packet."""
    meta = f"{song_name}||{device_name}"
    pkt = struct.pack(">II", 1, 0) + meta.encode('utf-8')
    sock.sendto(pkt, addr)
    print(f"Meta: {song_name}")

def send_audio(sock, addr, samples, seq):
    """Send a chunk of audio samples."""
    data = samples.tobytes()
    pkt = struct.pack(">II", 0, seq) + data
    sock.sendto(pkt, addr)

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    wav_path = sys.argv[1]
    pico_ip = sys.argv[2] if len(sys.argv) > 2 else input("Enter Pico IP: ")
    song_name = sys.argv[3] if len(sys.argv) > 3 else os.path.basename(wav_path)

    if not pico_ip:
        print("Need Pico IP address")
        sys.exit(1)

    addr = (pico_ip, PICO_PORT)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    print(f"Loading: {wav_path}")
    samples = load_wav(wav_path)
    total = len(samples)
    chunk_size = BUF_SAMPLES
    print(f"Loaded {total} samples ({total / SAMPLE_RATE:.1f}s)")
    print(f"Sending to {pico_ip}:{PICO_PORT}")

    # Send metadata first
    send_metadata(sock, addr, song_name, "Python Sender")
    time.sleep(0.1)

    # Stream audio
    seq = 0
    for i in range(0, total, chunk_size):
        chunk = samples[i:i + chunk_size]
        # Pad last chunk
        if len(chunk) < chunk_size:
            padded = samples[-1:] * chunk_size if len(samples) > 0 else array.array('h', [0]) * chunk_size
            chunk = array.array('h', chunk)
            while len(chunk) < chunk_size:
                chunk.append(samples[-1] if len(samples) > 0 else 0)

        send_audio(sock, addr, chunk, seq)
        seq += 1
        time.sleep(chunk_size / SAMPLE_RATE * 0.9)  # slightly faster than real-time
        sys.stdout.write(f"\rSent: {i * 100 // total}%  ({i // SAMPLE_RATE}s / {total // SAMPLE_RATE}s)")
        sys.stdout.flush()

    print(f"\nDone. Sent {seq} packets.")

if __name__ == "__main__":
    # Handle if you want to use a different sample module
    try:
        main()
    except ImportError as e:
        print(f"Missing module: {e}")
        print("Install: pip install wave")
        sys.exit(1)
