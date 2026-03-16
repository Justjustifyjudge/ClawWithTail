"""
core.agent.context_budget — Context window budget manager.

Enforces token budgets for each section of the LLM context:
  - System prompt (task goal + constraints)
  - Summaries (recent historical summaries)
  - Sensor stats (aggregated sensor data)
  - Tool history (previous tool calls in this run)

Design principle: LLM context must NEVER contain raw images or large tables.
All sections are truncated to their budget before being assembled.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class AgentContext:
    """
    Assembled context for one Agent run.
    Built by ContextBuilder from TaskConfig.context settings.
    """
    summaries: list[str] = field(default_factory=list)
    sensor_stats: dict[str, dict] = field(default_factory=dict)


class ContextBudget:
    """
    Manages token budgets for each section of the LLM context window.

    Token estimation: simple character-count / 4 heuristic.
    This avoids a tiktoken dependency and is accurate enough for budget enforcement.
    """

    # Per-section token budgets
    SYSTEM_PROMPT_MAX: int = 1000
    SUMMARIES_MAX: int = 2000
    SENSOR_STATS_MAX: int = 500
    TOOL_HISTORY_MAX: int = 3000
    TOTAL_MAX: int = 8000

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """
        Estimate token count from character count.
        Rule of thumb: 1 token ≈ 4 characters for English text.
        """
        return max(1, len(text) // 4)

    @staticmethod
    def truncate_to_budget(text: str, max_tokens: int) -> str:
        """
        Truncate text to fit within max_tokens.
        Appends '...[truncated]' if truncation occurred.
        """
        max_chars = max_tokens * 4
        if len(text) <= max_chars:
            return text
        truncated = text[:max_chars - 20]
        return truncated + "...[truncated]"

    def build_messages(
        self,
        task,  # TaskConfig
        context: AgentContext,
        tool_history: list[dict],
    ) -> list[dict]:
        """
        Assemble the messages list for the LLM, enforcing per-section budgets.

        Message structure:
          1. system: task goal + constraints + context summaries + sensor stats
          2. user: "Begin." (initial trigger)
          3. assistant/tool: tool_history entries (interleaved)

        Args:
            task: TaskConfig with goal, constraints, max_steps.
            context: AgentContext with summaries and sensor_stats.
            tool_history: List of previous tool call/result dicts in this run.

        Returns:
            OpenAI-format messages list.
        """
        # ── 1. Build system prompt ────────────────────────────────────────────
        constraints_text = ""
        if task.constraints:
            constraints_text = "\n\nConstraints:\n" + "\n".join(
                f"- {c}" for c in task.constraints
            )

        system_core = (
            f"You are ClawWithTail, a physical-world AI agent.\n\n"
            f"Goal: {task.goal}"
            f"{constraints_text}\n\n"
            f"You have access to tools. Use them to accomplish the goal.\n"
            f"When you have enough information, provide a final answer without calling any tools.\n"
            f"Maximum steps: {task.max_steps}."
        )
        system_core = self.truncate_to_budget(system_core, self.SYSTEM_PROMPT_MAX)

        # ── 2. Build summaries section ────────────────────────────────────────
        summaries_section = ""
        if context.summaries:
            summaries_text = "\n---\n".join(context.summaries)
            summaries_text = self.truncate_to_budget(summaries_text, self.SUMMARIES_MAX)
            summaries_section = f"\n\n## Recent Summaries\n{summaries_text}"

        # ── 3. Build sensor stats section ─────────────────────────────────────
        sensor_section = ""
        if context.sensor_stats:
            stats_lines = []
            for device_id, stats in context.sensor_stats.items():
                stats_str = json.dumps(stats, ensure_ascii=False)
                stats_lines.append(f"- {device_id}: {stats_str}")
            sensor_text = "\n".join(stats_lines)
            sensor_text = self.truncate_to_budget(sensor_text, self.SENSOR_STATS_MAX)
            sensor_section = f"\n\n## Sensor Stats\n{sensor_text}"

        # ── 4. Assemble system message ────────────────────────────────────────
        system_content = system_core + summaries_section + sensor_section
        messages: list[dict] = [
            {"role": "system", "content": system_content}
        ]

        # ── 5. Inject tool history ────────────────────────────────────────────
        if tool_history:
            # Serialize and budget-check the entire history
            history_text = json.dumps(tool_history, ensure_ascii=False)
            if self.estimate_tokens(history_text) > self.TOOL_HISTORY_MAX:
                # Keep only the most recent entries that fit
                kept = []
                budget_remaining = self.TOOL_HISTORY_MAX
                for entry in reversed(tool_history):
                    entry_text = json.dumps(entry, ensure_ascii=False)
                    entry_tokens = self.estimate_tokens(entry_text)
                    if entry_tokens <= budget_remaining:
                        kept.insert(0, entry)
                        budget_remaining -= entry_tokens
                    else:
                        break
                tool_history = kept
                logger.debug(
                    "ContextBudget: tool_history truncated to %d entries", len(kept)
                )

            # Inject as alternating assistant/tool messages
            for entry in tool_history:
                if entry.get("role") == "assistant":
                    messages.append({"role": "assistant", "content": entry.get("content", ""), "tool_calls": entry.get("tool_calls", [])})
                elif entry.get("role") == "tool":
                    messages.append({
                        "role": "tool",
                        "tool_call_id": entry.get("tool_call_id", ""),
                        "content": entry.get("content", ""),
                    })
                else:
                    messages.append(entry)
        else:
            # First step: add initial user message
            messages.append({"role": "user", "content": "Begin."})

        # ── 6. Final total budget check ───────────────────────────────────────
        total_text = json.dumps(messages, ensure_ascii=False)
        total_tokens = self.estimate_tokens(total_text)
        if total_tokens > self.TOTAL_MAX:
            logger.warning(
                "ContextBudget: total estimated tokens %d exceeds TOTAL_MAX %d",
                total_tokens, self.TOTAL_MAX,
            )

        return messages
