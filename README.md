# UPSLog 2

Utility for logging APC UPS status to a PostgreSQL database in Linux

## What?

This module repeatedly calls the apcaccess utility on a Linux host,
parses the response, and records it in a PostgreSQL database.

## Why?

Amongst other things, this gives you the ability to track trends in
power quality, server power utilization, battery charge state, etc.

## How?

Nothing actually stops you from invoking this module as a library and
calling the individual methods, however, this is not the intended use
case.  The intended use case is to call it as a script.

### Setup

You will need three things:

 * APC UPS connected to your host
 * apcupsd package installed and configured to your liking
 * PostgreSQL installed and configured to your liking

#### UPS

You will need an APC UPS, it will need to be communicating with your
server, and you should be able to get a status report by typing
apcaccess on the command line.  You should get a response like this:

    phreakiture@Cana:~$ apcaccess 
    APC      : 001,038,0966
    DATE     : 2022-06-27 19:11:08 -0400  
    HOSTNAME : Cana
    VERSION  : 3.14.14 (31 May 2016) debian
    UPSNAME  : Cana
    CABLE    : USB Cable
    DRIVER   : USB UPS Driver
    UPSMODE  : Stand Alone
    STARTTIME: 2022-06-26 09:06:38 -0400  
    MODEL    : Back-UPS LS 500 
    STATUS   : ONLINE 
    LINEV    : 119.0 Volts
    LOADPCT  : 17.0 Percent
    BCHARGE  : 100.0 Percent
    TIMELEFT : 30.6 Minutes
    MBATTCHG : 50 Percent
    MINTIMEL : 10 Minutes
    MAXTIME  : 0 Seconds
    SENSE    : Low
    LOTRANS  : 106.0 Volts
    HITRANS  : 133.0 Volts
    ALARMDEL : 30 Seconds
    BATTV    : 13.9 Volts
    LASTXFER : Automatic or explicit self test
    NUMXFERS : 1
    XONBATT  : 2022-06-26 17:07:02 -0400  
    TONBATT  : 0 Seconds
    CUMONBATT: 9 Seconds
    XOFFBATT : 2022-06-26 17:07:11 -0400  
    LASTSTEST: 2022-06-26 17:07:02 -0400  
    SELFTEST : NO
    STATFLAG : 0x05000008
    SERIALNO : 3B0737X46718  
    BATTDATE : 2021-07-20
    NOMINV   : 120 Volts
    NOMBATTV : 12.0 Volts
    NOMPOWER : 315 Watts
    FIRMWARE : 16.b6 .D USB FW:b6 
    END APC  : 2022-06-27 19:12:04 -0400  
    phreakiture@Cana:~$ 

#### PostgreSQL

You will need:

 * PostgreSQL.  This was developed on version 14.4, however, it should
   work on older versions.

 * Psycopg2.  This is the PostgreSQL module for Python.

Psycopg2 will need to be built against the version of PostgreSQL you
are using, however, if you install these both via your distributiion's
package manager to install them both, they should line up.

You will need to create a role in PostgreSQL for the logger.  By
default, the username and password for this role are upslog.  You will
also need to create an empty database owned by that role.

You can set these up like this from the postgres user:

    postgres@Cana:~$ psql 
    psql (14.4)
    Type "help" for help.

    postgres=# CREATE USER upslog WITH ENCRYPTED PASSWORD 'upslog';
    CREATE ROLE
    postgres=# CREATE DATABASE upslog_v2 WITH OWNER upslog; 
    CREATE DATABASE
    postgres=# EXIT;

### Running it

You can run this task as any user.  There are two approaches to
running it: looped or one-shot.

In one-shot mode, the module will capture a sample of data, determine
if it needs to be logged, and if so, log it.  To do this, simply call
the module.

In loop mode, it will repeat the process at regular intervals.  This
is more efficient, because it avoids the costs of starting,
connectiong and cleaning up repeatedly.  To do this, call the module
with the loop option (-l or --loop) and give it a looping interval (in
seconds).

There are options to get verbose output (-v or --verbose) and to get
debugging output (-D or --debug).  There is also an option to
designate a non-default database (-d or --dsn followed by a psycopg2
DSN).

## Workings

### Theory

On each loop (or each call in one-shot mode) the module will:

 * Get the status from the UPS by calling apcaccess
 * Parse the output from apcaccess and sort it into a dictionary
 * Determine if it needs to insert any records, and insert them.

The reason_v2 and status_v2 tables are used to normalize repeating
strings.  Each string is unique and is assigned an ID number.  The ID
numbers are dynamically assigned, so are not guaranteed to be the same
on every instance.

The transfer_v2 table lists every time the power is transferred either to or from battery power.  It contains:

 * the timestamp of a transfer
 * a boolean (to_batt) which is true if the transfer was from line to battery and false for transfers from battery to line
 * a reason code that refers to the reason_v2 table.

A record is only inserted if it is different from the most recent one.

The upslog_v2 table lists all of the observations, consisting of

 * the timestamp of the observation
 * a status code, which refers to the status_v2 table
 * line voltage
 * battery voltage
 * current load (watts)
 * battery state of charge (percent)
 * expected life of the battery (minutes)
 * whether we are currently on battery

A record is only inserted if it has a different timestamp than the most recent one.

## To Do:

 * Create a utility to import data from the older version of this logger (the database schema has changed)
 * Create a utility to generate reports
