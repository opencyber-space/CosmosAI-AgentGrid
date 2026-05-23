import streamlit as st
import requests
import datetime
import json
import time

# --- Configuration ---
import os
from dotenv import load_dotenv

# Find .env by walking up to the directory containing .git
def find_git_root(path):
    current = os.path.abspath(path)
    while True:
        if os.path.exists(os.path.join(current, '.git')):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent

_git_root = find_git_root(__file__)
if _git_root:
    load_dotenv(os.path.join(_git_root, '.env'))
else:
    load_dotenv()

HIS_BASE_URL = os.environ["HIS_BASE_URL"]

SUBJECT_ID = "movieplanner-bookmyshow-agent"
FETCH_URL = f"{HIS_BASE_URL}/subject-responses/by-subject/{SUBJECT_ID}"
SUBMIT_URL_TEMPLATE = HIS_BASE_URL + "/subject-responses/{id}/set-response"

st.set_page_config(page_title="Movie Planner - Human in the Loop", layout="wide")

st.title("🎬 Movie Planner HIS Dashboard")
st.markdown("Use this dashboard to review and approve movie recommendations.")

# --- Functions ---

def fetch_pending_responses():
    try:
        response = requests.get(FETCH_URL)
        if response.status_code == 200:
            data = response.json()
            if data.get("ok"):
                return [r for r in data.get("data", []) if r.get("status") == "pending"]
        return []
    except Exception as e:
        st.error(f"Error fetching data: {e}")
        return []

def submit_response(response_id, user_choice):
    url = SUBMIT_URL_TEMPLATE.format(id=response_id)
    payload = {
        "response_data": {
            "user_choice": user_choice
        },
        "status": "COMPLETED"
    }
    try:
        res = requests.post(url, json=payload)
        if res.status_code == 200:
            st.success("Response submitted successfully!")
            return True
        else:
            st.error(f"Failed to submit response: {res.text}")
            return False
    except Exception as e:
        st.error(f"Error submitting response: {e}")
        return False

# --- UI Logic ---

pending_ops = fetch_pending_responses()

if not pending_ops:
    st.info("No pending requests found. Polling...")
    if st.button("Refresh Now"):
        st.rerun()
    time.sleep(5)
    st.rerun()

else:
    for idx, op in enumerate(pending_ops):
        with st.container():
            st.divider()
            col1, col2 = st.columns([1, 2])
            
            with col1:
                st.subheader("Request Info")
                # Format creation_time
                creation_time = op.get("creation_time")
                if creation_time:
                    dt_object = datetime.datetime.fromtimestamp(creation_time)
                    st.write(f"📅 **Time:** {dt_object.strftime('%Y-%m-%d %H:%M:%S')}")
                
                st.code(f"ID: {op.get('id')}", language="text")
                st.info(f"Status: {op.get('status').upper()}")

            with col2:
                st.subheader("Task Details")
                input_data = op.get("input_data", {})
                st.write(f"📝 **Task:** {input_data.get('task')}")
                st.markdown(f"**Description:** \n\n {input_data.get('text')}")
                if input_data.get("Analysis"):
                    st.info(f"**Analysis (Reasoning):** \n\n {input_data.get('Analysis')}")

            # Feedback Input
            st.subheader("Your Decision")
            user_input = st.text_area("Enter your feedback or choice:", key=f"input_{op.get('id')}", placeholder="e.g., I'll go with the PVR Cinemas option at 20:00")
            
            if st.button("Submit Choice", key=f"btn_{op.get('id')}"):
                if user_input.strip():
                    if submit_response(op.get('id'), user_input):
                        st.info("Refreshing list...")
                        time.sleep(2)
                        st.rerun()
                else:
                    st.warning("Please enter some feedback before submitting.")

    st.divider()
    if st.button("Manual Refresh"):
        st.rerun()

# Sidebar
st.sidebar.header("System Settings")
st.sidebar.write(f"**Target Subject:** {SUBJECT_ID}")
st.sidebar.write(f"**HIS API:** {HIS_BASE_URL}")
st.sidebar.caption("Polling every 5 seconds when no requests are pending.")
