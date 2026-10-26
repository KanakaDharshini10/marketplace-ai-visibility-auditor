"""Single source of truth for the marketplace version string."""

__version__ = "1.11.2"

TOOL_NAME = "marketplace-ai-visibility-auditor"

#: User-Agent used for every outbound request. It is honest about what the
#: crawler is and links to the marketplace so a site owner reading their logs
#: can identify it. Never spoof a browser or a known crawler.
USER_AGENT = (
    "MarketplaceAIVisibilityAuditor/{v} (+read-only site audit; "
    "respects robots.txt; contact: site owner via audit operator)"
).format(v=__version__)

#: The product token this auditor obeys in robots.txt.
ROBOTS_UA_TOKEN = "MarketplaceAIVisibilityAuditor"
