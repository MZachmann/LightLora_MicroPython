from time import sleep
from machine import Pin, SPI

# loraconfig is the project definition for pins <-> hardware

class SpiControl:
	''' simple higher level spi stuff '''
	def __init__(self, lora_reset, lora_ss, sck, mosi, miso, lora_dio0):
		self.spi = SPI(1, baudrate=5000000, polarity=0, phase=0, bits=8,
				 firstbit=SPI.MSB,
				 sck=Pin(sck, Pin.OUT),
				 mosi=Pin(mosi, Pin.OUT),
				 miso=Pin(miso, Pin.IN))
		self.pinss = Pin(lora_ss, Pin.OUT)
		self.pinrst = Pin(lora_reset, Pin.OUT)
		self.irqPin = Pin(lora_dio0, Pin.IN)

	# sx127x transfer is always write two bytes while reading the second byte
	# a read doesn't write the second byte. a write returns the prior value.
	# write register # = 0x80 | read register #
	def transfer(self, address, value=0x00):
		response = bytearray(1)
		self.pinss.value(0)					 # hold chip select low
		self.spi.write(bytearray([address])) # write register address
		self.spi.write_readinto(bytearray([value]), response) # write or read register walue
		self.pinss.value(1)
		return response

	# this doesn't belong here but it doesn't really belong anywhere, so put
	# it with the other loraconfig-ed stuff
	def getIrqPin(self):
		return self.irqPin

	# this doesn't belong here but it doesn't really belong anywhere, so put
	# it with the other loraconfig-ed stuff
	def initLoraPins(self):
		''' initialize the pins for the LoRa device. '''
		self.pinss.value(1)		# initialize CS to high (off)
		self.pinrst.value(1)	# do a reset pulse
		sleep(.01)
		self.pinrst.value(0)
		sleep(.01)
		self.pinrst.value(1)
