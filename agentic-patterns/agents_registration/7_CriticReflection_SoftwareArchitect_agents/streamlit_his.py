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

SOFTWARE_AGENT_ID = "software-agent"
ARCHITECT_AGENT_ID = "senior-architect-agent"

SUBMIT_URL_TEMPLATE = HIS_BASE_URL + "/subject-responses/{id}/set-response"

st.set_page_config(page_title="Architecture Debater - HIS", layout="wide")

# --- Custom CSS for Sticky Tabs and Condensed UI ---
st.markdown("""
    <style>
    /* Ensure the main container doesn't hide sticky elements */
    .main .block-container {
        padding-top: 2rem !important;
    }
    
    /* Target the Tabs bar specifically */
    div[data-testid="stTabs"] [data-baseweb="tab-list"] {
        position: sticky !important;
        top: 60px !important;  /* Position it below the top app header */
        background-color: white !important;
        z-index: 1000 !important;
        padding: 10px 0 !important;
        border-bottom: 2px solid #f0f2f6 !important;
    }

    /* Dark mode support */
    @media (prefers-color-scheme: dark) {
        div[data-testid="stTabs"] [data-baseweb="tab-list"] {
            background-color: #0e1117 !important;
            border-bottom: 2px solid #262730 !important;
        }
    }
    
    /* Reduce vertical spacing for condensed look */
    .stExpander {
        margin-bottom: 0.2rem !important;
    }
    .stExpander > div > div > div {
        padding: 0.5rem 1rem !important;
    }
    </style>
    """, unsafe_allow_html=True)

st.title("🏗️ Architecture Debater HIS Dashboard")
st.markdown("Monitor the collaborative design process between the Software Generator and Senior Architect.")

# --- Functions ---

def fetch_responses(subject_id):
    url = f"{HIS_BASE_URL}/subject-responses/by-subject/{subject_id}"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            if data.get("ok"):
                res_list = data.get("data", [])
                res_list.sort(key=lambda x: x.get("creation_time", 0), reverse=True)
                return res_list
        return []
    except Exception as e:
        st.error(f"Error fetching data for {subject_id}: {e}")
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

def clear_all_pending():
    """Iterates through all pending responses for both agents and completes them."""
    with st.spinner("Clearing all pending items..."):
        all_cleared = 0
        for subject_id in [SOFTWARE_AGENT_ID, ARCHITECT_AGENT_ID]:
            responses = fetch_responses(subject_id)
            pending = [r for r in responses if r.get("status") == "pending"]
            for op in pending:
                url = SUBMIT_URL_TEMPLATE.format(id=op.get('id'))
                payload = {
                    "response_data": {},
                    "status": "COMPLETED"
                }
                try:
                    res = requests.post(url, json=payload, timeout=5)
                    if res.status_code == 200:
                        all_cleared += 1
                except Exception as e:
                    st.error(f"Failed to clear {op.get('id')}: {e}")
        
    if all_cleared > 0:
        st.success(f"Successfully cleared {all_cleared} pending items!")
        time.sleep(1)
        st.rerun()
    else:
        st.info("No pending items found to clear.")

def delete_all():
    """Fetches all responses for both agents and deletes each one."""
    with st.spinner("Deleting all responses..."):
        deleted_count = 0
        for subject_id in [SOFTWARE_AGENT_ID, ARCHITECT_AGENT_ID]:
            responses = fetch_responses(subject_id)
            for resp in responses:
                response_id = resp.get("id")
                if response_id:
                    url = f"{HIS_BASE_URL}/subject-responses/{response_id}"
                    try:
                        res = requests.delete(url, timeout=5)
                        if res.status_code == 200:
                            deleted_count += 1
                    except Exception as e:
                        st.error(f"Failed to delete {response_id}: {e}")
        
    if deleted_count > 0:
        st.success(f"Successfully deleted {deleted_count} responses!")
        time.sleep(1)
        st.rerun()
    else:
        st.info("No responses found to delete.")

def display_merged_timeline():
    sw_responses = fetch_responses(SOFTWARE_AGENT_ID)
    arch_responses = fetch_responses(ARCHITECT_AGENT_ID)
    
    # Tag each response for column placement
    for r in sw_responses: r["column"] = 0
    for r in arch_responses: r["column"] = 1
    
    all_responses = sw_responses + arch_responses
    # Sort by time descending (latest at top)
    all_responses.sort(key=lambda x: x.get("creation_time", 0), reverse=True)
    
    if not all_responses:
        st.info("No debate data found yet. Waiting for agents to start...")
        return

    # Header for columns
    col_sw, col_arch = st.columns(2)
    with col_sw:
        st.subheader("🏗️ Software Agent")
    with col_arch:
        st.subheader("🔍 Senior Architect")
    st.divider()

    for op in all_responses:
        col_idx = op["column"]
        cols = st.columns(2)
        with cols[col_idx]:
            creation_time = op.get("creation_time", 0)
            ts = datetime.datetime.fromtimestamp(creation_time).strftime('%H:%M:%S')
            status = op.get("status", "unknown")
            status_icon = "🔴" if status == "pending" else "⚪"
            
            # Extract a snippet for the header
            input_text = op.get("input_data", {}).get("text", "")
            snippet = (input_text[:80] + "...") if len(input_text) > 80 else input_text
            snippet = snippet.replace("\n", " ")
            
            label = f"{status_icon} [{ts}] {snippet}"
            
            with st.expander(label, expanded=False):
                draw_response_card(op)

def draw_response_card(op):
    st.write("📅 **Full Timestamp:**", datetime.datetime.fromtimestamp(op.get("creation_time")).strftime('%Y-%m-%d %H:%M:%S'))
    st.write(f"🆔 **ID:** `{op.get('id')}`  |  **Status:** {op.get('status').upper()}")
    
    input_data = op.get("input_data", {})
    st.markdown("---")
    st.markdown("**Message Content:**")
    st.markdown(input_data.get("text", "No content found."))
    
    if input_data.get("Analysis"):
        st.info(f"**Analysis:** {input_data.get('Analysis')}")
    elif input_data.get("reasoning"):
        st.info(f"**Reasoning:** {input_data.get('reasoning')}")
    
    if input_data.get("feedback"):
        st.warning(f"**Critique/Feedback:** {input_data.get('feedback')}")

    if op.get("status") == "pending":
        st.subheader("Your Intervention")
        user_input = st.text_area("Inject feedback or manually approve:", key=f"input_{op.get('id')}")
        if st.button("Submit Intervention", key=f"btn_{op.get('id')}"):
            if user_input.strip():
                if submit_response(op.get('id'), user_input):
                    st.rerun()
            else:
                st.warning("Please enter content before submitting.")

# --- Main Layout ---

display_merged_timeline()

# Sidebar
st.sidebar.header("Control Panel")
if st.sidebar.button("Refresh Dashboard"):
    st.rerun()

if st.sidebar.button("🗑️ Clear All Pending"):
    clear_all_pending()

if st.sidebar.button("🔥 Delete All"):
    delete_all()

st.sidebar.divider()
st.sidebar.write("🟢 **Auto-refresh Every 10s**")
st.sidebar.info(f"Watching: \n- {SOFTWARE_AGENT_ID}\n- {ARCHITECT_AGENT_ID}")
st.sidebar.caption(f"HIS API: {HIS_BASE_URL}")
