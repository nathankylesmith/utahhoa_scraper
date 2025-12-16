import csv
import re
import time
import os
import threading
import tkinter as tk
from tkinter import messagebox, filedialog, ttk  # ttk for the Progressbar
from configparser import ConfigParser
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup

# --- CONFIGURATION ---
CONFIG_FILE = 'hoa_scraper_settings.ini'
DEFAULT_URL = "https://services.commerce.utah.gov/hoa"
DEFAULT_SAVE_DIR = os.path.expanduser("~") # User's home directory
# --- END CONFIGURATION ---

# --- PERSISTENT SETTINGS MANAGEMENT ---
def load_settings():
    """Loads settings from the config file or returns defaults."""
    config = ConfigParser()
    config.read(CONFIG_FILE)
    
    settings = {
        'url': config.get('Scraper', 'base_url', fallback=DEFAULT_URL),
        'limit': config.get('Scraper', 'scrape_limit', fallback='10'),
        'term': config.get('Scraper', 'search_term', fallback=''),
        'wait': config.get('Scraper', 'wait_time', fallback='15'),
        'savedir': config.get('Scraper', 'save_directory', fallback=DEFAULT_SAVE_DIR)
    }
    return settings

def save_settings(url, limit, term, wait, savedir):
    """Saves current settings to the config file."""
    config = ConfigParser()
    config['Scraper'] = {
        'base_url': url,
        'scrape_limit': limit,
        'search_term': term,
        'wait_time': wait,
        'save_directory': savedir
    }
    with open(CONFIG_FILE, 'w') as f:
        config.write(f)

# --- SCRAPER LOGIC (Modified for GUI Integration) ---

# Helper functions remain the same: extract_contact_info, scrape_hoa_details, generate_final_data

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
    fixed_fields['DBA'] = soup.find('h3', class_='my-0').text.replace('DBA:', '').strip() if soup.find('h3') else ''
    
    reg_block = soup.find('h6')
    if reg_block:
        reg_text = reg_block.get_text('\n', strip=True)
        fixed_fields['Registration #'] = re.search(r'Registration #:\s*([^\n]+)', reg_text).group(1).strip() if re.search(r'Registration #:\s*([^\n]+)', reg_text) else ''
        fixed_fields['Registration Type'] = re.search(r'Registration Type:\s*([^\n]+)', reg_text).group(1).strip() if re.search(r'Registration Type:\s*([^\n]+)', reg_text) else ''
        fixed_fields['Status'] = soup.find('h6').find('span').text.strip() if soup.find('h6') and soup.find('h6').find('span') else ''
        fixed_fields['Expires'] = re.search(r'Expires:\s*([^\n]+)', reg_text).group(1).strip() if re.search(r'Expires:\s*([^\n]+)', reg_text) else ''

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

# --- CORE SCRAPER FUNCTION ---

