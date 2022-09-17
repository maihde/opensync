class Notecard:
    def __init__(self):
        pass

class OpenI2C(Notecard):

import machine
i2c = machine.SoftI2C(scl=machine.Pin(22), sda=machine.Pin(23))
i2c.scan()
i2c.writeto(addr, b'1234')
i2c.readfrom(addr, 4)
