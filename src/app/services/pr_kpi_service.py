import os
import re
import sys
import hashlib
import logging
import unicodedata
import asyncio
from collections import Counter
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlparse, parse_qs, unquote
from typing import List, Dict, Any, Optional, Tuple
from datetime import UTC

import aiohttp
import feedparser
import pandas as pd
import tldextract
from dateutil import parser as dateparser
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.pr_campaign import Campaign, CampaignJob, Article, BrandKPI, PublicationKPI, GenericKeywordAnalysis
from ..crud.crud_campaign import crud_campaign_job

logger = logging.getLogger(__name__)

class PRKPIService:
    def __init__(self, db: AsyncSession, campaign_id: int):
        self.db = db
        self.campaign_id = campaign_id
        self.campaign = None
        self.job = None
        self.analyzer = SentimentIntensityAnalyzer()
        
        # Configuration
        self.USER_AGENT = "Mozilla/5.0 (compatible; PR-KPI/1.4; +https://example.com)"
        self.HEADERS = {"User-Agent": self.USER_AGENT, "Accept": "application/rss+xml,text/xml;q=0.9,*/*;q=0.8"}
        self.AGGREGATOR_DOMAINS = {
            "google.com", "news.google.com", "bing.com", "www.bing.com", 
            "news.bing.com", "news.yahoo.com", "yahoo.com"
        }
        self.MARKETS = {
            "IN": {
                "google": {"hl": "en-IN", "gl": "IN", "ceid": "IN:en"},
                "bing": {"setmkt": "en-IN", "cc": "IN"},
                "yahoo": {"vl": "lang_en"},
            },
            "US": {
                "google": {"hl": "en-US", "gl": "US", "ceid": "US:en"},
                "bing": {"setmkt": "en-US", "cc": "US"},
                "yahoo": {"vl": "lang_en"},
            },
        }
        self.TIER_WEIGHTS = {"tier1": 1.50, "tier2": 1.00, "tier3": 0.65}
        self.TIER1_DOMAINS = {
            "reuters.com", "bloomberg.com", "wsj.com", "ft.com", "nytimes.com", 
            "theguardian.com", "economictimes.com", "livemint.com", "business-standard.com",
            "indianexpress.com", "moneycontrol.com", "forbes.com", "cnbc.com", 
            "techcrunch.com", "theverge.com", "venturebeat.com"
        }
        self.BASELINE_CPM_INR = 200
        self.STOPWORDS = {
            "the", "a", "an", "of", "for", "and", "or", "in", "to", "on", "by", 
            "with", "at", "from", "as", "is", "are", "was", "were", "it", "this", "that"
        }
        self.ENGINE_BUILDERS = {
            "google": self.build_google_url, 
            "bing": self.build_bing_url, 
            "yahoo": self.build_yahoo_url
        }

    async def update_job_progress(self, progress: int, stage: str):
        """Update job progress and current stage"""
        try:
            self.job = await crud_campaign_job.update_progress(
                self.db, self.campaign_id, progress, stage
            )
        except Exception as e:
            logger.error(f"Error updating job progress: {e}")

    # ========== ORIGINAL PR_KPI.PY FUNCTIONS (Converted to async) ==========
    
    def build_google_url(self, query: str, market: str) -> str:
        m = self.MARKETS.get(market, self.MARKETS["US"])["google"]
        params = {"q": query, **m}
        return "https://news.google.com/rss/search?" + urlencode(params)

    def build_bing_url(self, query: str, market: str) -> str:
        m = self.MARKETS.get(market, self.MARKETS["US"])["bing"]
        params = {"q": query, "format": "rss", **m}
        return "https://www.bing.com/news/search?" + urlencode(params)

    def build_yahoo_url(self, query: str, market: str) -> str:
        m = self.MARKETS.get(market, self.MARKETS["US"])["yahoo"]
        params = {"p": query, **m}
        return "https://news.search.yahoo.com/rss?" + urlencode(params)

    def norm_domain(self, url: str) -> str:
        try:
            ext = tldextract.extract(url)
            if ext.domain and ext.suffix:
                return f"{ext.domain}.{ext.suffix}".lower()
        except Exception:
            pass
        try:
            netloc = urlparse(url).netloc.lower()
            return netloc.split(":")[0]
        except Exception:
            return ""

    def clean_text(self, s: str) -> str:
        if not s:
            return ""
        s = re.sub(r"<[^>]+>", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    def normalize(self, s: str) -> str:
        if not s:
            return ""
        s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
        s = s.lower()
        s = re.sub(r"\s+", " ", s).strip()
        return s

    def safe_parse_date(self, dt_str):
        if not dt_str:
            return None
        try:
            return dateparser.parse(dt_str)
        except Exception:
            return None

    def strip_title_for_dedupe(self, title: str) -> str:
        """Strip title for deduplication by removing common words and normalizing"""
        if not title:
            return ""
        s = title.lower()
        s = re.sub(r"[\W_]+", " ", s)
        s = re.sub(r"\b(update|breaking|exclusive)\b", "", s)
        return s.strip()

    def hash_id(self, *parts) -> str:
        """Generate hash ID from multiple parts"""
        h = hashlib.sha1()
        for p in parts:
            h.update(str(p).encode("utf-8"))
        return h.hexdigest()[:16]

    def peel_redirect_param(self, url: str) -> str | None:
        """Try to peel target from common redirect params like ?url=, ?u=, etc."""
        try:
            q = parse_qs(urlparse(url).query)
            for key in ("url", "u", "r", "ru", "to", "out"):
                if key in q and q[key]:
                    return unquote(q[key][0])
        except Exception:
            pass
        return None

    async def resolve_publisher_url_async(self, link: str, timeout: int = 10) -> str:
        """
        Return the best-guess publisher article URL.
        Strategy:
          1) Peel explicit redirect param if present (?url=...).
          2) GET with allow_redirects=True (HEAD often blocked by CDNs).
          3) Fallback to original link.
        """
        # (1) peel
        peeled = self.peel_redirect_param(link)
        if peeled:
            return peeled

        # (2) follow redirects (some aggregators 302 to publisher)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(link, headers=self.HEADERS, timeout=timeout, allow_redirects=True) as response:
                    return str(response.url) or link
        except Exception:
            return link

    def is_aggregator_domain(self, domain: str) -> bool:
        """Check if domain is a news aggregator"""
        return domain in self.AGGREGATOR_DOMAINS

    def tier_for_domain(self, domain: str) -> str:
        """Determine publisher tier based on domain"""
        if domain in self.TIER1_DOMAINS:
            return "tier1"
        if domain.endswith(".gov") or domain.endswith(".gov.in"):
            return "tier1"
        if domain.endswith(".edu") or domain.endswith(".org"):
            return "tier2"
        return "tier2"  # Default to tier2 for other domains

    def estimate_monthly_visits(self, domain: str) -> float:
        """Estimate monthly visits based on domain tier"""
        tier = self.tier_for_domain(domain)
        if tier == "tier1":
            return 30_000_000
        elif tier == "tier2":
            return 5_000_000
        return 1_000_000

    def article_reach_score(self, domain: str, position_weight: float = 1.0) -> float:
        """Calculate article reach score based on domain authority and position"""
        monthly = self.estimate_monthly_visits(domain)
        daily = monthly / 30.0
        news_share = 0.20  # 20% of traffic goes to news section
        base_ctr = 0.01    # 1% click-through rate
        tier_w = self.TIER_WEIGHTS.get(self.tier_for_domain(domain), 1.0)
        return float(daily * news_share * base_ctr * tier_w * position_weight)

    def position_to_weight(self, idx: int) -> float:
        """Convert article position in feed to weight"""
        if idx <= 2:  return 1.2
        if idx <= 5:  return 1.0
        if idx <= 10: return 0.8
        return 0.6

    def sentiment_score(self, text: str) -> float:
        """Calculate sentiment score using VADER"""
        if not text:
            return 0.0
        vs = self.analyzer.polarity_scores(text)
        return float(vs["compound"])

    def parse_query(self, query: str, include: str | None, exclude: str | None):
        """Parse query into phrases, tokens, include/exclude terms"""
        PHRASE_RE = re.compile(r'"([^"]+)"')
        phrases = PHRASE_RE.findall(query)
        q_wo_phrases = PHRASE_RE.sub(" ", query)
        tokens = [w for w in re.split(r"[^\w@#+/.-]+", q_wo_phrases) if w]

        inc = [s.strip() for s in (include or "").split(";") if s.strip()]
        exc = [s.strip() for s in (exclude or "").split(";") if s.strip()]

        norm_tokens = []
        for t in tokens:
            nt = self.normalize(t)
            if nt and nt not in self.STOPWORDS:
                norm_tokens.append(nt)

        norm_phrases = [self.normalize(p) for p in phrases if p.strip()]
        norm_inc = [self.normalize(x) for x in inc]
        norm_exc = [self.normalize(x) for x in exc]
        return norm_phrases, norm_tokens, norm_inc, norm_exc

    def word_boundary_pattern(self, term: str) -> re.Pattern:
        """Create word boundary pattern for matching"""
        if re.match(r"^[A-Za-z0-9@#+/.-]+$", term):
            return re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.IGNORECASE)
        return re.compile(re.escape(term), re.IGNORECASE)

    def score_match(self, row, phrases, tokens, inc_terms, exc_terms,
                    require_title=False, min_score=2.0, min_token_hits=1, strict_match=False):
        """Score article match based on keywords and phrases"""
        title = self.normalize(row.get("title", ""))
        summary = self.normalize(row.get("summary", ""))
        body = self.normalize(row.get("body", ""))

        # Exclusions
        for t in exc_terms:
            pat = self.word_boundary_pattern(t)
            if pat.search(title) or pat.search(summary) or pat.search(body):
                return False, 0.0

        score = 0.0
        token_hits = 0

        # Phrases & includes
        for ph in phrases + inc_terms:
            pat = self.word_boundary_pattern(ph)
            if pat.search(title):   score += 3.0
            if pat.search(summary): score += 2.0
            if pat.search(body):    score += 1.25

        # Tokens
        for tk in tokens:
            pat = self.word_boundary_pattern(tk)
            ht = bool(pat.search(title)); hs = bool(pat.search(summary)); hb = bool(pat.search(body))
            if ht or hs or hb:
                token_hits += 1
                if ht: score += 1.0
                if hs: score += 0.6
                if hb: score += 0.35

        if require_title:
            title_ok = any(self.word_boundary_pattern(ph).search(title) for ph in phrases + inc_terms + tokens)
            if not title_ok:
                return False, score

        if strict_match:
            strict_ok = (any(self.word_boundary_pattern(ph).search(" ".join([title, summary, body])) for ph in phrases + inc_terms)
                         or token_hits >= max(1, min_token_hits))
            if not strict_ok:
                return False, score

        return (score >= min_score), score

    def compute_scores(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute all scores and metrics for articles"""
        df["title_key"] = df["title"].apply(self.strip_title_for_dedupe)
        df["row_id"] = [self.hash_id(r["link"], r["title_key"]) for _, r in df.iterrows()]
        df = df.drop_duplicates(subset=["row_id"]).copy()

        df["sentiment"] = df["title"].fillna("").map(self.sentiment_score)
        df["position_w"] = df["rank_in_feed"].fillna(50).astype(int).map(self.position_to_weight)
        df["est_ars"] = df.apply(lambda r: self.article_reach_score(r["domain"], r["position_w"]), axis=1)

        title_counts = df.groupby("title_key")["domain"].nunique().to_dict()
        df["pickup_count"] = df["title_key"].map(lambda k: max(0, title_counts.get(k, 1) - 1))

        df["inferred_clicks"] = (df["est_ars"] * 1.0) * (1 + df["sentiment"].clip(lower=-0.2, upper=0.5) * 0.2)
        df["engagement_rate"] = (df["pickup_count"] + df["inferred_clicks"]) / (df["est_ars"] + 1e-6)
        df["tier"] = df["domain"].map(self.tier_for_domain)
        df["is_aggregator"] = df["domain"].map(self.is_aggregator_domain)
        return df

    def kpis_by_brand(self, df: pd.DataFrame, brand_map: dict) -> pd.DataFrame:
        """Compute brand-level KPIs"""
        df["brand"] = df["query"].map(brand_map).fillna(df["query"])
        grp = df.groupby("brand")
        out = pd.DataFrame({
            "mentions": grp["row_id"].count(),
            "weighted_reach": grp["est_ars"].sum(),
            "avg_sentiment": grp["sentiment"].mean(),
            "avg_engagement_rate": grp["engagement_rate"].mean(),
            "avg_pickup_rate": grp["pickup_count"].mean(),
            "inferred_clicks": grp["inferred_clicks"].sum(),
        }).reset_index()

        total_mentions = out["mentions"].sum()
        out["share_of_voice_%"] = (out["mentions"] / max(1, total_mentions)) * 100.0
        out["ad_equivalent_value_inr"] = (out["weighted_reach"] / 1000.0) * self.BASELINE_CPM_INR

        for col in ["weighted_reach", "inferred_clicks", "ad_equivalent_value_inr"]:
            out[col] = out[col].round(0).astype(int)
        for col in ["avg_sentiment", "avg_engagement_rate", "avg_pickup_rate", "share_of_voice_%"]:
            out[col] = out[col].round(3)
        return out.sort_values("weighted_reach", ascending=False)

    def kpis_by_publication(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute publication-level KPIs"""
        grp = df.groupby("domain")
        out = pd.DataFrame({
            "mentions": grp["row_id"].count(),
            "weighted_reach": grp["est_ars"].sum(),
            "avg_engagement_rate": grp["engagement_rate"].mean(),
            "avg_sentiment": grp["sentiment"].mean(),
            "tier": grp["tier"].agg(lambda x: Counter(x).most_common(1)[0][0]),
            "is_aggregator": grp["is_aggregator"].agg(lambda x: Counter(x).most_common(1)[0][0]),
        }).reset_index().sort_values("weighted_reach", ascending=False)
        out["weighted_reach"] = out["weighted_reach"].round(0).astype(int)
        out["avg_engagement_rate"] = out["avg_engagement_rate"].round(3)
        out["avg_sentiment"] = out["avg_sentiment"].round(3)
        return out

    # ========== ASYNC HTTP METHODS ==========

    async def fetch_feed_async(self, url: str) -> feedparser.FeedParserDict:
        """Fetch and parse RSS feed asynchronously"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.HEADERS, timeout=15) as response:
                    text = await response.text()
                    return feedparser.parse(text)
        except Exception as e:
            logging.warning(f"Feed fetch failed: {e}")
            return feedparser.parse("")

    async def fetch_news_async(self, query: str, days: int = 14, max_items: int = 100, markets: List[str] = None) -> List[Dict]:
        """Fetch news articles from multiple sources and markets"""
        if markets is None:
            markets = ["IN", "US"]
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        results = []
        
        for market in markets:
            for engine, builder in self.ENGINE_BUILDERS.items():
                feed_url = builder(query, market)
                d = await self.fetch_feed_async(feed_url)
                entries = d.entries[:max_items]
                
                for i, e in enumerate(entries):
                    title = self.clean_text(getattr(e, "title", ""))
                    raw_link = getattr(e, "link", "")
                    summary = self.clean_text(getattr(e, "summary", getattr(e, "description", "")))
                    pubdate = self.safe_parse_date(getattr(e, "published", getattr(e, "pubDate", ""))) or datetime.now(timezone.utc)
                    
                    if pubdate.tzinfo is None:
                        pubdate = pubdate.replace(tzinfo=timezone.utc)
                    if pubdate < cutoff:
                        continue

                    # Resolve to publisher URL
                    final_url = await self.resolve_publisher_url_async(raw_link)
                    domain = self.norm_domain(final_url)
                    if not domain:
                        domain = self.norm_domain(raw_link)

                    results.append({
                        "engine": engine,
                        "market": market,
                        "query": query,
                        "title": title,
                        "summary": summary,
                        "link": final_url or raw_link,
                        "orig_link": raw_link,
                        "domain": domain,
                        "published_at": pubdate,
                        "rank_in_feed": i + 1,
                        "body": ""
                    })
        return results

    # ========== BODY EXTRACTION METHODS ==========

    async def _extract_body_trafilatura_async(self, url: str, timeout: int = 15) -> str:
        """Extract article body using trafilatura (async)"""
        try:
            import trafilatura
            downloaded = trafilatura.fetch_url(url, timeout=timeout, no_ssl=True, user_agent=self.USER_AGENT)
            if not downloaded:
                return ""
            text = trafilatura.extract(downloaded, include_comments=False, include_tables=False)
            return self.clean_text(text) if text else ""
        except Exception:
            return ""

    async def enrich_bodies_async(self, df: pd.DataFrame, fetch_limit: int = 80, max_workers: int = 10):
        """Enrich articles with body text asynchronously"""
        import asyncio
        df["_rank"] = df["rank_in_feed"].fillna(999999).astype(int)
        to_fetch = df.sort_values("_rank").head(fetch_limit).copy()
        url_map = dict(zip(to_fetch.index, to_fetch["link"].tolist()))

        logging.info(f"Fetching article bodies for {len(url_map)} urls (limit {fetch_limit})...")
        
        # Create tasks for all URLs
        tasks = {}
        for idx, url in url_map.items():
            tasks[idx] = asyncio.create_task(self._extract_body_trafilatura_async(url))
        
        # Wait for all tasks to complete
        bodies = {}
        for idx, task in tasks.items():
            try:
                bodies[idx] = await task
            except Exception:
                bodies[idx] = ""

        df.loc[list(bodies.keys()), "body"] = list(bodies.values())
        df.drop(columns=["_rank"], errors="ignore", inplace=True)
        return df

    # ========== CAMPAIGN EXECUTION METHODS ==========

    async def execute_campaign(self):
        """Main async execution method for the campaign"""
        try:
            # Get campaign and job
            from ..crud.crud_campaign import crud_campaign
            self.campaign = await crud_campaign.get_by_id(self.db, self.campaign_id)
            self.job = await crud_campaign_job.get_by_campaign_id(self.db, self.campaign_id)
            
            if not self.campaign or not self.job:
                raise Exception("Campaign or job not found")

            # Update status to in progress
            await crud_campaign_job.update_status(self.db, self.campaign_id, 'in_progress')
            
            # Step 1: Data Collection
            await self.update_job_progress(20, "Fetching news articles")
            all_articles = await self.fetch_campaign_articles()
            
            if not all_articles:
                raise Exception("No articles found for the given criteria")
            
            # Step 2: Data Processing
            await self.update_job_progress(40, "Processing and filtering articles")
            processed_df = await self.process_articles(all_articles)
            
            # Step 3: Analysis & Scoring
            await self.update_job_progress(70, "Computing KPIs and scores")
            await self.compute_kpis(processed_df)
            
            # Step 4: Finalize campaign
            await self.update_job_progress(100, "Completed")
            await crud_campaign_job.update_status(self.db, self.campaign_id, 'completed')
            
            # Update campaign status
            from sqlalchemy import update
            await self.db.execute(
                update(Campaign)
                .where(Campaign.id == self.campaign_id)
                .values(status='completed', completed_at=datetime.now(UTC))
            )
            await self.db.commit()
            
            return True

        except Exception as e:
            logger.error(f"Campaign execution failed: {e}")
            await self.handle_campaign_error(str(e))
            return False
    
    async def fetch_campaign_articles(self):
        """Fetch articles for all campaign queries"""
        all_articles = []
        queries = [self.campaign.brand_keyword] + self.campaign.competitors
        
        for query in queries:
            articles = await self.fetch_news_async(
                query=query,
                days=self.campaign.duration_days,
                max_items=60,
                markets=self.campaign.regions
            )
            all_articles.extend(articles)
            logger.info(f"Fetched {len(articles)} articles for query: {query}")
            
        return all_articles

    async def process_articles(self, articles):
        """Process and filter articles based on campaign criteria"""
        # Convert to DataFrame for processing
        df = pd.DataFrame(articles)
        
        # Apply matching logic
        filtered_frames = []
        queries = [self.campaign.brand_keyword] + self.campaign.competitors
        
        form_data = self.campaign.form_data or {}
        
        for query in queries:
            phrases, tokens, inc_terms, exc_terms = self.parse_query(
                query, 
                form_data.get('include'),
                form_data.get('exclude')
            )
            
            sub = df[df["query"] == query].copy()
            keep_flags = []
            scores = []
            
            for _, row in sub.iterrows():
                ok, s = self.score_match(
                    row, phrases, tokens, inc_terms, exc_terms,
                    require_title=form_data.get('require_title', False),
                    min_score=form_data.get('min_score', 2.0),
                    min_token_hits=form_data.get('min_token_hits', 2),
                    strict_match=form_data.get('strict_match', False)
                )
                keep_flags.append(ok)
                scores.append(s)
                
            sub["match_score"] = scores
            kept = sub[keep_flags]
            logger.info(f"Query '{query}': {len(sub)} candidates -> {len(kept)} kept after matching")
            filtered_frames.append(kept)
            
        result_df = pd.concat(filtered_frames, ignore_index=True)
        
        if result_df.empty:
            raise Exception("After filtering, no articles matched the provided keywords/phrases.")
        
        # Fetch article bodies if enabled
        if not form_data.get('no_fetch_html', True):
            try:
                import trafilatura
                result_df = await self.enrich_bodies_async(result_df, fetch_limit=form_data.get('fetch_limit', 80))
            except ImportError:
                logger.warning("trafilatura not available, skipping body extraction")
        
        # Compute scores
        result_df = self.compute_scores(result_df)
        
        # Store articles in database
        await self.store_articles_in_db(result_df)
        
        return result_df

    async def store_articles_in_db(self, df):
        """Store processed articles in database"""
        articles_to_create = []
        
        for _, row in df.iterrows():
            article = Article(
                campaign_id=self.campaign_id,
                engine=row.get('engine', ''),
                market=row.get('market', ''),
                query=row.get('query', ''),
                title=row.get('title', ''),
                summary=row.get('summary', ''),
                link=row.get('link', ''),
                orig_link=row.get('orig_link', ''),
                domain=row.get('domain', ''),
                published_at=row.get('published_at'),
                rank_in_feed=row.get('rank_in_feed', 0),
                body=row.get('body', ''),
                title_key=row.get('title_key', ''),
                row_id=row.get('row_id', ''),
                sentiment=row.get('sentiment', 0.0),
                position_w=row.get('position_w', 1.0),
                est_ars=row.get('est_ars', 0.0),
                pickup_count=row.get('pickup_count', 0),
                inferred_clicks=row.get('inferred_clicks', 0.0),
                engagement_rate=row.get('engagement_rate', 0.0),
                tier=row.get('tier', 'tier2'),
                is_aggregator=row.get('is_aggregator', False),
                match_score=row.get('match_score', 0.0)
            )
            articles_to_create.append(article)
        
        self.db.add_all(articles_to_create)
        await self.db.commit()
        logger.info(f"Stored {len(articles_to_create)} articles in database")

    async def compute_kpis(self, df):
        """Compute and store KPIs in database"""
        # Brand KPIs
        brand_kpis = self.compute_brand_kpis(df)
        await self.store_brand_kpis(brand_kpis)
        
        # Publication KPIs
        pub_kpis = self.compute_publication_kpis(df)
        await self.store_publication_kpis(pub_kpis)
        
        # Generic Keyword Analysis
        generic_analysis = self.compute_generic_analysis(df)
        await self.store_generic_analysis(generic_analysis)

    def compute_brand_kpis(self, df):
        """Compute brand-level KPIs"""
        brand_map = {self.campaign.brand_keyword: "Client"}
        for i, comp in enumerate(self.campaign.competitors):
            brand_map[comp] = f"Competitor {chr(65+i)}"
            
        return self.kpis_by_brand(df, brand_map)

    async def store_brand_kpis(self, kpis_df):
        """Store brand KPIs in database"""
        kpis_to_create = []
        for _, kpi in kpis_df.iterrows():
            brand_kpi = BrandKPI(
                campaign_id=self.campaign_id,
                brand=kpi['brand'],
                mentions=kpi['mentions'],
                weighted_reach=kpi['weighted_reach'],
                avg_sentiment=kpi['avg_sentiment'],
                avg_engagement_rate=kpi['avg_engagement_rate'],
                avg_pickup_rate=kpi['avg_pickup_rate'],
                inferred_clicks=kpi['inferred_clicks'],
                share_of_voice=kpi['share_of_voice_%'],
                ad_equivalent_value_inr=kpi['ad_equivalent_value_inr']
            )
            kpis_to_create.append(brand_kpi)
        
        self.db.add_all(kpis_to_create)
        await self.db.commit()

    def compute_publication_kpis(self, df):
        """Compute publication-level KPIs"""
        return self.kpis_by_publication(df)

    async def store_publication_kpis(self, kpis_df):
        """Store publication KPIs in database"""
        kpis_to_create = []
        for _, kpi in kpis_df.iterrows():
            pub_kpi = PublicationKPI(
                campaign_id=self.campaign_id,
                domain=kpi['domain'],
                mentions=kpi['mentions'],
                weighted_reach=kpi['weighted_reach'],
                avg_engagement_rate=kpi['avg_engagement_rate'],
                avg_sentiment=kpi['avg_sentiment'],
                tier=kpi['tier'],
                is_aggregator=kpi['is_aggregator']
            )
            kpis_to_create.append(pub_kpi)
        
        self.db.add_all(kpis_to_create)
        await self.db.commit()

    def compute_generic_analysis(self, df):
        """Compute generic keyword analysis"""
        generic_keyword = self.campaign.form_data.get('generic_keyword', '')
        if not generic_keyword:
            return pd.DataFrame()
            
        gk = self.normalize(generic_keyword)
        gk_pat = re.compile(rf"(?<!\w){re.escape(gk)}(?!\w)", re.IGNORECASE) if gk else None
        
        brand_map = {self.campaign.brand_keyword: "Client"}
        for i, comp in enumerate(self.campaign.competitors):
            brand_map[comp] = f"Competitor {chr(65+i)}"
            
        stats = []
        tmp = df.copy()
        tmp["brand"] = tmp["query"].map(brand_map).fillna(tmp["query"])
        
        for brand in tmp["brand"].unique():
            sub = tmp[tmp["brand"] == brand]
            if gk_pat:
                hay = (sub["title"].str.lower().fillna("") + " " + 
                       sub["summary"].str.lower().fillna("") + " " + 
                       sub["body"].str.lower().fillna(""))
                hits = sub[hay.str.contains(gk, na=False)]
            else:
                hits = pd.DataFrame(columns=sub.columns)
            total_hits = len(hits)
            pos_hits = int((hits["sentiment"] > 0.05).sum()) if total_hits else 0
            stats.append({
                "brand": brand, 
                "generic_keyword_mentions": total_hits, 
                "positive_generic_mentions": pos_hits, 
                "positive_rate": round((pos_hits / total_hits * 100.0) if total_hits else 0.0, 2)
            })
            
        return pd.DataFrame(stats)

    async def store_generic_analysis(self, analysis_df):
        """Store generic keyword analysis in database"""
        if analysis_df.empty:
            return
            
        analysis_to_create = []
        for _, analysis in analysis_df.iterrows():
            generic_analysis = GenericKeywordAnalysis(
                campaign_id=self.campaign_id,
                brand=analysis['brand'],
                generic_keyword_mentions=analysis['generic_keyword_mentions'],
                positive_generic_mentions=analysis['positive_generic_mentions'],
                positive_rate=analysis['positive_rate']
            )
            analysis_to_create.append(generic_analysis)
        
        self.db.add_all(analysis_to_create)
        await self.db.commit()

    async def handle_campaign_error(self, error_message: str):
        """Handle campaign execution errors"""
        await crud_campaign_job.update_status(
            self.db, self.campaign_id, 'failed', error_message
        )
        
        from sqlalchemy import update
        await self.db.execute(
            update(Campaign)
            .where(Campaign.id == self.campaign_id)
            .values(status='error', error_message=error_message)
        )
        await self.db.commit()