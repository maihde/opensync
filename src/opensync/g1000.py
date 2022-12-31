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

import pandas as pd
import numpy as np
import datetime
import logging
import math
from io import StringIO
import os
try:
    from neobase import NeoBase, OPTD_POR_URL
    mydir=os.path.dirname(__file__)
    paths_to_check = (
        os.path.join(mydir, "../../dat/optd_por_public_all.csv"),
        os.path.expanduser("~/OpenSync/dat/optd_por_public_all.csv"),
    )
    for airport_db in paths_to_check:
        if os.path.exists(airport_db):
            with open(airport_db, encoding="utf-8") as f:
                NeoBase.KEY = 1 # icao_code
                geo_a = NeoBase(f)
                break
    else:
        logging.debug("couldn't find airport database")
    
except ImportError:
    logging.debug("cannot lookup airports without neobase")
    geo_a = None

if geo_a is None:
    logging.warning("cannot lookup airports without neobase and airport database")

def coerce_float(v):
    try:
        return float(v)
    except ValueError:
        return None

def coerce_date(v):
    try:
        return datetime.datetime.strptime(v, "%Y-%m-%d")
    except ValueError:
        return None

def coerce_time(v):
    try:
        return datetime.datetime.strptime(v, "%H:%M:%S")
    except ValueError:
        return None

def coerce_tzinfo(v):
    try:
        if v == "+00:00":
            return datetime.timezone.utc
        else:
            hours, minutes = v.split(":")
            hours = int(hours)
            minutes = int(minutes)
            return datetime.timezone(datetime.timedelta(hours=hours, minutes=minutes))
    except ValueError:
        return None

def table_format(v):
    try:
        return "%0.2f" % v
    except TypeError:
        return str(v)

G1000_TYPES = {
    'yyy-mm-dd': coerce_date,
    'hh:mm:ss': coerce_time,
    'hh:mm': coerce_tzinfo,
    'degrees': coerce_float, # lat/lon
    'ft Baro': coerce_float,
    'inch': coerce_float,
    'ft msl': coerce_float,
    'deg C': coerce_float,
    'kt': coerce_float,
    'fpm': coerce_float,
    'deg': coerce_float, # angle
    'G':  coerce_float,
    'volts': coerce_float,
    'amps': coerce_float,
    'gals': coerce_float,
    'gph': coerce_float,
    'deg F': coerce_float,
    'psi': coerce_float,
    'Hg': coerce_float,
    'rpm': coerce_float, 
    '%': coerce_float,
    'ft wgs': str,
    'MHz': coerce_float,
    'fsd': str,
    'nm': coerce_float,
    'bool': bool,
    'mt': str,
}

def iter_parse_flight_log(flight_log_lines, flight_log_types, flight_log_fields):
    try:
        time_fields = (
            flight_log_fields.index('Lcl Date'),
            flight_log_fields.index('Lcl Time'),
            flight_log_fields.index('UTCOfst')
        )
    except ValueError:
        time_fields = None

    # Next lines are CSV values
    for ll in  flight_log_lines:
        data_record = []
        for ii, vv in enumerate( ll.split(",") ):
            field_type = flight_log_types[ii]
            field_name = flight_log_fields[ii]
            field_coerce = G1000_TYPES.get(field_type, str)
            data_record.append( field_coerce(vv.strip()) )

        # only report full data records
        if len(data_record) == len(flight_log_fields):
            if time_fields:
                # Join the date and utc offset into the time record
                # so that you can use that column by itself, otherwise
                # Lcl Time will use the date from the system clock
                data_record[time_fields[1]] = datetime.datetime.combine(
                    data_record[time_fields[0]].date(),
                    data_record[time_fields[1]].time(),
                    data_record[time_fields[2]],
                )

            yield data_record

def parse_flight_log(flight_log):
    # The first line is the airframe info
    lines = [ x.strip() for x in flight_log.split("\n") ]
    if not lines[0].startswith('#airframe_info, log_version="1.00"'):
        raise RuntimeError("unsupported flight log format")

    airframe_info = {}
    for airframe_field in lines[0].split(","):
        try:
            field_name, field_value = airframe_field.split("=")
        except ValueError:
            continue
        if field_value[0] == '"' and field_value[-1] == '"':
            field_value = field_value[1:-1]
        airframe_info[field_name] = field_value

    # Next two lines are field types and field names
    flight_log = []
    types = [ x.strip("#").strip() for x in lines[1].split(",") ]
    fields = [ x.strip() for x in lines[2].split(",") ]

    data = pd.DataFrame.from_records(
        iter_parse_flight_log(lines[3:], types, fields),
        columns = fields
    )
    logging.info("loaded airframe info %s", airframe_info)
    logging.info("loaded flight log with %s data points", len(data))
    
    return airframe_info, data

