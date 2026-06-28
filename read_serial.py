import serial, time
for a in range(5):
    try:
        s = serial.Serial('COM6', 115200, timeout=2)
        break
    except:
        time.sleep(2)
else:
    raise SystemExit(1)
time.sleep(2)
s.reset_input_buffer()
s.timeout = 0
time.sleep(5)
data = s.read(10000)
s.close()
print(data.decode('utf-8', errors='replace'))
