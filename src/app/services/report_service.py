import base64
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List
import pandas as pd
import plotly.graph_objects as go
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from weasyprint import HTML
import io

from ..models import Campaign, Article, BrandKPI, PublicationKPI, GenericKeywordAnalysis


class ReportService:
    """Service for generating PDF reports from campaign data"""

    def __init__(self, db: AsyncSession, campaign_id: int):
        self.db = db
        self.campaign_id = campaign_id
        self.campaign = None
        self.logo_path = Path(__file__).parent.parent.parent.parent / "logo.png"

    async def generate_pdf_report(self) -> bytes:
        """Generate PDF report from campaign data"""

        # Fetch campaign
        campaign_result = await self.db.execute(
            select(Campaign).where(Campaign.id == self.campaign_id)
        )
        self.campaign = campaign_result.scalar_one_or_none()
        if not self.campaign:
            raise ValueError(f"Campaign {self.campaign_id} not found")

        # Fetch all data
        articles = await self._fetch_articles()
        brand_kpis = await self._fetch_brand_kpis()
        pub_kpis = await self._fetch_publication_kpis()
        generic_analysis = await self._fetch_generic_analysis()

        # Convert to DataFrames for easier processing
        articles_df = pd.DataFrame([self._article_to_dict(a) for a in articles])
        brand_kpis_df = pd.DataFrame([self._brand_kpi_to_dict(k) for k in brand_kpis])
        pub_kpis_df = pd.DataFrame([self._pub_kpi_to_dict(k) for k in pub_kpis])
        generic_df = pd.DataFrame([self._generic_to_dict(g) for g in generic_analysis])

        # Encode logo as base64
        logo_base64 = self._get_logo_base64()

        # Generate HTML
        html = self._build_html(
            logo_base64=logo_base64,
            campaign_name=self.campaign.name,
            brand_keyword=self.campaign.brand_keyword,
            competitors=self.campaign.competitors,
            regions=self.campaign.regions,
            articles_count=len(articles),
            brand_kpis_df=brand_kpis_df,
            pub_kpis_df=pub_kpis_df,
            generic_df=generic_df,
            articles_df=articles_df
        )

        # Convert HTML to PDF
        pdf_bytes = HTML(string=html).write_pdf()
        return pdf_bytes

    def _get_logo_base64(self) -> str:
        """Read logo and convert to base64"""
        try:
            with open(self.logo_path, 'rb') as f:
                logo_bytes = f.read()
                return base64.b64encode(logo_bytes).decode('utf-8')
        except Exception:
            return ""

    async def _fetch_articles(self) -> List[Article]:
        result = await self.db.execute(
            select(Article).where(Article.campaign_id == self.campaign_id)
        )
        return result.scalars().all()

    async def _fetch_brand_kpis(self) -> List[BrandKPI]:
        result = await self.db.execute(
            select(BrandKPI).where(BrandKPI.campaign_id == self.campaign_id)
        )
        return result.scalars().all()

    async def _fetch_publication_kpis(self) -> List[PublicationKPI]:
        result = await self.db.execute(
            select(PublicationKPI).where(PublicationKPI.campaign_id == self.campaign_id)
        )
        return result.scalars().all()

    async def _fetch_generic_analysis(self) -> List[GenericKeywordAnalysis]:
        result = await self.db.execute(
            select(GenericKeywordAnalysis).where(GenericKeywordAnalysis.campaign_id == self.campaign_id)
        )
        return result.scalars().all()

    def _article_to_dict(self, article: Article) -> Dict[str, Any]:
        return {
            'title': article.title,
            'domain': article.domain,
            'link': article.link,
            'sentiment': article.sentiment,
            'tier': article.tier,
            'published_at': article.published_at,
            'query': article.query  # This is the brand/competitor keyword searched
        }

    def _brand_kpi_to_dict(self, kpi: BrandKPI) -> Dict[str, Any]:
        return {
            'brand': kpi.brand,
            'mentions': kpi.mentions,
            'weighted_reach': kpi.weighted_reach,
            'avg_sentiment': kpi.avg_sentiment,
            'avg_engagement_rate': kpi.avg_engagement_rate,
            'avg_pickup_rate': kpi.avg_pickup_rate,
            'inferred_clicks': kpi.inferred_clicks,
            'share_of_voice_%': kpi.share_of_voice,
            'ad_equivalent_value_inr': kpi.ad_equivalent_value_inr
        }

    def _pub_kpi_to_dict(self, kpi: PublicationKPI) -> Dict[str, Any]:
        return {
            'domain': kpi.domain,
            'mentions': kpi.mentions,
            'weighted_reach': kpi.weighted_reach,
            'avg_engagement_rate': kpi.avg_engagement_rate,
            'avg_sentiment': kpi.avg_sentiment,
            'tier': kpi.tier,
            'is_aggregator': kpi.is_aggregator
        }

    def _generic_to_dict(self, gen: GenericKeywordAnalysis) -> Dict[str, Any]:
        return {
            'brand': gen.brand,
            'generic_keyword_mentions': gen.generic_keyword_mentions,
            'positive_generic_mentions': gen.positive_generic_mentions,
            'positive_rate_%': gen.positive_rate
        }

    def _build_html(
        self,
        logo_base64: str,
        campaign_name: str,
        brand_keyword: str,
        competitors: List[str],
        regions: List[str],
        articles_count: int,
        brand_kpis_df: pd.DataFrame,
        pub_kpis_df: pd.DataFrame,
        generic_df: pd.DataFrame,
        articles_df: pd.DataFrame
    ) -> str:
        """Build HTML report"""

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Generate charts
        sov_chart = self._generate_sov_chart(brand_kpis_df)
        sentiment_chart = self._generate_sentiment_chart(articles_df)
        generic_chart = self._generate_generic_chart(generic_df)

        # Build HTML
        html = f"""<!doctype html><html><head><meta charset='utf-8'>
<title>PR KPI Report — {campaign_name}</title>
<style>
  body {{ font: 14px/1.45 -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial; margin: 24px; color:#111;}}
  .header {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 24px; }}
  .logo {{ height: 60px; }}
  h1 {{ font-size: 28px; margin: 0 0 8px; }}
  h2 {{ font-size: 20px; margin: 24px 0 8px; }}
  .card {{ background: #fff; border:1px solid #eee; border-radius:12px; padding:16px; margin:12px 0; box-shadow:0 1px 2px rgba(0,0,0,.04);}}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ border: 1px solid #eee; padding: 8px; text-align: left; }}
  th {{ background: #fafafa; }}
  .small {{ color:#666; }}
  .badge {{ display:inline-block; padding:2px 8px; border-radius:999px; background:#f1f5f9; font-size:12px; margin-left:8px; }}
  a {{ color:#0b57d0; text-decoration:none; }}
</style>
</head><body>
<div class='header'>
  <div>
    <h1>PR KPI Report — {campaign_name}</h1>
    <div class='small'>Generated on {timestamp}</div>
  </div>
  {"<img src='data:image/png;base64," + logo_base64 + "' class='logo' />" if logo_base64 else ""}
</div>

<div class='card'>
  <div><strong>Brand:</strong> {brand_keyword} &nbsp;&nbsp; <strong>Competitors:</strong> {', '.join(competitors)}</div>
  <div class='small'><strong>Markets:</strong> {', '.join(regions)} &nbsp;&nbsp; <strong>Articles:</strong> {articles_count}</div>
</div>

<h2>Share of Voice & Media KPIs</h2>
<div class='card'>
{brand_kpis_df.to_html(index=False, border=1, classes='dataframe') if not brand_kpis_df.empty else '<p>No data available</p>'}
</div>

{sov_chart}

<h2>Sentiment by Brand</h2>
{sentiment_chart}

<h2>Generic Keyword Analysis</h2>
<div class='card'>
{generic_df.to_html(index=False, border=1, classes='dataframe') if not generic_df.empty else '<p>No data available</p>'}
</div>

{generic_chart}

<h2>Top Publications</h2>
<div class='card'>
{pub_kpis_df.head(10).to_html(index=False, border=1, classes='dataframe') if not pub_kpis_df.empty else '<p>No data available</p>'}
</div>

<h2>Top Headlines</h2>
<div class='card'>
<ol>
{self._generate_headlines_list(articles_df)}
</ol>
</div>

</body></html>"""

        return html

    def _generate_sov_chart(self, df: pd.DataFrame) -> str:
        """Generate Share of Voice pie chart"""
        if df.empty:
            return ""

        fig = go.Figure(data=[go.Pie(
            labels=df['brand'],
            values=df['mentions'],
            hole=0.45
        )])
        fig.update_layout(title="Share of Voice (Mentions)")

        return f"<div class='card'><div>{fig.to_html(include_plotlyjs='cdn', div_id='sov-chart')}</div></div>"

    def _generate_sentiment_chart(self, df: pd.DataFrame) -> str:
        """Generate sentiment distribution chart"""
        if df.empty:
            return ""

        # Create sentiment buckets
        df['sent_bucket'] = df['sentiment'].apply(
            lambda x: 'Positive' if x > 0.1 else ('Negative' if x < -0.1 else 'Neutral')
        )

        # Group by query (brand searched) and sentiment
        sentiment_counts = df.groupby(['query', 'sent_bucket']).size().unstack(fill_value=0)

        fig = go.Figure()
        for sentiment in ['Negative', 'Neutral', 'Positive']:
            if sentiment in sentiment_counts.columns:
                fig.add_trace(go.Bar(
                    name=sentiment,
                    x=sentiment_counts.index,
                    y=sentiment_counts[sentiment]
                ))

        fig.update_layout(
            title="Sentiment Distribution",
            xaxis_title="Brand",
            yaxis_title="Articles",
            barmode='group'
        )

        return f"<div class='card'><div>{fig.to_html(include_plotlyjs='cdn', div_id='sentiment-chart')}</div></div>"

    def _generate_generic_chart(self, df: pd.DataFrame) -> str:
        """Generate generic keyword usage chart"""
        if df.empty:
            return ""

        fig = go.Figure(data=[go.Bar(
            x=df['brand'],
            y=df['generic_keyword_mentions']
        )])
        fig.update_layout(
            title="Generic Keyword Mentions by Brand",
            xaxis_title="Brand",
            yaxis_title="Mentions"
        )

        return f"<div class='card'><div>{fig.to_html(include_plotlyjs='cdn', div_id='generic-chart')}</div></div>"

    def _generate_headlines_list(self, df: pd.DataFrame) -> str:
        """Generate top headlines HTML list"""
        if df.empty:
            return "<li>No articles found</li>"

        # Sort by published date and take top 15
        df_sorted = df.sort_values('published_at', ascending=False).head(15)

        headlines = []
        for _, row in df_sorted.iterrows():
            headlines.append(
                f"<li><a href='{row['link']}' target='_blank'>{row['title']}</a> "
                f"<span class='badge'>{row['domain']}</span></li>"
            )

        return '\n'.join(headlines)
