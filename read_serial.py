import serial, time

for attempt in range(5):
    try:
        s = serial.Serial('COM6', 115200, timeout=1)
        break
    except:
        time.sleep(2)
else:
    print("Could not open COM6")
    raise SystemExit(1)

time.sleep(1)
s.reset_input_buffer()
s.write(b'\x04')

data = b''
start = time.time()
while time.time() - start < 30:
    chunk = s.read(2048)
    if chunk:
        data += chunk
    else:
        time.sleep(0.3)

s.close()
text = data.decode('utf-8', errors='replace')
print(text)
