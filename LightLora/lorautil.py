''' this adds a little high-level init to an sx1276 and it also
	packetizes messages with address headers'''
from time import sleep
from LightLora import spicontrol, sx127x

class LoraPacket:
	def __init__(self):
		self.srcAddress = None
		self.dstAddress = None
		self.srcLineCount = None
		self.payLength = None
		self.msgTxt = None
		self.rssi = None
		self.snr = None

	def clear(self):
		self.msgTxt = ''

class LoraUtil:
	''' a LoraUtil object has an sx1276 and it can send and receive LoRa packets
		sendPacket -> send a string
		isPacketAvailable -> do we have a packet available?
		readPacket -> get the latest packet
	'''
	# these default pin values are for a Heltec LoRa module
	# def __init__(self, lora_reset=14, lora_ss=18, sck=5, mosi=27, miso=19, lora_dio0=26):
	# these default pin values are for a Feather ESP32 Wroom board
	def __init__(self, lora_reset=33, lora_ss=27, sck=5, mosi=18, miso=19, lora_dio0=12):
		# just be neat and init variables in the __init__
		self.linecounter = 0
		self.packet = None
		self.doneTransmit = False

		# init spi
		self.spic = spicontrol.SpiControl(lora_reset, lora_ss, sck, mosi, miso, lora_dio0)
		# init lora
		params = {'tx_power_level': 5,
			'frequency' : 915e6,
			'signal_bandwidth': 125000,
			'spreading_factor': 9,
			'coding_rate': 8,
			'power_pin' : 1,		# boost pin is 1, non-boost pin is 0
			'enable_CRC': True}
		self.lora = sx127x.SX127x(spiControl=self.spic, parameters=params)
		self.spic.initLoraPins() # init pins
		self.lora.init()
		self.lora.onReceive(self._doReceive)
		self.lora.onTransmit(self._doTransmit)
		# put into receive mode and wait for an interrupt
		self.lora.receive()

	# we received a packet, deal with it
	def _doReceive(self, sx12, pay):
		pkt = LoraPacket()
		self.packet = None
		if pay and len(pay) > 4:
			pkt.srcAddress = pay[0]
			pkt.dstAddress = pay[1]
			pkt.srcLineCount = pay[2]
			pkt.payLength = pay[3]
			pkt.rssi = sx12.packetRssi()
			pkt.snr = sx12.packetSnr()
			try:
				pkt.msgTxt = pay[4:].decode('utf-8', 'ignore')
			except Exception as ex:
				print("doReceiver error: ")
				print(ex)
			self.packet = pkt

	# the transmit ended
	def _doTransmit(self):
		self.doneTransmit = True
		self.lora.receive() # wait for a packet (?)

	def writeInt(self, value):
		self.lora.write(bytearray([value]))

	def sendPacket(self, dstAddress, localAddress, outGoing):
		'''send a packet of header info and a bytearray to dstAddress
			asynchronous. Returns immediately. '''
		try:
			self.linecounter = self.linecounter + 1
			self.doneTransmit = False
			self.lora.beginPacket()
			self.writeInt(dstAddress)
			self.writeInt(localAddress)
			self.writeInt(self.linecounter)
			self.writeInt(len(outGoing))
			self.lora.write(outGoing)
			self.lora.endPacket()
		except Exception as ex:
			print(str(ex))

	def setFrequency(self, frequency) :
		''' set the center frequency of the device. 902-928 for 915 band '''
		self.lora.setFrequency(frequency)

	def sleep(self) :
		''' sleep the device '''
		self.lora.sleep()

	def reset(self) :
		''' reset the device '''
		self.spic.initLoraPins() # init pins

	def isPacketSent(self) :
		return self.doneTransmit

	def isPacketAvailable(self):
		''' convert to bool result from none, true '''
		return True if self.packet else False

	def readPacket(self):
		'''return the current packet (or none) and clear it out'''
		pkt = self.packet
		self.packet = None
		return pkt
