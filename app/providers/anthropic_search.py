"""Anthropic web search (Claude's server-side `web_search` tool, basic version) as a web search provider.

Anthropic runs the search on its own infrastructure, so this provider needs only
outbound access to api.anthropic.com and an Anthropic API key - useful where the
search APIs themselves are blocked, or to run on a single vendor key.

Evidence rules are the same as for the other providers: result URLs and titles
come from the `web_search_result` blocks, and snippets are built ONLY from the
citations' `cited_text` (verbatim text from the page). The model's own wording
is never used as evidence.

Cost (as published at the time of writing - verify on anthropic.com): web
search is billed per search (US$10 per 1,000) plus the tokens of the results
the model reads.
"""

from __future__ import annotations

from typing import Any

import anthropic

from .base import ProviderError, SearchHit

FALLBACK_BETA = "server-side-fallback-2026-07-01"
THUNDER_BAY = {"type": "approximate", "city": "Thunder Bay", "region": "Ontario", "country": "CA",
               "timezone": "America/Toronto"}

PROMPT = (
    "Search the web for: {query}\n\n"
    "Then list the most relevant results (suppliers, product pages, distributors, reviews). For each result, "
    "quote the exact passages that mention the product, its price, availability, shipping, warranty, minimum "
    "order or reviews. Quote; do not summarise, estimate or add facts of your own."
)

ERROR_KINDS = {"too_many_requests": "rate_limit", "unavailable": "upstream", "invalid_tool_input": "bad_request",
               "query_too_long": "bad_request", "max_uses_exceeded": None}


class AnthropicSearchProvider:
    name = "Anthropic web search"

    def __init__(self, api_key: str, *, model: str, base_url: str, effort: str = "low", client: Any | None = None,
                 timeout_s: float = 90.0):
        if not api_key and client is None:
            raise ProviderError(self.name, "not_configured", "set ANTHROPIC_API_KEY")
        self.client = client or anthropic.AsyncAnthropic(api_key=api_key, base_url=base_url, timeout=timeout_s,
                                                         max_retries=1)
        self.model = model
        self.effort = effort
        self.credits_used = 0.0      # web searches billed
        self.tokens = {"input_tokens": 0, "output_tokens": 0}
        self._fallbacks_supported = True

    async def _create(self, kwargs: dict[str, Any]) -> Any:
        try:
            if self._fallbacks_supported:
                try:
                    return await self.client.beta.messages.create(**kwargs, betas=[FALLBACK_BETA], fallbacks="default")
                except anthropic.BadRequestError:
                    self._fallbacks_supported = False
            return await self.client.messages.create(**kwargs)
        except anthropic.AuthenticationError as exc:
            raise ProviderError(self.name, "auth", "check ANTHROPIC_API_KEY", 401) from exc
        except anthropic.PermissionDeniedError as exc:
            raise ProviderError(self.name, "auth", "the key isn't allowed to use web search (enable it in the "
                                                   "Anthropic Console)", 403) from exc
        except anthropic.RateLimitError as exc:
            raise ProviderError(self.name, "rate_limit", "Anthropic rate limit reached", 429) from exc
        except anthropic.BadRequestError as exc:
            raise ProviderError(self.name, "bad_request", str(exc.message)[:200], 400) from exc
        except anthropic.APIStatusError as exc:
            kind = "quota" if exc.status_code == 402 else "upstream"
            raise ProviderError(self.name, kind, str(exc.message)[:200], exc.status_code) from exc
        except anthropic.APITimeoutError as exc:
            raise ProviderError(self.name, "timeout", "no response in time") from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderError(self.name, "network", "cannot reach api.anthropic.com (check firewall)") from exc

    async def search(self, query: str, *, purpose: str, max_results: int = 8, depth: str = "basic",
                     country: str | None = None, include_raw: bool = False) -> list[SearchHit]:
        # The basic tool version on purpose: with web_search_20260209 (dynamic filtering) the search runs
        # inside code execution and the answer carries no citations, so there is no verbatim page text to
        # use as evidence. web_search_20250305 returns citations with cited_text (verified live 2026-10-20).
        tool: dict[str, Any] = {"type": "web_search_20250305", "name": "web_search",
                                "max_uses": 2 if depth == "advanced" else 1}
        if country == "canada":
            tool["user_location"] = THUNDER_BAY
        messages: list[dict[str, Any]] = [{"role": "user", "content": PROMPT.format(query=query)}]
        kwargs: dict[str, Any] = dict(model=self.model, max_tokens=8000, tools=[tool], messages=messages,
                                      output_config={"effort": self.effort})
        results: dict[str, dict[str, Any]] = {}
        cited: dict[str, list[str]] = {}
        for _ in range(3):  # a server-side tool loop may pause; resume it at most twice
            resp = await self._create(kwargs)
            self._count(resp)
            if getattr(resp, "stop_reason", None) == "refusal":
                raise ProviderError(self.name, "upstream", "the model declined this search")
            for block in resp.content:
                btype = getattr(block, "type", "")
                if btype == "web_search_tool_result":
                    content = block.content
                    if isinstance(content, list):
                        for r in content:
                            if getattr(r, "type", "") == "web_search_result" and r.url not in results:
                                results[r.url] = {"title": r.title or "", "page_age": getattr(r, "page_age", None)}
                    else:
                        kind = ERROR_KINDS.get(getattr(content, "error_code", ""), "upstream")
                        if kind:
                            raise ProviderError(self.name, kind, f"web search error: {content.error_code}")
                elif btype == "text":
                    for c in getattr(block, "citations", None) or []:
                        if getattr(c, "type", "") == "web_search_result_location" and c.cited_text:
                            cited.setdefault(c.url, [])
                            if c.cited_text not in cited[c.url]:
                                cited[c.url].append(c.cited_text)
                            if c.url not in results:
                                results[c.url] = {"title": c.title or "", "page_age": None}
            if getattr(resp, "stop_reason", None) != "pause_turn":
                break
            # resume: send the assistant turn back unchanged (including any thinking blocks)
            content = [b.to_dict() if hasattr(b, "to_dict") else b for b in resp.content]
            messages = messages + [{"role": "assistant", "content": content}]
            kwargs["messages"] = messages
        hits = []
        for rank, (url, meta) in enumerate(list(results.items())[: max(1, min(max_results, 20))], start=1):
            hits.append(SearchHit(provider=self.name, query=query, purpose=purpose, url=url, title=meta["title"],
                                  snippet=" … ".join(cited.get(url, []))[:1500], rank=rank,
                                  published_date=meta["page_age"]))
        return hits

    def _count(self, resp: Any) -> None:
        usage = getattr(resp, "usage", None)
        if usage is None:
            return
        self.tokens["input_tokens"] += getattr(usage, "input_tokens", 0) or 0
        self.tokens["output_tokens"] += getattr(usage, "output_tokens", 0) or 0
        stu = getattr(usage, "server_tool_use", None)
        self.credits_used += float(getattr(stu, "web_search_requests", 0) or 0) if stu else 0.0
