#!/usr/bin/env python
#
# OpenSync
# Copyright (C) 2022 Michael Ihde
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>

import logging

from binascii import a2b_base64, b2a_base64
import hashlib
import time
import io


def open_i2c_micropython():
    import machine

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

    return card

def open_i2c_raspberrypi():
    from periphery import I2C

    port = I2C(args.notecard_port)
    card = notecard.OpenI2C(port, 0, 0)

    return card

def sync_and_wait(card, timeout=None):
    # Perform a sync now
    logging.debug("Performing hub sync")
    req = {"req": "hub.sync.status"}
    req["sync"] = True
    rsp = card.Transaction(req)

    # Wait until the sync has been completed
    timeout_at = None
    if timeout is not None:
        timeout_at = time.time() + timeout

    logging.debug("Performed hub sync %s", rsp)
    while rsp.get("sync", False) is True:
        if timeout_at and time.time() > timeout_at:
            logging.warning("Timeout during sync_and_wait")
            break
        time.sleep(1)
        req = {"req": "hub.sync.status"}
        req["sync"] = False
        rsp = card.Transaction(req)
        logging.debug("Status hub sync %s", rsp)

class temporary_mode():
    def __init__(self, card, mode, wait_for_connection=True, timeout=None):
        self.card = card
        self.mode = mode
        self.current_mode = None
        self.wait_for_connection = wait_for_connection
        self.timeout = timeout

    def __enter__(self):
        # get the current mode
        req = {
            "req": "hub.get",
        }
        rsp = self.card.Transaction(req)
        self.current_mode = rsp.get("mode")

        if self.current_mode != self.mode:
            # set the new mode
            req = {
                "req": "hub.set",
                "mode": self.mode
            }
            rsp = self.card.Transaction(req)
            logging.info("Setting to %s mode %s", self.mode, rsp)


        else:
            logging.info("Card is already in mode %s with response %s", self.mode, rsp)

        
        # wait for the notecard to become connected
        timeout_at = None
        if self.timeout is not None:
            timeout_at = time.time() + self.timeout
        rsp = {}
        while self.wait_for_connection:
            if timeout_at is not None and time.time() > timeout_at:
                raise RuntimeError("timeout waiting for continuous connection")
            req = {"req": "hub.status"}
            rsp = self.card.Transaction(req)
            logging.info("Checking connection %s", rsp)
            # TODO one time is became 'connected {connected-closed}'

            if rsp.get("connected") == True:
                break

            req = {"req": "hub.sync.status"}
            rsp = self.card.Transaction(req)
            logging.info("Checking sync status %s", rsp)
            
            time.sleep(5)
            if timeout_at is not None:
                time_remaining = timeout_at - time.time()
                logging.info("time remaining waiting for continuous connection %s", time_remaining)

    def __exit__(self, *args, **kwargs):
        if self.current_mode != self.mode:
            # restore the old mode
            req = {
                "req": "hub.set",
                "mode": self.current_mode
            }
            rsp = self.card.Transaction(req)
            logging.info("Restoring original mode %s response %s", self.current_mode, rsp)

from notecard import notecard as _notecard
class temporary_segment_delay():
    """
    Temporarily change CARD_REQUEST_SEGMENT_DELAY_MS. Note, this is not thread-safe.
    """
    def __init__(self, delay_ms):
        if delay_ms < 25:
            raise ValueError("segment delay less than 25ms could result in unstable operation")
        self.initial_delay_ms = _notecard.CARD_REQUEST_SEGMENT_DELAY_MS
        self.new_delay_ms = delay_ms
        
    def __enter__(self):

        logging.info("setting CARD_REQUEST_SEGMENT_DELAY_MS from %s to %s", self.initial_delay_ms, self.new_delay_ms)
        _notecard.CARD_REQUEST_SEGMENT_DELAY_MS = self.new_delay_ms
        
    def __exit__(self, *args, **kwargs):
        logging.info("restoring CARD_REQUEST_SEGMENT_DELAY_MS to %s", self.initial_delay_ms)
        _notecard.CARD_REQUEST_SEGMENT_DELAY_MS = self.initial_delay_ms


