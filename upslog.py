#!/usr/bin/python3

import argparse
import re
import psycopg2
import subprocess
import time

class Common(object):

    """Class Common is a carrier for utility functions to be used by other classes in this library."""

    def __init__(self, verbose=False, debug=False):
        self.verbose = verbose or debug
        self.debug   = debug

    def message(self, content, debug=False):

        """Common.message is an instance class that takes a message to be
presented (content) and an optional parameter to indicate if this is a
debugging message (debug).  Setting debug=True will cause the message
only to be presented if self.debug is also True.  Messages where
debug=False (which is the default) will be presented when
verbose=True.

        """

        if self.debug:
            print(content)
        elif self.verbose and not debug:
            print (content)

class UPS (Common):
    """class UPS is an interface to the apcaccess utility.  It is designed
to call that and parse the response"""

    #re_set is a collection of regexes used to parse the results
    #returned by apcaccess.  It's placed in a dict so that we can
    #simply apply the regex, and if it matches, the dict key tells us
    #what we got.  The useful response will always be in group(1) of
    #the resulting regex match object.
    
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
        """Initializes the UPS object.  Generally speaking, this will be just
called as default, but you can point the object to call a the client
at a diffferent path.  This was developed on Debian, and should work
on Ubuntu, Mint, and so on.  Other distros may place this at a
different path."""
        
        self.verbose = verbose or debug
        self.debug   = debug

        self.clientpath = clientpath
        self.encoding   = encoding

        self.message("Created UPS device object.", debug=True)
        
    def parse(self, result):
        """UPS.parse() is takes a string containing the response from
apcaccess and returns a dict with the results.  It uses. self.re_set
to find the relevant data and match it up with its purpose.

        """
        parsed = {}
        for line in result.split('\n'):
            for key in self.re_set:
                match = self.re_set[key].match(line)
                if match:
                    parsed[key] = match.group(1).strip()
        return parsed

    def get_data(self):
        """UPS.get_data() calls apcaccess, sends the response through
UPS.parse() to conver it to a dict, then returns this.

        """
        result = subprocess.run(self.clientpath, capture_output=True)
        returnval = self.parse(result.stdout.decode(self.encoding))
        self.message("Got this data: %s" % (returnval))
        return returnval

