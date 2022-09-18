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

# System imports
import logging
import os
import re
import csv
import datetime
import time
import signal
import platform
import io
import sys
import zoneinfo
import pytz

# Pip installed imports
import requests
import pandas as pd
from tinydb import TinyDB, Query
from dateutil import tz
import serial
import notecard

# Local imports
from . import ezshare
from . import flashair
from . import g1000
from . import savvy
from . import notecard_helpers

# RaspberryPi Imports
try:
    import RPi.GPIO as GPIO
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(17, GPIO.IN)

    GPIO.setmode(GPIO.BCM)
    GPIO.setup(27, GPIO.IN)

    GPIO.setup(18, GPIO.OUT)
    GPIO.output(18, GPIO.LOW)

    from periphery import I2C
except ImportError:
    GPIO = None
    I2C = None
    EXTERNAL_POWER = True

def check_battery_available():
    # GPIO27 UPS is on-line pin 27 toggles every 0.5 seconds
    if GPIO is not None:
        timeout_at = time.time() + 1
        ups_status1 = GPIO.input(27)
        logging.info("Checking initial GPIO pin 27 %s", ups_status1)
        while time.time() < timeout_at:
            time.sleep(0.1)
            ups_status2 = GPIO.input(27)
            logging.info("Checking GPIO pin 27 %s", ups_status2)
            if (ups_status1 != ups_status2):
                logging.info("Detected UPS battery")
                return True
        return False
    else:
        return True

def external_power_available():
    # https://github.com/buyapi/ups/blob/master/scripts/ups.sh
    # GPIO17 0 - normal (or battery switched on manually) , 1 - power fault (switched to battery)
    
    if GPIO is not None:
        power_status = GPIO.input(17)
        logging.info("Checking GPIO pin 17 %s", power_status)
        return (power_status == 0)
    else:
        global EXTERNAL_POWER
        return EXTERNAL_POWER

def process_flight_log(cfg, db, fname, flight_log):
    logging.info("Processing flight log %s", fname)
    flight_log_metadata = re.match("log_(\d+)_(\d+)_(.*).csv", os.path.basename(fname))

    bfname = os.path.basename(fname)

    Q = Query()
    result = db.search((Q.type == "log") & (Q.fname == bfname))

    update = False
    if len(result) > 0:
        if cfg.get("force") == True:
            update = True
        else:
            logging.info("Already have processed %s", bfname)
            return

    airframe_info, flight_log_df = g1000.parse_flight_log(flight_log)
    
    dname = os.path.splitext(bfname)[0] + ".pkl"
    dpath = os.path.join(
        cfg["data_path"], 
        dname
    )

    if not flight_log_metadata:
        logging.warning("couldn't extract flight log metadata from file name %s", bfname)
        origin = "UNK"
    else:
        origin = flight_log_metadata.group(3)
    
    flight_log_summary = g1000.summarize_flight_log(flight_log_df)
    flight_log_summary['origin'] = origin
    flight_log_summary['airframe_info'] = airframe_info
    flight_log_summary['fname'] = bfname

    record = {
        'type': 'log',
        'fname': bfname,
        'datapath': dpath,
        'origin': origin,
        'flight_log_summary': flight_log_summary
    }
    
    if update == False:
        logging.info("Inserting record %s:", record)
        db.insert(record)
    else:
        logging.info("Updating record %s:", record)
        db.update(record, (Q.type == "log") & (Q.fname == bfname))
    flight_log_df.to_pickle(dpath)

    return flight_log_summary