def web_post(card, route, payload, name=None, chunk_size=4096, content=None, wait_for_connection=True, connection_timeout=None):
    offset = 0
    fragmented = ( len(payload) > chunk_size )

    s = time.time()
    # web.post requires continuous mode
    with temporary_mode(card, "continuous", wait_for_connection=wait_for_connection, timeout=connection_timeout):
        # Use a faster segment delay on web.post
        with temporary_segment_delay(50):
            while offset < len(payload):
                req = {"req": "web.post"} 
                req["route"] = route
                if name:
                    req["name"] = name
                if content:
                    req['content'] = content # undocumented feature

                if fragmented:
                    fragment = payload[offset:offset+chunk_size]

                    req["total"] = len(payload)
                    req["payload"] = b2a_base64( fragment, newline=False).decode("ascii")
                    req["status"] = hashlib.md5( fragment ).hexdigest()
                    req["offset"] = offset
                    req["verify"] = True

                    logging.debug("sending web.post fragment of length %s at offset %s", len(fragment), offset)
                else:
                    req["payload"] = b2a_base64( payload, newline=False ).decode("ascii")
                    logging.debug("sending web.post of length %s", len(payload))

                offset += chunk_size
                rsp = card.Transaction(req)
                logging.debug("web.post response %s", rsp)

                if rsp.get("err"):
                    raise RuntimeError("card reported an error %s" %  rsp.get("err"))
                # if data remains to be transmitted we expect a 100 request
                #if offset < len(payload) and rsp.get("result") != 100:
                #    raise RuntimeError("error in fragmented web.post")

    response_payload = None
    if rsp.get("payload"):
        response_payload = a2b_base64(rsp['payload']).decode("ascii")
    e = time.time()
    logging.debug("web.post took %s seconds for %s bytes", e-s, len(payload))

    return rsp, response_payload

