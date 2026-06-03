import streamlit as st
import requests
import datetime
import json
import time
import html
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
    "Legal Workflow": [
        "clause-extractor-agent-2",
        "simple-workflow-router-agent",
        "risk-identifier-agent-2",
        "compliance-checker-agent-2",
        "negotiation-adviser-agent-2",
        "legal-memo-agent-2"
    ]
}

SUBMIT_URL_TEMPLATE = HIS_BASE_URL + "/subject-responses/{id}/set-response"

st.set_page_config(
    page_title="Hierarchical Agents - HIS",
    layout="wide",
    initial_sidebar_state="expanded"
)

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
    
    .agent-header {
        font-size: 1.1em;
        font-weight: 600;
        margin-bottom: 15px;
        text-align: center;
        padding: 10px;
        background-color: #f0f2f6;
        border-radius: 5px;
    }
    
    /* Condensed Item Card exactly matching 111111111.png */
    .condensed-item {
        position: relative;
        display: block;
        width: 100%;
        background-color: #ffffff;
        padding: 14px;
        border: 1px solid #e2e8f0;
        text-align: left;
        cursor: pointer;
        border-radius: 8px;
        margin-bottom: 12px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        transition: all 0.2s;
        font-family: sans-serif;
    }
    .condensed-item:hover {
        border-color: #cbd5e1;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
    }
    @media (prefers-color-scheme: dark) {
        .condensed-item {
            background-color: #1e1e1e;
            border-color: #334155;
            color: #eee;
        }
        .condensed-item:hover {
            border-color: #475569;
        }
    }
    
    /* Hover Tooltip for Quick Previews */
    .tooltip-text {
        visibility: hidden;
        opacity: 0;
        position: fixed; 
        z-index: 99999;
        left: 50%;
        top: 50%;
        transform: translate(-50%, -50%);
        background-color: #1e1e1e;
        color: #d4d4d4;
        text-align: left;
        border-radius: 8px;
        padding: 20px;
        box-shadow: 0px 10px 40px rgba(0,0,0,0.6);
        border: 1px solid #444444;
        transition: opacity 0.15s, visibility 0.15s;
        width: 65vw;
        max-height: 40vh;
        overflow: hidden;
        cursor: auto;
        pointer-events: auto; /* Allow mouse hover and interaction inside tooltip */
    }
    .condensed-item:hover .tooltip-text {
        visibility: visible;
        opacity: 1;
    }
    
    /* Enlarge Button inside Card */
    .enlarge-btn {
        position: absolute;
        bottom: 8px;
        right: 8px;
        background-color: #0066cc;
        color: white !important;
        text-decoration: none !important;
        padding: 3px 8px;
        font-size: 10px;
        border-radius: 4px;
        font-weight: bold;
        transition: background-color 0.2s;
        z-index: 10;
    }
    .enlarge-btn:hover {
        background-color: #004499;
    }

    /* Enlarge Button inside Hover Tooltip */
    .tooltip-enlarge-btn {
        position: absolute !important;
        top: 15px !important;
        right: 15px !important;
        background-color: #0066cc !important;
        color: white !important;
        text-decoration: none !important;
        padding: 5px 10px !important;
        font-size: 11px !important;
        border-radius: 4px !important;
        font-weight: bold !important;
        transition: background-color 0.2s !important;
        z-index: 100000 !important;
    }
    .tooltip-enlarge-btn:hover {
        background-color: #004499 !important;
    }

    /* Modal Overlay (Target based) */
    .timeline-modal {
        display: none;
        position: fixed;
        top: 0;
        left: 0;
        width: 100vw;
        height: 100vh;
        background-color: rgba(0, 0, 0, 0.75);
        z-index: 9999999;
        justify-content: center;
        align-items: center;
    }
    
    .timeline-modal:target {
        display: flex;
    }

    /* Modal Content Box - Highly compact and focused layout */
    .modal-content {
        background-color: #1a1a1a;
        color: #e2e8f0;
        width: 70vw;
        max-height: 75vh;
        padding: 24px;
        border-radius: 12px;
        border: 1px solid #334155;
        box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.7);
        position: relative;
        overflow: hidden;
        display: flex;
        flex-direction: column;
    }

    /* Close Button inside Modal */
    .modal-close-btn {
        position: absolute;
        top: 15px;
        right: 20px;
        font-size: 28px;
        font-weight: bold;
        color: #94a3b8 !important;
        text-decoration: none !important;
        cursor: pointer;
        transition: color 0.2s;
        z-index: 100;
    }
    .modal-close-btn:hover {
        color: #ffffff !important;
    }

    /* Absolute Custom Overrides to completely crush Streamlit's white/light code themes */
    .modal-content pre {
        background-color: #111111 !important;
        color: #9cdcfe !important;
        border: 1px solid #334155 !important;
        border-radius: 6px !important;
        padding: 16px !important;
        margin: 0 !important;
        font-family: monospace !important;
        font-size: 13px !important;
        white-space: pre-wrap !important;
        word-wrap: break-word !important;
        overflow-y: auto !important;
        overflow-x: auto !important;
        max-height: 48vh !important;
        flex-grow: 1;
        display: block !important;
    }
    
    .modal-content code {
        background-color: transparent !important;
        color: #9cdcfe !important;
        font-family: monospace !important;
        font-size: 13px !important;
        white-space: pre-wrap !important;
        word-wrap: break-word !important;
        border: none !important;
        padding: 0 !important;
    }

    /* Beautiful Scrollbar styles for the expanded view pre box */
    .modal-content pre::-webkit-scrollbar {
        width: 8px !important;
        height: 8px !important;
    }
    .modal-content pre::-webkit-scrollbar-track {
        background: #111111 !important;
        border-radius: 4px !important;
    }
    .modal-content pre::-webkit-scrollbar-thumb {
        background: #475569 !important;
        border-radius: 4px !important;
    }
    .modal-content pre::-webkit-scrollbar-thumb:hover {
        background: #64748b !important;
        border-radius: 4px !important;
    }
    </style>
    """, unsafe_allow_html=True)

st.title("⚖️ Legal Workflow Dashboard")
st.markdown("Live monitor of the linear agent sequence execution.")

# --- Functions ---

def fetch_responses(subject_id):
    url = f"{HIS_BASE_URL}/subject-responses/by-subject/{subject_id}"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data.get("ok"):
                res_list = data.get("data", [])
                for x in res_list:
                    precise_ts = x.get("input_data", {}).get("timestamp")
                    x["precise_time"] = float(precise_ts) if precise_ts is not None else x.get("creation_time", 0)
                
                res_list.sort(key=lambda x: x["precise_time"], reverse=True)
                return res_list
        return []
    except Exception as e:
        st.error(f"Error fetching data for {subject_id}: {e}")
        return []

def clear_all_data():
    """Iterates through all known agents and deletes their responses."""
    print("👉 [Streamlit] [BUTTON CLICK] 'Delete All' Pressed! Purging sequentially...")
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
                    return parsed
                except : pass
                
                try:
                    import ast
                    parsed = ast.literal_eval(data)
                    if isinstance(parsed, (dict, list)):
                        return parsed
                except:
                    pass
        elif isinstance(data, dict) or isinstance(data, list):
            return data
    except Exception:
        pass
    return data

def json_to_html(data, open_attr="open", level=0):
    """Recursively converts a JSON dictionary or list into a collapsible HTML structure."""
    if isinstance(data, dict):
        if not data:
            return "<span style='color:#ce9178;'>{}</span>"
        html = f'<details {open_attr} style="margin-left:{level*15}px;"><summary style="cursor:pointer; font-weight:bold; color:#dcdcaa;">{'{'}</summary>'
        for k, v in data.items():
            html += f'<div style="margin-left: 20px;"><span style="color:#9cdcfe;">"{k}"</span>: '
            html += json_to_html(v, open_attr="", level=level+1)
            html += "</div>"
        html += f'<div style="color:#dcdcaa; font-weight:bold;">{'}'}</div></details>'
        return html
    elif isinstance(data, list):
        if not data:
            return "<span style='color:#ce9178;'>[]</span>"
        html = f'<details {open_attr} style="margin-left:{level*15}px;"><summary style="cursor:pointer; font-weight:bold; color:#4ec9b0;">[ Array ({len(data)}) ]</summary>'
        for i, item in enumerate(data):
            html += f'<div style="margin-left: 20px; margin-bottom: 2px;">'
            html += json_to_html(item, open_attr="", level=level+1)
            html += "</div>"
        html += f'<div style="color:#4ec9b0; font-weight:bold;">]</div></details>'
        return html
    elif isinstance(data, str):
        import html
        return f'<span style="color:#ce9178;">"{html.escape(data)}"</span>'
    elif isinstance(data, bool):
        return f'<span style="color:#569cd6;">{"true" if data else "false"}</span>'
    elif data is None:
        return f'<span style="color:#569cd6;">null</span>'
    else:
        return f'<span style="color:#b5cea8;">{data}</span>'

def draw_response_card(op):
    input_data = op.get("input_data", {})
    ts = datetime.datetime.fromtimestamp(op.get("creation_time", 0)).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    
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
        
    # Render Headers FIRST, so we always see the agents
    header_cols = st.columns(len(agent_ids))
    for idx, agent_id in enumerate(agent_ids):
        with header_cols[idx]:
            st.markdown(f"<div class='agent-header'>🤖 {agent_id}</div>", unsafe_allow_html=True)

    # Check if we have any data to show
    if len(all_team_messages) == 0:
        st.info(f"No messages found for {team_name} yet. Waiting for agents to communicate...")
        return
        
    # Sort ALL messages globally by precise time (descending: newest at the top)
    all_team_messages.sort(key=lambda x: x.get("precise_time", x.get("creation_time", 0)), reverse=True)
            
    # Render Messages Row by Row (Limit to latest 50 to prevent Streamlit UI from hanging/crashing)
    for op in all_team_messages[:50]:
        cols = st.columns(len(agent_ids))
        
        agent_id = op["agent_context"]
        col_idx = agent_ids.index(agent_id)
        
        with cols[col_idx]:
            input_data = op.get("input_data", {})
            dest = input_data.get("destination_id", "Unknown")
            source = input_data.get("source_id", "Unknown")
            
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
            
            precise_t = op.get("precise_time", op.get("creation_time", 0))
            ts = datetime.datetime.fromtimestamp(precise_t).strftime('%H:%M:%S.%f')[:-3]
            
            # Format payload safely
            raw_json = format_json_safely(text_content)
                
            safe_dest = html.escape(dest)
            safe_source = html.escape(source)
            safe_task_type = html.escape(task_type_label)
            
            # String preview for the small card
            if isinstance(raw_json, str):
                preview_text = html.escape(raw_json)[:100]
                collapsible_html = f'<pre style="margin: 0; padding: 10px; background-color: #2d2d2d; color: #9cdcfe; border-radius: 4px; font-family: monospace; font-size: 13px; white-space: pre-wrap;"><code>{html.escape(raw_json)}</code></pre>'
            else:
                preview_text = html.escape(json.dumps(raw_json))[:100]
                collapsible_html = json_to_html(raw_json)
                
            # Determine direction label
            direction_label = "Payload"
            header_label = f"Target: {safe_dest}"
            if "INCOMING" in task_type_label:
                direction_label = "Input to Agent"
                header_label = f"Source: {safe_source}"
            elif "OUTGOING" in task_type_label:
                direction_label = "Output to Next Agent"
                header_label = f"Next Agent: {safe_dest}"
            
            card_id = f"card-{op.get('id')}"
            
            # Render custom HTML card instead of st.expander -> it triggers hover tooltip natively!
            html_string = f"""<div class="condensed-item"><div style="font-weight: 600; margin-bottom: 4px; display: flex; justify-content: space-between; font-size: 14px; color: #333333;"><span>{header_label}</span><span style="color: #888888; font-weight: 400; font-size: 11px;">[{ts}]</span></div><div style="font-size: 12px; color: #0066cc; font-weight: bold; margin-bottom: 6px;">{direction_label} {safe_task_type}</div><div style="font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: #666666; font-family: monospace; margin-bottom: 12px;">{preview_text}...</div><a class="enlarge-btn" href="#{card_id}">🔎 Enlarge</a><div class="tooltip-text"><a class="tooltip-enlarge-btn" href="#{card_id}">🔎 Enlarge</a><div style="margin-bottom: 10px; padding-bottom: 10px; border-bottom: 1px solid #444444; font-size: 13px; padding-right: 90px;"><span style="color: #9cdcfe; font-weight: bold;">{header_label}</span> <br/><span style="color: #9cdcfe; font-weight: bold;">Time:</span> {ts}</div><span style="color: #9cdcfe; font-weight: bold;">{direction_label}:</span><br/><div style="background-color: #1e1e1e; padding: 10px; border-radius: 4px; font-family: monospace; font-size: 13px; max-height: 25vh; overflow: auto; border: 1px solid #444444;">{collapsible_html}</div></div></div><div id="{card_id}" class="timeline-modal"><div class="modal-content"><a class="modal-close-btn" href="#">&times;</a><div style="margin-bottom: 12px; padding-bottom: 10px; border-bottom: 1px solid #444444; font-size: 13px;"><h4 style="margin: 0 0 8px 0; color: #ffffff; font-size: 16px;">🔍 Message Details</h4><div style="display: flex; gap: 20px; color: #9cdcfe;"><span><strong>{header_label}</strong></span><span><strong>Time:</strong> {ts}</span><span><strong>Type:</strong> <span style="color: #60a5fa;">{direction_label} {safe_task_type}</span></span></div></div><h4 style="margin: 0 0 8px 0; color: #ffffff; font-size: 13px;">Full Message Content:</h4><div style="background-color: #1e1e1e; padding: 10px; border-radius: 4px; font-family: monospace; font-size: 14px; overflow: auto; max-height: 50vh;">{collapsible_html}</div></div></div>"""
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
    print("Refresh Dashboard button is pressed in workflows_examples/simple-workflow2/deploy_run/streamlit_app.py", flush=True)
    import logging
    logging.warning("Refresh Dashboard button is pressed in workflows_examples/simple-workflow2/deploy_run/streamlit_app.py")
    st.rerun()

st.sidebar.divider()
if st.sidebar.button("Delete All"):
    print("Delete All button is pressed in workflows_examples/simple-workflow2/deploy_run/streamlit_app.py", flush=True)
    import logging
    logging.warning("Delete All button is pressed in workflows_examples/simple-workflow2/deploy_run/streamlit_app.py")
    clear_all_data()

st.sidebar.divider()
st.sidebar.write("🟢 **Auto-refresh Every 10s**")
st.sidebar.caption(f"HIS API: {HIS_BASE_URL}")

