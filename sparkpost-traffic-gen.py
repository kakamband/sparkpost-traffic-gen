#!/usr/bin/env python3
#
# Simple SparkPost Traffic Generator
# Sends emails towards the Solution Engineering smart bounce/sink server domains
#
# Configurable traffic volume per minute
#
# Can be run periodically via Heroku Scheduler on free dynos
# Uses redis to communicate results to webReporter
#
import random, os, time, json
from sparkpost import SparkPost
from sparkpost.exceptions import SparkPostAPIException
from datetime import datetime, timezone
from webReporter import getResults, setResults

# -----------------------------------------------------------------------------------------
# Configurable recipient domains, recipient substitution data, html clickable link, campaign, subject etc
# -----------------------------------------------------------------------------------------

recipDomains = [
    "not-gmail.com.bouncy-sink.trymsys.net",
    "not-yahoo.com.bouncy-sink.trymsys.net",
    "not-yahoo.co.uk.bouncy-sink.trymsys.net",
    "not-hotmail.com.bouncy-sink.trymsys.net",
    "not-hotmail.co.uk.bouncy-sink.trymsys.net",
    "not-aol.com.bouncy-sink.trymsys.net",
    "not-orange.fr.bouncy-sink.trymsys.net",
    "not-mail.ru.bouncy-sink.trymsys.net",
]

recipCities = ["Baltimore", "Boston", "London", "New York", "Paris", "Rio de Janeiro", "Seattle", "Sydney", "Tokyo" ]
recipGenders = ["female", "male"]

htmlLink = 'http://example.com/index.html'

content = [
    {'campaign': 'sparkpost-traffic-gen Todays_Sales', 'subject': 'Today\'s sales', 'linkname': 'Deal of the Day'},
    {'campaign': 'sparkpost-traffic-gen Newsletter', 'subject': 'Newsletter', 'linkname': 'More Daily News'},
    {'campaign': 'sparkpost-traffic-gen Last Minute Savings', 'subject': 'Savings', 'linkname': 'Last Minute Savings'},
    {'campaign': 'sparkpost-traffic-gen Password_Reset', 'subject': 'Password reset', 'linkname': 'Password Reset'},
    {'campaign': 'sparkpost-traffic-gen Welcome_Letter', 'subject': 'Welcome letter', 'linkname': 'Contact Form'},
    {'campaign': 'sparkpost-traffic-gen Holiday_Bargains', 'subject': 'Holiday bargains', 'linkname': 'Holiday Bargains'}
]

ToAddrPrefix = 'test+'                              # prefix - random digits are appended to this
ToName = 'traffic-generator'
sendInterval = 10                                   # minutes
batchSize = 2000                                    # efficient transmission API call batch size

# -----------------------------------------------------------------------------
def randomRecip():
    numDigits = 20                                  # Number of random local-part digits to generate
    localpartnum = random.randrange(0, 10**numDigits)
    domain = random.choice(recipDomains)
    # Pad the number out to a fixed length of digits
    addr = ToAddrPrefix+str(localpartnum).zfill(numDigits) + '@' + domain
    recip = {
        "address": addr,
        "name": ToName,
        "substitution_data": {
            "gender":  random.choice(recipGenders),
            "city": random.choice(recipCities),
        }
    }
    return recip

htmlTemplate = \
'''<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>test mail</title>
  </head>
  <body>
    Click <a href="{}" data-msys-linkname="{}">{}</a>
  </body>
</html>'''

# Contents include a valid http(s) link with custom link name
def randomContents():
    c = random.choice(content)
    htmlBody = htmlTemplate.format(htmlLink, c['linkname'], htmlLink)
    return c['campaign'], c['subject'], htmlBody

# Inject the messages into SparkPost for a batch of recipients, using the specified transmission parameters
def sendToRecips(sp, recipBatch, sendObj):
    print('  To', str(len(recipBatch)).rjust(5, ' '),'recipients | campaign "'+sendObj['campaign']+'" | ', end='', flush=True)
    # Compose in additional API-call parameters
    sendObj.update({
        'recipients': recipBatch,
    })
    startT = time.time()
    try:
        res = sp.transmissions.send(**sendObj)                  # Unpack for the call
        endT = time.time()
        if res['total_accepted_recipients'] != len(recipBatch):
            print(res)
        else:
            print('OK - in', round(endT - startT, 3), 'seconds')
        return res['total_accepted_recipients'], ''
    except SparkPostAPIException as err:
        errMsg = 'error code ' + str(err.status) + ' : ' + str(err.errors)
        print(errMsg)
        return 0, errMsg

def sendRandomCampaign(sp, recipients, trackOpens=True, trackClicks=True):
    campaign, subject, htmlBody = randomContents()
    txObj = {
        'text': 'hello world',
        'html': htmlBody,
        'subject': subject,
        'campaign': campaign,
        'track_opens':  trackOpens,
        'track_clicks': trackClicks,
        'from_email': fromEmail,
    }
    if 'api.e.sparkpost.com' in sp.base_uri:                       # SPE demo system needs named ip_pool
        rp = 'bounces@' + fromEmail.split('@')[1]
        txObj.update( { 'ip_pool': 'outbound', 'return_path': rp } )
    return sendToRecips(sp, recipients, txObj)

