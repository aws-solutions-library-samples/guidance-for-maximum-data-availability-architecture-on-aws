"""
This is Rananeeti Data Platform module to import into Flask App.
It recieves the Engine and POST data from the outer App.
"""

# https://docs.sqlalchemy.org/en/20/core/connections.html
import sqlalchemy as db
from sqlalchemy.exc import SQLAlchemyError, InvalidRequestError, \
 DisconnectionError, OperationalError, IntegrityError, InvalidatePoolError
import time
import random
import json
import os
import boto3

PGHOST=os.environ['PGHOST']
PGDATABASE="cafedb"
PGUSER="cafeapp"
PGSCHEMA="cafe"
# TODO: Replace with IAM / Password manager
PGPASS=os.environ['PGPASSWORD']
SQLALCHEMY_DATABASE_URI=f"postgresql://{PGUSER}:{PGPASS}@{PGHOST}/{PGDATABASE}"
# print(f"... DB Conn: {SQLALCHEMY_DATABASE_URI}")
DDBGBLTBL = 'cafeordrsglbl'
orddir = "/var/www/html/orders"
ddb = boto3.client('dynamodb')
ddb1fetchsz = 50 # Max DDB records to fetch at once
# Defining the Engine - only one for whole program, with single pool.
# Hence, it is at the top of the module and not in "def", so it can be
# executed on import by Gunicorn or Batc or Batch, only once. The Connection Pool will stay.
engine = db.create_engine(SQLALCHEMY_DATABASE_URI, \
 #https://stackoverflow.com/questions/15685861/setting-application-name-on-postgres-sqlalchemy
 # https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-CONNECT-TIMEOUT
 connect_args={"application_name":"rananeeti_data_platform",
  "connect_timeout":"5"}, # fail fast without exceeding Apache Proxy wait etc
 echo=True, echo_pool=True, \
 # docs.sqlalchemy.org/en/20/core/pooling.html#pool-disconnects-pessimistic
 # Using Pessimistic Disconnect Handling to test the connection at check-out.
 # We could do Optimistic Disconnect Handling, but it uses Pool.recreate method,
 # and I want to control the Engine directly, doing it from my own code and
 # not relying on SQL Alchemy embedded QueuePool logic
 pool_pre_ping=True, pool_recycle=1800)
statement = db.text("""INSERT INTO cafe.ordersraw
 (ordrdgst, ordrname, ordrppl, ordrdttm, ordrtxt) VALUES
 (:p_ordrdgst, :p_ordrname, :p_ordrppl, :p_ordrdttm, :p_ordrtxt)""")

#############################################################
# Batch processing of queued transactions
#############################################################
# Run with systemd as "rananeeti_tx_cache.service" 
# 1/ Use "scan" DDB API to fetch "ddb1fetchsz" cached TXs
# 2/ loop through them, inserting row by raw into Aurora
#    On the first SQL error quit the whole program - wait to Aurora to fix itlself 
#    If succeeded, leave the record in the Order log page
# 3/ Remove from DDB all completed orders, one by one, in a loop
# 4/ Sleep for "qsleepsec" and repeat from 1/
qsleepsec = 10
def bulkprocesstxqueue():
 br="<br>\n" # So it looks good in the page source code too 
 s1b = "<span class='w3-tag w3-gray w3-text-white'>"
 s1e = "</span>"
 try:
    r = ddb.scan(TableName=DDBGBLTBL, Limit=ddb1fetchsz)
    # hash key: r['Items'][_x_]['ordrdgst']['S']
    # json parameters data for SQL: 
    # json.loads(r['Items'][_x_]['ordrdata']['S'])

    for iorder in r['Items']:
      ordrdgst = iorder['ordrdgst']['S']
      # Clearing the template for this file
      bulkhtml = """<div class="w3-card w3-green w3-center"> 
        <p><b>RANANEETI</b> Data Platform - <b>Transactions Queue Code</b></p> </div>"""
      print(f"\n*********\n... processing Order {ordrdgst}")
      try:
        data  = json.loads(iorder['ordrdata']['S'])
        consql = engine.connect()  
        consql.execute(statement, data) 
        # not committing yet
        bulktxres = True
        bulkhtml += f"{s1b}{time.time()}{s1e} " 
        bulkhtml += f" Success!{br} Order <b>{ordrdgst}</b> completed after fetching from the queue{br} \
         <div class=\"w3-card w3-green w3-center\"> <p>The End.</p> </div>"+br
        rcolor = "w3-green"
      except IntegrityError as k:
        # Most probably order with this digest already exists
        print(f"... ignored duplicated order {ordrdgst}")
        bulktxres = False
        bulkhtml += f"{s1b}{time.time()}{s1e} "
        bulkhtml += f"Your order <b>{ordrdgst}</b> has been placed before \
         <div class=\"w3-card w3-yellow w3-center\"> <p>Order ignored.</p> </div>"+br         
        rcolor = "w3-yellow"
      except Exception as serr: # All SQL erros
       print(f"... SQL error {repr(serr)}- order {ordrdgst}")
       return False 
      # Finalising the Order Log file
      ordfile = f"{orddir}/{ordrdgst}.html" 
      # Open with Append!
      try:
        with open(ordfile, 'a', encoding="utf-8") as ofl: 
          ofl.write(bulkhtml)
        # Now we can commit the DB record
        consql.commit()
        # And remove this order from DDB cache, as very last step
        ddb.delete_item( # TODO: handle this errot
         TableName=DDBGBLTBL,
         Key={
            'ordrdgst': {'S': ordrdgst}
         })
        print(f"... deleted processed order {ordrdgst}")
      except Exception as ferr: # All file write issues
          print(f"... Final processing error {repr(ferr)}- order {ordrdgst}")
          consql.rollback() # No point in entering Order if we can't inform user

 except Exception as derr: # All other DDB erros
    print(f"... DDB scan error: {repr(derr)}")
    return False
 return True

