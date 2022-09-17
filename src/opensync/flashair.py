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

try:
    import requests
except ImportError:
    import urequests as requests

import re
import logging
import datetime
import csv
import io

"""

list_files = 100
count_files = 101
memory_changed = 102
get_ssid = 104
get_password = 105
get_mac = 106
get_browser_lang = 107
get_fw_version = 108
get_ctrl_image = 109
get_wifi_mode = 110
free_space = 140

$ curl 'http://flashair.local/command.cgi?op=140'
31229504/31236096,512

Empty/Total,SectorSize

$ curl 'http://flashair.local/command.cgi?op=108'
F15DBW3BW4.00.03

$ curl 'http://flashair.local/command.cgi?op=100&DIR=/'
WLANSD_FILELIST
,airframe_info.xml,606,32,21809,25134
,data_log,0,16,21809,29857
,DCIM,0,16,21787,401

$ curl 'http://flashair.local/command.cgi?op=100&DIR=/data_log'
WLANSD_FILELIST
/data_log,log_220917_122052______.csv,16384,32,21809,25256
/data_log,log_220917_124302_KJYO.csv,1630208,32,21809,27564
/data_log,log_220917_143703_KHGR.csv,1277952,32,21809,31173

"""

class FlashAir(object):
    def __init__(self, baseurl="http://flashair.local"):
        self.baseurl = baseurl
    
    def version(self):
        r = requests.get(f"{self.baseurl}/command.cgi?op=108")
        if r.status_code != 200:
            raise RuntimeError("Failed to fetch version")

        return r.text

    def decodeAttributes(self, attributes):
        attributes = int(attributes)
        return {
            "isArchive": bool((attributes >> 5) & 0x1),
            "isDirectory": bool((attributes >> 4) & 0x1),
            "isVolume": bool((attributes >> 3) & 0x1),
            "isSystem": bool((attributes >> 2) & 0x1),
            "isHidden": bool((attributes >> 1) & 0x1), # hidden files don't seem to be returned by 'dir' without perhaps additional info
            "isReadOnly": bool((attributes >> 0) & 0x1),
        }

    def isDir(self, attributes):
        attrs = self.decodeAttributes(
            attributes
        )
        return attrs["isDirectory"]

    def isFile(self, attributes):
        attrs = self.decodeAttributes(
            attributes
        )
        return (attrs["isArchive"] and not attrs["isSystem"] and not attrs["isHidden"])
    
    def decode_time(self, date_val: int, time_val: int):
        year = (date_val >> 9) + 1980  # 0-val is the year 1980
        month = (date_val & (0b1111 << 5)) >> 5
        day = date_val & 0b11111
        hour = time_val >> 11
        minute = ((time_val >> 5) & 0b111111)
        second = (time_val & 0b11111) * 2
        try:
            decoded = datetime.datetime(year, month, day, hour, minute, second)
        except ValueError:
            year = max(1980, year)  # FAT32 doesn't go higher
            month = min(max(1, month), 12)
            day = max(1, day)
            decoded = datetime.datetime(year, month, day, hour, minute, second)
        return decoded

    def files(self, directory="/"):
        """
        Attributes is a bitfield

        isFile | isDirectory | isVolume | isSystem | isHidden | isReadONly

        date is packed integer representation, bits 15-9 are year, bits 8-5 month, bits 4-0 day
        time is same 15-11 hour, 10-5 minute, 4-0 second/2
        """
        _directory = directory.replace("/", "%2F")
        r = requests.get(f"{self.baseurl}/command.cgi?op=100&DIR={_directory}")
        if r.status_code != 200:
            raise RuntimeError("Failed to fetch directory list")

        if r.headers['Content-Type'] != "text/plain":
            raise RuntimeError("Received unexpected content-type %s", r.headers['Content-Type'])

        result = []
        reader = csv.reader(io.StringIO(r.text))
        for line in reader:
            if len(line) < 6:
                continue
            dname, fname, size_bytes, attributes, date, time, *_ = line
            created_at = self.decode_time(int(date), int(time))
            if self.isFile(attributes):
                url = f"{self.baseurl}{dname}/{fname}"
                result.append((f"{dname}/{fname}", fname, created_at, size_bytes))
        return result

    def dirs(self, directory="/"):
        _directory = directory.replace("/", "%2F")
        r = requests.get(f"{self.baseurl}/command.cgi?op=100&DIR={directory}")
        if r.status_code != 200:
            raise RuntimeError("Failed to fetch directory list %s" % r.text)

        if r.headers['Content-Type'] != "text/plain":
            raise RuntimeError("Received unexpected content-type %s", r.headers['Content-Type'])

        result = []
        reader = csv.reader(io.StringIO(r.text))
        for line in reader:
            if len(line) < 6:
                continue
            dir, fname, size, attributes, date, time, *_ = line
            if self.isDir(attributes):
                result.append(fname)

        return result

    def download(self, fname):
        r = requests.get(f"{self.baseurl}/{fname}", headers={"Accept": "*/*"})
        if r.status_code != 200:
            raise RuntimeError("Failed to download file")
        
        logging.info("Downloading %s: %s", fname, r.headers)
        return r.text