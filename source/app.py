from markupsafe import escape
from hashlib import blake2b
from urllib.parse import urlparse
import base64,json # Decoding ID Token
from flask import Flask,render_template,redirect,request,url_for,session
from oauthlib.oauth2 import WebApplicationClient
from oauthlib.oauth2.rfc6749.errors import CustomOAuth2Error
import requests # Python's, not Flask! To POST token request.
import rananeeti_dp
import excludefromgit # No secrets in code repositories!
import os # We terminate TLS at ELB, so I need to set Env Var

app = Flask(__name__)
# https://flask.palletsprojects.com/en/3.0.x/deploying/proxy_fix/
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(
    app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1
)

app.secret_key = excludefromgit.nogit_secret_key # Sign cookies for sessions

# Set these values from the Linkedin app you created
CONSUMER_KEY = excludefromgit.NOGIT_CONSUMER_KEY
CONSUMER_SECRET = excludefromgit.NOGIT_CONSUMER_SECRET
# Constants
LIN_STATE_LEN = 80

# We terminate TLS at ELB, so I need to set this Env Var.
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

client = WebApplicationClient(CONSUMER_KEY)
authorization_url = 'https://www.linkedin.com/oauth/v2/authorization' # LinkedIn side
token_url = 'https://www.linkedin.com/oauth/v2/accessToken'
redirect_uri = 'https://cafe.olddba.people.aws.dev/login/authorized' # My webserver side
lin_state = ''
lin_user_name = 'Unknown Visitor'

# https://tedboy.github.io/flask/generated/werkzeug.html
@app.route('/')
def back_home():
    homepage= f"http://{urlparse(request.base_url).hostname}"
    return redirect(homepage, code=302)

################################################################################
# See https://flask.palletsprojects.com/en/2.3.x/quickstart/,
# "Unique URLs / Redirection Behavior" section
@app.route('/order', methods=['POST'])
def place_order():
    # 0. Check autheticated user cookie
    lin_user_name = session.get('username')
    if lin_user_name is None:
      return redirect(url_for('login'))
    # 1. Process POST fields
    # 2. Send request to Data Platform (DP) service
    # 3. Generate static Order page for user to refresh for status updates from DP
    orddir = "/var/www/html/orders"
    jpostdata = json.dumps(request.form) # See json.loads() to decode
    # generate Order Number as non-salted digest of its POST data - see DB Unique
    h = blake2b(digest_size=10)
    h.update(str(jpostdata).encode('utf-8')) 
    # Parameters for Data Functions
    ordrdgst =  h.hexdigest() # p_ordrdgst
    ordrname = escape(request.form['Name'][:40]) # p_ordrname
    ordrppl = escape(request.form['People'][:4]) # p_ordrppl
    ordrdttm = escape(request.form['date'][:20]) # p_ordrdttm
    ot = lin_user_name+':'+escape(request.form['Message'])
    ordrtxt = ot[:200] # p_ordrtxt
    try: # Emulate is a checkbox, sending only when ticked
     emulate = escape(request.form['Emulate'][:2]) 
     faildb = True
    except:
     faildb = False
    # DB actions
    (dbtxres, dbouthtml) = rananeeti_dp.addorder(ordrdgst, ordrname, ordrppl, \
     ordrdttm, ordrtxt, faildb)
    rcolor = "w3-green" if dbtxres else "w3-yellow"
    # Prepare the "order log"
    ordfile = f"{orddir}/{ordrdgst}.html"
    # We create or replace order file if exists
    with open(ordfile, 'w', encoding="utf-8") as ofl:
      # Parsing the template
      tmpl =  render_template('tmpl_order_log.html', 
       lin_user_name=lin_user_name, ordernum=ordrdgst, ppl=ordrppl, rcolor=rcolor)
      ofl.write(tmpl)
      ofl.write(dbouthtml)
    # File is closed by "with" above
    # Redirect user to their order file
    return redirect(f'/orders/{ordrdgst}.html', code=302) 



####################################################################################
# OpenID Connect auth part
# This should be in separate module, but in this demo I want everything in one place

@app.route('/login')
def login():
    global lin_state # Crypto random string set once _per exchange_
    # The primitive approach would be:
    # import random, string
    # lin_state = ''.join(random.choices(string.ascii_uppercase + 
    #  string.digits, k=LIN_STATE_LEN))
    #
    # Generator must be reinit'd here to produce different strings
    oauthcodeverifer = client.create_code_verifier(length=LIN_STATE_LEN)
    # lin_state = client.create_code_challenge(oauthcodeverifer, 'S256')
    lin_state = 'PDyJZWp4pl5u2HG8QHHpslmzmRvBnbJIdCAumkIQSLw' # Testing
    # When called often, LinkedIn OpenID server sometimes sends stale states values!
    print(f'... state: {lin_state}')
    lin_auth_url = client.prepare_request_uri(
      authorization_url, redirect_uri,
      scope = ['openid','profile'], # don't need "email" scope
      #scope = ['openid','email'], 
      state = lin_state
      )
    print(f'... linkedin auth url: {lin_auth_url}')
    return render_template('tmpl_lin_auth.html',
     linauthlink=lin_auth_url)

@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect('/', 302)


@app.route('/login/authorized')
def authorized():
    cburl = request.url
    print(f'... recieved callback {cburl}')

    try:
     # For non-TLS server, set envvar "export OAUTHLIB_INSECURE_TRANSPORT=1"
     lin_auth_resp=client.parse_request_uri_response(cburl, state=lin_state)
     lin_auth_code = lin_auth_resp['code']
     print(f'... LinkedIn Auth.Code: {lin_auth_code}')
     token_request = client.prepare_request_body(code=lin_auth_code,
        client_secret = CONSUMER_SECRET,
        redirect_uri = redirect_uri)
     token_req_url = f'{token_url}?{token_request}'
     print(f'... requesting token: {token_req_url}')
     # This request must be done by this program, _not_ by client's browser.
     # So, no redirect here
     # w3schools.com/python/ref_requests_response.asp
     token_resp = requests.get(token_req_url)
     # ID_Token consists of 3 dot-separated fields (header, data and signature)
     # Each of those individually Base64 encoded.
     id1 = token_resp.json()['id_token'].split('.')[1]
     id1 += '=' * (-len(id1) % 4)
     # stackoverflow.com/questions/2941995/
     #  python-ignore-incorrect-padding-error-when-base64-decoding
     # id1 = base64.b64decode(id1, '-_')
     id1 = base64.urlsafe_b64decode(id1).decode("utf-8") # id_token is "binary" data, b'xx'
     dict_id1 = json.loads(id1) # From UTF string to dictionary
     # learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/sign-in-with-linkedin-v2
     lin_user_name = dict_id1['name']
     session['username'] = lin_user_name
     print(f'... recieved token: {id1}')
     #return f'Welcome, {lin_user_name}!',200 # Known LinkedIn user.
     redirect('/', 302)

    except CustomOAuth2Error:
     print('... User Cancelled Authorization!')
     return redirect(url_for('unauthorized'))
    except Exception as e_auth:
     print(f'... Authentication error. {repr(e_auth)}\n'
      '... Redirecting to the home page')
     return redirect(url_for('unauthorized'))

    return redirect('/', 302)

@app.route('/login/unauthorized')
def unauthorized():
   print('... Authentication error. Go somewehere else')
   return '<h1>Please, go somewehere else</h1><h3>Unathorized - LinkedIn did not like you!</h3>'

