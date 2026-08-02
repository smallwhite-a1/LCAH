"""Session compaction boundary."""

from .compaction_summary import build_summary
from .context_usage import estimate_tokens
from .quality import (
    SUMMARY_CONTRACT,
    critical_context_signals,
    verify_compaction_continuity,
)
from .workspace import now


class CompactManager:
    def __init__(self, agent):
        self.agent = agent

    def compact(self, trigger="manual", keep_recent_turns=2):
        history = list(self.agent.session.get("history", []))
        groups = self._group(history)
        if len(groups) <= keep_recent_turns:
            summary = self._summary(trigger, history, history, "")
            summary["applied"] = False
            summary["quality_repair_attempts"] = 0
            summary["quality_verification"] = verify_compaction_continuity(
                history, history, "", keep_recent_turns=keep_recent_turns
            )
            self.agent.session_event_bus.emit("compaction_created", summary)
            return summary

        compacted_turns = groups[:-keep_recent_turns]
        kept_turns = groups[-keep_recent_turns:]
        compacted_items = [item for _, items in compacted_turns for item in items]
        kept_items = [item for _, items in kept_turns for item in items]
        quality_repair_attempts = 0
        summary_text = ""
        compacted_history = []
        quality_verification = None
        for attempt in range(2):
            summary_text = self._summary_text(compacted_items)
            if attempt == 1:
                summary_text = self._repair_summary_text(compacted_items, summary_text)
            summary_item = self.agent.turn_history.enrich(
                {
                    "role": "system",
                    "kind": "compact_summary",
                    "content": summary_text,
                    "created_at": now(),
                    "source": "compact",
                }
            )
            compacted_history = [summary_item, *kept_items]
            quality_verification = verify_compaction_continuity(
                history,
                compacted_history,
                summary_text,
                keep_recent_turns=keep_recent_turns,
            )
            if quality_verification["passed"]:
                break
            if attempt == 0:
                quality_repair_attempts += 1
        summary = self._summary(trigger, history, compacted_history, summary_text)
        summary["applied"] = quality_verification["passed"]
        summary["quality_repair_attempts"] = quality_repair_attempts
        summary["quality_verification"] = quality_verification
        if not quality_verification["passed"]:
            self.agent.session_event_bus.emit("compaction_quality_failed", summary)
            return summary
        self.agent.session["history"] = compacted_history
        self.agent.session.setdefault("compactions", []).append(summary)
        self.agent.session_path = self.agent.session_store.save(self.agent.session)
        self.agent.session_event_bus.emit("compaction_created", summary)
        if self.agent.current_task_state:
            self.agent.emit_trace(self.agent.current_task_state, "compaction_started", {"trigger": trigger, "pre_tokens": summary["pre_tokens"]})
            self.agent.emit_trace(self.agent.current_task_state, "compaction_finished", summary)
        return summary

    @staticmethod
    def _repair_summary_text(items, summary_text):
        """Add omitted evidence on the bounded repair attempt."""

        summary_text = str(summary_text or "")
        if not all(marker in summary_text for marker in SUMMARY_CONTRACT):
            return summary_text
        summary_lower = summary_text.lower()
        missing = [
            signal
            for signal in critical_context_signals(items)
            if signal.lower() not in summary_lower
        ]
        if not missing:
            return summary_text
        evidence = "; ".join(missing)
        return "\n".join(
            [
                summary_text,
                f"- Evidence: repair_required_signals={evidence}",
                f"- Critical context: repaired={evidence}",
            ]
        )

    @staticmethod
    def _group(history):
        groups = []
        by_id = {}
        for item in history:
            turn_id = str(item.get("turn_id") or "legacy")
            if turn_id not in by_id:
                by_id[turn_id] = []
                groups.append((turn_id, by_id[turn_id]))
            by_id[turn_id].append(item)
        return groups

    def _summary(self, trigger, before, after, summary_text):
        pre_chars = sum(len(str(item.get("content", ""))) for item in before)
        post_chars = sum(len(str(item.get("content", ""))) for item in after)
        return {
            "trigger": str(trigger),
            "created_at": now(),
            "pre_tokens": estimate_tokens(pre_chars),
            "post_tokens": estimate_tokens(post_chars),
            "pre_items": len(before),
            "post_items": len(after),
            "summary_chars": len(summary_text),
        }

    def _summary_text(self, items):
        return build_summary(items)