def summarize_flight_log(flight_log_df):
    summary = {}

    summary['beg_time'] = datetime.datetime.combine(
        flight_log_df.iloc[0]['Lcl Date'].date(),
        flight_log_df.iloc[0]['Lcl Time'].time(),
        flight_log_df.iloc[0]['UTCOfst']
    ).isoformat()

    summary['end_time'] = datetime.datetime.combine(
        flight_log_df.iloc[-1]['Lcl Date'].date(),
        flight_log_df.iloc[-1]['Lcl Time'].time(),
        flight_log_df.iloc[-1]['UTCOfst']
    ).isoformat()

    # Only include lines where the GPS has locked, this has the side-effect
    # of also ensure most of the other sensor values are stablized
    flight_log_df.dropna(subset = ['Latitude', 'Longitude'], inplace=True)
    flight_log_df.reset_index(drop=True, inplace=True)

    if len(flight_log_df) == 0:
        return summary

    # Fuel Summary
    # Use rolling average to smooth out the noise
    total_fuel_rolling = (flight_log_df['FQtyL'] + flight_log_df['FQtyR']).rolling(15, min_periods=1, center=True).median()
    
    # TODO if fuel read-outs are constantly adjusting due to turns
    # and such, see if we can find some smoothing filter
    summary['max_fuel'] = total_fuel_rolling[30:60].max()
    summary['min_fuel'] = total_fuel_rolling[-15:].min()
    summary['fuel_remaining'] = summary['min_fuel']

    # Trapizodal integration over the data
    try:
        summary['fuel_consumed'] = 0
        fuel_flow = flight_log_df[['Lcl Time', 'E1 FFlow']].dropna()
        summary['fuel_consumed'] = np.trapz(y=fuel_flow['E1 FFlow'], x=fuel_flow['Lcl Time'].astype('int64')) / (3600 * 10**9)
    except:
        logging.exception("error calculating fuel consumed")
        summary['fuel_consumed'] = summary['max_fuel'] - summary['min_fuel']

    # Engine Summary
    summary['max_cht'] = [ flight_log_df[f'E1 CHT{ii}'].max() for ii in range(1,7) ]
    summary['max_egt'] = [ flight_log_df[f'E1 EGT{ii}'].max() for ii in range(1,7) ]
    summary['max_tit'] = [ flight_log_df[f'E1 TIT{ii}'].max() for ii in range(1,3) ]
    summary['max_oil_temp'] = flight_log_df['E1 OilT'].max()
    summary['max_oil_pressure'] = flight_log_df['E1 OilP'].max()
    summary['max_manifold_pressure'] = flight_log_df['E1 MAP'].max()
    summary['max_rpm'] = flight_log_df['E1 RPM'].max()

    # Performance Summary
    summary['max_ias'] = flight_log_df[f'IAS'].max()
    summary['max_tas'] = flight_log_df[f'TAS'].max()
    summary['max_lat_accel'] = flight_log_df[f'LatAc'].max()
    summary['max_norm_accel'] = flight_log_df[f'NormAc'].max()

    # Battery Summary
    summary['min_bat1_volts'] = flight_log_df['volt1'].min()
    summary['min_bat2_volts'] = flight_log_df['volt2'].min()
    summary['max_bat1_amps'] = flight_log_df['amp1'].max()
    
    # Estimate flight time and Hobbs Time
    # POH states flight time is accumulated whenever KIAS > 35KTS
    start_hobbs = None
    end_hobbs = None
    total_hobbs_time = datetime.timedelta(hours=0, minutes=0)
    for ii, rpm in enumerate(flight_log_df['E1 RPM']):
        if rpm > 0.0 and start_hobbs is None:
            start_hobbs = datetime.datetime.combine(
                flight_log_df.iloc[ii]['Lcl Date'].date(),
                flight_log_df.iloc[ii]['Lcl Time'].time(),
                flight_log_df.iloc[ii]['UTCOfst']
            )
            end_hobbs = None
        elif rpm <= 0.0 and start_hobbs is not None:
            end_hobbs = datetime.datetime.combine(
                flight_log_df.iloc[ii]['Lcl Date'].date(),
                flight_log_df.iloc[ii]['Lcl Time'].time(),
                flight_log_df.iloc[ii]['UTCOfst']
            )
            hobbs_time = end_hobbs - start_hobbs
            total_hobbs_time += hobbs_time
            start_hobbs = None
            end_hobbs = None

    if start_hobbs is not None and end_hobbs is None:
        end_hobbs = datetime.datetime.combine(
            flight_log_df.iloc[-1]['Lcl Date'].date(),
            flight_log_df.iloc[-1]['Lcl Time'].time(),
            flight_log_df.iloc[-1]['UTCOfst']
        )
        hobbs_time = end_hobbs - start_hobbs
        total_hobbs_time += hobbs_time

    hobbs_hours = (total_hobbs_time.days * 24) + int(float(total_hobbs_time.seconds) / 3600)
    hobbs_fractional_hours = math.ceil((float(total_hobbs_time.seconds % 3600) / 360)) * 0.1
    summary['hobbs_time'] = hobbs_hours + hobbs_fractional_hours

    start_flight = None
    end_flight = None
    total_flight_time = datetime.timedelta(hours=0, minutes=0)
    for ii, kias in enumerate(flight_log_df['IAS']):
        if kias > 35 and start_flight is None:
            start_flight = datetime.datetime.combine(
                flight_log_df.iloc[ii]['Lcl Date'].date(),
                flight_log_df.iloc[ii]['Lcl Time'].time(),
                flight_log_df.iloc[ii]['UTCOfst']
            )
            end_flight = None
        elif kias < 35 and start_flight is not None:
            end_flight = datetime.datetime.combine(
                flight_log_df.iloc[ii]['Lcl Date'].date(),
                flight_log_df.iloc[ii]['Lcl Time'].time(),
                flight_log_df.iloc[ii]['UTCOfst']
            )
            flight_time = end_flight - start_flight
            total_flight_time += flight_time

            start_flight = None
            end_flight = None

    if start_flight is not None and end_flight is None:
        end_flight = datetime.datetime.combine(
            flight_log_df.iloc[-1]['Lcl Date'].date(),
            flight_log_df.iloc[-1]['Lcl Time'].time(),
            flight_log_df.iloc[-1]['UTCOfst']
        )
        flight_time = end_flight - start_flight
        total_flight_time += flight_time

    flight_hours = (total_flight_time.days * 24) + int(float(total_flight_time.seconds) / 3600)
    flight_fractional_hours = math.ceil((float(total_flight_time.seconds % 3600) / 360)) * 0.1
    summary['flight_time'] = flight_hours + flight_fractional_hours

    # Locations
    ii = flight_log_df['Latitude'].first_valid_index()
    if ii is not None:
        summary['origin_pos'] = {
            'lat': flight_log_df.iloc[ii]['Latitude'],
            'lon': flight_log_df.iloc[ii]['Longitude'],
        }

    ii = flight_log_df['Latitude'].last_valid_index()
    if ii is not None:
        summary['destination_pos'] = {
            'lat': flight_log_df.iloc[ii]['Latitude'],
            'lon': flight_log_df.iloc[ii]['Longitude'],
        }

    if (summary.get('origin_pos') is not None) and (geo_a is not None):
        point = summary["origin_pos"]["lat"], summary["origin_pos"]["lon"]
        origin_airports = [k for (_, k) in sorted(geo_a.find_near_location(point, 10), key=lambda x: x[0]) ]
        if origin_airports:
            summary["origin"] = origin_airports[0]

    if (summary.get('destination_pos') is not None) and (geo_a is not None):
        point = summary["destination_pos"]["lat"], summary["destination_pos"]["lon"]
        destination_airports = [k for (_, k) in sorted(geo_a.find_near_location(point, 10), key=lambda x: x[0]) ]
        if destination_airports:
            summary["destination"] = destination_airports[0]
    else:
        logging.info("Not looking up destination airport")

    return summary

