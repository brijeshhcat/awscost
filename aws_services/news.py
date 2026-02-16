"""
AWS News Service
Fetches the latest AWS blog posts / announcements via RSS feeds.
"""

import feedparser
from datetime import datetime


class AWSNewsService:
    # AWS official RSS feeds
    FEEDS = {
        "aws_blog": "https://aws.amazon.com/blogs/aws/feed/",
        "whats_new": "https://aws.amazon.com/about-aws/whats-new/recent/feed/",
        "cost_management": "https://aws.amazon.com/blogs/aws-cloud-financial-management/feed/",
    }

    def get_latest_news(self, limit=20):
        """Aggregate and sort latest articles from multiple AWS RSS feeds."""
        articles = []
        for source, url in self.FEEDS.items():
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:limit]:
                    published = ""
                    if hasattr(entry, "published_parsed") and entry.published_parsed:
                        published = datetime(*entry.published_parsed[:6]).strftime(
                            "%Y-%m-%d %H:%M"
                        )
                    elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
                        published = datetime(*entry.updated_parsed[:6]).strftime(
                            "%Y-%m-%d %H:%M"
                        )

                    # Clean up summary
                    summary = entry.get("summary", "")
                    if len(summary) > 300:
                        summary = summary[:300] + "..."

                    articles.append({
                        "title": entry.get("title", ""),
                        "link": entry.get("link", ""),
                        "published": published,
                        "summary": summary,
                        "source": source.replace("_", " ").title(),
                        "author": entry.get("author", "AWS"),
                    })
            except Exception:
                continue

        # Sort by published date descending
        articles.sort(key=lambda a: a["published"], reverse=True)
        return articles[:limit]