if __name__ == "__main__":
    import argparse
    import datetime

    import notecard
    try:
        import serial
    except ImportError:
        serial = None

    try:
        from periphery import I2C
    except ImportError:
        I2Cc = None

    try:
        from opensearchpy import OpenSearch
    except ImportError:
        OpenSearch = None

    parser = argparse.ArgumentParser()
    parser.add_argument("--notecard-port", default="/dev/i2c-1")
    parser.add_argument("--notecard-mode", default="i2c")
    parser.add_argument("--poll", default=5, type=int)
    parser.add_argument("--opensearch")
    parser.add_argument("--product")
    parser.add_argument("--no-wait-for-connection", default=False, action="store_true")
    parser.add_argument("action", nargs='+')
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s:%(levelname)s:%(name)s:%(message)s')

    logging.info("Connecting to notecard on port %s", args.notecard_port)
    if args.notecard_mode == "i2c":
        port = I2C(args.notecard_port)
        nCard = notecard.OpenI2C(port, 0, 0, debug=True)
    else:
        port = serial.Serial(args.notecard_port, 9600)
        nCard = notecard.OpenSerial(port)

    db = None
    if args.opensearch:
        db = OpenSearch(args.opensearch)

    req = {"req": "card.version"}
    rsp = nCard.Transaction(req)

    if args.product:
        req = {"req": "hub.set", "product": args.product}
        rsp = nCard.Transaction(req)
        device = rsp.get("device")

    req = {"req": "hub.get"}
    rsp = nCard.Transaction(req)
    device = rsp.get("device")

    synccount = 0
    while True:
        for action in args.action:
            logging.info("-------------- Action %s --------------", action)

            if action.startswith("pause"):
                time.sleep(int(action[5:]))

            elif action == "connect-wait":
                # wait for the notecard to become connected
                rsp = {}
                while True:
                    responses = []

                    req = {"req": "hub.sync"}
                    rsp = nCard.Transaction(req)
                    rsp['req'] = req
                    rsp['@timestamp'] = datetime.datetime.now().isoformat()
                    rsp['device'] = device
                    responses.append(rsp)

                    req = {"req": "hub.status"}
                    rsp = nCard.Transaction(req)
                    rsp['req'] = req
                    rsp['@timestamp'] = datetime.datetime.now().isoformat()
                    rsp['device'] = device
                    responses.append(rsp)

                    connected = rsp.get("connected")
   
                    req = {"req": "hub.sync.status"}
                    rsp = nCard.Transaction(req)
                    rsp['req'] = req
                    rsp['@timestamp'] = datetime.datetime.now().isoformat()
                    rsp['device'] = device
                    responses.append(rsp)

                    req = {"req": "card.wireless"}
                    rsp = nCard.Transaction(req)
                    rsp['req'] = req
                    rsp['@timestamp'] = datetime.datetime.now().isoformat()
                    rsp['device'] = device
                    responses.append(rsp)

                    if db is not None:
                        for rsp in responses:
                            
                            db.index(
                                index = "notecard",
                                body = rsp,
                            )
                   
                    if connected == True:
                        break

                    time.sleep(args.poll)

            elif action == "monitor":
                responses = []

                req = {"req": "hub.status"}
                rsp = nCard.Transaction(req)
                rsp['req'] = req
                rsp['@timestamp'] = datetime.datetime.now().isoformat()
                rsp['device'] = device
                responses.append(rsp)

                req = {"req": "hub.sync.status"}
                rsp = nCard.Transaction(req)
                rsp['req'] = req
                rsp['@timestamp'] = datetime.datetime.now().isoformat()
                rsp['device'] = device
                responses.append(rsp)

                req = {"req": "card.wireless"}
                rsp = nCard.Transaction(req)
                rsp['req'] = req
                rsp['@timestamp'] = datetime.datetime.now().isoformat()
                rsp['device'] = device
                responses.append(rsp)

                if db is not None:
                    for rsp in responses:
                        
                        db.index(
                            index = "notecard",
                            body = rsp,
                        )

                time.sleep(args.poll)

            elif action == "get":
                req = {"req": "hub.get"}
                rsp = nCard.Transaction(req)
                rsp['req'] = req
                rsp['device'] = device

                if db is not None:
                    db.index(
                        index = "notecard",
                        body = rsp,
                    )

            elif action.startswith("mode:"):
                _, mode = action.split(":", 1)
                req = {"req": "hub.set", "mode": mode}
                rsp = nCard.Transaction(req)
                rsp['req'] = req
                rsp['device'] = device

                if db is not None:
                    db.index(
                        index = "notecard",
                        body = rsp,
                    )

            elif action == "sync":
                synccount += 1
                req = {"req": "hub.sync"}
                rsp = nCard.Transaction(req)
                rsp['req'] = req
                rsp['device'] = device
                rsp['@timestamp'] = datetime.datetime.now().isoformat()

                if db is not None:
                    db.index(
                        index = "notecard",
                        body = rsp,
                    )
        
            elif action == "sync-once" and synccount == 0:
                synccount += 1
                req = {"req": "hub.sync"}
                rsp = nCard.Transaction(req)

            elif action.startswith("post:"):
                _, route, data = action.split(":", 2)
                if data[0] == "@":
                    logging.debug("Loading content from %s", data[1:])
                    fpath = data[1:]
                    with open(fpath, 'rb') as ff:
                        dd = ff.read()
                        rsp = web_post(nCard, route, dd, wait_for_connection=not args.no_wait_for_connection)
                        print(rsp)
                else:
                    rsp = web_post(nCard, route, data.encode("ascii"), wait_for_connection=not args.no_wait_for_connection)
                    print(rsp)