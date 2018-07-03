import time
from LightLora import lorautil

lr = lorautil.LoraUtil()	# the LoraUtil object

# a really ugly example using the LightLora micropython library
# do:
#      import lorarun
#      lorarun.doreader()
# to start running a loop test. Ctrl-C to stop.
# this ping-pongs fully with the Arduino LightLora example

def syncSend(lutil, txt) :
	''' send a packet synchronously '''
	lutil.sendPacket(0xff, 0x41, txt.encode())
	sendTime = 0
	while not lutil.isPacketSent() :
		time.sleep(.1)
		# after 2 seconds of waiting for send just give up
		sendTime = sendTime + 1
		if sendTime > 19 :
			break

# this ping-pongs fully with the Arduino LightLora example
def doreader():
	global lr
	endt = time.time() + 2
	startTime = time.time()
	ctr = 0
	while True:
		if lr.isPacketAvailable():
			packet = None
			try:
				packet = lr.readPacket()
				if packet and packet.msgTxt:
					txt = packet.msgTxt + str(ctr)
					syncSend(lr, txt)
					endt = time.time() + 4
					etime = str(int(time.time() - startTime))
					print("@" + etime + "r=" + str(txt))
				ctr = ctr + 1
			except Exception as ex:
				print(str(ex))
		if time.time() > endt:
			txt = 'P Lora' + str(ctr)
			syncSend(lr, txt)
			ctr = ctr + 1
			endt = time.time() + 4
		else:
			time.sleep(.05)
