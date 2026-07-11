# Wi-Fi scan test
import wifi, time
print("Test start")
wifi.radio.stop_scanning_networks()
time.sleep(0.5)
n = wifi.radio.start_scanning_networks()
print("Scanner type:", type(n))
deadline = time.monotonic() + 5
count = 0
while time.monotonic() < deadline:
    try:
        x = n.__next__()
        count += 1
        print(f"#{count} ssid={x.ssid!r} rssi={x.rssi} auth={x.authmode} chan={x.channel}")
        if count >= 3:
            break
    except StopIteration:
        # No results yet, keep waiting
        time.sleep(0.2)
    except TypeError as e:
        print(f"Hash bug: {e}")
        time.sleep(0.2)
    except Exception as e:
        print(f"Other: {e}")
        break
print(f"Total found: {count}")
wifi.radio.stop_scanning_networks()
print("Done")
