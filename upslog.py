#!/usr/bin/python3

import argparse
import re
import psycopg2
import subprocess

class Common(object):
    def __init__(self, verbose=False, debug=False):
        self.verbose = verbose or debug
        self.debug   = debug

    def message(self, content, debug=False):
        if self.debug:
            print(content)
        elif self.verbose and not debug:
            print (content)

class UPS (Common):
    re_set     = {
        'date'           : re.compile('^DATE     \: (.*)$'),
        'status'         : re.compile('^STATUS   \: (.*)$'),
        'line_voltage'   : re.compile('^LINEV    \: (.*) Volts$'),
        'load_percent'   : re.compile('^LOADPCT  \: (.*) Percent$'),
        'batt_percent'   : re.compile('^BCHARGE  \: (.*) Percent$'),
        'batt_time'      : re.compile('^TIMELEFT \: (.*) Minutes$'),
        'batt_volts'     : re.compile('^BATTV    \: (.*) Volts$'),
        'xfer_reason'    : re.compile('^LASTXFER \: (.*)$'),
        'on_batt'        : re.compile('^XONBATT  \: (.*)$'),
        'off_batt'       : re.compile('^XOFFBATT \: (.*)$'),
        'load_max_watts' : re.compile('^NOMPOWER \: (.*) Watts$')
    }

    def __init__(self, clientpath='/usr/bin/apcaccess', encoding='utf-8', verbose=False, debug=False):
        self.verbose = verbose or debug
        self.debug   = debug

        self.clientpath = clientpath
        self.encoding   = encoding

        self.message("Created UPS device object.", debug=True)
        
    def parse(self, result):
        parsed = {}
        for line in result.split('\n'):
            for key in self.re_set:
                match = self.re_set[key].match(line)
                if match:
                    parsed[key] = match.group(1).strip()
        return parsed

    def get_data(self):
        result = subprocess.run(self.clientpath, capture_output=True)
        returnval = self.parse(result.stdout.decode(self.encoding))
        self.message("Got this data: %s" % (returnval))
        return returnval