def report_flight(nCard, record, flight_log, **kwargs):
    # Skip empty records
    if record is None:
        return

    # Skip reporting of zero hour flights
    if kwargs.get("report_zero_hour_flights", False) == False and record.get("hobbs_time", 0) < 0.05:
        logging.info("Skipping zero hour flight")
        return

    if nCard:    
        logging.info("Sending note %s", record)
        req = {"req": "note.add"}
        req["body"] = record
        rsp = nCard.Transaction(req)

    if kwargs.get("savvy_aviation_token"):
        if kwargs.get("savvy_full_log") is not True:
            logging.info("Pruning flight log")
            pruned_flight_log = io.StringIO()
            try:
                with io.StringIO(flight_log) as inf:
                    g1000.prune_flight_log(
                        inf,
                        pruned_flight_log
                    )

                savvy_flight_log = pruned_flight_log.getvalue()
            finally:
                pruned_flight_log.close()
        else:
            savvy_flight_log = flight_log

        if nCard:
            try:
                with notecard_helpers.temporary_mode(nCard, "continuous", timeout=kwargs.get("savvy_aviation_timeout")):
                    savvy.publish_flight_log_notecard(
                        nCard,
                        kwargs["savvy_aviation_token"],
                        kwargs["savvy_aviation_aircraft_id"],
                        record['fname'],
                        savvy_flight_log
                    )
            except RuntimeError:
                logging.exception("couldn't publish to savvy aviation")
        else:
            savvy.publish_flight_log_direct(
                kwargs["savvy_aviation_token"],
                kwargs["savvy_aviation_aircraft_id"],
                record['fname'],
                savvy_flight_log
            )

def opensync_g1000_file_process(db, nCard, **kwargs):
    #############################
    # Running in offline file processing mode, primarily useful for debugging
    if len(kwargs.get("files")) == 1 and os.path.isdir(kwargs.get("files")[0]):
        files = [ os.path.join(kwargs.get("files")[0], ff) for ff in os.listdir(kwargs.get("files")[0]) ]
    else:
        files = kwargs.get("files")

    for fpath in sorted(files, key=lambda x: os.path.basename(x)):
        if os.path.isfile(fpath):
            with open(fpath, errors="replace") as f:
                record = None
                flight_log = f.read()
                try:
                    record = process_flight_log(kwargs, db, fpath, flight_log)
                except (SystemExit, KeyboardInterrupt):
                    raise
                except:
                    logging.exception("Unexpected error processing flight log %s", fpath)
                # If a record was created and we are connected to a notecard,
                # send the message
                report_flight(nCard, record, flight_log, **kwargs)

