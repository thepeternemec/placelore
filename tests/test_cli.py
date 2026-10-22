"""CLI behaviour for the error paths that used to raise tracebacks."""

from __future__ import annotations

import os
import tempfile
import unittest

from placeswiki.cli import main


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "cli.sqlite")

    def tearDown(self):
        for name in os.listdir(self.tmp):
            os.unlink(os.path.join(self.tmp, name))
        os.rmdir(self.tmp)


class TestValidation(Base):
    def test_lat_without_lon_is_refused(self):
        with self.assertRaises(SystemExit):
            main(["collect", "--lat", "41.8", "--db", self.db, "--limit", "1"])

    def test_lon_without_lat_is_refused(self):
        with self.assertRaises(SystemExit):
            main(["collect", "--lon", "12.4", "--db", self.db, "--limit", "1"])

    def test_unknown_sparql_endpoint_is_refused(self):
        with self.assertRaises(SystemExit):
            main(["bulk", "fetch", "--db", self.db, "--endpoint", "nope", "--limit", "1"])

    def test_missing_database_is_refused_by_serve(self):
        with self.assertRaises(SystemExit):
            main(["serve", "--db", os.path.join(self.tmp, "absent.sqlite"), "--port", "8133"])

    def test_removing_unknown_link_is_refused(self):
        with self.assertRaises(SystemExit):
            main([
                "link", "remove", "--db", self.db, "--place", "wc:nope",
                "--google-id", "ChIJrTLr-GyuEmsRBfy61i59si0",
            ])

    def test_promoting_unknown_link_is_refused(self):
        with self.assertRaises(SystemExit):
            main([
                "link", "promote", "--db", self.db, "--place", "wc:nope",
                "--google-id", "ChIJrTLr-GyuEmsRBfy61i59si0",
            ])


if __name__ == "__main__":
    unittest.main()
