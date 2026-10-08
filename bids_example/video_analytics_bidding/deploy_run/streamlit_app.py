"""Video Analytics bidding round -- what every agent in every company did.

Two sources, used for what each is good at:

**HIS** is the live view. Every one of the 30 agents posts what it received and what it
produced against its own `SUBJECT_ID`, so a round can be watched agent by agent while it
is still running -- including companies that decline before any bid exists.

**The bid** is the durable record. Each Bid Manager also writes an `agent_trace` onto
the bid it submits, so a finished round stays explainable after HIS has been purged.

The Companies tab prefers HIS and falls back to the trace, which means it shows
something useful whether you open it mid-round or a week later.

Read-only apart from the explicit "clear HIS" control, which deletes only this example's
own records. Nothing here is required for a round to run.

    bash run_streamlit_app.bash          # or: streamlit run streamlit_app.py
"""
import datetime
import json
import os

import altair as alt
import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv


def find_git_root(path):
    current = os.path.abspath(path)
    while True:
        if os.path.exists(os.path.join(current, ".git")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


_git_root = find_git_root(__file__)
load_dotenv(os.path.join(_git_root, ".env") if _git_root else None)

EXCHANGE_URL = os.environ.get("EXCHANGE_BASE_URL", "http://localhost:5000").rstrip("/")
BIDDING_URL = os.environ.get("OPENARCADE_BIDDING_URL", "http://localhost:5000").rstrip("/")
HIS_BASE_URL = os.environ.get("HIS_BASE_URL", "").rstrip("/")

COMPANIES = ["CamFaceSolution", "MultiFaceTech", "NewGenTech", "UltraVideoTech", "VideoProcTech"]
SLUGS = {c: c.lower() for c in COMPANIES}

# role -> (subject-id suffix, label), in the order the Bid Manager consults them.
ROLES = [
    ("bid_manager", "bid-manager", "Bid Manager"),
    ("ai_compliance", "ai-compliance", "AI Compliance Agent"),
    ("sizing", "sizing", "Sizing Agent"),
    ("finance", "finance", "Finance Agent"),
    ("bid_reviewer", "bid-reviewer", "Bid Reviewer Agent"),
    ("head", "head", "Head Agent"),
]

# The stage key a Bid Manager files each subordinate's report under.
ROLE_STAGE = {"ai_compliance": "compliance", "sizing": "sizing", "finance": "finance",
              "bid_reviewer": "review", "head": "approval"}

ROLE_LABEL = {role: label for role, _suffix, label in ROLES}

# A bid that does not reach the buyer names the stage that stopped it. The stage key on
# its own says "approval" or "pqt", which does not say who refused, so it is shown as the
# agent that made the call. `pqt` is not one of the stages above: it is OpenArcade's
# pre-qualification function turning the bid away before any of this company's agents
# were asked.
DECLINE_LABEL = {"pqt": "PQT Decline"}
DECLINE_LABEL.update({stage: f"{ROLE_LABEL[role]} Decline"
                      for role, stage in ROLE_STAGE.items()})

BID_MANAGER_IDS = {f"{slug}-bid-manager": company for company, slug in SLUGS.items()}

EVENT_ICON = {"INCOMING_TASK": "⬇️", "OUTGOING_RESULT": "⬆️",
              "STAGE_DISPATCH": "➡️", "STAGE_RESULT": "⬅️"}
STATE_ICON = {"submitted": "🟢", "declined": "⚪", "rejected": "🔴"}

st.set_page_config(page_title="Video Analytics Bidding", layout="wide",
                   initial_sidebar_state="expanded")
st.markdown("<style>.block-container{padding-top:2rem}</style>", unsafe_allow_html=True)


# --- transport --------------------------------------------------------------

def get(url):
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        return r.json(), None
    except Exception as e:
        return None, str(e)


def post(url, payload):
    try:
        r = requests.post(url, json=payload, timeout=15)
        r.raise_for_status()
        return r.json(), None
    except Exception as e:
        return None, str(e)


def unwrap(envelope, default=None):
    """Both services answer with {"ok": ..., "data": ...}."""
    return envelope.get("data", default) if isinstance(envelope, dict) else default


def subject_id_for(company, suffix):
    return f"{SLUGS[company]}-{suffix}"


# --- HIS --------------------------------------------------------------------

@st.cache_data(ttl=5)
def fetch_his(subject_id):
    """Every record this agent posted, oldest first.

    Ordered by the timestamp the agent stamped rather than by HIS insert time, so the
    sequence reads as the agent actually ran it.
    """
    if not HIS_BASE_URL:
        return []
    body, err = get(f"{HIS_BASE_URL}/subject-responses/by-subject/{subject_id}")
    if err or not isinstance(body, dict) or not body.get("ok"):
        return []
    records = body.get("data", []) or []
    for record in records:
        stamped = (record.get("input_data") or {}).get("timestamp")
        record["_when"] = float(stamped) if stamped is not None else record.get("creation_time", 0)
    records.sort(key=lambda r: r["_when"])
    return records


def his_for_round(subject_id, bid_job_id):
    """This agent's records, narrowed to one round when the bid job is known.

    Records predating the trace fields carry no bid_job_id; they are kept rather than
    dropped, so an older round is still legible.
    """
    records = fetch_his(subject_id)
    if not bid_job_id:
        return records
    scoped = [r for r in records
              if (r.get("input_data") or {}).get("bid_job_id") in (bid_job_id, None)]
    return scoped or records


def clear_his():
    deleted = 0
    for company in COMPANIES:
        for _role, suffix, _label in ROLES:
            for record in fetch_his(subject_id_for(company, suffix)):
                rid = record.get("id")
                if not rid:
                    continue
                try:
                    if requests.delete(f"{HIS_BASE_URL}/subject-responses/{rid}",
                                       timeout=10).status_code == 200:
                        deleted += 1
                except Exception:
                    pass
    return deleted


# --- round data -------------------------------------------------------------

@st.cache_data(ttl=10)
def recent_bidding_tasks():
    body, err = post(f"{EXCHANGE_URL}/tasks/query", {"task_assignment_type": "bidding"})
    if err:
        return [], err
    tasks = unwrap(body, []) or []
    tasks.sort(key=lambda t: t.get("taski_creation_time") or "", reverse=True)
    return tasks, None


@st.cache_data(ttl=5)
def load_round(task_id):
    task_body, err = get(f"{EXCHANGE_URL}/tasks/{task_id}")
    if err:
        return {"error": f"could not read task {task_id}: {err}"}
    task = unwrap(task_body, {}) or {}

    bid_job_id = (task.get("task_metadata") or {}).get("bid_job_id")
    bid_job, bids, results = {}, [], []
    if bid_job_id:
        bid_job = unwrap(get(f"{BIDDING_URL}/bid-jobs/{bid_job_id}")[0], {}) or {}
        bids = unwrap(get(f"{BIDDING_URL}/bid-jobs/{bid_job_id}/bids")[0], []) or []
        results = unwrap(get(f"{BIDDING_URL}/bid-jobs/{bid_job_id}/task-results")[0], []) or []
    return {"task": task, "bid_job_id": bid_job_id, "bid_job": bid_job,
            "bids": bids, "task_results": results}


def bid_state(bid_data):
    if str(bid_data.get("bid_status", "")).lower() == "declined":
        return "declined"
    if bid_data.get("bid_rejected"):
        return "rejected"
    return "submitted"


def decline_stage(bid, bid_data):
    """Which agent stopped this bid, or "" if nothing did.

    A pre-qualification rejection carries `decline_stage: "pqt"` when the Bid Manager
    recorded it, but an older bid may only carry `bid_rejected`, so that flag is read as
    a PQT decline too. An unrecognised stage is shown as itself rather than dropped --
    a new stage should be visible in the table, not silently blank.
    """
    if bid_state(bid_data) == "submitted":
        return ""
    stage = bid_data.get("decline_stage")
    if stage:
        return DECLINE_LABEL.get(stage, f"{str(stage).replace('_', ' ').title()} Decline")
    if bid_data.get("bid_rejected") or bid.get("bid_rejected"):
        return "PQT Decline"
    return "stage not recorded"


# --- sidebar ----------------------------------------------------------------

with st.sidebar:
    st.header("Round")
    st.caption(f"Exchange · `{EXCHANGE_URL}`")
    st.caption(f"Bidding · `{BIDDING_URL}`")
    st.caption(f"HIS · `{HIS_BASE_URL or 'not configured'}`")
    if not HIS_BASE_URL:
        st.warning("HIS_BASE_URL is unset, so the live agent view is off. "
                   "The Companies tab falls back to the trace on each bid.")

    tasks, tasks_err = recent_bidding_tasks()
    if tasks_err:
        st.error(f"Could not list tasks: {tasks_err}")

    options = {}
    for task in tasks[:25]:
        options[f"{(task.get('taski_creation_time') or '')[:19]}  "
                f"{task.get('task_assignment_status', '?')}  "
                f"{task.get('task_id', '')[:8]}"] = task.get("task_id")

    chosen = st.selectbox("Recent bidding tasks", list(options) or ["(none found)"])
    task_id = st.text_input("Task id", value=options.get(chosen, ""))

    if st.button("Refresh", width="stretch"):
        st.cache_data.clear()
        st.rerun()

    st.divider()
    if HIS_BASE_URL and st.button("Clear HIS records", width="stretch"):
        removed = clear_his()
        st.cache_data.clear()
        st.success(f"Deleted {removed} record(s).")
        st.rerun()
    st.caption("Clearing removes only this example's 30 agents' records.")


if not task_id:
    st.title("Video Analytics Bidding")
    st.info("Pick a task in the sidebar, or paste a task id, to inspect a round.")
    if HIS_BASE_URL:
        st.caption("Agent activity appears here as soon as a round starts.")
    st.stop()

round_data = load_round(task_id)
if round_data.get("error"):
    st.error(round_data["error"])
    st.stop()

task = round_data["task"]
bids = round_data["bids"]
bid_job = round_data["bid_job"]
bid_job_id = round_data["bid_job_id"]
bids_by_company = {BID_MANAGER_IDS.get(b.get("bid_subject_id")): b for b in bids}
winner_company = next((BID_MANAGER_IDS.get(b.get("bid_subject_id"))
                       for b in bids if b.get("is_winner")), None)


# --- header -----------------------------------------------------------------

st.title("Video Analytics Bidding")
task_data = task.get("task_data") or {}
st.caption(task_data.get("rfp_name") or "Video Analytics RFP")

cols = st.columns(5)
cols[0].metric("Task status", task.get("task_assignment_status", "?"))
cols[1].metric("Bidders", len(bid_job.get("bid_job_subject_ids") or []))
cols[2].metric("Bids on record", len(bids))
cols[3].metric("Declined / rejected",
               sum(1 for b in bids if bid_state(b.get("bid_data") or {}) != "submitted"))
cols[4].metric("Winner", winner_company or "—")

resolved = bid_job.get("bid_job_subject_ids") or []
if resolved and len(resolved) < 5:
    invited = ((task.get("task_metadata") or {}).get("task_assignment") or {}).get(
        "bid_job_subject_ids") or []
    st.warning(
        f"The bid job resolved to {len(resolved)} bidders. The task named {len(invited)} "
        f"by id and also requested the topic `videoanalytics_bidding`, so the topic "
        f"listeners did not join — the exchange took the explicit list and skipped the "
        f"topic query. The round still completes, but topic-based participation is not "
        f"being demonstrated in this run."
    )

overview_tab, companies_tab, timeline_tab, evaluation_tab, raw_tab = st.tabs(
    ["Overview", "Companies", "Timeline", "Evaluation", "Raw"])


# --- overview ---------------------------------------------------------------

with overview_tab:
    st.subheader("The RFP")
    rfp = task_data.get("rfp") or {}
    left, right = st.columns([3, 2])
    with left:
        st.write(f"**{task_data.get('rfp_name', '—')}**")
        if rfp.get("url"):
            st.markdown(f"[Download the RFP]({rfp['url']})")
        st.caption(f"Submitted by {task_data.get('submitted_by', '—')} · task `{task_id}`")
    with right:
        assignment = (task.get("task_metadata") or {}).get("task_assignment") or {}
        st.caption(f"Bid job `{bid_job_id or '—'}`")
        st.caption(f"Invited by id: {', '.join(assignment.get('bid_job_subject_ids') or []) or '—'}")
        st.caption(f"Topics requested: {', '.join(assignment.get('topics') or []) or '—'}")

    st.subheader("Bids")
    if not bids:
        st.info("No bids on record yet. The Companies tab shows live agent activity "
                "before any bid exists.")
    else:
        rows = []
        for bid in bids:
            data = bid.get("bid_data") or {}
            compliance = data.get("compliance") or {}
            sizing = data.get("sizing") or {}
            state = bid_state(data)
            rows.append({
                "": STATE_ICON.get(state, ""),
                "Company": BID_MANAGER_IDS.get(bid.get("bid_subject_id"), "?"),
                "State": state,
                "Budget": data.get("total_budget"),
                "Compliance": (f"{compliance.get('met')}/{compliance.get('total')}"
                               if compliance.get("total") else "—"),
                "vCPU": sizing.get("cpu_cores"),
                "GPU": sizing.get("gpu_count"),
                "Endpoints": len(data.get("live_endpoints") or []),
                "Winner": "★" if bid.get("is_winner") else "",
                "Decline Stage": decline_stage(bid, data),
                "Why not": data.get("decline_reason") or data.get("pqt_reason") or "",
            })
        st.dataframe(rows, width="stretch", hide_index=True)


# --- companies: every agent's input and output ------------------------------

def render_record(record):
    """One HIS record: what the agent got, or what it produced."""
    body = record.get("input_data") or {}
    event = body.get("event", "?")
    payload = body.get("payload")
    if payload is None:                       # a record from before the structured fields
        payload = body.get("text")
    label = (f"{EVENT_ICON.get(event, '·')} {event}"
             + (f" · {body['stage']}" if body.get("stage") else "")
             + (f" → {body['destination_id']}" if body.get("destination_id") else ""))
    with st.expander(label, expanded=False):
        if isinstance(payload, (dict, list)):
            st.json(payload, expanded=False)
        else:
            st.code(str(payload)[:4000])


with companies_tab:
    if HIS_BASE_URL:
        st.caption("Live from HIS: every agent reports what it received and what it "
                   "produced, against its own subject id. Companies that decline before "
                   "bidding appear here too.")
    else:
        st.caption("HIS is not configured, so this falls back to the `agent_trace` each "
                   "Bid Manager writes onto its bid.")

    for company in COMPANIES:
        bid = bids_by_company.get(company)
        data = (bid or {}).get("bid_data") or {}
        state = bid_state(data) if bid else "no bid yet"
        header = (f"{STATE_ICON.get(state, '⏳')} {company} — {state}"
                  + ("  ★ winner" if company == winner_company else ""))

        with st.expander(header, expanded=(company == winner_company)):
            if bid:
                top = st.columns(4)
                budget = data.get("total_budget")
                top[0].metric("Budget", f"{budget:,.0f}" if isinstance(budget, (int, float)) else "—")
                compliance = data.get("compliance") or {}
                top[1].metric("Compliance", f"{compliance.get('met')}/{compliance.get('total')}"
                              if compliance.get("total") else "—")
                top[2].metric("Live endpoints", len(data.get("live_endpoints") or []))
                top[3].metric("Stages traced", len(data.get("agent_trace") or []))
                for key, label in (("commercials_url", "Commercial workbook"),
                                   ("sizing_url", "Sizing workbook")):
                    if data.get(key):
                        st.markdown(f"[{label}]({data[key]})")
                if data.get("decline_reason"):
                    st.warning(f"**{decline_stage(bid, data) or 'Declined'}** — "
                               f"{data['decline_reason']}")

            trace_by_stage = {t.get("stage"): t for t in (data.get("agent_trace") or [])}
            any_activity = False

            for role, suffix, label in ROLES:
                subject_id = subject_id_for(company, suffix)
                records = his_for_round(subject_id, bid_job_id)

                st.markdown(f"**{label}** · `{subject_id}`")

                if records:
                    any_activity = True
                    for record in records:
                        render_record(record)
                else:
                    entry = trace_by_stage.get(ROLE_STAGE.get(role))
                    if entry:
                        any_activity = True
                        st.caption(f"from the bid's trace · {entry.get('seconds', 0)}s")
                        io_left, io_right = st.columns(2)
                        with io_left:
                            st.caption("Input")
                            st.json(entry.get("input"), expanded=False)
                        with io_right:
                            st.caption("Output")
                            st.json(entry.get("output"), expanded=False)
                    else:
                        st.caption("_no activity recorded_")
                st.divider()

            if not any_activity:
                st.info("Nothing recorded for this company yet.")


# --- timeline ---------------------------------------------------------------
#
# A Gantt row is one agent inside one company, and its bar is the wall-clock window
# between being handed work and handing back a result.
#
# Scoping is strict here, which `his_for_round` is not. That function keeps untagged
# records and falls back to every record an agent ever posted, so the Companies tab can
# still show a round that predates the trace fields. The timeline cannot afford it: one
# record from yesterday stretches the x axis across days -- 15:00, 19:00, 23:00, 03:00 --
# and squashes the round itself into a hairline. Only records carrying this bid job id
# are drawn, and anything else is counted and reported rather than quietly mixed in.

OPEN_EVENTS = ("INCOMING_TASK",)
CLOSE_EVENTS = ("OUTGOING_RESULT",)

AGENT_ORDER = [label for _role, _suffix, label in ROLES]
STAGE_LABEL = {stage: ROLE_LABEL[role] for role, stage in ROLE_STAGE.items()}


def his_only_this_round(subject_id, bid_job_id):
    """(records for this bid job, how many belonged to another round or to none).

    A task with no bid job has not started bidding, so every record this agent holds is
    from some earlier round: none are kept.
    """
    records = fetch_his(subject_id)
    if not bid_job_id:
        return [], len(records)
    kept = [r for r in records
            if (r.get("input_data") or {}).get("bid_job_id") == bid_job_id]
    return kept, len(records) - len(kept)


def round_records(companies, bid_job_id):
    """{(company, agent label): records} for this round only, plus the skipped count."""
    per_agent, skipped = {}, 0
    if not HIS_BASE_URL:
        return per_agent, skipped
    for company in companies:
        for _role, suffix, label in ROLES:
            records, dropped = his_only_this_round(subject_id_for(company, suffix),
                                                   bid_job_id)
            skipped += dropped
            if records:
                per_agent[(company, label)] = records
    return per_agent, skipped


def clock(stamp):
    """A HIS timestamp as wall-clock time, to the millisecond.

    The agents stamp `time.time()`, so the record carries microseconds -- 14:53:18.770162
    for the first bid manager of round c1605d15. Rounding that to the second made a
    sizing agent that answered in 0.3s and one that answered in 0.1s look identical, and
    made four agents that started 100ms apart look simultaneous. Milliseconds are as far
    as the display goes: below that the number is dominated by clock skew between pods,
    not by anything the agent did.
    """
    return datetime.datetime.fromtimestamp(stamp).strftime("%H:%M:%S.%f")[:-3]


def took(seconds):
    """A duration at a precision that suits its size, never rounded to nothing."""
    return f"{seconds:.3f}s" if seconds < 10 else f"{seconds:.2f}s"


def spans_from_records(records):
    """Pair each INCOMING_TASK with the OUTGOING_RESULT that answers it.

    STAGE_DISPATCH and STAGE_RESULT are deliberately not turned into bars. They are the
    Bid Manager's view of a subordinate that already owns a row of its own, so drawing
    them would put the same interval on the chart twice -- once as the Sizing Agent's
    work and once as the Bid Manager waiting for it.

    Yields (start, end, opening_record, closing_record). `end` is None when the agent
    was handed work and no result was ever recorded: still running, or it died.
    """
    spans = []
    open_at, opened = None, None
    for record in records:
        body = record.get("input_data") or {}
        event = body.get("event")
        when = record.get("_when", 0)
        if event in OPEN_EVENTS:
            if open_at is not None:         # handed work twice with no answer between
                spans.append((open_at, None, opened, None))
            open_at, opened = when, record
        elif event in CLOSE_EVENTS:
            spans.append((open_at if open_at is not None else when, when, opened, record))
            open_at, opened = None, None
    if open_at is not None:
        spans.append((open_at, None, opened, None))
    return spans


def gantt_from_his(per_agent):
    rows = []
    for (company, label), records in per_agent.items():
        for start, end, opened, closed in spans_from_records(records):
            body = ((closed or opened) or {}).get("input_data") or {}
            rows.append({"Company": company, "Agent": label,
                         "Row": f"{company} · {label}",
                         "Stage": body.get("stage") or "—",
                         "start": start, "end": end})
    return rows


def row_order(rows, companies):
    """Companies in their usual order, and within a company the order the Bid Manager
    consults its subordinates -- so the chart reads top to bottom the way the round ran."""
    present = {row["Row"] for row in rows}
    return [f"{company} · {label}" for company in companies for label in AGENT_ORDER
            if f"{company} · {label}" in present]


def render_his_gantt(rows, companies):
    started = [r["start"] for r in rows]
    finished = [r["end"] for r in rows if r["end"]]
    earliest, latest = min(started), max(finished or started)
    span = max(latest - earliest, 1.0)

    # A bar narrower than a pixel or two is invisible, and several stages of this round
    # genuinely take 100-300ms. The floor is a fraction of the round rather than a fixed
    # number of milliseconds, so it stays at roughly two pixels whatever the round's
    # length, and it is small enough that most sub-second stages keep their true width.
    # A bar's start is never moved -- only its width -- and the caption says how many
    # were widened.
    floor = span * 0.0025

    frame = []
    for row in rows:
        end, open_ended = row["end"], row["end"] is None
        drawn_end = max(end if end is not None else latest, row["start"] + floor)
        frame.append({
            "Row": row["Row"], "Company": row["Company"], "Agent": row["Agent"],
            "Stage": row["Stage"],
            "Start": datetime.datetime.fromtimestamp(row["start"]),
            "Finish": datetime.datetime.fromtimestamp(drawn_end),
            "Began": clock(row["start"]),
            "Ended": "—" if open_ended else clock(end),
            "Took": "still open" if open_ended else took(end - row["start"]),
            "State": "open" if open_ended else "answered",
        })

    order = row_order(rows, companies)
    window = (f"{datetime.datetime.fromtimestamp(earliest):%d %b} {clock(earliest)} → "
              f"{clock(latest)} · {took(span)} end to end · "
              f"{len(order)} agents · {len(frame)} spans")
    widened = sum(1 for row in rows
                  if row["end"] is not None and row["end"] - row["start"] < floor)
    if widened:
        window += (f" · {widened} span(s) shorter than {floor * 1000:.0f}ms are drawn at "
                   f"that width so they stay visible -- hover for the real figure")
    st.caption(window)

    # nice=False keeps the axis on the round's own edges. Left to itself Vega rounds the
    # domain out to whole hours, which is the other half of how a two-minute round ends
    # up labelled 15:00, 19:00, 23:00.
    chart = (
        alt.Chart(pd.DataFrame(frame))
        .mark_bar(cornerRadius=2, height=15)
        .encode(
            x=alt.X("Start:T", title="Time", scale=alt.Scale(nice=False, padding=6),
                    axis=alt.Axis(format=("%H:%M:%S.%L" if span < 10 else
                                          "%H:%M:%S" if span < 3600 else "%H:%M"),
                                  tickCount=8, labelOverlap=True, grid=True)),
            x2=alt.X2("Finish:T"),
            y=alt.Y("Row:N", title=None, sort=order),
            color=alt.Color("Agent:N", sort=AGENT_ORDER, legend=alt.Legend(title="Agent")),
            # A bar with no result recorded is drawn faint and runs to the end of the
            # round, so an agent that never answered cannot be mistaken for a slow one.
            opacity=alt.Opacity("State:N", legend=None,
                                scale=alt.Scale(domain=["answered", "open"],
                                                range=[0.95, 0.35])),
            tooltip=["Company", "Agent", "Stage", "Began", "Ended", "Took", "State"],
        )
        .properties(height=max(160, 26 * len(order)))
    )
    st.altair_chart(chart, width="stretch")

    unanswered = [r for r in frame if r["State"] == "open"]
    if unanswered:
        st.caption("Faint bars were handed work and never recorded a result: "
                   + ", ".join(sorted(r["Row"] for r in unanswered)))


def gantt_from_trace(companies):
    """The same picture rebuilt from the `agent_trace` each Bid Manager writes onto its
    bid, for a round whose HIS records have been cleared or purged.

    The trace stores how long each stage took but not when it began, so the stages are
    chained in the order the Bid Manager ran them, from that company's own zero. The
    durations are real; the placement is inferred.
    """
    rows = []
    for company in companies:
        data = (bids_by_company.get(company) or {}).get("bid_data") or {}
        cursor = 0.0
        for entry in data.get("agent_trace") or []:
            seconds = max(float(entry.get("seconds") or 0), 0.0)
            stage = entry.get("stage") or "?"
            label = STAGE_LABEL.get(stage, stage)
            rows.append({"Company": company, "Agent": label, "Stage": stage,
                         "Row": f"{company} · {label}",
                         "Start": cursor, "Finish": cursor + max(seconds, 0.2),
                         "Took": took(seconds)})
            cursor += seconds
    return rows


def render_trace_gantt(rows, companies):
    order = row_order(rows, companies)
    chart = (
        alt.Chart(pd.DataFrame(rows))
        .mark_bar(cornerRadius=2, height=15)
        .encode(
            x=alt.X("Start:Q", title="Seconds into that company's own run",
                    scale=alt.Scale(nice=False)),
            x2=alt.X2("Finish:Q"),
            y=alt.Y("Row:N", title=None, sort=order),
            color=alt.Color("Agent:N", sort=AGENT_ORDER, legend=alt.Legend(title="Agent")),
            tooltip=["Company", "Agent", "Stage", "Took"],
        )
        .properties(height=max(160, 26 * len(order)))
    )
    st.altair_chart(chart, width="stretch")


with timeline_tab:
    picked = st.selectbox("Company", ["All companies"] + COMPANIES, key="timeline_company")
    companies = COMPANIES if picked == "All companies" else [picked]

    per_agent, skipped = round_records(companies, bid_job_id)
    rows = gantt_from_his(per_agent)

    heading = "Round timeline" if len(companies) > 1 else f"Round timeline · {picked}"
    st.subheader(heading)
    st.caption(f"Bid job `{bid_job_id or '—'}` only — one bar per agent, from the moment "
               f"it was handed work to the moment it answered. Task `{task_id[:8]}`.")

    if rows:
        render_his_gantt(rows, companies)
    else:
        reconstructed = gantt_from_trace(companies)
        if reconstructed:
            st.caption("HIS holds no records for this bid job, so this is rebuilt from "
                       "the `agent_trace` on each bid: the durations are real, the start "
                       "times are inferred by chaining each company's stages in order.")
            render_trace_gantt(reconstructed, companies)
        elif not HIS_BASE_URL:
            st.info("Set HIS_BASE_URL for the live view. A finished round can also be "
                    "drawn from the trace on each bid, once bids exist.")
        else:
            st.info("No agent activity recorded for this bid job yet.")

    if skipped:
        st.caption(f"{skipped} record(s) held by these agents belong to other rounds, or "
                   f"predate the bid job tag, and are left out of both the chart and the "
                   f"table below.")

    events = []
    for (company, label), records in per_agent.items():
        for record in records:
            body = record.get("input_data") or {}
            events.append({
                "when": record.get("_when", 0),
                "Company": company,
                "Agent": label,
                "Event": f"{EVENT_ICON.get(body.get('event',''), '')} {body.get('event','?')}",
                "Stage": body.get("stage") or "",
                "To": body.get("destination_id") or "",
            })

    if events:
        events.sort(key=lambda e: e["when"])
        for e in events:
            e["Time"] = clock(e["when"])
        with st.expander(f"Every record in this round, oldest first ({len(events)})",
                         expanded=False):
            st.dataframe([{k: e[k] for k in ("Time", "Company", "Agent", "Event", "Stage", "To")}
                          for e in events], width="stretch", hide_index=True)


# --- evaluation -------------------------------------------------------------
#
# The two functions OpenArcade calls now report to HIS exactly as the agents do, so this
# tab shows what they were given and what they decided, not only the numbers that
# survived onto the task result. That matters because the scores reach the buyer by a
# long route -- the evaluator answers OpenArcade, which notifies the winning Bid Manager,
# whose acknowledgement carries them back to the task -- and anything that breaks along
# it left this tab blank with no way to tell whether the evaluator had even run.

EVALUATOR_SUBJECT = "va-bid-eval"
PQT_SUBJECT = "va-bidding-pqt"


def function_records(subject_id, bid_job_id):
    """This function's records for this round, oldest first.

    Strictly scoped, for the same reason the timeline is: these subjects accumulate a
    record per bid per round, and an earlier round's pre-qualification of the same
    company is indistinguishable at a glance from this one's.
    """
    records, _skipped = his_only_this_round(subject_id, bid_job_id)
    return records


def paired(records):
    """[(company, incoming, outgoing)] -- one entry per decision, in order.

    Pre-qualification files one pair per bid and the evaluator one pair per round, so
    pairing on the company (the evaluator's is None) reads both without special-casing.
    """
    pending, out = {}, []
    for record in records:
        body = record.get("input_data") or {}
        key = body.get("company")
        if body.get("event") == "INCOMING_TASK":
            pending[key] = record
        elif body.get("event") == "OUTGOING_RESULT":
            out.append((key, pending.pop(key, None), record))
    for key, incoming in pending.items():      # asked but never answered
        out.append((key, incoming, None))
    return out


def as_text(value):
    """A cell that reads the same whether it holds a list, a number or a string."""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value) or "none"
    return "" if value is None else str(value)


