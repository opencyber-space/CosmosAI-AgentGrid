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


# Team Mapping to Agent IDs
TEAM_MAPPING = {
    "CEO Team": ["company-ceo-agent"],
    "COS Team": ["company-chief-of-staff-agent"],
    "Architecture Team": [
        "company-arch-design-team-lead", 
        "company-arch-senior-agent", 
        "company-arch-junior-agent"
    ],
    "Finance Team": [
        "company-financial-team-lead", 
        "company-financial-strategist-agent", 
        "company-financial-controller-agent", 
        "company-financial-accountant-agent"
    ],
    "Marketing Team": [
        "company-marketing-team-lead", 
        "company-marketing-strategy-agent", 
        "company-marketing-planning-agent", 
        "company-marketing-content-agent", 
        "company-marketing-visual-agent"
    ],
    "Developer Team": [
        "company-developer-team-lead", 
        "company-dev-frontend-agent", 
        "company-dev-backend-agent",
    ],
    "Testing Team": [
        "company-testing-team-lead", 
        "company-testing-dev-agent",
    ]
}

SUBMIT_URL_TEMPLATE = HIS_BASE_URL + "/subject-responses/{id}/set-response"

st.set_page_config(page_title="Hierarchical Agents - HIS", layout="wide")

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
    
    .agent-header {
        font-size: 1.1em;
        font-weight: 600;
        margin-bottom: 15px;
        text-align: center;
        padding: 10px;
        background-color: #f0f2f6;
        border-radius: 5px;
    }
    
    /* Hover Tooltip for Payloads */
    .payload-tooltip-container {
        position: relative;
        display: block;
        width: 100%;
        background-color: #e2e6ea;
        padding: 8px;
        border: 1px dashed #adb5bd;
        text-align: center;
        cursor: help;
        border-radius: 4px;
        margin-bottom: 10px;
        transition: background-color 0.2s;
    }
    .payload-tooltip-container:hover {
        background-color: #ced4da;
    }
    .payload-preview {
        font-weight: 600;
        color: #212529;
    }
    .tooltip-text {
        visibility: hidden;
        opacity: 0;
        position: fixed; 
        z-index: 999999;
        left: 50%;
        top: 50%;
        transform: translate(-50%, -50%);
        background-color: #1e1e1e;
        color: #d4d4d4;
        text-align: left;
        border-radius: 8px;
        padding: 20px;
        box-shadow: 0px 10px 40px rgba(0,0,0,0.6);
        border: 1px solid #444;
        transition: opacity 0.15s, visibility 0.15s;
        width: 85vw;
        max-height: 85vh;
        overflow-y: auto;
        overflow-x: auto;
        cursor: auto;
    }
    @media (prefers-color-scheme: dark) {
        .payload-tooltip-container {
            background-color: #262730;
            border-color: #555;
        }
        .payload-tooltip-container:hover {
            background-color: #333;
        }
        .payload-preview {
            color: #fafafa;
        }
    }
    .payload-tooltip-container:hover .tooltip-text {
        visibility: visible;
        opacity: 1;
    }
    .tooltip-text code {
        white-space: pre-wrap !important;
        word-wrap: break-word !important;
        font-family: inherit; /* use regular font in json preview */
        font-size: 14px;
        color: #9cdcfe;
    }
    
    /* Condensed Item Card */
    .condensed-item {
        position: relative;
        display: block;
        width: 100%;
        background-color: #ffffff;
        padding: 12px;
        border: 1px solid #e6e6e6;
        text-align: left;
        cursor: pointer;
        border-radius: 8px;
        margin-bottom: 10px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        transition: all 0.2s;
        font-family: sans-serif;
        font-size: 14px;
    }
    .condensed-item:hover {
        border-color: #b3b3b3;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    @media (prefers-color-scheme: dark) {
        .condensed-item {
            background-color: #1e1e1e;
            border-color: #444;
            color: #eee;
        }
        .condensed-item:hover {
            border-color: #666;
        }
    }
    .condensed-item:hover .tooltip-text {
        visibility: visible;
        opacity: 1;
    }
    </style>
    """, unsafe_allow_html=True)

st.title("👨‍💼 Hierarchical Software Company Dashboard")
st.markdown("Live monitor of inter-agent messages, delegates, and P2P communication across all functional teams.")

# --- Functions ---

def fetch_responses(subject_id):
    url = f"{HIS_BASE_URL}/subject-responses/by-subject/{subject_id}"
    try:
        response = requests.get(url, timeout=5)
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

def clear_all_data():
    """Iterates through all known agents and deletes their responses."""
    with st.spinner("Deleting all responses..."):
        deleted_count = 0
        all_agents = []
        for agents in TEAM_MAPPING.values():
            all_agents.extend(agents)
            
        for subject_id in all_agents:
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
        st.success(f"Successfully deleted {deleted_count} messages across the system!")
        time.sleep(1)
        st.rerun()
    else:
        st.info("No messages found to delete.")

def format_json_safely(data):
    try:
        if isinstance(data, str):
            # Try parsing the string to JSON first
            if data.startswith("{") or data.startswith("["):
                try:
                    parsed = json.loads(data)
                    return json.dumps(parsed, indent=2)
                except : pass
        elif isinstance(data, dict) or isinstance(data, list):
            return json.dumps(data, indent=2)
    except Exception:
        pass
    return str(data)

def draw_response_card(op):
    input_data = op.get("input_data", {})
    ts = datetime.datetime.fromtimestamp(op.get("creation_time", 0)).strftime('%Y-%m-%d %H:%M:%S')
    
    st.caption(f"📅 **Time:** {ts}")
    st.caption(f"🆔 **ID:** `{op.get('id')}`")
    
    # Dest extraction
    destination_id = input_data.get("destination_id", "Unknown Destination")
    st.markdown(f"**To:** `{destination_id}`")
    
    st.markdown("---")
    
    # Text Payload extraction
    text_content = input_data.get("text", "")
    
    if text_content:
        # Check if text looks like a python repr dict (e.g. `{'task_type': ..., ...}`)
        # or proper json and format it nicely
        if str(text_content).startswith("{"):
            st.markdown("**Payload:**")
            
            formatted_json = format_json_safely(text_content)
            
            import html
            safe_json = html.escape(formatted_json)
            
            html_string = f"""
            <div class="payload-tooltip-container">
                <div class="payload-preview">🔍 Hover to Enlarge JSON Payload</div>
                <div class="tooltip-text">
                    <pre><code>{safe_json}</code></pre>
                </div>
            </div>
            """
            st.markdown(html_string, unsafe_allow_html=True)
            st.code(formatted_json, language="json")
        else:
            st.markdown("**Message:**")
            st.write(text_content)
    else:
        st.write("No text payload.")

def display_team_timeline(team_name, agent_ids):
    st.subheader(f"🏢 {team_name} Communications")
    st.divider()
    
    # Fetch data concurrently for this team and tag them
    all_team_messages = []
    for agent_id in agent_ids:
        responses = fetch_responses(agent_id)
        for r in responses:
            r["agent_context"] = agent_id
        all_team_messages.extend(responses)
        
    # Check if we have any data to show
    if len(all_team_messages) == 0:
        st.info(f"No messages found for {team_name} yet. Waiting for agents to communicate...")
        return
        
    # Sort ALL messages globally by time (descending: newest at the top, or ascending if we want reading order)
    # The original was reverse=True so newest at top
    all_team_messages.sort(key=lambda x: x.get("creation_time", 0), reverse=True)
    
    # Render Headers
    header_cols = st.columns(len(agent_ids))
    for idx, agent_id in enumerate(agent_ids):
        with header_cols[idx]:
            st.markdown(f"<div class='agent-header'>🤖 {agent_id}</div>", unsafe_allow_html=True)
            
    # Render Messages Row by Row
    for op in all_team_messages:
        cols = st.columns(len(agent_ids))
        
        agent_id = op["agent_context"]
        col_idx = agent_ids.index(agent_id)
        
        with cols[col_idx]:
            input_data = op.get("input_data", {})
            dest_raw = str(input_data.get("destination_id", "Unknown"))
            dest = dest_raw.replace("company-", "") if dest_raw.startswith("company-") else dest_raw
            
            # Extract task type label
            text_content = str(input_data.get("text", ""))
            task_type_label = ""
            if "'task_type': " in text_content:
                try:
                    import re
                    task_type_match = re.search(r"'task_type':\s*'([^']+)'", text_content)
                    if task_type_match:
                        task_type_label = f"[{task_type_match.group(1).upper()}]"
                except: pass
            
            ts = datetime.datetime.fromtimestamp(op.get("creation_time", 0)).strftime('%H:%M:%S')
            
            # Format payload safely
            formatted_json = format_json_safely(text_content)
            import html
            safe_json = html.escape(formatted_json)
            safe_dest = html.escape(dest)
            safe_task_type = html.escape(task_type_label)
            
            # Render custom HTML card instead of st.expander -> it triggers hover tooltip natively!
            html_string = f"""<div class="condensed-item"><div style="font-weight: 600; margin-bottom: 4px; display: flex; justify-content: space-between;"><span>To: {safe_dest}</span><span style="color: #888; font-weight: 400; font-size: 12px;">[{ts}]</span></div><div style="font-size: 12px; color: #0066cc; margin-bottom: 2px;">{safe_task_type}</div><div style="font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: #888;">{safe_json[:100]}...</div><div class="tooltip-text"><div style="margin-bottom: 10px; padding-bottom: 10px; border-bottom: 1px solid #444;"><span style="color: #9cdcfe; font-weight: bold;">Destination:</span> {safe_dest} <br/><span style="color: #9cdcfe; font-weight: bold;">Time:</span> {ts}</div><pre style="margin: 0; padding: 0;"><code>{safe_json}</code></pre></div></div>"""
            st.markdown(html_string, unsafe_allow_html=True)


# --- Tabs UI ---
tab_names = list(TEAM_MAPPING.keys())
tabs = st.tabs(tab_names)

for idx, tab in enumerate(tabs):
    with tab:
        team_name = tab_names[idx]
        agent_ids = TEAM_MAPPING[team_name]
        display_team_timeline(team_name, agent_ids)


# --- Sidebar ---
st.sidebar.header("Control Panel")
if st.sidebar.button("Refresh Dashboard"):
    st.rerun()

st.sidebar.divider()
if st.sidebar.button("🔥 Delete ALL Messages"):
    if st.sidebar.checkbox("Confirm Delete All Data"):
        clear_all_data()
    else:
        st.sidebar.warning("Check the box above to confirm.")

st.sidebar.divider()
st.sidebar.write("🟢 **Auto-refresh Every 10s**")
st.sidebar.caption(f"HIS API: {HIS_BASE_URL}")