DEFAULT_KEEP_COLUMNS = (
    "Lcl Date",
    "Lcl Time",
    "OAT",
    "AltMSL",
    "FQtyL", 
    "FQtyR",
    "E1 FFLow",
    "E1 OilT",
    "E1 OilP",
    "E1 MAP",
    "E1 RPM", 
    "E1 %Pwr",
    "E1 CHT1",
    "E1 CHT2",
    "E1 CHT3",
    "E1 CHT4",
    "E1 CHT5",
    "E1 CHT6",
    "E1 EGT1",
    "E1 EGT2",
    "E1 EGT3",
    "E1 EGT4",
    "E1 EGT5",
    "E1 EGT6",
    "E1 TIT1",
    "E1 TIT2",
    "volt1",
    "volt2",
    "amp1",
)
def prune_flight_log(flight_log, output, keep_columns=DEFAULT_KEEP_COLUMNS):
    for ii, ll in enumerate(flight_log):
        # The first line is the airframe info
        if ii == 0:
            output.write(ll)
        elif ii == 1:
            types = [ x.strip() for x in ll.split(",") ]
        elif ii == 2:
            fields = [ x.strip() for x in ll.split(",") ]

            keep_idx = []
            for idx, field in enumerate(fields):
                if field in keep_columns:
                    keep_idx.append(idx)             

            row = [ types[idx] for idx in keep_idx]
            output.write(",".join(row))
            output.write("\n")

            row = [ fields[idx] for idx in keep_idx]
            output.write(",".join(row))
            output.write("\n")
        else:
            row = [ x.strip() for x in ll.split(",") ]
            # the end of a flight log is sometimes only a partial line
            # because the MFD got turned off in the middle
            if len(fields) != len(row):
                continue
            row = [ row[idx] for idx in keep_idx]
            output.write(",".join(row))
            output.write("\n")

