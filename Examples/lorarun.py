import time
from LightLora import lorautil
# a really ugly example using the LightLora micropython library
# do:
#      import lorarun
#      lorarun.doreader()
# to start running a loop test. Ctrl-C to stop.
# this ping-pongs fully with the Arduino LightLora example
def doreader():
	lr = lorautil.LoraUtil()	# the LoraUtil object
	endt = time.time() + 2
	startTime = time.time()
	ctr = 0
	while True:
		if lr.isPacketAvailable():
			packet = None
			try:
				packet = lr.readPacket()
				if packet and packet.msgTxt:
					txt = packet.msgTxt
					lr.sendPacket(0xff, 0x41, (txt + str(ctr)).encode())
					endt = time.time() + 4
					etime = str(int(time.time() - startTime))
					print("@" + etime + "r=" + str(txt))
				ctr = ctr + 1
			except Exception as ex:
				print(str(ex))
		if time.time() > endt:
			lr.sendPacket(0xff, 0x41, ('P Lora' + str(ctr)).encode())
			ctr = ctr + 1
			endt = time.time() + 4
		else:
			time.sleep(.05)