class UPSDatabase (Common):
    create_steps = [
        "CREATE SEQUENCE IF NOT EXISTS status_v2_seq",
        "CREATE SEQUENCE IF NOT EXISTS reason_v2_seq",
        "CREATE TABLE IF NOT EXISTS status_v2 (status_id INTEGER PRIMARY KEY NOT NULL DEFAULT NEXTVAL('status_v2_seq'), status TEXT UNIQUE NOT NULL)",
        "CREATE TABLE IF NOT EXISTS reason_v2 (reason_id INTEGER PRIMARY KEY NOT NULL DEFAULT NEXTVAL('reason_v2_seq'), reason TEXT UNIQUE NOT NULL)",
        "CREATE TABLE IF NOT EXISTS upslog_v2 (timestamp TIMESTAMP WITH TIME ZONE PRIMARY KEY NOT NULL, status_id INTEGER REFERENCES status_v2(status_id), linevoltage FLOAT, battvoltage FLOAT, load FLOAT, batterysoc FLOAT, timeleft FLOAT, onbatt BOOLEAN)",
        "CREATE TABLE IF NOT EXISTS transfer_v2 (timestamp TIMESTAMP WITH TIME ZONE PRIMARY KEY NOT NULL, to_batt BOOLEAN, reason_id INTEGER REFERENCES reason_v2(reason_id))"
    ]

    drop_steps = [
        "DROP TABLE IF EXISTS transfer_v2",
        "DROP TABLE IF EXISTS upslob_v2",
        "DROP TABLE IF EXISTS reason_v2",
        "DROP TABLE IF EXISTS status_v2",
        "DROP SEQUENCE IF EXISTS reason_v2_seq",
        "DROP SEQUENCE IF EXISTS status_v2_seq"
    ]

    get_status_id_select = "SELECT status_id FROM status_v2 WHERE status = %s"
    get_status_id_insert = "INSERT INTO status_v2(status) VALUES (%s)"
    get_status_id_curval = "SELECT CURRVAL('status_v2_seq')"
    
    get_reason_id_select = "SELECT reason_id FROM reason_v2 WHERE reason = %s"
    get_reason_id_insert = "INSERT INTO reason_v2(reason) VALUES (%s)"
    get_reason_id_curval = "SELECT CURRVAL('reason_v2_seq')"

    update_transfer_select = "SELECT to_batt, reason_id FROM transfer_v2 WHERE timestamp = (SELECT MAX(timestamp) FROM transfer_v2)"
    update_transfer_insert = "INSERT INTO transfer_v2 (timestamp, to_batt, reason_id) values (%s, %s, %s)"

    insert_observation_select = "SELECT timestamp FROM upslog_v2 WHERE timestamp=%s"
    insert_observation_insert = "INSERT INTO upslog_v2 (timestamp, status_id, linevoltage, battvoltage, load, batterysoc, timeleft, onbatt) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
    
    def __init__(self, dsn, create=True, drop=False, reset=False, verbose=False, debug=False):
        self.dsn       = dsn
        self.verbose   = verbose or debug
        self.debug     = debug

        self.connected = False
        self.dbi       = None

        self.drop      = drop or reset
        self.create    = create or reset

        self.connect_if_possible()

        if self.connected and self.drop:
            self.drop_table()
        if self.connected and self.create:
            self.create_table()

    def connect_if_possible(self):
        if not self.connected:
            self.message("Not connected.  Trying to connect. to %s" % (self.dsn,), debug=True)
            try:
                self.dbi       = psycopg2.connect(self.dsn)
                self.connected = True
                self.message("Now connected.", debug=True)
            except:
                self.connected = False
                self.message("Nope, that failed.", debug=True)

    def drop_table(self):
        cursor = self.dbi.cursor()
        for command in self.drop_steps:
            cursor.execute(command)
            self.dbi.commit()

    def create_table(self):
        cursor = self.dbi.cursor()
        for command in self.create_steps:
            cursor.execute(command)
            self.dbi.commit()

    def get_status_id(self, status):
        cursor = self.dbi.cursor()
        cursor.execute(self.get_status_id_select, (status,))
        result = cursor.fetchone()
        if result is None:
            cursor.execute(self.get_status_id_insert, (status,))
            cursor.execute(self.get_status_id_curval)
            result = cursor.fetchone()
        return result[0]

    def get_reason_id(self, reason):
        cursor = self.dbi.cursor()
        cursor.execute(self.get_reason_id_select, (reason,))
        result = cursor.fetchone()
        if result is None:
            cursor.execute(self.get_reason_id_insert, (reason,))
            cursor.execute(self.get_reason_id_curval)
            result = cursor.fetchone()
        return result[0]

    def update_transfer(self, timestamp, to_batt, reason=None):
        cursor = self.dbi.cursor()
        cursor.execute (self.update_transfer_select, (timestamp,))
        result = cursor.fetchone()
        if result is None:
            last_to_batt   = None
            last_reason_id = None
        else:
            last_to_batt, last_reason_id = result
        if reason is not None:
            reason_id = self.get_reason_id(reason)

        if not (last_to_batt == to_batt and last_reason_id == reason_id):
            self.message("Inserting transfer.", debug=True)
            cursor.execute(self.update_transfer_insert, (timestamp, to_batt, reason_id))
            self.dbi.commit()
        else:
            self.message("Already had that transfer.", debug=True)
    def insert_observation(self, timestamp, status, linevoltage, battvoltage, load, batterysoc, timeleft, onbatt):
        cursor = self.dbi.cursor()
        cursor.execute(self.insert_observation_select, (timestamp,))
        result = cursor.fetchone()
        if result is None:
            status_id = self.get_status_id(status)
            cursor.execute(self.insert_observation_insert, (timestamp, status_id, linevoltage, battvoltage, load, batterysoc, timeleft, onbatt))
            self.message("Inserted observation.", debug=True)
            self.dbi.commit()
        else:
            self.message("Already had that observation.", debug=True)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", help="Verbose output",   action="store_true"                                                         )
    parser.add_argument("-D", "--debug",   help="Debugging output", action="store_true"                                                         )
    parser.add_argument("-d", "--dsn",     help="Database string",    type=str, default="dbname=upslog_v2 user=upslog password=upslog host=cana")
    #parser.add_argument("-l", "--loop",    help="Loop with interval", type=float                                                                )
    args = parser.parse_args()

    database = UPSDatabase(args.dsn, verbose=args.verbose, debug=args.debug)
    device   = UPS(verbose=args.verbose, debug=args.debug)
    status   = device.get_data()

    database.insert_observation(timestamp=status['date'],
                                status=status['status'], linevoltage=status['line_voltage'],
                                battvoltage=status['batt_volts'],
                                load=float(status['load_percent'])*float(status['load_max_watts'])/100.0,
                                batterysoc=status['batt_percent'],
                                timeleft=float(status['batt_time']),
                                onbatt=status['status']!='ONLINE')
    database.update_transfer(timestamp=status['date'],
                             to_batt=status['status']!='ONLINE', reason=status['xfer_reason'])
if __name__ == "__main__":
    main()
    
