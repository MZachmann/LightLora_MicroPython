A MicroPython Library for Controlling a Semtech SX127x LoRa Chip
---
This is yet another library for controlling an SX127x Semtech chip. This is entirely interrupt driven (transmit and receive) with callbacks.

For power usage, you can sleep the CPU while waiting for an interrupt during transmit and receive cycles.

There is a nearly exact copy of this library for Arduino here https://github.com/MZachmann/LightLora_Arduino

Installation
--
The library (LightLora) folder can just be copied and used as-is in a project.

Usage
--
During setup call 
```python
from LightLora import lorautil

lru = lorautil.LoraUtil()
```
During the loop you can
```python
if lru.isPacketAvailable():
	pkt = lru.readPacket()
	print(pkt.msgTxt)
...
txt = "Hello World"
lru.sendPacket(0xff, 0x11, txt.encode()) # random dst, src at
```

Customization
---
The ports for the LoRa device are set in spicontrol.py for now.

The _doTransmit and _doReceive methods in lorautil.LoraUtil are the callbacks on interrupt.

