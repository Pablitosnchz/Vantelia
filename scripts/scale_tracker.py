"""Seguimiento local del plan de escala de Vantelia.

Uso:
  python scripts/scale_tracker.py init
  python scripts/scale_tracker.py checkin --contacts 20 --calls 10 --conversations 1 --note "..."
  python scripts/scale_tracker.py status

Los datos viven en storage/growth/ (ignorado por git) y STATUS.md se regenera
en cada check-in para que Codex pueda leer el estado actual rápidamente.
"""

from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
GROWTH_DIR = ROOT / "storage" / "growth"
ACTIVITY_PATH = GROWTH_DIR / "activity.csv"
PIPELINE_PATH = GROWTH_DIR / "pipeline.csv"
STATUS_PATH = GROWTH_DIR / "STATUS.md"

ACTIVITY_FIELDS = [
    "date",
    "researched",
    "contacts",
    "followups",
    "calls",
    "positive_replies",
    "conversations",
    "meetings",
    "proposals",
    "won",
    "eur_sold",
    "new_recurring",
    "delivery_hours",
    "note",
    "blocker",
    "next_action",
]

PIPELINE_FIELDS = [
    "company",
    "campaign",
    "offer",
    "stage",
    "value_eur",
    "decision_date",
    "next_action",
    "next_action_date",
    "owner",
    "notes",
]

NUMERIC_FIELDS = {
    "researched",
    "contacts",
    "followups",
    "calls",
    "positive_replies",
    "conversations",
    "meetings",
    "proposals",
    "won",
    "eur_sold",
    "new_recurring",
    "delivery_hours",
}


def ensure_files() -> None:
    GROWTH_DIR.mkdir(parents=True, exist_ok=True)
    if not ACTIVITY_PATH.exists():
        with ACTIVITY_PATH.open("w", newline="", encoding="utf-8") as handle:
            csv.DictWriter(handle, fieldnames=ACTIVITY_FIELDS).writeheader()
    if not PIPELINE_PATH.exists():
        with PIPELINE_PATH.open("w", newline="", encoding="utf-8") as handle:
            csv.DictWriter(handle, fieldnames=PIPELINE_FIELDS).writeheader()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def number(row: dict[str, str], key: str) -> float:
    try:
        return float(row.get(key, 0) or 0)
    except ValueError:
        return 0


def fmt_number(value: float) -> str:
    numeric = float(value)
    return str(int(numeric)) if numeric.is_integer() else f"{numeric:.1f}"


def pct(part: float, total: float) -> str:
    return f"{(part / total * 100):.1f}%" if total else "0.0%"


def aggregate(rows: list[dict[str, str]]) -> dict[str, float]:
    return {
        key: sum(number(row, key) for row in rows)
        for key in NUMERIC_FIELDS
    }


def rows_since(rows: list[dict[str, str]], days: int) -> list[dict[str, str]]:
    threshold = date.today() - timedelta(days=days - 1)
    selected = []
    for row in rows:
        try:
            row_date = date.fromisoformat(row.get("date", ""))
        except ValueError:
            continue
        if row_date >= threshold:
            selected.append(row)
    return selected


def metric_table(label: str, values: dict[str, float]) -> str:
    contacts = values["contacts"]
    conversations = values["conversations"]
    meetings = values["meetings"]
    proposals = values["proposals"]
    return "\n".join(
        [
            f"### {label}",
            "",
            "| Métrica | Valor |",
            "|---|---:|",
            f"| Investigados | {fmt_number(values['researched'])} |",
            f"| Contactos | {fmt_number(contacts)} |",
            f"| Follow-ups | {fmt_number(values['followups'])} |",
            f"| Llamadas | {fmt_number(values['calls'])} |",
            f"| Respuestas positivas | {fmt_number(values['positive_replies'])} ({pct(values['positive_replies'], contacts)}) |",
            f"| Conversaciones | {fmt_number(conversations)} ({pct(conversations, contacts)}) |",
            f"| Reuniones | {fmt_number(meetings)} ({pct(meetings, conversations)}) |",
            f"| Propuestas | {fmt_number(proposals)} ({pct(proposals, meetings)}) |",
            f"| Ganadas | {fmt_number(values['won'])} ({pct(values['won'], proposals)}) |",
            f"| EUR vendidos | {fmt_number(values['eur_sold'])} |",
            f"| Nuevos recurrentes | {fmt_number(values['new_recurring'])} |",
            f"| Horas de entrega | {fmt_number(values['delivery_hours'])} |",
        ]
    )