def main_scraper(gui_app, base_url, search_term, scrape_limit, wait_time, save_directory):
    """
    Main function to orchestrate the Selenium-driven scraping process,
    integrated with the GUI for status updates and input parameters.
    """
    gui_app.update_status("🛠️ Initializing Scraper...", clear=True)
    
    # Validation is done in the UI thread before calling this function

    # 1. Initialize WebDriver
    try:
        options = webdriver.ChromeOptions()
        options.add_argument('--headless=new') # HEADLESS MODE
        options.add_argument('--disable-gpu') # Recommended for headless environments
        
        # NOTE: SERVICE_PATH is omitted here, relying on automatic driver management
        driver = webdriver.Chrome(options=options) 
            
    except Exception as e:
        gui_app.update_status(f"❌ CRITICAL ERROR: Failed to initialize WebDriver. Details: {e}", force_stop=True)
        return

    FIXED_FIELDNAMES = [
        'Entity ID', 'HOA Name', 'DBA', 'Registration #', 'Registration Type',
        'Status', 'Expires', 'Location', 'Mailing Address'
    ]
    scraped_data_structured = [] 
    all_dynamic_columns = set()
    
    gui_app.update_status(f"🌐 Navigating to {base_url} (Headless)...")

    try:
        # 2. Navigate and Trigger Search
        driver.get(base_url)
        wait = WebDriverWait(driver, wait_time)

        search_box = wait.until(
            EC.presence_of_element_located((By.ID, "HOAsearch"))
        )
        
        gui_app.update_status(f"🔍 Triggering search with term: '{search_term}'")
        search_box.send_keys(search_term)
        
        wait.until(
            EC.presence_of_element_located((By.ID, "tblEntities"))
        )
        gui_app.update_status("   -> Results table loaded.")
        
        # 3. Collect All Entity IDs and Names (Robust Fix)
        hoas_to_process = []
        
        gui_app.update_status("   -> Waiting for result rows to appear...")
        result_row_selector = "#tblEntities tbody tr.link-view"
        
        try:
            wait.until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, result_row_selector))
            )
            results_rows = driver.find_elements(By.CSS_SELECTOR, result_row_selector)
        except Exception as e:
            gui_app.update_status(f"   ❌ CRITICAL ERROR: No result rows found within {wait_time}s.", force_stop=True)
            return

        for i, row in enumerate(results_rows):
            try:
                entity_id = row.get_attribute("data-pid")
                name = row.find_element(By.TAG_NAME, 'td').text.split('\n')[0].strip()
                if entity_id:
                    hoas_to_process.append({'id': entity_id, 'name': name})
            except Exception:
                gui_app.update_status(f"   ⚠️ WARNING: Element {i} became stale during ID collection. Skipping.")
                continue

        total_hoas_found = len(hoas_to_process)
        limit = min(scrape_limit, total_hoas_found) if scrape_limit > 0 else total_hoas_found
        
        hoas_to_process = hoas_to_process[:limit]
        total_to_process = len(hoas_to_process)

        gui_app.update_status(f"Total HOAs found: {total_hoas_found}. Processing {total_to_process} HOAs.")
        gui_app.update_status("---------------------------------------------")
        
        # Set progress bar maximum
        gui_app.set_progress_max(total_to_process)

        # 4. Loop Through and Scrape Each Detail Page
        for i, hoa in enumerate(hoas_to_process):
            entity_id = hoa['id']
            hoa_name = hoa['name']
            
            gui_app.update_status(f"--- ({i+1}/{total_to_process}) Processing: {hoa_name} (ID: {entity_id}) ---")

            # A. Click the row
            try:
                target_row_selector = f"#tblEntities tr[data-pid='{entity_id}']"
                target_row = wait.until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, target_row_selector))
                )
                target_row.click()
                gui_app.update_status("   -> Clicked successfully.")
            except Exception as e:
                gui_app.update_status(f"   ❌ ERROR: Could not click entity {entity_id}. Skipping.")
                try: driver.find_element(By.ID, "btnList").click(); wait.until(EC.presence_of_element_located((By.ID, "tblEntities")))
                except: pass
                continue

            # B. Wait for the Detail Page to Load
            try:
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#areaResult h1")))
                time.sleep(0.5) 
            except:
                gui_app.update_status(f"   ❌ ERROR: Detail page for {entity_id} failed to load. Skipping.")
                try: driver.find_element(By.ID, "btnList").click(); wait.until(EC.presence_of_element_located((By.ID, "tblEntities")))
                except: pass
                continue

            # C. Rip the HTML and Scrape Data
            try:
                details_container = driver.find_element(By.ID, "areaResult")
                details_html = details_container.get_attribute('outerHTML')
                
                structured_data = scrape_hoa_details(details_html, entity_id)
                scraped_data_structured.append(structured_data)

                gui_app.update_status("   -> Data extracted successfully.")
            except Exception as e:
                gui_app.update_status(f"   ❌ ERROR: Failed to scrape data from loaded page. Details: {e}")
                
            # D. Navigate Back and Update Progress
            try:
                back_button = wait.until(EC.presence_of_element_located((By.ID, "btnList")))
                back_button.click()
                wait.until(EC.presence_of_element_located((By.ID, "tblEntities")))
                gui_app.update_status("   -> Returned to results list.")
                
                # Update progress bar value
                gui_app.update_progress(i + 1)
            except Exception as e:
                gui_app.update_status("   ❌ CRITICAL ERROR: Failed to click 'Back to Results'. Stopping scrape loop.")
                break

    finally:
        # 5. Clean Up, Transform, and Export
        gui_app.update_status("\n🗑️ Closing browser...")
        driver.quit()

        gui_app.update_status("🔄 Transforming structured data into CSV format...")
        scraped_data_flat = generate_final_data(scraped_data_structured)

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
            gui_app.update_status(f"   Total columns created: {len(FINAL_FIELDNAMES)}")
        
        except Exception as e:
            gui_app.update_status(f"\n❌ CRITICAL ERROR: Failed to write CSV file. Details: {e}", force_stop=True)
            
        gui_app.reset_progress()


