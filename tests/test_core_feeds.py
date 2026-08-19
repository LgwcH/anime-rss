from __future__ import annotations

import unittest
from datetime import UTC

from anirss.core.feeds import FeedParseError, parse_feed


class FeedParsingTests(unittest.TestCase):
    def test_rss_enclosure_magnet_and_dates(self) -> None:
        document = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel>
          <item>
            <title>[Group] Example Show - 12 [1080p]</title>
            <guid>episode-12</guid>
            <pubDate>Thu, 06 Aug 2026 20:00:00 +0800</pubDate>
            <enclosure url="https://cdn.example/show-12.mkv" type="video/x-matroska" />
            <link>https://example.test/posts/12</link>
          </item>
          <item>
            <title>Example Show EP13</title>
            <description><![CDATA[Download magnet:?xt=urn:btih:ABC123&amp;dn=Show]]></description>
          </item>
        </channel></rss>"""

        items = parse_feed(document, subscription_id=7)

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].subscription_id, 7)
        self.assertEqual(items[0].download_url, "https://cdn.example/show-12.mkv")
        self.assertEqual(items[0].content_type, "video/x-matroska")
        self.assertEqual(items[0].episode, "12")
        assert items[0].published_at is not None
        self.assertEqual(items[0].published_at.tzinfo, UTC)
        self.assertEqual(items[1].download_url, "magnet:?xt=urn:btih:ABC123&dn=Show")
        self.assertEqual(items[1].episode, "13")

    def test_atom_enclosure_and_updated(self) -> None:
        document = """<feed xmlns="http://www.w3.org/2005/Atom">
          <entry>
            <id>tag:example.test,2026:14</id>
            <title>Example S02E03</title>
            <updated>2026-08-06T12:34:56Z</updated>
            <link rel="alternate" href="https://example.test/14" />
            <link rel="enclosure" href="https://example.test/files/14.torrent" />
          </entry>
        </feed>"""

        item = parse_feed(document, subscription_id=2)[0]

        self.assertEqual(item.guid, "tag:example.test,2026:14")
        self.assertEqual(item.download_url, "https://example.test/files/14.torrent")
        self.assertEqual(item.link, "https://example.test/14")
        self.assertEqual(item.episode, "S02E03")
        assert item.published_at is not None
        self.assertEqual(item.published_at.isoformat(), "2026-08-06T12:34:56+00:00")

    def test_missing_guid_gets_stable_hash(self) -> None:
        document = "<rss><channel><item><title>Show [01]</title></item></channel></rss>"
        first = parse_feed(document)[0]
        second = parse_feed(document)[0]
        self.assertTrue(first.guid.startswith("sha256:"))
        self.assertEqual(first.guid, second.guid)

    def test_relative_links_resolve_against_feed_url(self) -> None:
        document = """<rss><channel><item><title>Show 01</title>
          <enclosure url="files/episode-01.torrent" />
          <link>/posts/1</link>
        </item></channel></rss>"""
        item = parse_feed(
            document,
            base_url="https://example.test/feeds/current.xml",
        )[0]
        self.assertEqual(
            item.download_url,
            "https://example.test/feeds/files/episode-01.torrent",
        )
        self.assertEqual(item.link, "https://example.test/posts/1")

    def test_preserves_torrent_enclosure_mime_type(self) -> None:
        document = """<rss><channel><item><title>Show 01</title>
          <enclosure url="https://example.test/download.php?id=1"
                     type="application/x-bittorrent" />
        </item></channel></rss>"""
        item = parse_feed(document)[0]
        self.assertEqual(item.content_type, "application/x-bittorrent")

    def test_rejects_dtd(self) -> None:
        with self.assertRaises(FeedParseError):
            parse_feed("<!DOCTYPE rss><rss><channel /></rss>")

    def test_rejects_dtd_after_a_long_prefix(self) -> None:
        document = (
            "<?xml version='1.0'?><!--" + "x" * 6000 + "--><!DOCTYPE rss [<!ENTITY leak 'unsafe'>]>"
            "<rss><channel><item><title>&leak;</title></item></channel></rss>"
        )
        with self.assertRaises(FeedParseError):
            parse_feed(document)

    def test_rejects_utf16_dtd_and_entity(self) -> None:
        document = (
            "<?xml version='1.0' encoding='UTF-16'?>"
            "<!DOCTYPE rss [<!ENTITY expanded 'EXPANDED'>]>"
            "<rss><channel><item><title>&expanded;</title></item></channel></rss>"
        ).encode("utf-16")
        with self.assertRaises(FeedParseError):
            parse_feed(document)


if __name__ == "__main__":
    unittest.main()
