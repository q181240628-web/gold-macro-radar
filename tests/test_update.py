import csv
import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import update as radar

class GoldRadarTests(unittest.TestCase):
    def test_real_yield_direction(self):
        self.assertEqual(radar.classify_factor('real_rate', -0.12, .05)[0], 'bull')
        self.assertEqual(radar.classify_factor('real_rate', .16, .05)[0], 'bear')
        self.assertEqual(radar.classify_factor('real_rate', .02, .05)[0], 'neutral')

    def test_oil_and_inflation_not_mechanically_bullish(self):
        self.assertEqual(radar.classify_factor('oil', 13., 4.)[0], 'mixed')
        self.assertEqual(radar.classify_factor('inflation', .34, .15)[0], 'mixed')
        self.assertEqual(radar.classify_factor('payroll', -300., 50)[0], 'unknown')

    def test_yoy_calculation_without_consensus(self):
        months=[('2025-%02d-01'%m, 100+m) for m in range(1,13)]
        months += [('2026-01-01', 115.0),('2026-02-01', 116.0)]
        cfg=('CPIAUCSL','CPI同比','inflation','yoy',.15,1,4)
        res=radar.create_factor(cfg, months)
        self.assertAlmostEqual(res['value'], (116.0/102.0-1)*100,places=3)
        self.assertIn('不是实际值与分析师一致预期',res['qualification'])

    def test_news_heuristics_are_low_confidence(self):
        self.assertEqual(radar.classify_headline('Fed cuts interest rates')[0], 'bull')
        self.assertEqual(radar.classify_headline('Oil prices surge during war')[0], 'mixed')
        self.assertEqual(radar.classify_headline('Fed issues FOMC statement')[0], 'unknown')

    def test_rss_parsing(self):
        sample=b'<rss><channel><item><title>Fed issues FOMC statement</title><link>https://www.federalreserve.gov/test</link><pubDate>Thu, 05 Nov 2026 14:00:00 GMT</pubDate></item></channel></rss>'
        entries=radar.parse_feed(sample,'Fed','policy')
        self.assertEqual(len(entries),1)
        self.assertEqual(entries[0]['group'],'policy')
        self.assertTrue(entries[0]['published_at'].startswith('2026-11-05T14:00'))

    def test_full_pipeline_idempotent_history(self):
        now=datetime.now(timezone.utc)
        rows=[((now-timedelta(days=(40-i))).date().isoformat(),2.4-0.015*i) for i in range(41)]
        def payload(series):
            out=io.StringIO();writer=csv.writer(out);writer.writerow(['observation_date',series]);writer.writerows(rows)
            return out.getvalue().encode()
        fake_rss=b'<rss><channel></channel></rss>'
        def fake_get(url):
            if 'fredgraph.csv' in url: return payload('DFII10')
            return fake_rss
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(radar,'DATA',Path(d)),mock.patch.object(radar,'SERIES', radar.SERIES[:1]),mock.patch.object(radar,'FEEDS',radar.FEEDS[:1]):
                first,events=radar.generate(fake_get)
                second,repeat=radar.generate(fake_get)
                self.assertEqual(first['status'],'ok')
                self.assertEqual(len(first['factors']),1)
                self.assertEqual(len(events),len(repeat))
                self.assertEqual(json.loads((Path(d)/'latest.json').read_text())['status'],'ok')

if __name__=='__main__': unittest.main()
