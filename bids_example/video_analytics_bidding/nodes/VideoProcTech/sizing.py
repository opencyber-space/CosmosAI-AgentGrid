"""VideoProcTech -- Sizing Agent.

Turns the compliance agent's findings into hardware. Every use case this company will
serve has a per-licence ratio in `config.yaml`; multiply by the licence count the RFP
asks for, sum across use cases, and that is the deployment.

Two outputs: the buyer's sizing template filled in and uploaded, and four single totals
-- CPU, RAM, disk, accelerators -- which go on the bid and are what the evaluator's
sizing dimension actually ranks.

The totals are computed in Python and written as literal values. `openpyxl` does not
evaluate formulas, so a number left to a spreadsheet formula could not be read back out
and put on the bid. The template's own formulas that only serve the human reader (the
licence subtotal) are left intact, so the delivered file still recalculates when opened.

This agent does not decide *whether* to bid. It is handed the use cases compliance
approved and sizes them; if compliance declined, the Bid Manager never gets here.
"""
import logging
import math
import os
import sys
from typing import Any, Dict, List, Optional

from agents_sdk.core.agent_executor import AgentTask, AgentResult, Context
from agents_sdk.core.main import main

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))
from common import company_config, his_logger, minio_store, spec_env, xlsx_fill  # noqa: E402

log = logging.getLogger(__name__)

COMPANY = "VideoProcTech"
ROLE = "sizing"

# Layout of Sizing_Template_simple_formated.xlsx, sheet "Sizing".
SHEET = "Sizing"
FIRST_ITEM_ROW = 5
LAST_ITEM_ROW = 23
ITEM_COLUMNS = {"sno": "A", "usecase": "B", "licenses": "C"}
# The four totals are single cells merged down the whole block (E4:E23 and friends).
TOTAL_CELLS = {"cpu_cores": "E4", "gpu_count": "F4", "disk_gb": "G4", "ram_gb": "H4"}

HARDWARE_FIELDS = ("cpu_cores", "ram_gb", "disk_gb", "gpu_count")


