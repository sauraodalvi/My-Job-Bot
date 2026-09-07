'''
Author:     Sai Vignesh Golla
LinkedIn:   https://www.linkedin.com/in/saivigneshgolla/

Copyright (c) 2024-2026 Sai Vignesh Golla

License:    MIT License
            https://opensource.org/license/mit
            
GitHub:     https://github.com/GodsScion/Auto_job_applier_linkedIn

Support me: https://github.com/sponsors/GodsScion

version:    26.01.20.5.08
'''

from modules.helpers import get_default_temp_profile, make_directories, get_chrome_major_version
from config.settings import run_in_background, auto_manage_driver, disable_extensions, safe_mode, file_name, failed_file_name, logs_folder_path, generated_resume_path
from config.questions import default_resume_path
import os
import sys
import time
if auto_manage_driver:
    import undetected_chromedriver as uc
else: 
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    # from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from modules.helpers import find_default_profile_directory, critical_error_log, print_lg
from selenium.common.exceptions import SessionNotCreatedException

def _clean_stale_temp_profile_chrome() -> None:
    '''
    Kill any lingering chrome.exe processes bound to OUR temp profile (e.g. a previous
    run that never closed cleanly). They hold the profile's SingletonLock and make the
    next boot fail with "cannot connect to chrome", forcing an extra ~1 min retry.
    Only targets chrome processes whose command line references the bot's temp profile,
    so the user's own browser is never touched.
    '''
    try:
        import subprocess
        temp_p = get_default_temp_profile()
        if not temp_p:
            return
        profile_token = temp_p.replace("'", "''")
        script = (
            "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" "
            "| Where-Object { $_.CommandLine -like '*" + profile_token + "*' } "
            "| ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
        )
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, timeout=20)
        time.sleep(1)
    except Exception:
        pass

def createChromeSession(isRetry: bool = False):
    make_directories([file_name,failed_file_name,logs_folder_path+"/screenshots",default_resume_path,generated_resume_path+"/temp"])
    # Set up WebDriver with Chrome Profile
    options = uc.ChromeOptions() if auto_manage_driver else Options()
    if run_in_background:   options.add_argument("--headless")
    if disable_extensions:  options.add_argument("--disable-extensions")

    print_lg("IF YOU HAVE MORE THAN 10 TABS OPENED, PLEASE CLOSE OR BOOKMARK THEM! Or it's highly likely that application will just open browser and not do anything!")
    profile_dir = find_default_profile_directory()
    if isRetry:
        print_lg("Will login with a guest profile, browsing history will not be saved in the browser!")
        temp_p = get_default_temp_profile()
        options.add_argument(temp_p if temp_p.startswith("--user-data-dir=") else f"--user-data-dir={temp_p}")
    elif profile_dir and not safe_mode:
        options.add_argument(f"--user-data-dir={profile_dir}")
    else:
        print_lg("Logging in with a guest profile, Web history will not be saved!")
        temp_p = get_default_temp_profile()
        options.add_argument(temp_p if temp_p.startswith("--user-data-dir=") else f"--user-data-dir={temp_p}")
    if auto_manage_driver:
        # try: 
        #     driver = uc.Chrome(driver_executable_path="C:\\Program Files\\Google\\Chrome\\chromedriver-win64\\chromedriver.exe", options=options)
        # except (FileNotFoundError, PermissionError) as e: 
        #     print_lg("(auto-managed driver) Got '{}' when using pre-installed ChromeDriver.".format(type(e).__name__))
            print_lg("Downloading the matching Chrome driver... This may take some time (this happens each run when auto_manage_driver is enabled).")
            chrome_major = get_chrome_major_version()
            driver = uc.Chrome(options=options, version_main=chrome_major) if chrome_major else uc.Chrome(options=options)
    else: driver = webdriver.Chrome(options=options) #, service=Service(executable_path="C:\\Program Files\\Google\\Chrome\\chromedriver-win64\\chromedriver.exe"))
    driver.maximize_window()
    wait = WebDriverWait(driver, 5)
    actions = ActionChains(driver)
    return options, driver, actions, wait

try:
    options, driver, actions, wait = None, None, None, None
    if os.environ.get("AJA_SMOKE"):
        print_lg("AJA_SMOKE set: skipping Chrome session creation (packaging smoke test).")
    else:
        try:
            _clean_stale_temp_profile_chrome()
            options, driver, actions, wait = createChromeSession()
        except SessionNotCreatedException as e:
            critical_error_log("Failed to create Chrome Session, retrying with guest profile", e)
            options, driver, actions, wait = createChromeSession(True)
except Exception as e:
    msg = 'Seems like Google Chrome is out dated. Update browser and try again! \n\n\nIf issue persists, try Safe Mode. Set, safe_mode = True in config.py \n\nPlease check GitHub discussions/support for solutions https://github.com/GodsScion/Auto_job_applier_linkedIn \n                                   OR \nReach out in discord ( https://discord.gg/fFp7uUzWCY )'
    if isinstance(e,TimeoutError): msg = "Couldn't download Chrome-driver. Set auto_manage_driver = False in config!"
    print_lg(msg)
    critical_error_log("In Opening Chrome", e)
    from pyautogui import alert
    alert(msg, "Error in opening chrome")
    if driver is not None:
        try: driver.quit()
        except Exception: pass
    sys.exit()
    