def opensync_g1000_wifi_sdcard_process(db, nCard, **kwargs):
    #############################
    # Running in WiFi SDCard Mode

    # Check if a battery is available, if not then once the batteries are turned off
    # the OpenSync will immediately lose power and not process the flight until the
    # next power cycle
    battery_status = check_battery_available()
    if battery_status == False:
        logging.warning("No battery is available, files will not be processed on shutdown")

    # Variables used within the main loop
    pending_files = {}
    version = None
    external_power_lost_at = None
    shutdown = False
    next_check = datetime.datetime.now()
    sdcard = None

    # The main loop
    while (not shutdown):
        
        if datetime.datetime.now() > next_check:
            # Schedule the next check
            next_check = datetime.datetime.now() + datetime.timedelta(seconds=kwargs["poll_period"])

            # Check that the external power is available, if it's been turned off
            # for more than 1 minute then initiate the shutdown procedure
            if kwargs.get("enable_ups"):
                power_status = external_power_available()
                if power_status and external_power_lost_at is not None:
                    external_power_lost_at = None
                    logging.info("External power restored")
                elif not power_status and external_power_lost_at is None:
                    external_power_lost_at = datetime.datetime.now()
                    logging.info("External power lost")
                elif external_power_lost_at is not None and datetime.datetime.now() - external_power_lost_at > datetime.timedelta(seconds=10): # TODO make configurable via kwargs
                    logging.info("External power lost for too long, initiating shutdown")
                    shutdown = True
                    continue

            if nCard:
                # Check card connection status
                req = {"req": "hub.status"}
                rsp = nCard.Transaction(req)
                logging.debug("hub.status: %s", rsp)

                req = {"req": "hub.sync.status"}
                rsp = nCard.Transaction(req)
                logging.debug("hub.sync.status: %s", rsp)
                if rsp.get("sync") is True:
                    req = {"req": "hub.sync"}
                    rsp = nCard.Transaction(req)
                    logging.debug("hub.sync: %s", rsp)

                req = {"req": "card.wireless"}
                rsp = nCard.Transaction(req)
                logging.debug("card.wireless: %s", rsp)

                req = {"req": "card.voltage"}
                rsp = nCard.Transaction(req)
                logging.debug("card.voltage: %s", rsp)

                req = {"req": "card.motion"}
                rsp = nCard.Transaction(req)
                logging.debug("card.motion: %s", rsp)

                # Get card time
                logging.info("Requesting card time")
                req = {"req": "card.time"}
                rsp = nCard.Transaction(req)
                logging.debug("Obtained card time %s", rsp)
                if rsp.get("zone") in (None, "UTC,Unknown") or rsp.get("time") in (None, 0, ""):
                    logging.warning("Failed to obtain card time")
                else:
                    try:
                        zone = rsp["zone"].split(",", 1)[-1]
                        tz = tzinfo=zoneinfo.ZoneInfo(zone)

                        card_now = datetime.datetime.fromtimestamp(
                            rsp["time"],
                            tz
                        ).astimezone(pytz.UTC)


                        now = datetime.datetime.now().astimezone(pytz.UTC)
                        tdelta = abs(now - card_now)
                        logging.info("Card time %s System time %s Delta %s", card_now, now, tdelta)
                        if tdelta > datetime.timedelta(seconds=2):    
                            set_time = "sudo date -s '%s'" % card_now.strftime("%Y-%m-%d %H:%M:%S")
                            logging.debug("Setting time: %s", set_time)
                            os.system(set_time)
                    except:
                        logging.exception("Failed to set time")
    
                # Get card location
                logging.info("Requesting card location")
                req = {"req": "card.location"}
                rsp = nCard.Transaction(req)
                logging.debug("Obtained card location %s", rsp)

            if sdcard is None:
                if kwargs.get("wifi_sdcard") == "ezshare":
                    try:
                        sdcard = ezshare.EzShare(kwargs["ezshare_url"])
                        version = sdcard.version()
                        logging.info("Connected to ezShare card: %s", version)
                        data_log_path = "A:%5Cdata_log"
                    except requests.exceptions.ConnectionError:
                        logging.info("Waiting for connection to ezShare card")
                        sdcard = None
                elif kwargs.get("wifi_sdcard") == "flashair":
                    try:
                        sdcard = flashair.FlashAir(kwargs["flashair_url"])
                        version = sdcard.version()
                        logging.info("Connected to flashair card: %s", version)
                        data_log_path = "/data_log"
                        if version[9:11] != "W4":
                            logging.info("Using earlier version of FlashAir")
                    except requests.exceptions.ConnectionError:
                        logging.info("Waiting for connection to flashAir card")
                        sdcard = None
            
            if sdcard is None or data_log_path is None:
                continue

            # List all the files on the SD card
            try:
                files = sdcard.files(data_log_path)
                print(files)
            except requests.exceptions.ConnectionError:
                logging.info("Lost connection to sd card")
                version = None
                continue

            # Filter out to only include G1000 logss
            files = list(filter(
                lambda x: re.match("log_\d+_\d+_(.*).csv", x[1]) != None,
                files
            ))
            logging.info("Card has %s files on it, %s files pending", len(files), len(pending_files))
    
            # For each file currently on the SD card
            for download_fname, fname, created_at, filesize in files:
                # Check if it's in our local database and skip processing it
                # unless Force is true
                Q = Query()
                result = db.search((Q.type == "log") & (Q.fname == fname))
                if len(result) > 0 and kwargs.get("force") != True:
                    # The file is in the database and force isn't used, so skip the file
                    logging.debug("Already have processed %s", fname)
                else:
                    # The pending files list is a set of files that we have seen, but haven't yet
                    # processed.  If a file stays the same size for two checks then it gets processed
                    # otherwise it is downloaded (since the G1000 will get powered off at the end of the flight)
                    # and stored in pending files...in practice there should be at most one pending file that
                    # has been fully download
                    flight_log = None
                    if (pending_files.get(fname)) is None:
                        # If the file stays the same size it will get processed next check
                        pending_files[fname] = (filesize, None)
                        continue
                    elif (pending_files[fname][0] != filesize):
                        # If the file is changing then it's the currently active log file,
                        # download it so that when the batteries are turned off (thus cutting power
                        # to opensync) it can be processed
                        logging.info("Downloading %s %s", fname, download_fname)
                        try:
                            flight_log = sdcard.download(download_fname)
                        except requests.exceptions.ConnectionError:
                            logging.info("Lost connection to sd card")
                            version = None
                            break
                        pending_files[fname] = (filesize, flight_log)
                        logging.info("File %s current size %s", fname, filesize)   
                        continue
                    else:
                        # The file hasn't changed size, so it can be processed now
                        _, flight_log = pending_files.pop(fname)

                    # If the file hasn't been downloaded yet
                    if flight_log is None:
                        try:
                            flight_log = sdcard.download(download_fname)
                        except requests.exceptions.ConnectionError:
                            logging.info("Lost connection to sd card")
                            version = None
                            break
                        
                    logging.info("Processing %s at %s", fname, download_fname)
                    record = None
                    try:
                        record = process_flight_log(kwargs, db, fname, flight_log)
                    except:
                        logging.exception("Unexpected error processing flight log")

                    # If a record was created and we are connected to a notecard,
                    # send the message
                    report_flight(nCard, record, flight_log, **kwargs)

        # Sleep 1 second
        time.sleep(1)

    logging.info("Beginning shutdown process, processing %s pending files", len(pending_files))
    for fname, (_, flight_log) in pending_files.items():
        logging.info("Processing %s at %s", fname, short_fname)
        record = None
        try:
            record = process_flight_log(kwargs, db, fname, flight_log)
        except (SystemExit, KeyboardInterrupt):
            break
        except:
            logging.exception("Unexpected error processing flight log")

        # If a record was created and we are connected to a notecard,
        # send the message
        report_flight(nCard, record, flight_log, **kwargs)