#############################################################
# Non-relational Transaction Caching part
#############################################################
# Using the client interface, so I can utilise DynamoDB JSON format, with types
# docs.aws.amazon.com/amazondynamodb/latest/developerguide/programming-with-python.html
# Using Global table, to avoid conflicts we write only in single region, default is "us-west-1"
# see file "cafedb.sql"
# docs.aws.amazon.com/amazondynamodb/latest/developerguide/V2globaltables.tutorial.html#V2creategt_cli
# docs.aws.amazon.com/amazondynamodb/latest/developerguide/HowItWorks.API.html

def cachefailedorder(ordrdgst, ordrdata):
   ddbouthtml = "<div class=\"w3-card w3-green w3-center\"> \
    <p><b>RANANEETI</b> Data Platform - <b>Backend Code</b></p> </div>"
   br="<br>\n" # So it looks good in the page source code too 
   s1b = "<span class='w3-tag w3-gray w3-text-white'>"
   s1e = "</span>"
   ddbouthtml += f"{s1b}{time.time()}{s1e} Caching order in DDB"+br 
   try:
       ddb.put_item(
        TableName=DDBGBLTBL,
        Item={
            'ordrdgst': {'S': ordrdgst},
            'ordrdata': {'S': json.dumps(ordrdata)}
        }
       )
       ddbouthtml += f"{s1b}{time.time()}{s1e} "
       ddbouthtml += f"Order placed in the queue. We will process it soon {br}"
       ddbouthtml += """<div class="w3-panel w3-leftbar w3-light-grey">
          <p><i>Please refresh this page periodically for updates.  </i></p>
        </div>"""
       ddbouthtml += " <div class=\"w3-card w3-green w3-center\"> "
       ddbouthtml += " <p>To Be Continued ...</p> </div>"+br
   except:
       ddbouthtml += f"{s1b}{time.time()}{s1e} " 
       ddbouthtml += f" Your order <u>completely</u> failed. Sorry.{br} " 
       ddbouthtml +=  "<div class=\"w3-card w3-red w3-center\">"
       ddbouthtml += " <p>The End.</p> </div>"+br
   return ddbouthtml

#############################################################
# Relational Part
#############################################################

