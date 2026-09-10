#!/usr/bin/env python3
"""
Scrape NYC fireworks and drone show events visible from Hoboken.
Aggregates from Reddit, NYC Parks, news sites, and drone companies.
Output: JSON file with upcoming events.
"""

import json
import os
import sys
from datetime import datetime, timedelta
import re
import requests
from typing import List, Dict

# Try to import optional dependencies
try:
    import praw
    HAS_PRAW = True
except ImportError:
    HAS_PRAW = False
    print("Warning: praw not installed. Reddit scraping disabled.")

try:
    from bs4 import BeautifulSoup
    HAS_BEAUTIFULSOUP = True
except ImportError:
    HAS_BEAUTIFULSOUP = False
    print("Warning: beautifulsoup4 not installed. Web scraping limited.")


class FireworksScraper:
    def __init__(self):
        self.events = []
        self.keywords = [
            'fireworks', 'drone show', 'light show',
            'pyrotechnic', 'celebration', 'skyline'
        ]

    def scrape_reddit(self) -> List[Dict]:
        """Scrape r/nyc and r/hoboken for fireworks mentions."""
        if not HAS_PRAW:
            print("Skipping Reddit: praw not installed")
            return []

        events = []
        reddit_id = os.getenv('REDDIT_CLIENT_ID')
        reddit_secret = os.getenv('REDDIT_CLIENT_SECRET')
        reddit_user = os.getenv('REDDIT_USER_AGENT', 'FireworksScraper/1.0')

        if not reddit_id or not reddit_secret:
            print("Skipping Reddit: REDDIT_CLIENT_ID or REDDIT_CLIENT_SECRET not set")
            return []

        try:
            reddit = praw.Reddit(
                client_id=reddit_id,
                client_secret=reddit_secret,
                user_agent=reddit_user
            )

            subreddits = ['nyc', 'hoboken']
            for sub_name in subreddits:
                try:
                    subreddit = reddit.subreddit(sub_name)
                    for submission in subreddit.search(
                        ' OR '.join(self.keywords),
                        time_filter='month',
                        limit=50
                    ):
                        if submission.created_utc > (datetime.now() - timedelta(days=30)).timestamp():
                            events.append({
                                'title': submission.title,
                                'description': submission.selftext[:200],
                                'source': f'r/{sub_name}',
                                'url': f'https://reddit.com{submission.permalink}',
                                'posted': datetime.fromtimestamp(submission.created_utc).isoformat(),
                                'type': self._classify_event(submission.title),
                                'confidence': 'medium'
                            })
                except Exception as e:
                    print(f"Error scraping r/{sub_name}: {e}")
        except Exception as e:
            print(f"Reddit authentication failed: {e}")

        return events

    def scrape_nyc_parks(self) -> List[Dict]:
        """Scrape NYC Parks calendar for events."""
        events = []
        try:
            # NYC Parks event calendar (basic approach - may need adjustment)
            url = "https://www.nycgovparks.org/api/events?types=fireworks"
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                data = response.json()
                for event in data.get('events', [])[:20]:
                    events.append({
                        'title': event.get('title', 'NYC Parks Event'),
                        'description': event.get('description', ''),
                        'source': 'NYC Parks',
                        'url': event.get('url', ''),
                        'date': event.get('date', ''),
                        'type': 'fireworks',
                        'confidence': 'high'
                    })
        except Exception as e:
            print(f"Error scraping NYC Parks: {e}")

        return events

    def scrape_news_sites(self) -> List[Dict]:
        """Scrape local NYC news for event announcements."""
        events = []

        if not HAS_BEAUTIFULSOUP:
            print("Skipping news scraping: beautifulsoup4 not installed")
            return []

        # Gothamist, Patch, etc.
        news_urls = [
            "https://gothamist.com/",
            "https://hoboken.patch.com/",
        ]

        for url in news_urls:
            try:
                response = requests.get(url, timeout=5)
                if response.status_code == 200:
                    soup = BeautifulSoup(response.content, 'html.parser')
                    # Look for articles mentioning fireworks/events
                    articles = soup.find_all(['article', 'div'], class_=re.compile('.*article.*', re.I))

                    for article in articles[:10]:
                        text = article.get_text(strip=True)
                        if any(kw in text.lower() for kw in self.keywords):
                            title_elem = article.find(['h2', 'h3', 'a'])
                            if title_elem:
                                events.append({
                                    'title': title_elem.get_text(strip=True)[:100],
                                    'description': text[:200],
                                    'source': url.split('/')[2],
                                    'url': url,
                                    'type': self._classify_event(text),
                                    'confidence': 'medium'
                                })
            except Exception as e:
                print(f"Error scraping {url}: {e}")

        return events

    def scrape_drone_companies(self) -> List[Dict]:
        """Check known drone show company websites for events."""
        events = []

        # Known drone show operators in NY area
        companies = {
            'Shoot Studio': 'https://www.shootstudio.com/',
            'Spark Drone Shows': 'https://sparkdroneshows.com/',
            'Intel': 'https://www.intel.com/content/www/us/en/technology-innovation/aerial-technology-light-show/overview.html'
        }

        if not HAS_BEAUTIFULSOUP:
            return []

        for company, url in companies.items():
            try:
                response = requests.get(url, timeout=5)
                if response.status_code == 200:
                    soup = BeautifulSoup(response.content, 'html.parser')
                    # Look for event dates, locations
                    text = soup.get_text()
                    if any(term in text.lower() for term in ['new york', 'nyc', 'hoboken', 'event', 'show']):
                        events.append({
                            'title': f'{company} Drone Show (Check Website)',
                            'description': 'Potential upcoming drone show - check source for details',
                            'source': f'{company} Website',
                            'url': url,
                            'type': 'drone show',
                            'confidence': 'low'
                        })
            except Exception as e:
                print(f"Error checking {company}: {e}")

        return events

    def _classify_event(self, text: str) -> str:
        """Classify event type based on text."""
        text_lower = text.lower()
        if 'drone' in text_lower:
            return 'drone show'
        elif 'fireworks' in text_lower or 'pyrotechnic' in text_lower:
            return 'fireworks'
        elif 'light' in text_lower or 'show' in text_lower:
            return 'light show'
        else:
            return 'event'

    def scrape_all(self) -> List[Dict]:
        """Run all scrapers and aggregate results."""
        all_events = []

        print("Starting scrape...")
        print("  Scraping Reddit...")
        all_events.extend(self.scrape_reddit())

        print("  Scraping NYC Parks...")
        all_events.extend(self.scrape_nyc_parks())

        print("  Scraping news sites...")
        all_events.extend(self.scrape_news_sites())

        print("  Checking drone companies...")
        all_events.extend(self.scrape_drone_companies())

        # Deduplicate by title similarity
        seen = set()
        unique_events = []
        for event in all_events:
            title_key = event.get('title', '').lower()[:50]
            if title_key not in seen:
                seen.add(title_key)
                unique_events.append(event)

        # Sort by confidence and date
        unique_events.sort(
            key=lambda e: (
                {'high': 0, 'medium': 1, 'low': 2}.get(e.get('confidence', 'low'), 3),
                e.get('date', e.get('posted', ''))
            )
        )

        return unique_events


def main():
    scraper = FireworksScraper()
    events = scraper.scrape_all()

    output = {
        'last_updated': datetime.now().isoformat(),
        'event_count': len(events),
        'events': events[:50]  # Limit to 50 most relevant
    }

    # Write to JSON
    output_dir = 'fireworks'
    os.makedirs(output_dir, exist_ok=True)

    output_file = os.path.join(output_dir, 'events.json')
    with open(output_file, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"✓ Wrote {len(events)} events to {output_file}")
    print(f"Last updated: {output['last_updated']}")


if __name__ == '__main__':
    main()
