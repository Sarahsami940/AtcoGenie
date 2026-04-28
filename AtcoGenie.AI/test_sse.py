"""Test Python SSE endpoint raw output to debug .NET proxy parsing."""
import requests

token = "5366dcfa91d34899b78a1a4446a381b6"
url = "http://localhost:8000/api/chat/"
headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
body = {"message": "hello, what reports can you generate?"}

print("Sending request...")
resp = requests.post(url, json=body, headers=headers, stream=True, timeout=120)
print(f"STATUS: {resp.status_code}")
print(f"CONTENT-TYPE: {resp.headers.get('content-type')}")
print("--- RAW SSE LINES ---")

line_count = 0
for line in resp.iter_lines(decode_unicode=True):
    line_count += 1
    print(f"[{line_count:03d}] {line}")

print(f"\n--- TOTAL LINES: {line_count} ---")
