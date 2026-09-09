"""NEXUS CLI - operate the platform from the command line.

Usage examples:
  python -m nexus.cli init-db
  python -m nexus.cli pipeline            # full intelligence loop
  python -m nexus.cli investigate 0xABC "Why is this wallet unusual?"
  python -m nexus.cli alert-rule add "high risk" risk ">" 0.8 --channels dashboard,email
  python -m nexus.cli automation seed     # canonical high-confidence anomaly workflow
  python -m nexus.cli runserver
"""

from __future__ import annotations

import argparse
import json
import sys

from nexus.core.logging_setup import get_logger, setup_logging

setup_logging()
log = get_logger("nexus.cli")


def cmd_init_db(args) -> int:
    from nexus.db.session import init_db

    init_db()
    print("database initialized")
    return 0


def cmd_pipeline(args) -> int:
    from nexus.db.session import db_session
    from nexus.pipelines.intelligence import run_full_pipeline

    with db_session() as db:
        report = run_full_pipeline(db, skip_ingest=args.skip_ingest)
    print(json.dumps(report.to_dict(), indent=2, default=str))
    return 0


def cmd_ingest(args) -> int:
    from nexus.db.session import db_session
    from nexus.pipelines.intelligence import stage_ingest

    with db_session() as db:
        stats = stage_ingest(db)
    print(json.dumps(stats, indent=2, default=str))
    return 0


def cmd_investigate(args) -> int:
    from nexus.agents.investigator import Investigator
    from nexus.db.session import db_session

    with db_session() as db:
        report = Investigator(db).investigate(args.entity, args.question)
        print(json.dumps(report.to_dict(), indent=2))
    return 0


def cmd_alert_rule(args) -> int:
    from nexus.alerts.service import evaluate_alert_rules
    from nexus.db.schema import AlertRule
    from nexus.db.session import db_session

    if args.action == "add":
        with db_session() as db:
            rule = AlertRule(
                name=args.name, metric=args.metric, operator=args.op,
                threshold=args.threshold, entity_id=args.entity,
                channels=args.channels.split(","),
                webhook_url=args.webhook,
            )
            db.add(rule)
            db.commit()
            print(f"rule #{rule.id} created")
        return 0
    if args.action == "evaluate":
        with db_session() as db:
            alerts = evaluate_alert_rules(db)
            print(f"raised {len(alerts)} alerts")
        return 0
    if args.action == "list":
        from nexus.db.session import db_session

        with db_session() as db:
            for r in db.query(AlertRule).all():
                print(json.dumps(r.to_dict()))
        return 0
    return 1


def cmd_automation(args) -> int:
    from nexus.db.schema import Automation
    from nexus.db.session import db_session

    if args.action == "seed":
        steps = [
            {"action": "investigate", "params": {"question": "Why is this entity unusual?"}},
            {"action": "gather_evidence", "params": {}},
            {"action": "generate_report", "params": {}},
            {"action": "notify", "params": {"severity": "critical"}},
            {"action": "webhook", "params": {"event": "anomaly.confirmed"}},
            {"action": "create_ticket", "params": {"priority": "high"}},
            {"action": "request_approval", "params": {"action": "external_report"}},
        ]
        with db_session() as db:
            exists = db.query(Automation).filter(Automation.name == "high-confidence anomaly").one_or_none()
            if exists:
                print("automation already seeded")
                return 0
            db.add(Automation(
                name="high-confidence anomaly",
                trigger_metric="risk", trigger_operator=">",
                trigger_threshold=0.8, steps=steps, requires_approval=True,
            ))
            db.commit()
            print("automation seeded")
        return 0
    if args.action == "run":
        from nexus.alerts.service import run_automation

        with db_session() as db:
            auto = db.get(Automation, args.id)
            run = run_automation(db, auto, args.entity)
            print(json.dumps(run.to_dict(), indent=2, default=str))
        return 0
    if args.action == "approve":
        from nexus.alerts.service import approve_run

        with db_session() as db:
            run = approve_run(db, args.run_id, approve=not args.reject)
            print(json.dumps(run.to_dict(), indent=2, default=str))
        return 0
    return 1


def cmd_runserver(args) -> int:
    import uvicorn

    uvicorn.run("nexus.api.app:app", host=args.host, port=args.port, reload=False)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="nexus")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init-db").set_defaults(func=cmd_init_db)
    sp = sub.add_parser("pipeline")
    sp.add_argument("--skip-ingest", action="store_true")
    sp.set_defaults(func=cmd_pipeline)
    sub.add_parser("ingest").set_defaults(func=cmd_ingest)

    sp = sub.add_parser("investigate")
    sp.add_argument("entity")
    sp.add_argument("question")
    sp.set_defaults(func=cmd_investigate)

    sp = sub.add_parser("alert-rule")
    sp.add_argument("action", choices=["add", "evaluate", "list"])
    sp.add_argument("name", nargs="?")
    sp.add_argument("--metric", default="risk")
    sp.add_argument("--op", default=">")
    sp.add_argument("--threshold", type=float, default=0.8)
    sp.add_argument("--entity", default=None)
    sp.add_argument("--channels", default="dashboard")
    sp.add_argument("--webhook", default=None)
    sp.set_defaults(func=cmd_alert_rule)

    sp = sub.add_parser("automation")
    sp.add_argument("action", choices=["seed", "run", "approve"])
    sp.add_argument("--id", type=int, default=1)
    sp.add_argument("--entity", default=None)
    sp.add_argument("--run-id", type=int, default=None)
    sp.add_argument("--reject", action="store_true")
    sp.set_defaults(func=cmd_automation)

    sp = sub.add_parser("runserver")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8000)
    sp.set_defaults(func=cmd_runserver)

    args = p.parse_args(argv)
    try:
        return args.func(args)
    except Exception as e:
        log.exception("command failed")
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
