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


###################################################### CONFIGURE YOUR BOT HERE ######################################################

# >>>>>>>>>>> LinkedIn Settings <<<<<<<<<<<

# Keep the External Application tabs open?
close_tabs = False                  # True or False, Note: True or False are case-sensitive
'''
Note: RECOMMENDED TO LEAVE IT AS `True`, if you set it `False`, be sure to CLOSE ALL TABS BEFORE CLOSING THE BROWSER!!!
'''

# Follow easy applied companies
follow_companies = False            # True or False, Note: True or False are case-sensitive

## >>>>>>>>>>> REFERRAL MESSAGING <<<<<<<<<<<

# Master switch for auto-sending referral messages via LinkedIn DM and/or Gmail
send_referral_dms = False           # True or False, Note: True or False are case-sensitive

# Which channels to use for sending referral messages
send_via_linkedin = True            # True or False — send via LinkedIn DM
send_via_gmail = True               # True or False — send via Gmail email

# LinkedIn DM template — uses {variable} placeholders
linkedin_dm_template = """Hi {employee_name},

I'm {your_name}, {your_role} at {your_company}. I'm reaching out because the {job_title} role at {company_name} lines up closely with my experience.

Would you be open to referring me? Here's the job: {job_link}

Best regards,
{your_name}"""

# Connection request note (used when the person is NOT already connected, so we
# can't DM them). LinkedIn caps the personal note at 300 characters, so this is
# intentionally short. Used by the connect-with-note outreach path.
linkedin_connect_note = "Hi {employee_name}, I'm {your_name}, {your_role} at {your_company}. I'd love a referral for the {job_title} role at {company_name}. Would be great to connect! {job_link}"

# Gmail subject line — uses {variable} placeholders
gmail_subject = "Applying for {job_title} at {company_name} \u2013 can you help with referral?"

# Gmail body template — uses {variable} placeholders
gmail_body = """Hi {employee_name},

I'm {your_name}, currently a {your_role} at {your_company} with about 3 years of hands-on experience delivering customer-facing solutions. I'm reaching out because the {job_title} role at {company_name} lines up closely with the way I work: ship fast, learn even faster, and solve real user problems with pragmatic AI and automation.

What I bring: emerging talent with rapid learning potential, plus deep, practical expertise in CLI and Zapier. I've built internal CLIs that streamline developer workflows, automated complex cross-app processes with Zapier and Make, and used Grok and Claude to power robust agentic and retrieval-driven features. In a forward-deployed capacity, I translate ambiguous requirements into shipped solutions\u2014exactly the kind of bias to action and systems thinking a strong {job_title} at {company_name} needs.

I'm particularly excited about {company_name} because of its bar for execution and learning culture. I thrive in environments where customer impact, thoughtful tooling, and reliable automation matter.

Would you be open to referring me? If helpful, you can skim my background here as well: {your_linkedin}

Here is the link to the job: {job_link}

Best regards,
{your_name}
{your_portfolio}"""

# Seconds to wait between messages (randomized, anti-detection)
referral_dm_delay = 45              # Only Non Negative Integers

# Max messages to send per channel per run
referral_dm_max = 10                # Only Non Negative Integers


## Upcoming features (In Development)
# # Send connection requests to HR's 
# connect_hr = True                  # True or False, Note: True or False are case-sensitive

# # What message do you want to send during connection request? (Max. 200 Characters)
# connect_request_message = ""       # Leave Empty to send connection request without personalized invitation (recommended to leave it empty, since you only get 10 per month without LinkedIn Premium*)

# Do you want the program to run continuously until you stop it? (Beta)
run_non_stop = False                # True or False, Note: True or False are case-sensitive
'''
Note: Will be treated as False if `run_in_background = True`
'''
alternate_sortby = True             # True or False, Note: True or False are case-sensitive
cycle_date_posted = True            # True or False, Note: True or False are case-sensitive
stop_date_cycle_at_24hr = True      # True or False, Note: True or False are case-sensitive





# >>>>>>>>>>> RESUME GENERATOR (Experimental & In Development) <<<<<<<<<<<

# Give the path to the folder where all the generated resumes are to be stored
generated_resume_path = "all resumes/" # (In Development)





# >>>>>>>>>>> Global Settings <<<<<<<<<<<

# Directory and name of the files where history of applied jobs is saved (Sentence after the last "/" will be considered as the file name).
file_name = "all excels/all_applied_applications_history.csv"
failed_file_name = "all excels/all_failed_applications_history.csv"
logs_folder_path = "logs/"

# Set the maximum amount of time allowed to wait between each click in secs
click_gap = 1                       # Enter max allowed secs to wait approximately. (Only Non Negative Integers Eg: 0,1,2,3,....)

# If you want to see Chrome running then set run_in_background as False (May reduce performance). 
run_in_background = False           # True or False, Note: True or False are case-sensitive ,   If True, this will make pause_at_failed_question, pause_before_submit and run_in_background as False

# If you want to disable extensions then set disable_extensions as True (Better for performance)
disable_extensions = False          # True or False, Note: True or False are case-sensitive

# Run in safe mode. Set this true if chrome is taking too long to open or if you have multiple profiles in browser. This will open chrome in guest profile!
safe_mode = True                    # True or False, Note: True or False are case-sensitive

# Do you want scrolling to be smooth or instantaneous? (Can reduce performance if True)
smooth_scroll = False               # True or False, Note: True or False are case-sensitive

# If enabled (True), the program would keep your screen active and prevent PC from sleeping. Instead you could disable this feature (set it to false) and adjust your PC sleep settings to Never Sleep or a preferred time. 
keep_screen_awake = True            # True or False, Note: True or False are case-sensitive (Note: Will temporarily deactivate when any application dialog boxes are present (Eg: Pause before submit, Help needed for a question..))

# Automatically download and manage the matching Chrome driver, so you don't have to install ChromeDriver yourself. If False, you must install a matching ChromeDriver manually (see setup step 5).
auto_manage_driver = True          # True or False, Note: True or False are case-sensitive

# Do you want to get alerts on errors related to AI API connection?
showAiErrorAlerts = False            # True or False, Note: True or False are case-sensitive

# Use ChatGPT for resume building (Experimental Feature can break the application. Recommended to leave it as False) 
# use_resume_generator = False       # True or False, Note: True or False are case-sensitive ,   This experimental feature may only work with 'auto_manage_driver = True'.











############################################################################################################
'''
THANK YOU for using my tool 😊! Wishing you the best in your job hunt 🙌🏻!

Sharing is caring! If you found this tool helpful, please share it with your peers 🥺. Your support keeps this project alive.

Support my work on <PATREON_LINK>. Together, we can help more job seekers.

As an independent developer, I pour my heart and soul into creating tools like this, driven by the genuine desire to make a positive impact.

Your support, whether through donations big or small or simply spreading the word, means the world to me and helps keep this project alive and thriving.

Gratefully yours 🙏🏻,
Sai Vignesh Golla
'''

# --- Load user settings saved by the local control panel (user_config.json).
# --- No-op if that file is absent: values fall back to the defaults above.
from config import _overrides as _o
_o.apply(__name__, globals())
############################################################################################################