def to_elasticsearch(flight_log_df):
    for record in flight_log_df.to_dict(orient='records'):
        record['@timestamp'] = datetime.datetime.combine(
            record['Lcl Date'].date(),
            record['Lcl Time'].time(),
            record['UTCOfst']
        ).isoformat()

        record['Lcl Date'] = str(record['Lcl Date'])
        record['Lcl Time'] = str(record['Lcl Time'])
        record['UTCOfst'] = str(record['UTCOfst'])

        if record['Latitude'] and record['Longitude']:
            if not (math.isnan(record['Latitude']) or math.isnan(record['Longitude'])):
                record['geo.point'] = {
                    "lat": record['Latitude'],
                    "lon": record['Longitude'],
                }

        yield record
        

OPENSYNC_MAPPING = {
    "mappings": {
        "properties": {
            "@timestamp": { "type": "date"},
            "AfcsOn": { "type": "boolean"},
            "AltB": { "type": "float"},
            "AltGPS": { "type": "float"},
            "AltMSL": { "type": "float"},
            "AtvWpt": { "type": "keyword"},
            "BaroA": { "type": "float"},
            "COM1": { "type": "float"},
            "COM2": { "type": "float"},
            "CRS": { "type": "float"},
            "E1 %Pwr": { "type": "float"},
            "E1 CHT1": { "type": "float"},
            "E1 CHT2": { "type": "float"},
            "E1 CHT3": { "type": "float"},
            "E1 CHT4": { "type": "float"},
            "E1 CHT5": { "type": "float"},
            "E1 CHT6": { "type": "float"},
            "E1 EGT1": { "type": "float"},
            "E1 EGT2": { "type": "float"},
            "E1 EGT3": { "type": "float"},
            "E1 EGT4": { "type": "float"},
            "E1 EGT5": { "type": "float"},
            "E1 EGT6": { "type": "float"},
            "E1 FFlow": { "type": "float"},
            "E1 MAP": { "type": "float"},
            "E1 OilP": { "type": "float"},
            "E1 OilT": { "type": "float"},
            "E1 RPM": { "type": "float"},
            "E1 TIT1": { "type": "float"},
            "E1 TIT2": { "type": "float"},
            "filename": { "type": "keyword"},
            "FQtyL": { "type": "float"},
            "FQtyR": { "type": "float"},
            "GPSfix": { "type": "keyword"},
            "GndSpd": { "type": "float"},
            "HAL": { "type": "long"},
            "HCDI": { "type": "float"},
            "HDG": { "type": "float"},
            "HPLfd": { "type": "float"},
            "HPLwas": { "type": "float"},
            "HSIS": { "type": "keyword"},
            "IAS": { "type": "float"},
            "LatAc": { "type": "float"},
            "Lcl Date": { "type": "keyword"},
            "Lcl Time": { "type": "keyword"},
            "Latitude": { "type": "float"},
            "Longitude": { "type": "float"},
            "MagVar": { "type": "float"},
            "NAV1": { "type": "float"},
            "NAV2": { "type": "float"},
            "NormAc": { "type": "float"},
            "OAT": { "type": "float"},
            "PichC": { "type": "float"},
            "Pitch": { "type": "float"},
            "PitchM": { "type": "keyword"},
            "Roll": { "type": "float"},
            "RollC": { "type": "float"},
            "RollM": { "type": "keyword"},
            "TAS": { "type": "float"},
            "TRK": { "type": "float"},
            "UTCOfst": { "type": "keyword"},
            "VAL": { "type": "float"},
            "VCDI": { "type": "float"},
            "VPLwas": { "type": "float"},
            "VSpd": { "type": "float"},
            "VSpdG": { "type": "float"},
            "WndDr": { "type": "float"},
            "WndSpd": { "type": "float"},
            "WptBrg": { "type": "float"},
            "WptDst": { "type": "float"},
            "amp1": { "type": "float"},
            "geo.point": { "type": "geo_point"},
            "volt1": { "type": "float"},
            "volt2": { "type": "float"},           
        }
    }
}

