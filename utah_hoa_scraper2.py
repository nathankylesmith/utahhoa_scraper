import csv
import re
import time
import os
import threading
import tkinter as tk
from tkinter import messagebox, filedialog, ttk
from configparser import ConfigParser
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup

# --- CONFIGURATION ---
CONFIG_FILE = 'hoa_scraper_settings.ini'
DEFAULT_URL = "https://services.commerce.utah.gov/hoa/assets/js/hoa-ajax.php"
DEFAULT_SAVE_DIR = os.path.expanduser("~") 

# --- PERSISTENT SETTINGS MANAGEMENT ---
def load_settings():
    """Loads settings from the config file or returns defaults."""
    config = ConfigParser()
    config.read(CONFIG_FILE)
    
    settings = {
        'limit': config.get('Scraper', 'scrape_limit', fallback='0'),
        'savedir': config.get('Scraper', 'save_directory', fallback=DEFAULT_SAVE_DIR)
    }
    return settings

def save_settings(limit, savedir):
    """Saves current settings to the config file."""
    config = ConfigParser()
    config['Scraper'] = {
        'scrape_limit': limit,
        'save_directory': savedir
    }
    with open(CONFIG_FILE, 'w') as f:
        config.write(f)

# --- NETWORK HELPERS ---

import ssl
ssl._create_default_https_context = ssl._create_unverified_context

def fetch_html_post(url, data_dict, retries=3):
    """Performs a POST request and returns the decoded HTML string."""
    data = urllib.parse.urlencode(data_dict).encode('utf-8')
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'
    }
    req = urllib.request.Request(url, data=data, headers=headers)
    
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.read().decode('utf-8')
        except Exception as e:
            if attempt == retries - 1:
                print(f"Failed to fetch {url} with data {data_dict}: {e}")
                return None
            time.sleep(1)

# --- PARSING LOGIC ---

def extract_contact_info(p_tag):
    """Extracts name, phone, email, and address from a role's <p> block."""
    text = p_tag.get_text('\n', strip=True) 
    lines = [line.strip() for line in text.split('\n') if line.strip()]

    contact = {
        'Name': '',
        'Phone': '',
        'Email': '',
        'Address': ''
    }

    if lines:
        contact['Name'] = lines[0]
        phone_match = re.search(r'\(?\d{3}\)?\s?\d{3}-\d{4}', text)
        email_match = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)

        if phone_match: contact['Phone'] = phone_match.group(0)
        if email_match: contact['Email'] = email_match.group(0)
        
        address_lines = [line for line in lines[1:] 
                         if not re.search(r'\(?\d{3}\)?\s?\d{3}-\d{4}', line) 
                         and '@' not in line 
                         and line != contact['Name']]
        contact['Address'] = ', '.join(address_lines)
    
    return contact


def scrape_hoa_details(details_html, entity_id):
    """Parses the detailed HTML for a single HOA using BeautifulSoup."""
    if not details_html:
        return None

    soup = BeautifulSoup(details_html, 'html.parser')
    
    data = {
        'Fixed Fields': {'Entity ID': entity_id},
        'President': [],
        'Manager': [],
        'Payoff Contact': [],
        'Board Member': []
    }

    # 1. FIXED HEADER DATA
    fixed_fields = data['Fixed Fields']
    fixed_fields['HOA Name'] = soup.find('h1', class_='mb-0').text.strip() if soup.find('h1') else ''
    
    # Check for DBA
    dba_tag = soup.find('h3', class_='my-0')
    if dba_tag and 'DBA' in dba_tag.text:
       fixed_fields['DBA'] = dba_tag.text.replace('DBA:', '').strip()
    else:
       fixed_fields['DBA'] = ''

    
    reg_block = soup.find('h6')
    if reg_block:
        reg_text = reg_block.get_text('\n', strip=True)
        # Use simple string checks or regex
        m_reg = re.search(r'Registration #:\s*([^\n]+)', reg_text)
        fixed_fields['Registration #'] = m_reg.group(1).strip() if m_reg else ''
        
        m_type = re.search(r'Registration Type:\s*([^\n]+)', reg_text)
        fixed_fields['Registration Type'] = m_type.group(1).strip() if m_type else ''
        
        status_span = soup.find('h6').find('span')
        fixed_fields['Status'] = status_span.text.strip() if status_span else ''
        
        m_exp = re.search(r'Expires:\s*([^\n]+)', reg_text)
        fixed_fields['Expires'] = m_exp.group(1).strip() if m_exp else ''

    location_h5 = soup.find('h5', string='Location:')
    fixed_fields['Location'] = location_h5.find_next_sibling('p').text.strip() if location_h5 and location_h5.find_next_sibling('p') else ''

    contact_h5 = soup.find('h5', string='Contact Info:')
    fixed_fields['Mailing Address'] = contact_h5.find_next_sibling('p').text.replace('\n', ', ').strip() if contact_h5 and contact_h5.find_next_sibling('p') else ''


    # 2. VARIABLE ROLE CARDS (President, Manager, Payoff)
    roles_container = soup.find('div', class_='row border primary-color-border mt-4')

    if roles_container:
        for role_h4 in roles_container.find_all('h4', class_='mb-0'):
            role_name = role_h4.text.strip()
            contact_p = role_h4.parent.find('p', class_='mt-0 ml-3')
            
            if contact_p:
                contact = extract_contact_info(contact_p)
                if 'President' in role_name:
                    data['President'].append(contact)
                elif 'Community Manager' in role_name:
                    data['Manager'].append(contact)
                elif 'Payoff Contact' in role_name:
                    data['Payoff Contact'].append(contact)


    # 3. BOARD MEMBERS / MANAGEMENT COMMITTEE
    board_header = soup.find('h4', class_='border-bottom')
    
    if board_header and ('Board Members' in board_header.text or 'Management Committee' in board_header.text):
        current_node = board_header.parent
        while True:
            current_node = current_node.find_next_sibling('div', class_=lambda c: c and ('col-md-6' in c or 'col-lg-3' in c))
            if not current_node: break
                
            member_p = current_node.find('p', class_='ml-3')
            if member_p:
                contact = extract_contact_info(member_p)
                data['Board Member'].append(contact)

    return data


