# Video Analytics RFP Bidding — XChange · OpenArcade · OpenMesh

A buyer posts one Video Analytics RFP to the Exchange. Five companies bid, or decline.
One wins. The buyer never touches the bidding system.

This example exists to show three systems working as one flow:

| System | What it does here |
|---|---|
| **XChange** | Accepts the RFP as a task in `bidding` mode and returns the winner |
| **OpenArcade** | Runs the bid job, pre-qualifies each bid, evaluates and picks a winner |
| **OpenMesh** | Two companies are never named in the task — they join by listening on a topic |

The companion example `bids_example/bids_processing` shows OpenArcade on its own, with
bid jobs created directly. The difference here is that the buyer posts **one task** and
everything else follows from it.

---

## The round

Five companies. The buyer names three; two more arrive because their Bid Manager subject
carries the topic `videoanalytics_bidding`.

| Company | How it joins | Outcome | Why |
|---|---|---|---|
| CamFaceSolution | invited by id | **scored** | meets coverage, certification and track record |
| MultiFaceTech | invited by id | declines | catalogue is indoor-only; the RFP is outdoor city surveillance |
| NewGenTech | invited by id | **rejected at PQT** | no benchmarking certificate, 3,500 licences supplied against a 10,000 bar |
| UltraVideoTech | **topic listener** | **scored** | meets everything, and can win |
| VideoProcTech | **topic listener** | declines | licence ceiling of 1,000 against a city-scale programme |

Two decline, one is rejected, two are scored, one wins. A topic listener is among the
two scored — so topic-based participation can decide the round rather than merely adding
a bidder who drops out.

**None of this is hardcoded.** Every outcome falls out of that company's `config.yaml`.
Raise `VideoProcTech.licensing.max_licenses` above the RFP's licence count and it bids
instead.

---

## Inside a company

Six agents. The Bid Manager is the only one that speaks outside the company; it finds its
own subordinates by querying the subject registry for its company tag, and matches each
one to a position in the workflow by that agent's `persona.role`.

```
bid_request ──► Bid Manager ── not video analytics ─────────────► declining bid
                     │ qualified
                     ├──► AI Compliance  ── no coverage / licence ceiling ──► declining bid
                     ├──► Sizing         (fills the sizing workbook)
                     ├──► Finance        (fills the commercial workbook)
                     ├──► Bid Reviewer   (reports gaps; never vetoes)
                     └──► Head Agent     ── not approved ────────► declining bid
                                              │ approved
                                              ▼
                                        priced bid ──► OpenArcade
```

**Every terminal path submits a bid.** Qualification failure, a licence ceiling, a Head
Agent refusal, a subordinate that times out — all of them end in an explicit declining
bid. This is not politeness: OpenArcade evaluates only once *every* participant has a bid
on file, and there is no timeout. One silent Bid Manager stalls the round forever.

### How a company hears of the RFP

Two routes, and a company can be reached by both at once:

* **`bid_request`** -- OpenArcade sends it to every company on the job's roster. The three
  companies invited by name rely on this alone.
* **Polling** -- UltraVideoTech and VideoProcTech listen on a topic: it is in their spec at
  `metadata.subject_metadata.topics` (not in `subject_search_tags`, which are only labels for
  finding agents), generated from `company.topics` in their `config.yaml`. Their Bid Manager
  asks OpenArcade (`GET /bid-jobs/by-tags`) for jobs carrying that topic or naming it, every
  `ORCADE_POLL_SECONDS`, and bids through the same pipeline (`on_bidding_task`).

The job is **claimed once** (`nodes/common/orcade.py`): a polled roster job waits 30 seconds
for its `bid_request` before taking over, and a `bid_request` for a job the poller already
took is acknowledged and dropped. The first poll after a pod starts is a baseline -- rounds
that already existed are ignored, so a restart does not re-run history.

The Bid Managers talk to OpenArcade through `agents_sdk/core/bidding_client.py`, one client
per thread (the Redis worker and the poller each have their own). `ORCADE_URL` and
`ORCADE_POLL_SECONDS` come from the pod's environment, else from the spec's
`persona.config.parameters`.

The AI Compliance Agent also registers up to **two live use-case endpoints** per company
into the function registry while it prepares its bid. The evaluator calls those back
later with a shared image set.

---

## How the winner is chosen

`va-bid-eval` excludes every declined and pre-qualification-rejected bid, then scores the
survivors on four dimensions, each out of 100:

| Dimension | How |
|---|---|
| **Budget** | ranked within the field — the cheapest bid scores highest |
| **Sizing** | cpu / ram / disk / gpu ranked separately, weighted `0.2 / 0.2 / 0.1 / 0.5` |
| **Compliance** | `met ÷ total` of the RFP's requirements |
| **Endpoint** | each company's live endpoints called with a shared image set, against a shared ground truth |

Highest total of the four wins. Ties break on lowest budget, then subject id.

Excluded bids take **no part in any percentile**, so a declining company's price cannot
drag a rival's budget rank.