def opensync_standalone_process(db, nCard, **kwargs):
    # Check if a battery is available, if not then once the batteries are turned off
    # the OpenSync will immediately lose power and not process the flight until the
    # next power cycle
    battery_status = check_battery_available()
    if battery_status == False:
        logging.warning("No battery is available, flights will not be reported on shutdown")

    # Variables used within the main loop
    version = None
    external_power_lost_at = None
    shutdown = False
    next_check = datetime.datetime.now()

    # The main loop
    while (not shutdown):
        
        if datetime.datetime.now() > next_check:
            # Schedule the next check
            next_check = datetime.datetime.now() + datetime.timedelta(seconds=kwargs["poll_period"])

            # Check that the external power is available, if it's been turned off
            # for more than 1 minute then initiate the shutdown procedure
            power_status = external_power_available()
            if power_status and external_power_lost_at is not None:
                external_power_lost_at = None
                logging.info("External power restored")
            elif not power_status and external_power_lost_at is None:
                external_power_lost_at = datetime.datetime.now()
                logging.info("External power lost")
            elif external_power_lost_at is not None and datetime.datetime.now() - external_power_lost_at > datetime.timedelta(minutes=1): # TODO make configurable via kwargs
                logging.info("External power lost for too long, initiating shutdown")
                shutdown = True

            if nCard:
                logging.info("Checking location")
                req = {"req": "card.location"}
                rsp = nCard.Transaction(req)
                logging.info("Location %s", rsp)

        # Sleep 1 second
        time.sleep(1)

    logging.info("Beginning shutdown process")
            