class VideoProcTechSizingAgent:

    def __init__(self, subject, context: Context) -> None:
        self.subject = subject
        self.context = context
        self.company = COMPANY
        self.config = company_config.load(self.company)
        self.slug = self.config["company"]["slug"]
        self.subject_id = getattr(getattr(subject, "identity", None), "subject_id", None) \
            or f"{self.slug}-{ROLE.replace('_', '-')}"
        # MinIO, the function registry and HIS all come from this subject's own spec.
        # Done before anything reads them, and before the first HIS client is built.
        spec_env.apply(subject)
        self.his_client = his_logger.build_client(subject)

    def _report(self, event, payload, stage=None, bid_job_id=None,
                destination_id="USER_OR_NEXT"):
        """Tell HIS what this agent received or produced. Never affects the outcome."""
        his_logger.report(self.his_client, subject_id=self.subject_id, company=self.company,
                          role=ROLE, event=event, payload=payload, stage=stage,
                          bid_job_id=bid_job_id, destination_id=destination_id)

    def get_muxer(self):
        return None

    def on_preprocess(self, task: AgentTask) -> Optional[List[AgentTask]]:
        return [task]

    def on_data(self, task: AgentTask) -> AgentResult:
        data = task.job_data or {}
        self._report("INCOMING_TASK", data, stage=data.get("stage"),
                     bid_job_id=data.get("bid_job_id"))
        compliance = (data.get("upstream") or {}).get("compliance") or {}

        try:
            report = self._size(compliance)
        except Exception as e:
            # The Bid Manager turns this into a declining bid. A shaped report carries
            # the reason onto the bid instead of losing it in a traceback.
            log.exception("%s: sizing failed", self.company)
            report = {"company": self.company, "totals": {}, "per_usecase": [],
                      "document_url": None, "error": str(e)}

        self._report("OUTGOING_RESULT", report, stage=data.get("stage"),
                     bid_job_id=data.get("bid_job_id"),
                     destination_id=f"{self.slug}-bid-manager")
        return AgentResult(task_id=task.task_id, job_output=report)

    # --- sizing ------------------------------------------------------------

    def _size(self, compliance):
        licences = int(compliance.get("total_licenses") or 0)
        usecases = self._priced_usecases(compliance)

        if not usecases:
            raise ValueError("compliance approved no use cases this company can size")
        if licences <= 0:
            # The RFP did not state a licence count the extractor could find. Sizing a
            # deployment of zero would silently produce a bid of zero hardware, which
            # would win the sizing dimension outright and be meaningless.
            raise ValueError("no licence count available from the RFP; cannot size the deployment")

        per_usecase, totals = self._compute(usecases, licences)
        log.info("%s: sized %d use cases at %d licences -> %s",
                 self.company, len(usecases), licences, totals)

        document_url = None
        try:
            document_url = self._write_workbook(per_usecase, totals, licences)
        except Exception as e:
            # A missing document is caught by the Bid Reviewer before submission. Losing
            # the totals as well, by raising here, would cost far more.
            log.error("%s: could not produce the sizing workbook: %s", self.company, e)

        return {
            "company": self.company,
            "totals": totals,
            "per_usecase": per_usecase,
            "total_licenses": licences,
            "document_url": document_url,
            "notes": [self.config["hardware"][u]["notes"]
                      for u in usecases if self.config["hardware"].get(u, {}).get("notes")],
        }

    def _priced_usecases(self, compliance):
        """Use cases compliance covered that this company has hardware ratios for."""
        covered = compliance.get("covered_usecases") or []
        hardware = self.config["hardware"]
        usable = [uc for uc in covered if uc in hardware]
        missing = [uc for uc in covered if uc not in hardware]
        if missing:
            log.warning("%s: no hardware ratio configured for %s; excluded from sizing",
                        self.company, missing)
        return usable

    def _compute(self, usecases, licences):
        """Scale each per-licence ratio by the licence count and sum."""
        hardware = self.config["hardware"]
        per_usecase, totals = [], {field: 0.0 for field in HARDWARE_FIELDS}

        for index, uc_id in enumerate(usecases, start=1):
            ratios = hardware[uc_id]
            row = {"sno": index, "id": uc_id, "usecase": self._display_name(uc_id),
                   "licenses": licences}
            for field in HARDWARE_FIELDS:
                value = float(ratios.get(field, 0.0)) * licences
                row[field] = round(value, 2)
                totals[field] += value
            per_usecase.append(row)

        # Accelerators are whole units -- you cannot buy 0.4 of a GPU -- and a
        # deployment that needs any inference at all needs at least one.
        totals["gpu_count"] = max(1, math.ceil(totals["gpu_count"])) if totals["gpu_count"] > 0 else 0
        for field in ("cpu_cores", "ram_gb", "disk_gb"):
            totals[field] = round(totals[field], 1)

        return per_usecase, totals

    def _display_name(self, uc_id):
        match = company_config.usecase(self.config, uc_id)
        return match["name"] if match else uc_id

    def _write_workbook(self, per_usecase, totals, licences):
        workbook = xlsx_fill.load(xlsx_fill.SIZING_TEMPLATE)
        sheet = workbook[SHEET]

        # Clearing to LAST_ITEM_ROW matters: the template ships with nineteen sample
        # rows, and leftovers would appear as work this company never quoted.
        xlsx_fill.fill_rows(sheet, FIRST_ITEM_ROW, ITEM_COLUMNS, per_usecase,
                            clear_to_row=LAST_ITEM_ROW)
        xlsx_fill.set_cells(sheet, {cell: totals[field] for field, cell in TOTAL_CELLS.items()})

        path = xlsx_fill.save_temp(workbook, f"sizing-{self.slug}-")
        try:
            store = minio_store.MinioStore()
            ref = store.put_file(
                path, minio_store.DOCS_BUCKET, f"{self.company}/sizing.xlsx",
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            log.info("%s: sizing workbook at %s", self.company, ref["url"])
            return ref["url"]
        finally:
            try:
                os.remove(path)
            except OSError:
                pass


if __name__ == "__main__":
    main(VideoProcTechSizingAgent)
