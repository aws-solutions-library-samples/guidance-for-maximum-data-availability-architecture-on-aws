#! /usr/bin/python3
# Started by systemd as rananeeti_tx_cache.service
import rananeeti_dp
import signal
import sys, time

def signal_handler(sig, frame):
    print('Exiting, new Orders will NOT be processed!')
    sys.exit(0)

# This is to exit the loop with "kill -SIGINT"
signal.signal(signal.SIGINT, signal_handler)

while True:

 try:
   rananeeti_dp.bulkprocesstxqueue()
 except Exception as e:
   print(f"... General error {repr(e)}")

 #print(f"... sleeping for {rananeeti_dp.qsleepsec} seconds")
 time.sleep(rananeeti_dp.qsleepsec)