# This will be called by App
def addorder(ordrdgst, ordrname, ordrppl, ordrdttm, ordrtxt, faildb):
    # The generic insert statement. We use SQL Alchemy Core only, closest to DBAPI
    startts = time.time()
    txres = True # Transaction entered real-time

    # Define data to bind
    data = (
     { "p_ordrdgst": ordrdgst,
       "p_ordrname": ordrname,
       "p_ordrppl": ordrppl,
       "p_ordrdttm": ordrdttm,
       "p_ordrtxt": ordrtxt},
    )

    outhtml = "<hr>" # All output to add to this string and return back to template
    br="<br>\n" # So it looks good in the page source code too
    s1b = "<span class='w3-tag w3-gray w3-text-white'>"
    s1e = "</span>"
    random.seed()

    # End user should not wait for more than 7 seconds.
    # Therefore, we attempt only twice and then go with Plan B,
    # placing the transaction in queue and processing it asynchronously,
    # providing updates on Order status page.
    # For this reason, I didn't implement the DB code below as single
    # unit, running in a loop - I want to have guaranteed wait time and
    # can't afford too many iterations.

    # Attempt 1 of 2
    try:
        # Faults emulation code
        if faildb and random.choice([True, False]):
           raise Exception("Other DB error - emulated")
        connection1 = engine.connect()
        outhtml += f"{s1b}{time.time()}{s1e} Attempt 1: "+br
        connection1.execute(statement, data)
        connection1.commit()
        outhtml += f"{s1b}{time.time()}{s1e} "
        outhtml += f" Success!{br} Transaction completed from 1st attempt in {str(round(time.time()-startts,2))} sec.{br} \
         <div class=\"w3-card w3-green w3-center\"> <p>The End.</p> </div>"+br
        txres = True
        try:
         connection1.close()
        except:
         pass
        return (txres, outhtml) # No further processing required
      # https://docs.sqlalchemy.org/en/20/core/exceptions.html
    except IntegrityError as k:
        # Most probably order with this digest already exists
        outhtml += f"{s1b}{time.time()}{s1e} "
        outhtml += "Your order has been placed before. \
         <div class=\"w3-card w3-yellow w3-center\"> <p>Order ignored.</p> </div>"+br         
        txres = False
        try:
         connection1.close()
        except:
         pass
        return (txres, outhtml)
    except DisconnectionError as e:
        # Pool may try to reconnect 3 times
        er1 = str(e.__dict__['orig'])
        outhtml += f"... got disconnect error: {er1},{br} ... waiting 1 sec"+br
        time.sleep(1) # Magic numbers are justidifed as part of fixed 7 sec max wait
    except (InvalidRequestError, OperationalError) as fatale:
        # Time to repeat this transaction with fresh connection
        er2 = str(fatale.__dict__['orig'])
        outhtml += f"{s1b}{time.time()}{s1e} "
        outhtml += f"... got first fatal DB error: {er2},{br} ... waiting 6 sec and reconnecting new pool"+br
        time.sleep(3)
        # https://docs.sqlalchemy.org/en/20/core/connections.html#sqlalchemy.engine.Engine.dispose
        # Just dereferencing, without closing, so "dispose"may be executed concurrently by many sessions.
        engine.dispose(close=False)
        outhtml += f"{s1b}{time.time()}{s1e} "
        outhtml += "... recreating new DB pool"+br
        # This will _not_ lead to the "login storm" since SQLAlchemy pool does _not_ pre-create DB connections
        # https://docs.sqlalchemy.org/en/20/core/pooling.html
        time.sleep(3)
    except: # All other Attempt 1 exceptions
        outhtml += f"{s1b}{time.time()}{s1e} "
        outhtml += f" Attempt 1: other DB error{br}"

    random.seed()
    # Attempt 2 of 2
    # This "with engine.connect() as connection2:" will _not_ work since it will not catch pool creation / checkout errors
    try:
        # Faults emulation code
        if faildb and random.choice([True, False]):
           raise Exception("Other DB error - emulated")
        connection2 = engine.connect()
        outhtml += f"{s1b}{time.time()}{s1e} Attempt 2: "+br
        connection2.execute(statement, data)
        connection2.commit()
        outhtml += f"{s1b}{time.time()}{s1e} "
        outhtml += f" Success!{br} Transaction completed from 2nd attempt in {str(round(time.time()-startts,2))} sec.{br} <div class=\"w3-card w3-green w3-center\"> <p>The End.</p> </div>"+br         
        txres = True
        try:
         connection2.close()
        except:
         pass
        return (txres, outhtml)
    except IntegrityError as k:
        # Most probably order with this digest already exists
        outhtml += f"{s1b}{time.time()}{s1e} "
        outhtml += "Your order has been placed before. \
         <div class=\"w3-card w3-yellow w3-center\"> <p>Order ignored.</p> </div>"+br         
        txres = False
        try:
         connection2.close()
        except:
         pass
        return (txres, outhtml)
    except (InvalidRequestError, OperationalError) as fatale2:
        er2 = str(fatale2.__dict__['orig'])
        outhtml += f"{s1b}{time.time()}{s1e} "
        outhtml += f"... got second fatal DB error: {er2},{br} \
         <div class=\"w3-card w3-red w3-center\"> <p>Order will be rerouted and delayed...</p> </div>"+br         
        engine.dispose(close=False)
        txres = False
        try:
         connection2.close()
        except:
         pass
        ##########
        # DDB actions call 
        ##########
        outhtml += cachefailedorder(ordrdgst, data)
    except: # All other Attempt 2 exceptions
        txres = False
        outhtml += f"{s1b}{time.time()}{s1e} "
        outhtml += f" Attempt 2: other DB error{br}"
        outhtml += f"... got second fatal DB error{br} \
         <div class=\"w3-card w3-red w3-center\"> <p>Order will be rerouted and delayed...</p> </div>"+br         
        ##########
        # DDB actions call
        ##########
        outhtml += cachefailedorder(ordrdgst, data)

    return (txres, outhtml)

