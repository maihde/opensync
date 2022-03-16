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
import os
import base64
import requests
import time
import hashlib
import json
from requests_toolbelt.multipart.encoder import MultipartEncoder
import notecard

try:
    import serial
except ImportError:
    serial = None

try:
    from periphery import I2C
except ImportError:
    I2Cc = None

from . import notecard_helpers

def publish_flight_log_direct(token, aircraft_id, fname, log):
    mp_encoder = MultipartEncoder(
        boundary="flight_log_data",
        fields={
            'token': token,
            # plain file object, no filename or mime type produces a
            # Content-Disposition header with just the part name
            'file': (fname, io.StringIO(log), 'text/plain'),
        }
    )

    r = requests.post(
        f'https://apps.savvyaviation.com/upload_files_api/{aircraft_id}/',
        data=mp_encoder,  # The MultipartEncoder is posted as data, don't use files=...!
        # The MultipartEncoder provides the content-type header with the boundary:
        headers={'Content-Type': mp_encoder.content_type}
    )
    print(r)
    print(mp_encoder.content_type)
    print(r.text)

def publish_flight_log_notecard(card, token, aircraft_id, fname, log, chunk_size=8192):
    mp_encoder = MultipartEncoder(
        fields={
            'token': token,
            # plain file object, no filename or mime type produces a
            # Content-Disposition header with just the part name
            'file': (fname, log, 'text/plain'),
        }
    )

    payload = mp_encoder.to_string()

    with notecard_helpers.temporary_mode(card, "continuous"):
        rsp, response_payload = notecard_helpers.web_post(
            card,
            "SavvyAnalysis",
             payload,
             name=f"{aircraft_id}/",
             chunk_size=chunk_size,
             content=mp_encoder.content_type
        )

        if rsp.get("result") != 200:
            logging.warning("Transaction error posting to SavvyAnalysis %s:  %s", rsp, response_payload)
        if response_payload:
            response_payload = json.loads(response_payload)
            if response_payload.get("status") == "Error":
                logging.warning("Error posting to SavvyAnalysis %s:  %s", rsp, response_payload)

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--savvy-aviation-aircraft-id")
    parser.add_argument("--savvy-aviation-token")
    parser.add_argument("--savvy-aviation-mode", default="native")
    parser.add_argument("--notehub-product")
    parser.add_argument("--notecard-port", default="/dev/i2c-1")
    parser.add_argument("--notecard-mode", default="i2c")

    parser.add_argument("files", nargs='*')
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s:%(levelname)s:%(name)s:%(message)s')

    if args.savvy_aviation_aircraft_id is None:
        parser.error("--savvy-aviation-aircraft-id must be provided")
    if args.savvy_aviation_token is None:
        parser.error("--savvy-aviation-token must be provided")

    nCard = None
    if args.savvy_aviation_mode == "notecard":
        logging.info("Connecting to notecard on port %s", args.notecard_port)
        if args.notecard_mode == "i2c":
            port = I2C(args.notecard_port)
            nCard = notecard.OpenI2C(port, 0, 0, debug=True)
        else:
            port = serial.Serial(args.notecard_port, 9600)
            nCard = notecard.OpenSerial(port)
        
        req = {"req": "card.version"}
        rsp = nCard.Transaction(req)
        logging.info("Found notecard %s", rsp)

        for f in args.files:
            with open(f, 'r', errors='ignore') as log:
                fname = os.path.basename(f)
                if args.savvy_aviation_mode == "native":
                    publish_flight_log_direct(
                        args.savvy_aviation_token,
                        args.savvy_aviation_aircraft_id,
                        fname,
                        log.read()
                    )
                else:
                    publish_flight_log_notecard(
                        nCard,
                        args.savvy_aviation_token,
                        args.savvy_aviation_aircraft_id,
                        fname,
                        log.read()
                    )