def generate_final_data(scraped_data):
    """Transforms the structured scraped data into a wide, flat dictionary."""
    final_data = []
    
    for structured_hoa in scraped_data:
        if not structured_hoa: continue
        
        flat_hoa = {}
        flat_hoa.update(structured_hoa['Fixed Fields'])
        
        for role, contacts in structured_hoa.items():
            if role == 'Fixed Fields': continue
                
            for i, contact in enumerate(contacts):
                column_prefix = f"{role} {i+1}"
                
                for field, value in contact.items():
                    flat_hoa[f"{column_prefix} {field}"] = value
                    
        final_data.append(flat_hoa)
        
    return final_data

# --- CORE LOGIC ---

def process_one_hoa(pid):
    """Worker function to fetch and parse a single HOA."""
    html = fetch_html_post(DEFAULT_URL, {'f': 'd', 'v': pid})
    if html:
        return scrape_hoa_details(html, pid)
    return None

def main_scraper(gui_app, scrape_limit, save_directory):
    """
    Main function to orchestrate the API-driven scraping process.
    """
    gui_app.update_status("🛠️ Initializing API Scraper...", clear=True)
    
    # 1. Fetch Full List
    gui_app.update_status(f"🌐 Fetching full HOA list from {DEFAULT_URL}...")
    
    list_html = fetch_html_post(DEFAULT_URL, {'f': 's', 'v': '%'}) # '%' wildcard for all
    
    if not list_html:
         gui_app.update_status("❌ CRITICAL ERROR: Failed to fetch HOA list. Check internet connection.", force_stop=True)
         return

    soup = BeautifulSoup(list_html, 'html.parser')
    rows = soup.select('tr.link-view')
    
    all_pids = []
    for row in rows:
        pid = row.get('data-pid')
        name = row.find('td').text.split('\n')[0].strip() if row.find('td') else "Unknown"
        if pid:
            all_pids.append((pid, name))
            
    total_found = len(all_pids)
    limit = min(scrape_limit, total_found) if scrape_limit > 0 else total_found
    pids_to_process = all_pids[:limit]
    
    gui_app.update_status(f"✅ Found {total_found} HOAs. Processing {limit}...")
    gui_app.set_progress_max(limit)
    
    scraped_data_structured = []
    
    # 2. Parallel Fetching
    gui_app.update_status("🚀 Starting parallel downloads (20 threads)...")
    
    with ThreadPoolExecutor(max_workers=20) as executor:
        future_map = {executor.submit(process_one_hoa, pid): name for pid, name in pids_to_process}
        
        completed_count = 0
        for future in as_completed(future_map):
            name = future_map[future]
            try:
                result = future.result()
                if result:
                    scraped_data_structured.append(result)
                completed_count += 1
                
                # Update GUI every 5 items to avoid UI lag, or every item if list is small
                if completed_count % 5 == 0 or completed_count == limit:
                    gui_app.update_progress(completed_count)
                    gui_app.update_status(f"   Processed: {completed_count}/{limit}", append_only=True)
                    
            except Exception as e:
                print(f"Error processing {name}: {e}")

    # 3. Export
    gui_app.update_status("\n🔄 Transforming data and saving CSV...")
    
    scraped_data_flat = generate_final_data(scraped_data_structured)
    
    all_dynamic_columns = set()
    FIXED_FIELDNAMES = [
        'Entity ID', 'HOA Name', 'DBA', 'Registration #', 'Registration Type',
        'Status', 'Expires', 'Location', 'Mailing Address'
    ]
    
    for row in scraped_data_flat:
        all_dynamic_columns.update(row.keys())

    FINAL_FIELDNAMES = FIXED_FIELDNAMES + sorted(list(all_dynamic_columns - set(FIXED_FIELDNAMES)))
    
    output_file_path = os.path.join(save_directory, 'utah_hoa_registry_data.csv')

    try:
        with open(output_file_path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=FINAL_FIELDNAMES, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(scraped_data_flat)
        
        gui_app.update_status(f"\n✅ Scraping complete! {len(scraped_data_flat)} HOAs processed.")
        gui_app.update_status(f"   Data saved to: {output_file_path}")
    
    except Exception as e:
        gui_app.update_status(f"\n❌ CRITICAL ERROR: Failed to write CSV file. Details: {e}", force_stop=True)
        
    gui_app.reset_progress()


# --- TKINTER GUI CLASS ---

class HOAScraperGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("HOA Registry Scraper (API Edition)")
        self.geometry("600x450")
        
        self.settings = load_settings()
        self.saved_dir = self.settings['savedir']
        
        # Tkinter variables
        self.limit_var = tk.StringVar(value=self.settings['limit'])
        
        self.create_widgets()

    def create_widgets(self):
        # Frame for controls
        control_frame = tk.Frame(self, padx=10, pady=10)
        control_frame.pack(side=tk.TOP, fill=tk.X)

        # Labels and Entry Widgets
        tk.Label(control_frame, text="Test Limit (0=Full):").grid(row=0, column=0, sticky="w", pady=2)
        tk.Entry(control_frame, textvariable=self.limit_var, width=10).grid(row=0, column=1, sticky="w", padx=5, pady=2)
        
        # Run Button
        self.run_button = tk.Button(control_frame, text="RUN SCRAPER", command=self.start_scraper_thread, bg="green", fg="white", font=('Arial', 10, 'bold'))
        self.run_button.grid(row=1, column=0, columnspan=2, sticky="ew", pady=10)
        
        # Progress Bar
        tk.Label(self, text="Progress:").pack(padx=10, pady=(10, 0), anchor="w")
        self.progress = ttk.Progressbar(self, orient="horizontal", length=100, mode="determinate")
        self.progress.pack(padx=10, pady=5, fill=tk.X)
        
        # Status Text Area
        tk.Label(self, text="Status / Console Output:").pack(padx=10, pady=(10, 0), anchor="w")
        self.status_text = tk.Text(self, wrap="word", height=15, bg="#2e2e2e", fg="lightgreen", font=('Consolas', 10))
        self.status_text.pack(padx=10, pady=5, fill=tk.BOTH, expand=True)
        
    def set_progress_max(self, max_value):
        self.progress["maximum"] = max_value
        self.progress["value"] = 0

    def update_progress(self, current_value):
        self.progress["value"] = current_value
        
    def reset_progress(self):
        self.progress["value"] = 0

    def update_status(self, message, clear=False, force_stop=False, append_only=False):
        if clear:
            self.status_text.delete(1.0, tk.END)
            self.reset_progress()
        
        # For rapid updates (processed counts), we might want to just update the last line
        if append_only:
             # Just append
             pass 
        else:
             self.status_text.insert(tk.END, f"{message}\n")
        
        self.status_text.see(tk.END)
        self.update_idletasks()
        
        if force_stop:
            self.run_button.config(state=tk.NORMAL, text="RUN SCRAPER", bg="green")


    def select_save_location(self):
        filepath = filedialog.asksaveasfilename(
            initialdir=self.saved_dir,
            initialfile="utah_hoa_registry_data.csv",
            defaultextension=".csv",
            title="Select Save Location and Filename",
            filetypes=[("CSV files", "*.csv")]
        )
        if filepath:
            new_dir = os.path.dirname(filepath)
            self.saved_dir = new_dir
            return new_dir
        return self.saved_dir

    def start_scraper_thread(self):
        self.run_button.config(state=tk.DISABLED, text="SCRAPING...", bg="red")
        
        limit_str = self.limit_var.get().strip()
        try:
            limit = int(limit_str)
        except ValueError:
            messagebox.showerror("Input Error", "Limit must be a number.")
            self.run_button.config(state=tk.NORMAL, text="RUN SCRAPER", bg="green")
            return

        if messagebox.askyesno("Save Location", f"Use default save directory:\n{self.saved_dir}\n\nClick 'No' to choose a new location."):
            save_location = self.saved_dir
        else:
            save_location = self.select_save_location()
            if not save_location or save_location == '.':
                 self.run_button.config(state=tk.NORMAL, text="RUN SCRAPER", bg="green")
                 self.update_status("Export canceled.")
                 return

        save_settings(limit_str, save_location)
        self.saved_dir = save_location

        scraper_thread = threading.Thread(target=main_scraper, args=(self, limit, save_location))
        scraper_thread.start()
        
        self.check_thread(scraper_thread)

    def check_thread(self, thread):
        if thread.is_alive():
            self.after(100, lambda: self.check_thread(thread))
        else:
            self.run_button.config(state=tk.NORMAL, text="RUN SCRAPER", bg="green")
            messagebox.showinfo("Done", "Scraping Finished!")


if __name__ == "__main__":
    app = HOAScraperGUI()
    app.mainloop()