def pipeline_summary(rows: list[dict[str, str]]) -> str:
    active = [row for row in rows if row.get("stage", "").lower() not in {"ganada", "perdida", "lost", "won"}]
    by_stage: dict[str, int] = {}
    value = 0.0
    for row in active:
        stage = row.get("stage", "").strip() or "sin_etapa"
        by_stage[stage] = by_stage.get(stage, 0) + 1
        value += number(row, "value_eur")
    stage_text = ", ".join(f"{key}: {count}" for key, count in sorted(by_stage.items())) or "sin oportunidades"
    return f"- Oportunidades activas: **{len(active)}**\n- Valor activo: **{fmt_number(value)} EUR**\n- Por etapa: {stage_text}"


def write_status() -> None:
    ensure_files()
    activity = read_csv(ACTIVITY_PATH)
    pipeline = read_csv(PIPELINE_PATH)
    last = activity[-1] if activity else {}
    recent_notes = [
        f"- {row.get('date', '')}: {row.get('note', '')}"
        for row in activity[-5:]
        if row.get("note", "").strip()
    ]
    blockers = [
        f"- {row.get('date', '')}: {row.get('blocker', '')}"
        for row in activity[-5:]
        if row.get("blocker", "").strip()
    ]
    content = [
        "# Estado de ejecución del plan de escala",
        "",
        f"Actualizado: {datetime.now().isoformat(timespec='minutes')}",
        "",
        "## Próxima acción declarada",
        "",
        last.get("next_action", "").strip() or "No registrada.",
        "",
        "## Pipeline",
        "",
        pipeline_summary(pipeline),
        "",
        metric_table("Últimos 7 días", aggregate(rows_since(activity, 7))),
        "",
        metric_table("Últimos 30 días", aggregate(rows_since(activity, 30))),
        "",
        "## Aprendizajes recientes",
        "",
        *(recent_notes or ["- Sin aprendizajes registrados."]),
        "",
        "## Bloqueos recientes",
        "",
        *(blockers or ["- Sin bloqueos registrados."]),
        "",
        "## Archivos fuente",
        "",
        "- `storage/growth/activity.csv`: actividad diaria.",
        "- `storage/growth/pipeline.csv`: oportunidades comerciales.",
        "- `docs/PLAN_ESCALA_AGENCIA_IA.md`: reglas y objetivos.",
    ]
    STATUS_PATH.write_text("\n".join(content) + "\n", encoding="utf-8")


def checkin(args: argparse.Namespace) -> None:
    ensure_files()
    row: dict[str, Any] = {"date": args.date or date.today().isoformat()}
    for field in ACTIVITY_FIELDS:
        if field == "date":
            continue
        value = getattr(args, field, "")
        row[field] = value if field not in NUMERIC_FIELDS else value or 0
    with ACTIVITY_PATH.open("a", newline="", encoding="utf-8") as handle:
        csv.DictWriter(handle, fieldnames=ACTIVITY_FIELDS).writerow(row)
    write_status()
    print(f"Check-in guardado en {ACTIVITY_PATH}")
    print(f"Estado actualizado en {STATUS_PATH}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Seguimiento del plan de escala")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init", help="Crea los archivos de seguimiento")
    subparsers.add_parser("status", help="Regenera el resumen de estado")
    check = subparsers.add_parser("checkin", help="Registra el cierre diario")
    check.add_argument("--date", default="")
    for field in sorted(NUMERIC_FIELDS):
        check.add_argument(f"--{field.replace('_', '-')}", dest=field, type=float, default=0)
    check.add_argument("--note", default="")
    check.add_argument("--blocker", default="")
    check.add_argument("--next-action", dest="next_action", default="")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "checkin":
        checkin(args)
        return
    ensure_files()
    write_status()
    print(f"Seguimiento preparado. Lee {STATUS_PATH}")


if __name__ == "__main__":
    main()
