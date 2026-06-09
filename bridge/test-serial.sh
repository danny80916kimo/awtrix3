#!/bin/bash
# Test script: sends each Claudy state to the AWTRIX3 via Serial.
# Usage: ./test-serial.sh [/dev/cu.usbserialXXX]

PORT="${1:-$(ls /dev/cu.usbserial* /dev/cu.usbmodem* 2>/dev/null | head -1)}"
if [ -z "$PORT" ]; then
  echo "No USB serial port found. Pass port as argument."
  exit 1
fi

echo "Sending test states to $PORT..."

python3 - "$PORT" <<'PY'
import serial, time, sys

port = sys.argv[1]
ser = serial.Serial()
ser.port = port
ser.baudrate = 115200
ser.timeout = 1
ser.dtr = False
ser.rts = False
ser.open()
time.sleep(0.5)

states = [
    ('{"state":"thinking","tool":"","msg":"What is this code?","pct":15}', 'thinking 15%'),
    ('{"state":"working","tool":"Read","msg":"main.cpp","pct":22}',        'working 22%'),
    ('{"state":"working","tool":"Edit","msg":"ClaydyApp.cpp","pct":35}',   'working 35%'),
    ('{"state":"thinking","tool":"Edit","msg":"","pct":42}',               'thinking 42%'),
    ('{"state":"waiting","tool":"Bash","msg":"Permission needed","pct":55}','waiting 55%'),
    ('{"state":"error","tool":"Bash","msg":"Command failed","pct":78}',    'error 78%'),
    ('{"state":"working","tool":"Write","msg":"test.py","pct":85}',        'working 85%'),
    ('{"state":"done","tool":"","msg":"Done","pct":95}',                   'done 95%'),
    ('{"state":"idle","tool":"","msg":"","pct":95}',                       'idle 95%'),
]

for json_str, label in states:
    ser.write((json_str + '\n').encode())
    ser.flush()
    print(f'  -> {label}')
    delay = 3 if 'done' in label else 2
    time.sleep(delay)

ser.close()
print('Done! Device should return to AWTRIX apps after 60s timeout.')
PY
