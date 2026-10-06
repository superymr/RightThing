"""小样本真实调用对比：python tools/compare_extraction_cost.py --limit 3。

每条JD分别调用完整/紧凑抽取，会产生模型费用。只打印token和技能差异，不回显原文或密钥。
"""
import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings
from app.llm import build_provider
from app.llm.extractor import Extractor
from app.models.db import Database
from app.analytics.lexicon import SkillLexicon
from app.analytics.normalizer import Normalizer
from app.services.orchestrator import Orchestrator


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=3, choices=range(1, 6))
    parser.add_argument("--mode", choices=("both", "compact"), default="both")
    args = parser.parse_args()
    settings = Settings.load()
    if settings.is_mock:
        raise SystemExit("需要配置真实模型；mock无法衡量token费用。")
    db = Database(settings.db_path)
    jobs = db.query("SELECT DISTINCT j.id, j.title, j.company, j.raw_text FROM raw_job j "
                    "JOIN jd_profile p ON p.raw_job_id=j.id WHERE p.extraction_status='ok' "
                    "AND j.source != 'sample' ORDER BY j.id DESC LIMIT ?", (args.limit,))
    totals = {mode: {"in": 0, "out": 0} for mode in
              (("full", "compact") if args.mode == "both" else ("compact",))}
    context = SimpleNamespace(normalizer=Normalizer(SkillLexicon.load(settings.alias_path)))
    comparisons = []
    for job in jobs:
        outcomes = {}
        for mode in totals:
            configured = replace(settings, llm_compact_extraction=mode == "compact")
            outcome = Extractor(build_provider(configured), configured).extract_profile(
                job_title=job["title"], company=job["company"], jd_text=job["raw_text"])
            if outcome.status != "ok":
                raise SystemExit(f"job={job['id']} mode={mode} failed: {outcome.error}")
            outcomes[mode] = outcome
            totals[mode]["in"] += outcome.token_in
            totals[mode]["out"] += outcome.token_out
        skills = {mode: {(skill.name, skill.required) for skill in
                         Orchestrator._canonicalize(context, outcomes[mode].profile).all_skills()}
                  for mode in totals}
        if args.mode == "compact":
            comparisons.append({"job_id": job["id"], "compact_skills": len(skills["compact"]),
                                "token_in": outcomes["compact"].token_in,
                                "token_out": outcomes["compact"].token_out,
                                "invalid_evidence": sum(skill.evidence not in job["raw_text"]
                                    for skill in outcomes["compact"].profile.all_skills())})
        else:
            comparisons.append({"job_id": job["id"], "full_skills": len(skills["full"]),
                            "compact_skills": len(skills["compact"]),
                            "only_full": sorted(skills["full"] - skills["compact"]),
                            "only_compact": sorted(skills["compact"] - skills["full"])})
        print(json.dumps(comparisons[-1], ensure_ascii=False), flush=True)
    print(json.dumps({"jobs": len(jobs), "tokens": totals,
                      "comparisons": comparisons}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
