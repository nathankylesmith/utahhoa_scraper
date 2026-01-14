import urllib.request
import urllib.parse
from bs4 import BeautifulSoup
import re

URL = "https://services.commerce.utah.gov/hoa/assets/js/hoa-ajax.php"

import ssl

# Bypass SSL verification
ssl._create_default_https_context = ssl._create_unverified_context

def fetch_post(data_dict):
    data = urllib.parse.urlencode(data_dict).encode('utf-8')
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'
    }
    req = urllib.request.Request(URL, data=data, headers=headers)
    with urllib.request.urlopen(req) as response:
        return response.read().decode('utf-8')

print("1. Testing List Fetch (Getting all IDs)...")
list_html = fetch_post({'f': 's', 'v': '%'})
soup = BeautifulSoup(list_html, 'html.parser')
rows = soup.select('tr.link-view')
print(f"   Success! Found {len(rows)} HOA records.")

if rows:
    first_pid = rows[0].get('data-pid')
    first_name = rows[0].find('td').text.strip()
    print(f"\n2. Testing Detail Fetch for ID {first_pid} ({first_name})...")
    
    detail_html = fetch_post({'f': 'd', 'v': first_pid})
    
    # Quick parse check
    dsoup = BeautifulSoup(detail_html, 'html.parser')
    president_header = dsoup.find('h4', string=re.compile('President'))
    
    print(f"   Detail HTML length: {len(detail_html)} chars")
    if president_header:
        print("   Found 'President' section: YES")
        # Try to extract name
        p_tag = president_header.parent.find('p')
        if p_tag:
            print(f"   President details extracted: {p_tag.get_text(separator=' | ', strip=True)}")
    else:
        print("   Found 'President' section: NO (Might be empty for this record)")

    print("\nVerification Complete.")
