"""
tools.knowledge.server — knowledge MCP Tool Package.

Provides tools for web search, plant identification, care guide retrieval,
and local knowledge base search.

Tools:
  knowledge.search_web       — search the web via Tavily
  knowledge.identify_plant   — identify a plant species from an image
  knowledge.fetch_care_guide — fetch and cache plant care instructions
  knowledge.search_local_kb  — keyword search over local summaries
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
from pathlib import Path

from mcp.server import Server
from mcp.types import TextContent, Tool

from tools.shared.errors import ToolError, ExternalAPIError

logger = logging.getLogger(__name__)

app = Server("knowledge-tools")


# ── Tool definitions ──────────────────────────────────────────────────────────

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="knowledge.search_web",
            description="Search the web using Tavily and return a list of relevant results.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query string",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results to return. Default: 5",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="knowledge.identify_plant",
            description=(
                "Identify a plant species from a camera frame image. "
                "Returns species name, common name, confidence, and a brief care summary."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "frame_path": {
                        "type": "string",
                        "description": "Absolute path to the JPEG frame file",
                    }
                },
                "required": ["frame_path"],
            },
        ),
        Tool(
            name="knowledge.fetch_care_guide",
            description=(
                "Fetch detailed care instructions for a plant species. "
                "Results are cached locally — subsequent calls for the same species are instant."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "species_name": {
                        "type": "string",
                        "description": "Plant species name (e.g. 'monstera deliciosa', 'pothos')",
                    }
                },
                "required": ["species_name"],
            },
        ),
        Tool(
            name="knowledge.search_local_kb",
            description=(
                "Search the local knowledge base (saved summaries) using keyword matching. "
                "Returns the most relevant summaries sorted by relevance score."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (keywords)",
                    },
                    "category": {
                        "type": "string",
                        "description": "Optional category filter",
                    },
                },
                "required": ["query"],
            },
        ),
    ]


# ── Tool dispatcher ───────────────────────────────────────────────────────────

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "knowledge.search_web":
            result = await _search_web(
                arguments["query"],
                int(arguments.get("max_results", 5)),
            )
        elif name == "knowledge.identify_plant":
            result = await _identify_plant(arguments["frame_path"])
        elif name == "knowledge.fetch_care_guide":
            result = await _fetch_care_guide(arguments["species_name"])
        elif name == "knowledge.search_local_kb":
            result = _search_local_kb(
                arguments["query"],
                arguments.get("category"),
            )
        else:
            raise ValueError(f"Unknown tool: {name}")
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
    except (ToolError, ExternalAPIError) as exc:
        return [TextContent(type="text", text=json.dumps({"error": str(exc)}))]
    except Exception as exc:
        logger.exception("knowledge tool error in %s", name)
        return [TextContent(type="text", text=json.dumps({"error": str(exc)}))]


# ── Implementation ────────────────────────────────────────────────────────────

async def _search_web(query: str, max_results: int = 5) -> list[dict]:
    from tools.shared.config import get_tool_config

    cfg = get_tool_config()
    if cfg.search_provider != "tavily":
        raise ToolError(
            "Only tavily is supported in MVP. "
            f"Current provider: {cfg.search_provider}",
            tool_name="knowledge.search_web",
        )
    if not cfg.tavily_api_key:
        raise ExternalAPIError(
            "TAVILY_API_KEY is not set. Add it to .env",
            tool_name="knowledge.search_web",
        )

    try:
        from tavily import TavilyClient  # type: ignore[import]
    except ImportError as exc:
        raise ToolError(
            "tavily-python is not installed. Install it with: pip install tavily-python",
            tool_name="knowledge.search_web",
        ) from exc

    client = TavilyClient(api_key=cfg.tavily_api_key)
    response = client.search(query=query, max_results=max_results)
    results = []
    for item in response.get("results", []):
        results.append({
            "title": item.get("title", ""),
            "snippet": item.get("content", "")[:500],
            "url": item.get("url", ""),
        })
    return results


async def _identify_plant(frame_path: str) -> dict:
    import litellm  # type: ignore[import]
    from tools.shared.config import get_tool_config

    cfg = get_tool_config()
    image_data = Path(frame_path).read_bytes()
    b64 = base64.b64encode(image_data).decode("utf-8")

    prompt = (
        "You are a botanist. Identify the plant in this image. "
        "Respond ONLY with a JSON object in this exact format:\n"
        '{"species": "<scientific name>", "common_name": "<common name>", '
        '"confidence": "<high|medium|low>", "care_summary": "<1-2 sentence care tip>"}\n'
        "If you cannot identify the plant, use 'unknown' for species and common_name."
    )

    try:
        response = await litellm.acompletion(
            model=cfg.vision_model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )
        text = response.choices[0].message.content or ""
        # Extract JSON from response
        json_match = re.search(r"\{.*\}", text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
    except (json.JSONDecodeError, Exception) as exc:
        logger.warning("identify_plant: failed to parse LLM response: %s", exc)

    return {
        "species": "unknown",
        "common_name": "unknown",
        "confidence": "low",
        "care_summary": "",
    }


def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "_", text)
    return text[:60]


def _cache_dir() -> Path:
    from core.config import app_config
    d = Path(app_config.storage.base_dir).expanduser() / "cache" / "care_guides"
    d.mkdir(parents=True, exist_ok=True)
    return d


async def _fetch_care_guide(species_name: str) -> dict:
    import litellm  # type: ignore[import]

    cache_path = _cache_dir() / f"{_slugify(species_name)}.json"

    # Cache hit — return immediately without network call
    if cache_path.exists():
        logger.debug("fetch_care_guide: cache hit for '%s'", species_name)
        return json.loads(cache_path.read_text(encoding="utf-8"))

    # Cache miss — search web + LLM extraction
    logger.info("fetch_care_guide: cache miss for '%s', fetching...", species_name)
    search_results = await _search_web(
        f"{species_name} plant care guide watering light temperature",
        max_results=3,
    )
    search_context = "\n\n".join(
        f"Source: {r['url']}\n{r['snippet']}" for r in search_results
    )

    from tools.shared.config import get_tool_config
    cfg = get_tool_config()

    prompt = (
        f"Based on the following search results about '{species_name}' plant care, "
        "extract structured care information. "
        "Respond ONLY with a JSON object in this exact format:\n"
        '{"watering": "<frequency and amount>", "light": "<light requirements>", '
        '"temperature": "<temperature range>", "humidity": "<humidity preference>", '
        '"notes": "<any important additional notes>"}\n\n'
        f"Search results:\n{search_context}"
    )

    try:
        response = await litellm.acompletion(
            model=cfg.default_model,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.choices[0].message.content or ""
        json_match = re.search(r"\{.*\}", text, re.DOTALL)
        if json_match:
            care_guide = json.loads(json_match.group())
        else:
            raise ValueError("No JSON found in LLM response")
    except Exception as exc:
        logger.warning("fetch_care_guide: LLM extraction failed: %s", exc)
        care_guide = {
            "watering": "Unknown",
            "light": "Unknown",
            "temperature": "Unknown",
            "humidity": "Unknown",
            "notes": f"Could not extract care guide for '{species_name}'",
        }

    # Write to cache
    cache_path.write_text(json.dumps(care_guide, ensure_ascii=False, indent=2), encoding="utf-8")
    return care_guide


def _search_local_kb(query: str, category: str | None = None) -> list[dict]:
    from core.config import app_config

    summaries_dir = Path(app_config.storage.base_dir).expanduser() / "summaries"
    if not summaries_dir.exists():
        return []

    query_words = [w.lower() for w in re.split(r"\W+", query) if w]
    if not query_words:
        return []

    results = []
    for json_file in summaries_dir.glob("*.json"):
        try:
            record = json.loads(json_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        if category and record.get("category") != category:
            continue

        content_lower = record.get("content", "").lower()
        score = sum(content_lower.count(word) for word in query_words)
        if score == 0:
            continue

        results.append({
            "summary_id": record["id"],
            "relevance_score": float(score),
            "snippet": record.get("content", "")[:300],
            "category": record.get("category", ""),
            "created_at": record.get("created_at", ""),
        })

    # Sort by relevance descending, then by recency
    results.sort(key=lambda x: (-x["relevance_score"], x["created_at"]))
    return results[:10]


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from tools.shared.mcp_base import run_server
    asyncio.run(run_server(app))
