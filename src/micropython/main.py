#!/usr/bin/env python

import notecard
import logging

from opensync import notecard_helpers

def opensync(card, **kwargs):
    # Print out the Notecard version
    req = { "req": "card.version" }
    rsp = card.Transaction(req)
    logging.debug("Found Notecard %s", rsp)

    # Set minimum hub sync
    req = {"req": "hub.set"}
    req['mode'] = "minimum"
    if kwargs.get('product'):
        req['product'] = kwargs['product']
    rsp = card.Transaction(req)
    logging.info("Setting minimum mode %s", rsp)

    # Perform a sync now
    notecard_helpers.sync_and_wait(card)

    # If GPS tracking is not disabled, establish it to be once per minute
    if kwargs.get("enable_tracking"):
        logging.info("Enabling GPS tracking")
        req = {"req": "card.location.mode"}
        req["mode"] = "periodic"
        req["seconds"] = 50
        rsp = card.Transaction(req)

        req = {"req": "card.location.track"}
        req["start"] = True
        req["seconds"] = 50
        rsp = card.Transaction(req)

    try:
        while True:
            time.sleep(1)
    finally:
        notecard_helpers.sync_and_wait(card)
    
def micropython_main():
    import machine
    import network


    logging.basicConfig(
        level=logging.DEBUG
    )

    # Establish the I2C bus and search for notecard
    port = machine.SoftI2C(
        scl=machine.Pin(22),
        sda=machine.Pin(23)
    )
    
    devices = port.scan()
    if 23 not in devices:
        logging.warning("Could not identify Notecard on I2C bus")

    # Connect to Notecard
    card = notecard.OpenI2C(
        port,
        0,
        0,
        debug=True
    )

    # Connect the WiFi
    sta_if = network.WLAN(network.STA_IF)
    sta_if.active(True)
    sta_if.connect("ez Share", "88888888")
    
    # Execute the main
    opensync(card)

if __name__ == "__main__":
    micropython_main()