def opensync(**kwargs):
    # Create the data path which will store the flight metadata and a
    # pickle copy of the pandas flight logs
    if not os.path.exists(kwargs["data_path"]):
        logging.info("Creating data directory %s", kwargs["data_path"])
        os.makedirs(kwargs["data_path"])

    # The local database stores flight metadata
    dbpath = os.path.join(kwargs["data_path"], "opensync.json")
    db = TinyDB(dbpath)

    # Connect to NoteHub if requested
    nCard = None
    if kwargs.get("notecard_port") and not kwargs.get("disable_notecard"):
        logging.info("Connecting to notecard on port %s", kwargs.get("notecard_port"))
        if kwargs.get("notecard_mode") == "i2c" and I2C is not None:
            port = I2C(kwargs.get("notecard_port"))
            nCard = notecard.OpenI2C(port, 0, 0)
        else:
            port = serial.Serial(kwargs.get("notecard_port"), 9600)
            nCard = notecard.OpenSerial(port)

        # Log Notecard Version
        req = {"req": "card.version"}
        rsp = nCard.Transaction(req)
        logging.info("Found notecard %s", rsp)

        # Get environment variables and merge them into kwargs
        req = {"req": "env.get"}
        rsp = nCard.Transaction(req)
        logging.info("Found environment %s", rsp)
        for env_key, env_val in rsp.get("body", {}).items():
            if env_key.startswith("opensync_"):
                opensync_arg = env_key[9:]
                if kwargs.get(opensync_arg) is None:
                    logging.info("Setting %s = %s", env_key[9:], env_val)
                    kwargs[env_key[9:]] = env_val

        # Set periodic hub sync by default
        req = {"req": "hub.set"}
        req['mode'] = "periodic"
        if kwargs.get('product'):
            req['product'] = kwargs['product']
        logging.info("Setting periodic mode %s", rsp)
        rsp = nCard.Transaction(req)
        logging.info("Setting periodic mode %s => %s", req, rsp)

        # Log power-up
        req = {"req": "hub.log"}
        req["text"] = "Open Sync Has Started"
        rsp = nCard.Transaction(req)

        # Perform a sync now
        logging.info("Performing hub sync")
        req = {"req": "hub.sync"}
        req["sync"] = True
        rsp = nCard.Transaction(req)

        # Wait until the sync has been completed
        logging.info("Performed hub sync %s", rsp)
        while rsp.get("sync", False) is True:
            time.sleep(1)
            req = {"req": "hub.sync.status"}
            req["sync"] = False
            rsp = nCard.Transaction(req)
            logging.info("Status hub sync %s", rsp)
    
    # If GPS tracking is not disabled, establish it to be once per minute
    if kwargs.get("enable_tracking"):
        logging.info("Enabling GPS tracking")
        req = {"req": "card.location.mode"}
        req["mode"] = "periodic"
        req["seconds"] = 60
        rsp = nCard.Transaction(req)

        req = {"req": "card.location.track"}
        req["start"] = True
        rsp = nCard.Transaction(req)

        # TODO
        req = {"req": "card.motion.mode"}
        req["start"] = True
        req["seconds"] = 10
        req["sensitivity"] = 2
        nCard.Transaction(req)

        req = {"req": "card.motion.sync"}
        req["start"] = True
        req["minutes"] = 20
        req["count"] = 20
        req["threshold"] = 5
        nCard.Transaction(req)

    try:
        # There are three different ways that OpenSync can work:
        #   1. Direct access to G1000 log files, this is useful for testing
        #   2. Reading log files from an ezShare WiFi SD card
        #   3. Running only as a GPS tracker
        if kwargs.get("files"):
            # Process files provided on command-line
            opensync_g1000_file_process(db, nCard, **kwargs)
        elif kwargs.get("ezshare_url") and kwargs.get('wifi_sdcard') is not None:
            # Process files obtained from ezShare Wifi
            opensync_g1000_wifi_sdcard_process(db, nCard, **kwargs)
        else:
            # GPS only
            opensync_standalone_process(db, nCard, **kwargs)
    finally:
        # Syncronize any remaining notes on shutdown
        if nCard:
            logging.info("Performing hub sync")
            req = {"req": "hub.sync"}
            req["sync"] = True
            rsp = nCard.Transaction(req)

            logging.info("Performed hub sync %s", rsp)
            while rsp.get("sync", False) is True:
                time.sleep(1)
                req = {"req": "hub.sync.status"}
                req["sync"] = False
                rsp = nCard.Transaction(req)
                logging.info("Status hub sync %s", rsp)

