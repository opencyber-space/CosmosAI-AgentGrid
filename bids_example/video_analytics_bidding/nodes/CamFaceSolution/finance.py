"""CamFaceSolution -- Finance Agent.

Prices the work. Each use case compliance approved has a per-licence rate in
`config.yaml`; multiply by the licence count, add the configured implementation and
maintenance percentages, and that is the bid.

Two outputs: the buyer's commercial template filled in and uploaded, and one single
total budget figure, which is what the evaluator's budget dimension ranks.

### A defect in the shipped template

`Commercials_Template_formated.xlsx` computes *Total License costs* at H28 as `=H8` --
the facial-detection line alone. The seventeen use-case rows beneath it are simply not
summed, so every downstream figure (implementation at 4% of H28, AMC, and the solution
total) is understated by however much those rows come to.

This agent therefore computes all four aggregates in Python and writes them as literal
values. That is also what the bid needs: `openpyxl` does not evaluate formulas, so a
total left as a formula could not be read back and put on the bid. The per-line
`=(F*D)` formulas are left intact -- they are correct, and they keep the delivered file
live for the human reading it.

The template defect is worth fixing at source; this agent works correctly either way.
"""
import logging
import os
import sys
from typing import Any, Dict, List, Optional

from agents_sdk.core.agent_executor import AgentTask, AgentResult, Context
from agents_sdk.core.main import main

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))
from common import company_config, his_logger, minio_store, spec_env, xlsx_fill  # noqa: E402

log = logging.getLogger(__name__)

COMPANY = "CamFaceSolution"
ROLE = "finance"

# Layout of Commercials_Template_formated.xlsx, sheet "Template".
SHEET = "Template"
FIRST_ITEM_ROW = 10          # the "Video Analytics" section
LAST_ITEM_ROW = 26
ITEM_COLUMNS = {"sno": "B", "usecase": "C", "licenses": "D", "unit_price": "F"}
# Section A ("Facial Detection System") ships pre-filled with sample figures. Its
# quantity and price are blanked so it cannot double-count; everything this company
# quotes goes in the Video Analytics section below it.
SECTION_A_CELLS = ("D8", "F8")
TOTAL_LICENCE_COST_CELL = "H28"
ONE_TIME_COST_CELL = "H30"
AMC_COST_CELL = "H32"
TOTAL_SOLUTION_CELL = "H34"


class CamFaceSolutionFinanceAgent:

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
            report = self._price(compliance)
        except Exception as e:
            log.exception("%s: pricing failed", self.company)
            report = {"company": self.company, "total_budget": None, "line_items": [],
                      "document_url": None, "error": str(e)}

        self._report("OUTGOING_RESULT", report, stage=data.get("stage"),
                     bid_job_id=data.get("bid_job_id"),
                     destination_id=f"{self.slug}-bid-manager")
        return AgentResult(task_id=task.task_id, job_output=report)

    # --- pricing -----------------------------------------------------------

    def _price(self, compliance):
        licences = int(compliance.get("total_licenses") or 0)
        usecases = self._priced_usecases(compliance)

        if not usecases:
            raise ValueError("compliance approved no use cases this company can price")
        if licences <= 0:
            # A bid of zero would win the budget dimension outright and mean nothing.
            raise ValueError("no licence count available from the RFP; cannot price the work")

        pricing = self.config["pricing"]
        line_items, licence_subtotal, timeline_weeks = [], 0.0, 0.0

        for index, uc_id in enumerate(usecases, start=1):
            terms = pricing[uc_id]
            unit_price = float(terms["unit_price"])
            line_total = unit_price * licences
            licence_subtotal += line_total
            timeline_weeks += float(terms.get("timeline_weeks_per_100_licenses", 0.0)) * (licences / 100.0)
            line_items.append({
                "sno": index, "id": uc_id, "usecase": self._display_name(uc_id),
                "licenses": licences, "unit_price": unit_price, "line_total": round(line_total, 2),
            })

        one_time_cost = licence_subtotal * float(pricing["one_time_implementation_pct"])
        amc_cost = licence_subtotal * float(pricing["amc_pct"])
        total_budget = licence_subtotal + one_time_cost + amc_cost

        licence_subtotal = round(licence_subtotal, 2)
        one_time_cost = round(one_time_cost, 2)
        amc_cost = round(amc_cost, 2)
        total_budget = round(total_budget, 2)

        log.info("%s: %d use cases x %d licences -> subtotal %s, one-time %s, AMC %s, total %s",
                 self.company, len(usecases), licences, licence_subtotal,
                 one_time_cost, amc_cost, total_budget)

        document_url = None
        try:
            document_url = self._write_workbook(line_items, licence_subtotal,
                                                one_time_cost, amc_cost, total_budget)
        except Exception as e:
            log.error("%s: could not produce the commercial workbook: %s", self.company, e)

        return {
            "company": self.company,
            "total_budget": total_budget,
            "currency": pricing.get("currency", "INR"),
            "licence_subtotal": licence_subtotal,
            "one_time_cost": one_time_cost,
            "amc_cost": amc_cost,
            "timeline_weeks": round(timeline_weeks, 1),
            "line_items": line_items,
            "total_licenses": licences,
            "document_url": document_url,
        }

    def _priced_usecases(self, compliance):
        covered = compliance.get("covered_usecases") or []
        pricing = self.config["pricing"]
        usable = [uc for uc in covered if isinstance(pricing.get(uc), dict)]
        missing = [uc for uc in covered if not isinstance(pricing.get(uc), dict)]
        if missing:
            log.warning("%s: no rate configured for %s; excluded from the commercials",
                        self.company, missing)
        return usable

    def _display_name(self, uc_id):
        match = company_config.usecase(self.config, uc_id)
        return match["name"] if match else uc_id

    def _write_workbook(self, line_items, licence_subtotal, one_time_cost, amc_cost, total_budget):
        workbook = xlsx_fill.load(xlsx_fill.COMMERCIALS_TEMPLATE)
        sheet = workbook[SHEET]

        for cell in SECTION_A_CELLS:
            xlsx_fill.set_cell(sheet, cell, None)

        # The template ships with seventeen sample use cases priced. Anything left
        # behind would read as work this company quoted for but never offered.
        xlsx_fill.fill_rows(sheet, FIRST_ITEM_ROW, ITEM_COLUMNS, line_items,
                            clear_to_row=LAST_ITEM_ROW)

        xlsx_fill.set_cells(sheet, {
            TOTAL_LICENCE_COST_CELL: licence_subtotal,   # replaces the template's =H8
            ONE_TIME_COST_CELL: one_time_cost,
            AMC_COST_CELL: amc_cost,
            TOTAL_SOLUTION_CELL: total_budget,
        })

        path = xlsx_fill.save_temp(workbook, f"commercials-{self.slug}-")
        try:
            store = minio_store.MinioStore()
            ref = store.put_file(
                path, minio_store.DOCS_BUCKET, f"{self.company}/commercials.xlsx",
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            log.info("%s: commercial workbook at %s", self.company, ref["url"])
            return ref["url"]
        finally:
            try:
                os.remove(path)
            except OSError:
                pass


if __name__ == "__main__":
    main(CamFaceSolutionFinanceAgent)
