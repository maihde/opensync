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

try:
    from bs4 import BeautifulSoup
except ImportError:
    # likely in a micropython environment
    BeautifulSoup = None


class EzShare(object):
    def __init__(self, baseurl="http://ezshare.card"):
        self.baseurl = baseurl
    
    def version(self):
        r = requests.get(f"{self.baseurl}/client?command=version")
        if r.status_code != 200:
            raise RuntimeError("Failed to fetch version")

        soup = BeautifulSoup(r.text, 'html.parser') # use HTML parser because it's more lienent 
        try:
            return soup.response.device.version.string
        except AttributeError:
            logging.error("Unexpected error processing response %s %s", r.text, soup)
            return None

    def files(self, directory="A:"):
        _directory = directory.replace("/", "%5C") # '/' needs to be replaced with %5C for ezShare to work correctly
        r = requests.get(f"{self.baseurl}/dir?dir={_directory}")
        if r.status_code != 200:
            raise RuntimeError("Failed to fetch directory list")

        if r.headers['Content-Type'] != "text/html;":
            raise RuntimeError("Received unexpected content-type %s", r.headers['Content-Type'])

        if r.encoding != "ISO-8859-1":
            raise RuntimeError("Received unexpected encoding %s", r.encoding)

        soup = BeautifulSoup(r.text, 'html.parser')
        
        #if soup.title.string != f"Index of {directory}":
        #    logging.warning("Unexpected title in directory list: %s", soup.title.string)

        result = []
        for a in soup.find_all('a'):
            if a.previousSibling == None:
                continue
            metadata_match = re.match("(\d{4})-( \d{1}|\d{2})-( \d{1}|\d{2})\s+( \d{1}|\d{2}):( \d{1}|\d{2}):( \d{1}|\d{2})\s+(\d+)KB", a.previousSibling.string.strip())
            fmatch = re.match("http://.+/download\?file=(.+)", a.get('href'))
            if metadata_match and fmatch:
                created_at = datetime.datetime(
                    int(metadata_match.group(1)),
                    int(metadata_match.group(2)),
                    int(metadata_match.group(3)),
                    int(metadata_match.group(4)),
                    int(metadata_match.group(5)),
                    int(metadata_match.group(6)),
                )
                size_kb = int(metadata_match.group(7))
                result.append((fmatch.group(1), a.string.strip(), created_at, size_kb))

        return result

    def dirs(self, directory="A:"):
        r = requests.get(f"{self.baseurl}/dir?dir={directory}")
        if r.status_code != 200:
            raise RuntimeError("Failed to fetch directory list")

        if r.headers['Content-Type'] != "text/html;":
            raise RuntimeError("Received unexpected content-type")

        if r.encoding != "ISO-8859-1":
            raise RuntimeError("Received unexpected encoding")

        soup = BeautifulSoup(r.text, 'html.parser')
        
        if soup.title.string != f"Index of {directory}":
            logging.warning("Unexpected title in directory list: %s", soup.title.string)

        result = []
        for a in soup.find_all('a'):
            if re.match("dir\?dir=.+", a.get('href')):
                result.append((self.baseurl + "/" + a.get('href'), a.string.strip()))

        return result

    def download(self, short_fname):
        r = requests.get(f"{self.baseurl}/download?file={short_fname}")
        if r.status_code != 200:
            raise RuntimeError("Failed to download file")
        
        logging.info("Downloading %s: %s", short_fname, r.headers)
        return r.text


        