---

## Running it

Full step-by-step, including what a correct run looks like:
[`specs/009-video-analytics-exchange-bidding/quickstart.md`](../../specs/009-video-analytics-exchange-bidding/quickstart.md)

Build and push the 30 images first (from `bids_example/`):

```bash
bash build_va_tenderprocessing_agents_and_push.bash             # all 30
bash build_va_tenderprocessing_agents_and_push.bash managers    # just the 5 Bid Managers
bash build_va_tenderprocessing_agents_and_push.bash CamFaceSolution
```

The image tag, the `AGENT` case in `entrypoint.sh` and the spec's `subject_id` are all
the same string (e.g. `ultravideotech-ai-compliance`). They have to agree or the pod
starts the wrong module; `local_check.py` asserts they do.

Then, from the repo root:

```bash
cd bids_example/video_analytics_bidding

bash functions/build.sh && bash functions/upload.sh   # PQT + evaluator
bash spec/register.sh                                 # 30 agents
bash spec/register_subjects_in_Exchange.sh            # 5 Bid Managers as subjects
bash deploy_run/deploy.sh                             # 30 pods

bash deploy_run/va_bidding_request.sh                 # post the RFP, watch for a winner
```

`RFP=chennai bash deploy_run/va_bidding_request.sh` runs the alternative RFP — the check
that the RFP is input data rather than embedded knowledge.

Teardown: `deploy_run/deploy_remove.sh`, `spec/unregister.sh`, `functions/delete.sh`.

### Seeing what happened

```bash
bash deploy_run/run_streamlit_app.bash     # http://localhost:8008
```

All 30 agents post what they received and what they produced to **HIS**, against their
own `SUBJECT_ID`, so a round can be watched agent by agent while it runs — including the
companies that decline before any bid exists. Each Bid Manager *also* writes an
`agent_trace` onto the bid it submits, so a finished round stays explainable after HIS
has been purged.

The dashboard prefers HIS and falls back to the trace, which means it shows something
useful whether you open it mid-round or a week later. Five tabs: Overview, Companies
(every agent's input and output), Timeline (the whole round in order, across all five
companies), Evaluation, and Raw.

Reporting never affects a decision. A Bid Manager that failed to log and therefore
failed to bid would stall the round permanently, so every HIS call swallows its own
errors.

---

## Layout

Building the images uses `bids_example/build_va_tenderprocessing_agents_and_push.bash`,
`build_docker.bash` and `entrypoint.sh`, which are shared with the other examples in
`bids_example/`.

```
deploy_run/     RFP PDFs, MinIO seeding, the submission script, deploy/teardown, dashboard
functions/      va-bidding-pqt, va-bid-eval, va-usecase-endpoint (+ build/upload/call/delete)
nodes/          30 agent modules — 6 roles x 5 companies — plus config.yaml and shared helpers
  common/       config loading, RFP reading, MinIO, spreadsheet filling, function
                publishing, HIS reporting
  local_check.py   off-cluster checks: imports, discovery, decline paths, scoring, workbooks
spec/           30 agent specs, the generator, registration and teardown scripts
```

**The 30 agent modules are standalone by design.** They share only *utilities* from
`nodes/common/`, never agent logic, so one company can diverge in ways `config.yaml`
cannot express without touching the other four.

---

## Two things to know before you run it

**The topic union and the polling depend on the servers.** The task is a `mixed`-mode bid
job: it names three companies *and* requests a topic, and expects the participant set to be
the union of both, with the job tagged so topic listeners can also find it by polling.
A task with three `bid_job_subject_ids` plus `topics: ["videoanalytics_bidding"]` resolved
to **five** bidders on 23 Sep 2026, the two listeners included. `bid_job_mode` and
`GET /bid-jobs/by-tags` need an OpenArcade built with them: on an older one the job runs as
`closed`, the Bid Managers' polling waits quietly for the endpoint to appear, and the round
still completes through the `bid_request` route. Both `va_bidding_request.sh` and the
dashboard print the resolved bidder count, and the script prints the mode the job actually
has, so which behaviour you have is visible in the output rather than something to assume.

**Pods reaching `Running` is not the same as being ready.** An agent has to join the NATS
mesh before it can receive a `bid_request`, and a Bid Manager that misses its request
never bids — which stalls the round permanently. Wait for the mesh join before
submitting.

---

## Checks that run without a cluster

```bash
PYTHONPATH=/home/cognitifai/Downloads/agent_codes \
    ./venv/bin/python bids_example/video_analytics_bidding/nodes/local_check.py

cd bids_example/video_analytics_bidding/functions
for f in va-bidding-pqt va-bid-eval va-usecase-endpoint; do (cd $f && ../../../../venv/bin/python test.py); done
```

These cover imports, subordinate discovery, decline paths, scoring maths, endpoint
robustness and workbook writing. **They prove the code is sound, not that the round
works** — agent behaviour is only genuinely exercised in a pod, against the live
inference server, delegate transport and registries.