def main():
    import configargparse

    parser = configargparse.ArgParser(
        default_config_files=[ "/etc/opensync.conf", f"{sys.prefix}/etc/opensync.conf", "~/.opensync.conf"]
    )
    parser.add_argument(
        "-c", "--config",
        is_config_file=True,
        help="path to configuration file"
    )
    parser.add_argument(
        "--product",
        help="set notehub product on startup"
    )
    parser.add_argument(
        "--data-path",
        default="~/.opensync",
        help="path to store database"
    )
    parser.add_argument(
        "--ezshare-url",
        default="http://ezshare.card",
        help="the url to connect to the ezShare card"
    )
    parser.add_argument(
        "--flashair-url",
        default="http://flashair.local",
        help="the url to connect to the flashAir card"
    )
    parser.add_argument(
        "--savvy-full-log",
        default=False,
        action="store_true",
        help="send full CSV log of unnecessary columns before upload to savvy"
    )
    parser.add_argument(
        "--force",
        default=False,
        action="store_true",
        help="force processing of a file"
    )
    parser.add_argument(
        "--poll-period",
        default=10,
        type=int,
        help="the data polling period"
    )
    parser.add_argument(
        "--report-zero-hour-flights",
        default=False,
        action="store_true",
        help="report zero hours flights"
    )
    parser.add_argument(
        "--wifi-sdcard",
        default=None,
        help="WiFi SD card type: (flashair, ezshare)"
    )
    parser.add_argument(
        "--enable-shutdown",
        default=False,
        action="store_true",
        help="send exit code 255 to tell systemctl to shutdown"
    )
    parser.add_argument(
        "--enable-ups",
        default=False,
        action="store_true",
        help="enable use of ups"
    )
    parser.add_argument(
        "--enable-tracking",
        default=False,
        action="store_true",
        help="enable GPS tracking"
    )
    parser.add_argument(
        "--disable-notecard",
        default=False,
        action="store_true"
    )
    parser.add_argument(
        "--notecard-port",
        default="/dev/i2c-1"
    )
    parser.add_argument(
        "--notecard-mode",
        default="i2c"
    )
    parser.add_argument(
        "--savvy-aviation-aircraft-id"
    )
    parser.add_argument(
        "--savvy-aviation-token"
    )
    parser.add_argument(
        "--savvy-aviation-timeout",
        default=120,
        help="connection timeout for making savvy avaition publish"
    )
    parser.add_argument(
        "files",
        nargs='*',
        help="one or more files to process in offline mode"
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG)

    if GPIO is not None:
        # Nothing special in RaspberryPi mode
        logging.info("Running in RaspberryPi mode")
    elif platform.uname().system == "Windows":
        # In Windows mode we just assume EXTERNAL_POWER is always available
        logging.info("Running in Windows mode")
        EXTERNAL_POWER = True
    else:
        # In Linux mode, sending SIGUSR1 will simulate the EXTERNAL_POWER being removed
        logging.info("Running in Linux mode")
        EXTERNAL_POWER = True
        def simulate_external_power_loss(*args, **kwargs):
            global EXTERNAL_POWER
            logging.info("Received simulated external power signal")
            EXTERNAL_POWER = not EXTERNAL_POWER
        signal.signal(signal.SIGUSR1, simulate_external_power_loss)

    # Set the data_path to an absolute path 
    args.data_path = os.path.abspath(
        os.path.normpath(os.path.expandvars(os.path.expanduser(args.data_path)))
    )

    # Start the opensync daemon
    try:
        logging.info("Starting opensync %s", vars(args))
        opensync(**vars(args))
        logging.info("Checking enable shutdown %s", args.enable_shutdown)
        if args.enable_shutdown:
            logging.info("Requesting shutdown with exit code 255")
            return 255
    except (SystemExit, KeyboardInterrupt):
        pass
    
    logging.info("Skipping shutdown request, exiting normally")
    return 0

if __name__ == "__main__":
    sys.exit(main())