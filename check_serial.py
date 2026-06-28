import serial, time, re

for attempt in range(5):
    try:
        s = serial.Serial('COM6', 115200, timeout=3)
        break
    except serial.SerialException as e:
        print(f'Attempt {attempt+1}: {e}')
        time.sleep(2)
else:
    print('Could not open COM6')
    raise SystemExit(1)

time.sleep(2)
s.write(b'\x04')  # Ctrl+D to soft-reload
time.sleep(6)
data = s.read(8192)
s.close()

text = data.decode('utf-8', errors='replace')
text = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text)
text = re.sub(r'\x1b\][^\x1b]*\x1b\\', '', text)
print(text[:3000])
