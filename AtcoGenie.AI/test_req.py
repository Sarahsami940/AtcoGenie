import sys
import json
import urllib.request
from urllib.error import HTTPError

req = urllib.request.Request(
    'http://localhost:8000/api/chat/',
    data=json.dumps({"message":"hi","chat_history":[]}).encode('utf-8'),
    headers={'Authorization': 'Bearer d4d5dd2630b5400fab45c1cde4ce96b0', 'Content-Type': 'application/json'}
)
try:
    resp = urllib.request.urlopen(req)
    print(resp.status, resp.read().decode())
except HTTPError as e:
    print(e.code, e.read().decode())