# --- TKINTER GUI CLASS ---

class HOAScraperGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("HOA Registry Scraper")
        self.geometry("800x600")
        
        self.settings = load_settings()
        self.saved_dir = self.settings['savedir']
        
        # Tkinter variables
        self.url_var = tk.StringVar(value=self.settings['url'])
        self.limit_var = tk.StringVar(value=self.settings['limit'])
        self.wait_var = tk.StringVar(value=self.settings['wait'])
        self.search_all_var = tk.BooleanVar(value=True)
        self.term_var = tk.StringVar(value=self.settings['term'])
        
        self.create_widgets()

    def create_widgets(self):
        # Frame for controls
        control_frame = tk.Frame(self, padx=10, pady=10)
        control_frame.pack(side=tk.TOP, fill=tk.X)

        # Labels and Entry Widgets
        tk.Label(control_frame, text="Base URL:").grid(row=0, column=0, sticky="w", pady=2)
        tk.Entry(control_frame, textvariable=self.url_var, width=50).grid(row=0, column=1, columnspan=2, sticky="ew", padx=5, pady=2)
        
        tk.Label(control_frame, text="Test Limit (0=Full):").grid(row=1, column=0, sticky="w", pady=2)
        tk.Entry(control_frame, textvariable=self.limit_var, width=10).grid(row=1, column=1, sticky="w", padx=5, pady=2)
        
        tk.Label(control_frame, text="Wait Time (s):").grid(row=1, column=2, sticky="e", pady=2)
        tk.Entry(control_frame, textvariable=self.wait_var, width=10).grid(row=1, column=3, sticky="w", padx=5, pady=2)
        
        # Search Controls
        tk.Checkbutton(control_frame, text="Search All (Space)", variable=self.search_all_var, command=self.toggle_search).grid(row=2, column=0, sticky="w", pady=5)
        self.term_entry = tk.Entry(control_frame, textvariable=self.term_var, width=30)
        self.term_entry.grid(row=2, column=1, columnspan=2, sticky="ew", padx=5, pady=5)
        
        # Run Button
        self.run_button = tk.Button(control_frame, text="RUN SCRAPER", command=self.start_scraper_thread, bg="green", fg="white", font=('Arial', 10, 'bold'))
        self.run_button.grid(row=3, column=0, columnspan=4, sticky="ew", pady=10)
        
        # Progress Bar
        tk.Label(self, text="Progress:").pack(padx=10, pady=(10, 0), anchor="w")
        self.progress = ttk.Progressbar(self, orient="horizontal", length=100, mode="determinate")
        self.progress.pack(padx=10, pady=5, fill=tk.X)
        
        # Status Text Area
        tk.Label(self, text="Status / Console Output:").pack(padx=10, pady=(10, 0), anchor="w")
        self.status_text = tk.Text(self, wrap="word", height=20, bg="#2e2e2e", fg="lightgreen", font=('Consolas', 10))
        self.status_text.pack(padx=10, pady=5, fill=tk.BOTH, expand=True)
        
        # Initialize search state
        self.toggle_search()
        
    def set_progress_max(self, max_value):
        """Sets the maximum value of the progress bar."""
        self.progress["maximum"] = max_value
        self.progress["value"] = 0

    def update_progress(self, current_value):
        """Updates the current value of the progress bar."""
        self.progress["value"] = current_value
        self.update_idletasks()
        
    def reset_progress(self):
        """Resets the progress bar to zero."""
        self.progress["value"] = 0

    def toggle_search(self):
        """Disables/enables the search term entry based on the checkbox."""
        if self.search_all_var.get():
            self.term_entry.config(state=tk.DISABLED, disabledforeground="grey")
        else:
            self.term_entry.config(state=tk.NORMAL)

    def update_status(self, message, clear=False, force_stop=False):
        """Updates the status Text widget with a new message."""
        if clear:
            self.status_text.delete(1.0, tk.END)
            self.reset_progress()
            
        self.status_text.insert(tk.END, f"{message}\n")
        self.status_text.see(tk.END) # Scroll to the bottom
        self.update_idletasks() # Ensure the GUI updates immediately
        
        if force_stop:
            self.run_button.config(state=tk.NORMAL, text="RUN SCRAPER", bg="green")


    def select_save_location(self):
        """Opens a file dialog for the user to select the save path."""
        # Use initialfile for the default filename
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
        """Prepares inputs and launches the scraper in a separate thread."""
        # Disable button during run
        self.run_button.config(state=tk.DISABLED, text="SCRAPING... PLEASE WAIT (Browser is Headless)", bg="red")
        
        # 1. Collect and Validate Inputs
        base_url = self.url_var.get().strip()
        search_term = ' ' if self.search_all_var.get() else self.term_var.get().strip()
        limit_str = self.limit_var.get().strip()
        wait_time_str = self.wait_var.get().strip()
        
        try:
            limit = int(limit_str)
            wait_time = int(wait_time_str)
        except ValueError:
            messagebox.showerror("Input Error", "Test Limit and Wait Time must be whole numbers.")
            self.run_button.config(state=tk.NORMAL, text="RUN SCRAPER", bg="green")
            return

        if not base_url.startswith('http'):
            messagebox.showerror("Error", "Base URL must start with http:// or https://")
            self.run_button.config(state=tk.NORMAL, text="RUN SCRAPER", bg="green")
            return
            
        # 2. Handle Save Location
        self.update_status("\n--- File Export ---")
        if messagebox.askyesno("Save Location", f"Use default save directory:\n{self.saved_dir}\n\nClick 'No' to choose a new location."):
            save_location = self.saved_dir
        else:
            save_location = self.select_save_location()
            if not save_location or save_location == '.': # Handle cancel
                 self.run_button.config(state=tk.NORMAL, text="RUN SCRAPER", bg="green")
                 self.update_status("Export canceled by user. Scrape aborted.")
                 return

        self.update_status(f"Saving data to: {save_location}")

        # 3. Save current settings (including new save location)
        save_settings(base_url, self.limit_var.get(), self.term_var.get(), self.wait_var.get(), save_location)
        self.saved_dir = save_location
        self.update_status("Settings saved successfully.")

        # 4. Execute Scraper in a new thread
        scraper_thread = threading.Thread(target=main_scraper, args=(self, base_url, search_term, limit, wait_time, save_location))
        scraper_thread.start()
        
        # 5. Re-enable button when thread finishes (check every 100ms)
        self.check_thread(scraper_thread)

    def check_thread(self, thread):
        """Checks if the scraper thread is alive and re-enables the button when it finishes."""
        if thread.is_alive():
            # If still running, check again in 100ms
            self.after(100, lambda: self.check_thread(thread))
        else:
            # If finished, re-enable the button
            self.run_button.config(state=tk.NORMAL, text="RUN SCRAPER", bg="green")
            messagebox.showinfo("Scrape Finished", "The scraping process has completed. Check the status box for details and the save location for your CSV file.")


if __name__ == "__main__":
    try:
        app = HOAScraperGUI()
        app.mainloop()
    except Exception as e:
        # A simple print for pre-GUI errors (e.g., Python environment issue)
        print(f"A fatal error occurred before starting the GUI: {e}")
