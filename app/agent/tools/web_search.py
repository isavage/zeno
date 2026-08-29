import httpx
from bs4 import BeautifulSoup
from typing import Dict, Any, List
from app.agent.tools.base import BaseTool
import logging

logger = logging.getLogger(__name__)

class WebSearchTool(BaseTool):
    name = "web_search"
    description = "Search the public web for real-time information, news, documentation, or facts."
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query keywords."
            },
            "num_results": {
                "type": "integer",
                "description": "Number of top results to return (default: 4)",
                "default": 4
            }
        },
        "required": ["query"]
    }

    async def execute(self, query: str, num_results: int = 4, **kwargs) -> Any:
        try:
            # Use DuckDuckGo HTML search for zero-API-key open-source web search
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                resp = await client.get(
                    "https://html.duckduckgo.com/html/",
                    params={"q": query},
                    headers=headers
                )
                if resp.status_code != 200:
                    return {"error": f"Search engine returned HTTP {resp.status_code}"}

                soup = BeautifulSoup(resp.text, "html.parser")
                results: List[Dict[str, str]] = []
                for result in soup.find_all("div", class_="result"):
                    title_elem = result.find("a", class_="result__a")
                    snippet_elem = result.find("a", class_="result__snippet")
                    url_elem = result.find("a", class_="result__url")

                    if title_elem and snippet_elem:
                        results.append({
                            "title": title_elem.get_text(strip=True),
                            "snippet": snippet_elem.get_text(strip=True),
                            "url": url_elem.get_text(strip=True) if url_elem else ""
                        })
                        if len(results) >= num_results:
                            break

                return {"query": query, "results": results if results else "No results found."}
        except Exception as e:
            logger.error(f"Web search error: {e}")
            return {"error": f"Search failed: {str(e)}"}
