import requests
import json

s = requests.Session()
s.headers.update({
    'Accept': 'application/json, text/plain, */*',
    'Content-Type': 'application/json',
    'x-requested-with': 'OnlineShopping.WebApp',
    'x-ui-ver': '7.72.37',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36',
})

r = s.get('https://www.woolworths.co.nz/api/v1/products', params=[
    ('dasFilter', 'Department;;frozen;false'),
    ('target', 'browse'),
    ('inStockProductsOnly', 'false'),
    ('size', '5'),
    ('page', '1'),
], timeout=15)

print('Status:', r.status_code)
if r.status_code == 200:
    data = r.json()
    print('Top-level keys:', list(data.keys()))
    print(json.dumps(data, indent=2)[:2000])
else:
    print(r.text[:500])