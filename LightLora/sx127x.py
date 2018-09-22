'''This is a generic sx127x driver for the Semtech chipsets.
In particular, it has a minor tweak for the sx1276.

This code supports interrupt driven send and receive for maximum efficiency.
Call onReceive and onTransmit to define the interrupt handlers.
	Receive handler gets a packet of data
	Transmit handler is informed the transmit ended

Communications is handled by an SpiControl object wrapping SPI


'''
import gc
import _thread
from machine import Pin

PA_OUTPUT_RFO_PIN = 0
PA_OUTPUT_PA_BOOST_PIN = 1

# registers
REG_FIFO = 0x00
REG_OP_MODE = 0x01
REG_FRF_MSB = 0x06
REG_FRF_MID = 0x07
REG_FRF_LSB = 0x08
REG_PA_CONFIG = 0x09
REG_OCP = 0x0b # overcurrent protection
REG_LNA = 0x0c
REG_FIFO_ADDR_PTR = 0x0d

REG_FIFO_TX_BASE_ADDR = 0x0e
FifoTxBaseAddr = 0x00
# FifoTxBaseAddr = 0x80

REG_FIFO_RX_BASE_ADDR = 0x0f
FifoRxBaseAddr = 0x00
REG_FIFO_RX_CURRENT_ADDR = 0x10
REG_IRQ_FLAGS_MASK = 0x11
REG_IRQ_FLAGS = 0x12
REG_RX_NB_BYTES = 0x13
REG_PKT_RSSI_VALUE = 0x1a
REG_PKT_SNR_VALUE = 0x1b
REG_MODEM_CONFIG_1 = 0x1d
REG_MODEM_CONFIG_2 = 0x1e
REG_PREAMBLE_MSB = 0x20
REG_PREAMBLE_LSB = 0x21
REG_PAYLOAD_LENGTH = 0x22
REG_FIFO_RX_BYTE_ADDR = 0x25
REG_MODEM_CONFIG_3 = 0x26
REG_RSSI_WIDEBAND = 0x2c
REG_DETECTION_OPTIMIZE = 0x31
REG_DETECTION_THRESHOLD = 0x37
REG_SYNC_WORD = 0x39
REG_DIO_MAPPING_1 = 0x40
REG_VERSION = 0x42
REG_PA_DAC = 0x4d


# modes
MODE_LONG_RANGE_MODE = 0x80  # bit 7: 1 => LoRa mode
MODE_SLEEP = 0x00
MODE_STDBY = 0x01
MODE_TX = 0x03
MODE_RX_CONTINUOUS = 0x05
# MODE_RX_SINGLE = 0x06
# 6 is not supported on the 1276
MODE_RX_SINGLE = 0x05

# PA config
PA_BOOST = 0x80

# Low Data Rate flag
LDO_FLAG = 8

# IRQ masks
IRQ_TX_DONE_MASK = 0x08
IRQ_PAYLOAD_CRC_ERROR_MASK = 0x20
IRQ_RX_DONE_MASK = 0x40
IRQ_RX_TIME_OUT_MASK = 0x80

# Buffer size
MAX_PKT_LENGTH = 255

# pass in non-default parameters for any/all options in the constructor parameters argument
DEFAULT_PARAMETERS = {'frequency': 915E6, 'tx_power_level': 2, 'signal_bandwidth': 125000,
					  'spreading_factor': 7, 'coding_rate': 5, 'preamble_length': 8,
					  'power_pin' : PA_OUTPUT_PA_BOOST_PIN,
					  'implicitHeader': False, 'sync_word': 0x12, 'enable_CRC': False}

REQUIRED_VERSION = 0x12