class UPSDatabase (Common):
    """UPSDatabase implements the database schema to store the log"""

    #create_steps contains the steps to create the schema in the
    #database.
    create_steps = [
        "CREATE SEQUENCE IF NOT EXISTS status_v2_seq",
        "CREATE SEQUENCE IF NOT EXISTS reason_v2_seq",
        "CREATE TABLE IF NOT EXISTS status_v2 (status_id INTEGER PRIMARY KEY NOT NULL DEFAULT NEXTVAL('status_v2_seq'), status TEXT UNIQUE NOT NULL)",
        "CREATE TABLE IF NOT EXISTS reason_v2 (reason_id INTEGER PRIMARY KEY NOT NULL DEFAULT NEXTVAL('reason_v2_seq'), reason TEXT UNIQUE NOT NULL)",
        "CREATE TABLE IF NOT EXISTS upslog_v2 (timestamp TIMESTAMP WITH TIME ZONE PRIMARY KEY NOT NULL, status_id INTEGER REFERENCES status_v2(status_id), linevoltage FLOAT, battvoltage FLOAT, load FLOAT, batterysoc FLOAT, timeleft FLOAT, onbatt BOOLEAN)",
        "CREATE TABLE IF NOT EXISTS transfer_v2 (timestamp TIMESTAMP WITH TIME ZONE PRIMARY KEY NOT NULL, to_batt BOOLEAN, reason_id INTEGER REFERENCES reason_v2(reason_id))"
    ]

    #drop_steps contains the steps to drop all of the objects that
    #this library uses in the database.
    drop_steps = [
        "DROP TABLE IF EXISTS transfer_v2",
        "DROP TABLE IF EXISTS upslob_v2",
        "DROP TABLE IF EXISTS reason_v2",
        "DROP TABLE IF EXISTS status_v2",
        "DROP SEQUENCE IF EXISTS reason_v2_seq",
        "DROP SEQUENCE IF EXISTS status_v2_seq"
    ]

    #get_status_id_* are used to normalize the status codes from the
    #UPS.  _select is used to check if a given status already exists
    #in the table, and retrieves its ide if so.  _insert adds a value
    #to the table.  _currval is used to retirev the ID of a
    #freshly-inserted row.
    get_status_id_select = "SELECT status_id FROM status_v2 WHERE status = %s"
    get_status_id_insert = "INSERT INTO status_v2(status) VALUES (%s)"
    get_status_id_curval = "SELECT CURRVAL('status_v2_seq')"
    
    #get_reason_id_* are used to normalize the reason codes from the
    #UPS.  _select is used to check if a given reason already exists
    #in the table, and retrieves its ide if so.  _insert adds a value
    #to the table.  _currval is used to retirev the ID of a
    #freshly-inserted row.
    get_reason_id_select = "SELECT reason_id FROM reason_v2 WHERE reason = %s"
    get_reason_id_insert = "INSERT INTO reason_v2(reason) VALUES (%s)"
    get_reason_id_curval = "SELECT CURRVAL('reason_v2_seq')"

    #update_transfer_* are used to manage records in the transfer_v2
    #table.  _select is used to determine if there is already a
    #relevant record; _insert is used to insert a record if not.
    update_transfer_select = "SELECT to_batt, reason_id FROM transfer_v2 WHERE timestamp = (SELECT MAX(timestamp) FROM transfer_v2)"
    update_transfer_insert = "INSERT INTO transfer_v2 (timestamp, to_batt, reason_id) values (%s, %s, %s)"

    #update_observation_* are used to manage records in the upslog_v2
    #table.  _select is used to determine if there is already a
    #relevant record; _insert is used to insert a record if not.
    insert_observation_select = "SELECT timestamp FROM upslog_v2 WHERE timestamp=%s"
    insert_observation_insert = "INSERT INTO upslog_v2 (timestamp, status_id, linevoltage, battvoltage, load, batterysoc, timeleft, onbatt) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
    
    def __init__(self, dsn, create=True, drop=False, reset=False, verbose=False, debug=False):
        """Initializes the UPSDatabase object.  Requires a dsn (must be
PostgreSQL for the time being; other databases may be implemented at a
later date).  If create is set to True (default), then any database
object needed will be created.  If drop is True, they will be deleted.
If reset is True, they will be dropped, then created, and this is
equivalent to setting create=True and drop=True."""
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
        """UPSDatabase.connect_if_possible() will attempt to connect to the
database.  If it succeeds, it will set self.connect to True."""
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
        """UPSDatabase.drop_table() will drop all of the DB objects used by this
library."""
        cursor = self.dbi.cursor()
        for command in self.drop_steps:
            cursor.execute(command)
            self.dbi.commit()

    def create_table(self):
        """UPSDatabase.create_table() will create all of the DB object used by
this library"""
        cursor = self.dbi.cursor()
        for command in self.create_steps:
            cursor.execute(command)
            self.dbi.commit()

    def get_status_id(self, status):
        """UPSDatabase.get_status_id() takes a status code and returns a
numeric representation for the same.  It attempts at first to locate
it in the database, and if it doesn't succeed, it will insert it and
return a new numeric id for that code.

        """
        cursor = self.dbi.cursor()
        cursor.execute(self.get_status_id_select, (status,))
        result = cursor.fetchone()
        if result is None:
            cursor.execute(self.get_status_id_insert, (status,))
            cursor.execute(self.get_status_id_curval)
            result = cursor.fetchone()
        return result[0]

    def get_reason_id(self, reason):
        """UPSDatabase.get_status_id() takes a reason description and returns
a numeric representation for the same.  It attempts at first to locate
it in the database, and if it doesn't succeed, it will insert it and
return a new numeric id for that description.

        """
        cursor = self.dbi.cursor()
        cursor.execute(self.get_reason_id_select, (reason,))
        result = cursor.fetchone()
        if result is None:
            cursor.execute(self.get_reason_id_insert, (reason,))
            cursor.execute(self.get_reason_id_curval)
            result = cursor.fetchone()
        return result[0]

    def update_transfer(self, timestamp, to_batt, reason=None):
        """UPSDatabase.update_transfer takes a timestamp, a boolean indicator
of whether the transfer was to the battery (True) or back to line
(False), and an optional reason.  If the timestamp and to_batt value
are the same as the most recent record in the transfer_v2 table, then
the method does nothing further; otherwise it will insert a new row to
the database.

        """
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
        """UPSDatabase.insert_obsservation() takes set of parameters
representing an observation of the UPS status, checks the database to
see if such an observation already exists, and if not, inserts a new
one."""
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
    parser.add_argument("-l", "--loop",    help="Loop with interval", type=float                                                                )
    args = parser.parse_args()

    database = UPSDatabase(args.dsn, verbose=args.verbose, debug=args.debug)
    device   = UPS(verbose=args.verbose, debug=args.debug)

    done = False
    
    while not done:

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

        if args.loop is None:
            done=True
        else:
            time.sleep(args.loop)
            
if __name__ == "__main__":
    main()