if __name__ == "__main__":
    import argparse
    import os
    import json
    import math
    import time
    from prettytable import PrettyTable

    parser = argparse.ArgumentParser()
    parser.add_argument("--opensearch")
    parser.add_argument('--fields', action='append', nargs='*', default=[])
    parser.add_argument("--prune", default=None)
    parser.add_argument("files", nargs='*')
    args = parser.parse_args()

    if args.opensearch:
        from opensearchpy import OpenSearch, helpers
        OS = OpenSearch(args.opensearch)
        if not OS.indices.exists(index="opensync"):
            OS.indices.create(index="opensync", body=OPENSYNC_MAPPING)

    logging.basicConfig(level=logging.INFO)
    if len(args.files) == 1 and os.path.isdir(args.files[0]):
        files = [ os.path.join(args.files[0], ff) for ff in os.listdir(args.files[0]) ]
    else:
        files = args.files

    table = PrettyTable()
    if not args.fields:
        args.fields = [ "date", "origin", "destination", "hobbs_time", "flight_time", "max_fuel", "min_fuel", "fuel_consumed", "fuel_remaining" ]
    table.field_names = args.fields

    for ff in sorted(files, key=lambda x: os.path.basename(x)):
        if os.path.isfile(ff):
            if args.prune:
                 with open(args.prune, "w") as prune_out:
                     with open(ff, errors="replace") as flight_log:
                        prune_flight_log(flight_log, prune_out)
            else:
                with open(ff, errors="replace") as flight_log:
                    try:
                        airframe_info, flight_log = parse_flight_log(flight_log.read())
                        print()
                        if args.opensearch:
                            # Delete previous records to avoid inserting duplicate
                            OS.delete_by_query(index="opensync", body={"query": {"term": {"filename": os.path.basename(ff) } } })

                            docs = []
                            for doc in to_elasticsearch(flight_log):
                                for f in list(doc.keys()):
                                    if (isinstance(doc[f], float) and math.isnan(doc[f])) or doc[f] is None:
                                        del doc[f]
                                # TODO convert to bulkd
                                doc['filename'] = os.path.basename(ff)
                                docs.append(doc)
                            helpers.bulk(OS, docs, index='opensync')
                            time.sleep(1) # rate limit
                            #print(doc)
                            #OS.index(index="opensync", body=json.dumps(doc))
                        else:
                            summary = summarize_flight_log(flight_log)
                            if "date"in args.fields and summary.get("beg_time"):
                                summary["date"] = summary["beg_time"][0:10]
                            if summary.get("hobbs_time", 0) > 0.01:
                                print(summary)
                                table.add_row([ table_format(summary.get(xx, "")) for xx in args.fields ])

                    except (SystemExit, KeyboardInterrupt):
                        raise
                    except:
                        logging.exception("Unexpected error processing flight log %s", ff)
                print(table)