class SX127x:
	''' Standard SX127x library. Requires an spicontrol.SpiControl instance for spiControl '''
	def __init__(self,
				 name='SX127x',
				 parameters={},
				 onReceive=None,
				 onTransmit=None,
				 spiControl=None):

		self.name = name
		self.parameters = parameters
		self.bandwidth = 125000	# default bandwidth
		self.spreading = 6	# default spreading factor
		self._onReceive = onReceive	 # the onreceive function
		self._onTransmit = onTransmit   # the ontransmit function
		self.doAcquire = hasattr(_thread, 'allocate_lock') # micropython vs loboris
		if self.doAcquire :
			self._lock = _thread.allocate_lock()
		else :
			self._lock = True
		self._spiControl = spiControl   # the spi wrapper - see spicontrol.py
		self.irqPin = spiControl.getIrqPin() # a way to need loracontrol only in spicontrol
		self.isLoboris = not callable(getattr(self.irqPin, "irq", None)) # micropython vs loboris

	# if we passed in a param use it, else use default
	def _useParam(self, who):
		return DEFAULT_PARAMETERS[who] if not who in self.parameters.keys() else self.parameters[who]

	def init(self):
		# check version
		version = self.readRegister(REG_VERSION)
		if version != REQUIRED_VERSION:
			print("Detected version:", version)
			raise Exception('Invalid version.')

		# put in LoRa and sleep mode
		self.sleep()

		# set auto AGC before setting bandwidth and spreading factor
		# because they'll set the low-data-rate flag bit
		self.writeRegister(REG_MODEM_CONFIG_3, 0x04)

		# config
		self.setFrequency(self._useParam('frequency'))
		self.setSignalBandwidth(self._useParam('signal_bandwidth'))

		# set LNA boost
		self.writeRegister(REG_LNA, self.readRegister(REG_LNA) | 0x03)

		powerpin = self._useParam('power_pin')
		self.setTxPower(self._useParam('tx_power_level'), powerpin)
		self._implicitHeaderMode = None
		self.implicitHeaderMode(self._useParam('implicitHeader'))
		self.setSpreadingFactor(self._useParam('spreading_factor'))
		self.setCodingRate(self._useParam('coding_rate'))
		self.setPreambleLength(self._useParam('preamble_length'))
		self.setSyncWord(self._useParam('sync_word'))
		self.enableCRC(self._useParam('enable_CRC'))

		# set base addresses
		self.writeRegister(REG_FIFO_TX_BASE_ADDR, FifoTxBaseAddr)
		self.writeRegister(REG_FIFO_RX_BASE_ADDR, FifoRxBaseAddr)

		self.standby()

	# start sending a packet (reset the fifo address, go into standby)
	def beginPacket(self, implicitHeaderMode=False):
		self.standby()
		self.implicitHeaderMode(implicitHeaderMode)
		# reset FIFO address and paload length
		self.writeRegister(REG_FIFO_ADDR_PTR, FifoTxBaseAddr)
		self.writeRegister(REG_PAYLOAD_LENGTH, 0)

	# finished putting packet into fifo, send it
	# non-blocking so don't immediately receive...
	def endPacket(self):
		''' non-blocking end packet '''
		if self._onTransmit:
		   # enable tx to raise DIO0
			self._prepIrqHandler(self._handleOnTransmit)		   # attach handler
			self.writeRegister(REG_DIO_MAPPING_1, 0x40)		   # enable transmit dio0
		else:
			self._prepIrqHandler(None)							# no handler
		# put in TX mode
		self.writeRegister(REG_OP_MODE, MODE_LONG_RANGE_MODE | MODE_TX)

	def isTxDone(self):
		''' if Tx is done return true, and clear irq register - so it only returns true once '''
		if self._onTransmit:
			print("Do not call isTxDone with transmit interrupts enabled. Use the callback.")
			return False
		irqFlags = self.getIrqFlags()
		if (irqFlags & IRQ_TX_DONE_MASK) == 0:
			return False
		# clear IRQ's
		self.collect_garbage()
		return True

	def write(self, buffer):
		currentLength = self.readRegister(REG_PAYLOAD_LENGTH)
		size = len(buffer)
		# check size
		size = min(size, (MAX_PKT_LENGTH - FifoTxBaseAddr - currentLength))
		# write data
		for i in range(size):
			self.writeRegister(REG_FIFO, buffer[i])
		# update length
		self.writeRegister(REG_PAYLOAD_LENGTH, currentLength + size)
		return size

	def acquire_lock(self, lock=False):
		if self._lock:
			# we have a lock object
			if self.doAcquire:
				if lock:
					self._lock.acquire()
				else:
					self._lock.release()
			# else lock the thread hard
			else:
				if lock:
					_thread.lock()
				else:
					_thread.unlock()

	def println(self, string, implicitHeader=False):
		self.acquire_lock(True)  # wait until RX_Done, lock and begin writing.
		self.beginPacket(implicitHeader)
		self.write(string.encode())
		self.endPacket()
		self.acquire_lock(False) # unlock when done writing

	def getIrqFlags(self):
		''' get and reset the irq register '''
		irqFlags = self.readRegister(REG_IRQ_FLAGS)
		self.writeRegister(REG_IRQ_FLAGS, irqFlags)
		return irqFlags

	def packetRssi(self):
		return self.readRegister(REG_PKT_RSSI_VALUE) - (164 if self._frequency < 868E6 else 157)

	def packetSnr(self):
		return self.readRegister(REG_PKT_SNR_VALUE) * 0.25

	def standby(self):
		self.writeRegister(REG_OP_MODE, MODE_LONG_RANGE_MODE | MODE_STDBY)

	def sleep(self):
		self.writeRegister(REG_OP_MODE, MODE_LONG_RANGE_MODE | MODE_SLEEP)

	def setTxPower(self, level, outputPin=PA_OUTPUT_PA_BOOST_PIN):
		if outputPin == PA_OUTPUT_RFO_PIN:
			# RFO
			level = min(max(level, 0), 14)
			self.writeRegister(REG_PA_CONFIG, 0x70 | level)
		else:
			# PA BOOST 2...20 are valid values
			level = min(max(level, 2), 20)
			dacValue = self.readRegister(REG_PA_DAC) & ~7
			ocpValue = 0
			if level > 17:
				dacValue = dacValue | 7
				ocpValue = 0x20 | 18 # 150 ma [-30 + 10*value]
				level = level - 5    # normalize to 15 max
			else:
				dacValue = dacValue | 4
				ocpValue = 11     # 100 mA [45 + 5*value]
				level = level - 2 # normalize to 15 max
			self.writeRegister(REG_PA_CONFIG, PA_BOOST | level)
			self.writeRegister(REG_PA_DAC, dacValue)
			self.writeRegister(REG_OCP, ocpValue)

	# set the frequency band. passed in Hz
	# Frf register setting = Freq / FSTEP where
	# FSTEP = FXOSC/2**19 where FXOSC=32MHz. So FSTEP==61.03515625
	def setFrequency(self, frequency):
		self._frequency = frequency
		frfs = (int)(frequency / 61.03515625)
		self.writeRegister(REG_FRF_MSB, frfs >> 16)
		self.writeRegister(REG_FRF_MID, frfs >> 8)
		self.writeRegister(REG_FRF_LSB, frfs)

	def setSpreadingFactor(self, sf):
		sf = min(max(sf, 6), 12)
		self.spreading = sf
		self.writeRegister(REG_DETECTION_OPTIMIZE, 0xc5 if sf == 6 else 0xc3)
		self.writeRegister(REG_DETECTION_THRESHOLD, 0x0c if sf == 6 else 0x0a)
		self.writeRegister(REG_MODEM_CONFIG_2, (self.readRegister(REG_MODEM_CONFIG_2) & 0x0f) | ((sf << 4) & 0xf0))
		self.setLdoFlag()

	def setSignalBandwidth(self, sbw):
		bins = (7800, 10400, 15600, 20800, 31250, 41700, 62500, 125000, 250000, 500000)
		bw = 9 # default to 500000 max
		for i in range(len(bins)):
			if sbw <= bins[i]:
				bw = i
				break
		self.bandwidth = bins[bw]
		self.writeRegister(REG_MODEM_CONFIG_1, (self.readRegister(REG_MODEM_CONFIG_1) & 0x0f) | (bw << 4))
		self.setLdoFlag()

	def setLdoFlag(self):
		''' set the low data rate flag. This must be 1 if symbol duration is > 16ms '''
		symbolDuration = 1000 / (self.bandwidth / (1 << self.spreading))
		config3 = self.readRegister(REG_MODEM_CONFIG_3) & ~LDO_FLAG
		if symbolDuration > 16:
			config3 = config3 | LDO_FLAG
		self.writeRegister(REG_MODEM_CONFIG_3, config3)

	def setCodingRate(self, denominator):
		''' this takes a value of 5..8 as the denominator of 4/5, 4/6, 4/7, 5/8 '''
		denominator = min(max(denominator, 5), 8)
		cr = denominator - 4
		self.writeRegister(REG_MODEM_CONFIG_1, (self.readRegister(REG_MODEM_CONFIG_1) & 0xf1) | (cr << 1))

	def setPreambleLength(self, length):
		self.writeRegister(REG_PREAMBLE_MSB, (length >> 8) & 0xff)
		self.writeRegister(REG_PREAMBLE_LSB, (length >> 0) & 0xff)

	def enableCRC(self, enable_CRC=False):
		modem_config_2 = self.readRegister(REG_MODEM_CONFIG_2)
		config = modem_config_2 | 0x04 if enable_CRC else modem_config_2 & 0xfb
		self.writeRegister(REG_MODEM_CONFIG_2, config)

	def setSyncWord(self, sw):
		self.writeRegister(REG_SYNC_WORD, sw)

	def dumpRegisters(self):
		for i in range(128):
			print("0x{0:02x}: {1:02x}".format(i, self.readRegister(i)))

	def implicitHeaderMode(self, implicitHeaderMode=False):
		if self._implicitHeaderMode != implicitHeaderMode:  # set value only if different.
			self._implicitHeaderMode = implicitHeaderMode
			modem_config_1 = self.readRegister(REG_MODEM_CONFIG_1)
			config = modem_config_1 | 0x01 if implicitHeaderMode else modem_config_1 & 0xfe
			self.writeRegister(REG_MODEM_CONFIG_1, config)

	def _prepIrqHandler(self, handlefn):
		''' attach the handler to the irq pin, disable if None '''
		if self.irqPin:
			if handlefn:
				if self.isLoboris:
					self.irqPin.init(handler=handlefn, trigger=Pin.IRQ_RISING)
				else:
					self.irqPin.irq(handler=handlefn, trigger=Pin.IRQ_RISING)
			else:
				if self.isLoboris:
					self.irqPin.init(handler=None, trigger=0)
				else:
					self.irqPin.irq(handler=handlefn, trigger=0)


	def onReceive(self, callback):
		''' establish a callback function for receive interrupts'''
		self._onReceive = callback
		self._prepIrqHandler(None) # in case we have one and we're receiving. stop.

	def onTransmit(self, callback):
		''' establish a callback function for transmit interrupts'''
		self._onTransmit = callback

	def receive(self, size=0):
		''' enable reception - call this when you want to receive stuff '''
		self.implicitHeaderMode(size > 0)
		if size > 0:
			self.writeRegister(REG_PAYLOAD_LENGTH, size & 0xff)
		# enable rx to raise DIO0
		if self._onReceive:
			self._prepIrqHandler(self._handleOnReceive)			# attach handler
			self.writeRegister(REG_DIO_MAPPING_1, 0x00)
		else:
			self._prepIrqHandler(None)							# no handler
		# The last packet always starts at FIFO_RX_CURRENT_ADDR
		# no need to reset FIFO_ADDR_PTR
		self.writeRegister(REG_OP_MODE, MODE_LONG_RANGE_MODE | MODE_RX_CONTINUOUS)

	# got a receive interrupt, handle it
	def _handleOnReceive(self, event_source):
		self.acquire_lock(True)			  # lock until TX_Done
		irqFlags = self.getIrqFlags()
		irqBad = IRQ_PAYLOAD_CRC_ERROR_MASK | IRQ_RX_TIME_OUT_MASK
		if (irqFlags & IRQ_RX_DONE_MASK) and \
		   ((irqFlags & irqBad) == 0) and \
			self._onReceive:
			# it's a receive data ready interrupt
			payload = self.read_payload()
			self.acquire_lock(False)	 # unlock when done reading
			self._onReceive(self, payload)
		else:
			self.acquire_lock(False)			 # unlock in any case.
			if not irqFlags & IRQ_RX_DONE_MASK:
				print("not rx done mask")
			elif (irqFlags & IRQ_PAYLOAD_CRC_ERROR_MASK) != 0:
				print("crc error")
			elif (irqFlags & IRQ_RX_TIME_OUT_MASK) != 0:
				print("receive timeout error")
			else:
				print("no receive method defined")

	# Got a transmit interrupt, handle it
	def _handleOnTransmit(self, event_source):
		self.acquire_lock(True)			  # lock until flags cleared
		irqFlags = self.getIrqFlags()
		if irqFlags & IRQ_TX_DONE_MASK:
			# it's a transmit finish interrupt
			self._prepIrqHandler(None)	   # disable handler since we're done
			self.acquire_lock(False)			 # unlock
			if self._onTransmit:
				self._onTransmit()
			else:
				print("transmit callback but no callback method")
		else:
			self.acquire_lock(False)			 # unlock
			print("transmit callback but not txdone: " + str(irqFlags))

	def receivedPacket(self, size=0):
		''' when no receive handler, this tells if packet ready. Preps for receive'''
		if self._onReceive:
			print("Do not call receivedPacket. Use the callback.")
			return False
		irqFlags = self.getIrqFlags()
		self.implicitHeaderMode(size > 0)
		if size > 0:
			self.writeRegister(REG_PAYLOAD_LENGTH, size & 0xff)
		# if (irqFlags & IRQ_RX_DONE_MASK) and \
		   # (irqFlags & IRQ_RX_TIME_OUT_MASK == 0) and \
		   # (irqFlags & IRQ_PAYLOAD_CRC_ERROR_MASK == 0):
		if irqFlags == IRQ_RX_DONE_MASK:  # RX_DONE only, irqFlags should be 0x40
			# automatically standby when RX_DONE
			return True
		elif self.readRegister(REG_OP_MODE) != (MODE_LONG_RANGE_MODE | MODE_RX_SINGLE):
			# no packet received and not in receive mode
			# reset FIFO address / # enter single RX mode
			self.writeRegister(REG_FIFO_ADDR_PTR, FifoRxBaseAddr)
			self.writeRegister(REG_OP_MODE, MODE_LONG_RANGE_MODE | MODE_RX_SINGLE)
		return False

	def read_payload(self):
		# set FIFO address to current RX address
		# fifo_rx_current_addr = self.readRegister(REG_FIFO_RX_CURRENT_ADDR)
		self.writeRegister(REG_FIFO_ADDR_PTR, self.readRegister(REG_FIFO_RX_CURRENT_ADDR))
		# read packet length
		packetLength = self.readRegister(REG_PAYLOAD_LENGTH) if self._implicitHeaderMode else \
					   self.readRegister(REG_RX_NB_BYTES)
		payload = bytearray()
		for i in range(packetLength):
			payload.append(self.readRegister(REG_FIFO))
		self.collect_garbage()
		return bytes(payload)

	def readRegister(self, address, byteorder='big', signed=False):
		response = self._spiControl.transfer(address & 0x7f)
		return int.from_bytes(response, byteorder)

	def writeRegister(self, address, value):
		self._spiControl.transfer(address | 0x80, value)

	def collect_garbage(self):
		gc.collect()
		#print('[Memory - free: {}   allocated: {}]'.format(gc.mem_free(), gc.mem_alloc()))