def timeStr(t):
    utc = datetime.fromtimestamp(t, timezone.utc)
    return datetime.isoformat(utc, sep='T', timespec='seconds')

def stripEnd(h, s):
    if h.endswith(s):
        h = h[:-len(s)]
    return h

# condense into library-ready form
def hostCleanup(host):
    if not host.startswith('https://'):
        host = 'https://' + host  # Add schema
    host = stripEnd(host, '/')
    host = stripEnd(host, '/api/v1')
    host = stripEnd(host, '/')
    return host


def strToBool(v):
    s = v.lower()
    if s in ("yes", "true", "t", "1"):
        return True
    elif s in ("no", "false", "f", "0"):
        return False
    else:
        return None

# -----------------------------------------------------------------------------
# Main code
# -----------------------------------------------------------------------------

msgPerMinLow = os.getenv('MESSAGES_PER_MINUTE_LOW', '')
if msgPerMinLow.isnumeric():
    msgPerMinLow = int(msgPerMinLow)
    if msgPerMinLow < 0 or msgPerMinLow > 10000:
        print('Invalid MESSAGES_PER_MINUTE_LOW setting - must be number 1 to 10000')
        exit(1)
else:
    print('Invalid MESSAGES_PER_MINUTE_LOW setting - must be number 1 to 10000')
    exit(1)

msgPerMinHigh = os.getenv('MESSAGES_PER_MINUTE_HIGH', '')
if msgPerMinHigh.isnumeric():
    msgPerMinHigh = int(msgPerMinHigh)
    if msgPerMinHigh < 0 or msgPerMinHigh > 10000:
        print('Invalid MESSAGES_PER_MINUTE_HIGH setting - must be number 1 to 10000')
        exit(1)
else:
    print('Invalid MESSAGES_PER_MINUTE_HIGH setting - must be number 1 to 10000')
    exit(1)

apiKey = os.getenv('SPARKPOST_API_KEY')        # API key is mandatory
if apiKey == None:
    print('SPARKPOST_API_KEY environment variable not set - stopping.')
    exit(1)

host = hostCleanup(os.getenv('SPARKPOST_HOST', default='api.sparkpost.com'))

fromEmail = os.getenv('FROM_EMAIL')
if fromEmail == None:
    print('FROM_EMAIL environment variable not set - stopping.')
    exit(1)

resultsKey = os.getenv('RESULTS_KEY')
if resultsKey == None:
    print('RESULTS_KEY environment variable not set - stopping.')
    exit(1)

trackOpens = strToBool(os.getenv('TRACK_OPENS', default='True'))
if trackOpens == None:
    print('TRACK_OPENS set to invalid value - should be True or False')
    exit(1)

trackClicks = strToBool(os.getenv('TRACK_CLICKS', default='True'))
if trackClicks == None:
    print('TRACK_CLICKS set to invalid value - should be True or False')
    exit(1)

sp = SparkPost(api_key = apiKey, base_uri = host)
print('Opened connection to', host)

startTime = time.time()                                         # measure run time
res = getResults()                                              # read back results from previous run (if any)
if not res:
    res = {
        'startedRunning': timeStr(startTime),                   # this is the first run - initialise
        'totalSentVolume': 0
    }

# Send every n minutes, between low and high traffic rate
thisRunSize = int(random.uniform(msgPerMinLow * sendInterval, msgPerMinHigh * sendInterval))
print('Sending from {} to {} recipients, TRACK_OPENS={}, TRACK_CLICKS={}'.format(fromEmail, thisRunSize, trackOpens, trackClicks))
recipients = []
countSent = 0
anyError = ''
for i in range(0, thisRunSize):
    recipients.append(randomRecip())
    if len(recipients) >= batchSize:
        c, err = sendRandomCampaign(sp, recipients, trackOpens=trackOpens, trackClicks=trackClicks)
        countSent += c
        if err:
            anyError = err                      # remember any error codes seen
        recipients=[]
if len(recipients) > 0:                         # Send residual batch
    c, err = sendRandomCampaign(sp, recipients, trackOpens=trackOpens, trackClicks=trackClicks)
    countSent += c
    if err:
        anyError = err                          # remember any error codes seen

# write out results to console and to redis
endTime = time.time()
runTime = endTime - startTime
print('Done in {0:.1f}s.'.format(runTime))
res.update( {
    'lastRunTime': timeStr(startTime),
    'lastRunDuration': round(runTime, 3),
    'lastRunSize': thisRunSize,
    'lastRunSent': countSent,
    'lastRunError': anyError,
    'nextRunTime': timeStr(startTime + 60 *sendInterval)
})
res['totalSentVolume'] += countSent

if setResults(json.dumps(res)):
    print('Results written to redis')