def payload_of(record):
    return ((record or {}).get("input_data") or {}).get("payload") or {}


def show_io(incoming, outgoing, input_caption, output_caption):
    left, right = st.columns(2)
    with left:
        st.caption(input_caption)
        if incoming is None:
            st.caption("_not recorded_")
        else:
            st.json(payload_of(incoming), expanded=False)
    with right:
        st.caption(output_caption)
        if outgoing is None:
            st.warning("Called, but no result was recorded — it raised, timed out, or "
                       "the pod died mid-call.")
        else:
            st.json(payload_of(outgoing), expanded=False)


with evaluation_tab:
    winner_result = next((r for r in round_data["task_results"]
                          if r.get("task_type") == "bid_winner"), None)

    # HIS first: the evaluator records its own verdict the moment it reaches one, where
    # the task result only appears once the winner has been notified and has replied.
    evaluator_pairs = paired(function_records(EVALUATOR_SUBJECT, bid_job_id)) if HIS_BASE_URL else []
    evaluator_out = payload_of(evaluator_pairs[-1][2]) if evaluator_pairs else {}

    scores = (evaluator_out.get("scores")
              or ((winner_result or {}).get("task_result") or {}).get("scores")
              or (task.get("task_output") or {}).get("scores") or {})
    weights = evaluator_out.get("weights")
    endpoint_detail = evaluator_out.get("endpoint_detail") or {}

    if not scores:
        st.info("No scores yet. The evaluator reports its verdict to HIS as soon as it "
                "reaches one, and separately the scores reach the buyer through the "
                "winning Bid Manager's reply to its bid_winner notification — so an "
                "empty table here with records below means the round scored but the "
                "notification has not come back yet.")
    else:
        st.subheader("How the surviving bids scored")
        st.caption("Budget and sizing are ranked within the field, so a lower figure "
                   "scores higher. Compliance is met/total and endpoint is correct/total. "
                   "Each dimension is out of 100; the total is out of 400."
                   + (f"  ·  from {'HIS' if evaluator_out.get('scores') else 'the task result'}"))
        rows = []
        for sid, e in scores.items():
            detail = endpoint_detail.get(sid) or {}
            rows.append({
                "Company": BID_MANAGER_IDS.get(sid, sid),
                "Budget": e.get("budget"), "Sizing": e.get("sizing"),
                "Compliance": e.get("compliance"),
                "Endpoint": e.get("endpoint"),
                "Endpoint calls": (f"{detail['correct']}/{detail['total']}"
                                   if detail.get("total") else ""),
                "Total": e.get("total"),
                "Winner": "★" if BID_MANAGER_IDS.get(sid) == winner_company else "",
            })
        rows.sort(key=lambda r: r["Total"] or 0, reverse=True)
        st.dataframe(rows, width="stretch", hide_index=True)

        chartable = {r["Company"]: r["Total"] for r in rows
                     if isinstance(r["Total"], (int, float))}
        if chartable:
            st.bar_chart(chartable)

        if weights:
            st.caption(f"Sizing weights applied: {weights}")

    excluded = (evaluator_out.get("excluded")
                or (task.get("task_output") or {}).get("excluded")
                or ((winner_result or {}).get("task_result") or {}).get("excluded") or [])
    if excluded:
        st.subheader("Excluded from scoring")
        st.caption("Declined and pre-qualification-rejected bids take no part in any "
                   "percentile, so they cannot shift another company's relative score.")
        st.dataframe([{"Company": BID_MANAGER_IDS.get(e.get("subject_id"), e.get("subject_id")),
                       "Why": e.get("why"), "Detail": e.get("detail", "")} for e in excluded],
                     width="stretch", hide_index=True)

    st.divider()

    if not HIS_BASE_URL:
        st.info("Set HIS_BASE_URL to see what the pre-qualification and evaluator "
                "functions were given and what they decided.")
    else:
        st.subheader("Pre-qualification · `va-bidding-pqt`")
        st.caption("OpenArcade calls this once per bid, before the bid is accepted. A "
                   "rejection reaches the bid as one line of prose; this is every check "
                   "it ran, what the RFP required and what the company presented.")

        pqt_pairs = paired(function_records(PQT_SUBJECT, bid_job_id))
        if not pqt_pairs:
            st.caption("_no pre-qualification records for this round_")
        for company, incoming, outgoing in pqt_pairs:
            decision = payload_of(outgoing)
            accepted = decision.get("accepted")
            icon = "🟢" if accepted else ("🔴" if outgoing is not None else "⏳")
            label = f"{icon} {company or 'unknown company'}"
            if outgoing is not None:
                label += " — " + ("qualified" if accepted else "rejected")
            with st.expander(label, expanded=not accepted and outgoing is not None):
                checks = decision.get("checks") or []
                if checks:
                    # Stringified: one check compares a list of certifications and the
                    # next an integer licence count, and a column holding both cannot be
                    # converted to Arrow -- Streamlit then coerces it and the
                    # certifications arrive as ['...', '...'], which is worse than
                    # useless in the one column a reader is checking.
                    st.dataframe([{"": "✅" if c.get("passed") else "❌",
                                   "Check": c.get("check"),
                                   "RFP requires": as_text(c.get("required")),
                                   "Company presented": as_text(c.get("found")),
                                   "Note": c.get("note", "")} for c in checks],
                                 width="stretch", hide_index=True)
                if decision.get("reason"):
                    (st.success if accepted else st.error)(decision["reason"])
                show_io(incoming, outgoing,
                        "Input — credentials and the bar they are held to",
                        "Output — the verdict as OpenArcade received it")

        st.subheader("Evaluation · `va-bid-eval`")
        st.caption("One call per round, on the background thread OpenArcade starts when "
                   "the last bid lands. It has 60 seconds and is not retried.")
        if not evaluator_pairs:
            st.caption("_no evaluator records for this round_")
        for _company, incoming, outgoing in evaluator_pairs:
            out = payload_of(outgoing)
            status = out.get("status", "no result")
            icon = {"resolved": "🟢", "no_valid_bids": "⚪"}.get(status, "🔴")
            with st.expander(f"{icon} {status}"
                             + (f" — winner {BID_MANAGER_IDS.get(out.get('winner_subject_id'), '')}"
                                if out.get("winner_subject_id") else ""),
                             expanded=True):
                if out.get("reason"):
                    st.caption(out["reason"])
                if out.get("tie_break"):
                    st.warning(f"Tie broken: {out['tie_break']}")
                show_io(incoming, outgoing,
                        "Input — the bids, the weights and the image set",
                        "Output — every dimension, the exclusions and the winner")


# --- raw --------------------------------------------------------------------

with raw_tab:
    which = st.radio("Show", ["Exchange task", "Bid job", "Bids", "Task results", "HIS (one agent)"],
                     horizontal=True)
    if which == "HIS (one agent)":
        company = st.selectbox("Company", COMPANIES)
        label_to_suffix = {label: suffix for _role, suffix, label in ROLES}
        agent_label = st.selectbox("Agent", list(label_to_suffix))
        payload = fetch_his(subject_id_for(company, label_to_suffix[agent_label]))
    else:
        payload = {"Exchange task": task, "Bid job": bid_job, "Bids": bids,
                   "Task results": round_data["task_results"]}[which]
    st.code(json.dumps(payload, indent=2, default=str), language="json")
